"""Backfill searchable topic metadata for already-ingested videos.

Reuses Whisper transcript sidecars (no re-transcription). Rebuilds Qdrant chunks
with topic headers + an overview chunk so embeddings can find videos by subject.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from qdrant_client import QdrantClient

from core.embeddings_utils import get_embeddings
from core.ingestion_service import _delete_document_from_qdrant, _upsert_chunks
from core.models import IngestedChunk, IngestedDocument
from core.qdrant_utils import ensure_sermon_collection
from core.storage_paths import admin_video_ingestion_dir
from core.transcript_normalize import TranscriptSegment
from core.video_ingestion import (
    DEFAULT_SPLITTER_KWARGS,
    _transcript_sidecar_path,
    build_video_chunks_with_topic_metadata,
)
from core.video_topic_metadata import qdrant_metadata_from_topic


def _segments_from_sidecar(payload: dict) -> list[TranscriptSegment]:
    rows = payload.get("segments_normalized") or payload.get("segments_raw") or []
    segments: list[TranscriptSegment] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        segments.append(TranscriptSegment(start=start, end=end, text=text))
    return segments


def _load_sidecar(doc: IngestedDocument) -> Optional[dict]:
    upload_dir = admin_video_ingestion_dir()
    path = upload_dir / doc.source_name
    sidecar = _transcript_sidecar_path(path)
    if not sidecar.is_file():
        # Legacy: sidecar next to a differently cased name.
        matches = list(upload_dir.glob(f"{Path(doc.source_name).stem}.transcript.json"))
        if not matches:
            return None
        sidecar = matches[0]
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None


def backfill_one_video(
    doc: IngestedDocument,
    *,
    embeddings,
    qdrant_client: QdrantClient,
    collection_name: str,
    chunk_size: int,
    overlap_segments: int,
    force: bool = False,
    log=None,
) -> bool:
    existing_meta = doc.topic_metadata or {}
    if existing_meta.get("topic_title") and existing_meta.get("keywords") and not force:
        if log:
            log(f"Skip {doc.source_name}: topic metadata already present (use --force).")
        return False

    payload = _load_sidecar(doc)
    if not payload:
        if log:
            log(f"Skip {doc.source_name}: no transcript sidecar found.")
        return False

    segments = _segments_from_sidecar(payload)
    if not segments:
        if log:
            log(f"Skip {doc.source_name}: empty transcript segments.")
        return False

    original_title = (
        str(payload.get("title") or "").strip()
        or (existing_meta.get("original_title") or "")
        or doc.title
        or Path(doc.source_name).stem
    )
    # Prefer date/filename style original when title was already upgraded.
    if existing_meta.get("original_title"):
        original_title = str(existing_meta["original_title"])
    elif payload.get("topic_metadata", {}).get("original_title"):
        original_title = str(payload["topic_metadata"]["original_title"])

    normalized_text = "\n".join(seg.text for seg in segments)
    topic_meta, display_title, chunks, per_chunk_metadata = build_video_chunks_with_topic_metadata(
        original_title=original_title,
        normalized_segments=segments,
        normalized_text=normalized_text,
        chunk_size=chunk_size,
        overlap_segments=overlap_segments,
    )
    topic_payload = topic_meta.as_dict()
    extra_metadata = {
        "content_type": "video_transcript",
        "media_type": "video",
        **qdrant_metadata_from_topic(topic_meta),
    }

    with transaction.atomic():
        _delete_document_from_qdrant(doc.source_name, doc.file_hash)
        IngestedChunk.objects.filter(document=doc).delete()
        created, skipped = _upsert_chunks(
            doc.source_name,
            display_title,
            chunks,
            doc.file_hash,
            document=doc,
            embeddings=embeddings,
            qdrant_client=qdrant_client,
            collection_name=collection_name,
            extra_metadata=extra_metadata,
            per_chunk_metadata=per_chunk_metadata,
        )
        doc.title = display_title
        doc.topic_metadata = topic_payload
        doc.chunk_count = created
        doc.save(update_fields=["title", "topic_metadata", "chunk_count", "updated_at"])

    # Refresh sidecar topic block when possible.
    upload_dir = admin_video_ingestion_dir()
    media_path = upload_dir / doc.source_name
    sidecar = _transcript_sidecar_path(media_path)
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            data["title"] = display_title
            data["topic_metadata"] = topic_payload
            sidecar.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    if log:
        log(
            f"Backfilled {doc.source_name}: title “{display_title}”, "
            f"topics={topic_meta.topics[:5]}, chunks={created}, skipped={skipped}"
        )
    return True


class Command(BaseCommand):
    help = (
        "Generate topic metadata for ingested videos and re-embed chunks "
        "(uses .transcript.json sidecars; does not re-run Whisper)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild even when topic_metadata is already present.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional max number of videos to process (0 = all).",
        )
        parser.add_argument(
            "--source",
            action="append",
            default=[],
            help="Only backfill this source_name (repeatable).",
        )

    def handle(self, *args, **options):
        force = bool(options["force"])
        limit = int(options["limit"] or 0)
        sources = [s.strip() for s in (options["source"] or []) if s and s.strip()]

        qs = IngestedDocument.objects.filter(source_kind="video").order_by("id")
        if sources:
            qs = qs.filter(source_name__in=sources)
        if limit > 0:
            qs = qs[:limit]

        chunk_size = int(
            os.environ.get("VIDEO_INGEST_CHUNK_SIZE", str(DEFAULT_SPLITTER_KWARGS["chunk_size"]))
        )
        overlap_segments = int(os.environ.get("VIDEO_INGEST_CHUNK_OVERLAP_SEGMENTS", "1"))
        embeddings = get_embeddings()
        qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
        collection_name = os.getenv("QDRANT_COLLECTION", "sermon_brain")
        ensure_sermon_collection(qdrant_client, collection_name)

        updated = 0
        skipped = 0
        for doc in qs:
            try:
                ok = backfill_one_video(
                    doc,
                    embeddings=embeddings,
                    qdrant_client=qdrant_client,
                    collection_name=collection_name,
                    chunk_size=chunk_size,
                    overlap_segments=overlap_segments,
                    force=force,
                    log=self.stdout.write,
                )
            except Exception as exc:
                skipped += 1
                self.stderr.write(f"Failed {doc.source_name}: {exc}")
                continue
            if ok:
                updated += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(f"Video topic metadata backfill done: updated={updated}, skipped={skipped}")
        )
