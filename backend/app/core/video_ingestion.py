"""
Admin video ingestion pipeline:

1. Store the original video under ``uploads/admin_video_ingestion``.
2. Extract audio with ffmpeg and transcribe with Whisper (segment timestamps).
3. Normalize the transcript: strip fillers/CTAs and drop isolated content that
   is not about Christianity, the Bible, or social ideas/issues.
4. Group timestamped segments into chunks, embed, and upsert into Qdrant.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import QdrantClient

from .embeddings_utils import get_embeddings
from .ingestion_service import (
    DEFAULT_SPLITTER_KWARGS,
    IngestionResult,
    _clean_text,
    _delete_source_from_qdrant,
    _persist_job_progress,
    _safe_upload_stem,
    _sha256_bytes,
    _to_markdown,
    _upsert_chunks,
)
from .models import IngestedDocument, IngestionJob, IngestionJobFileFailure
from .qdrant_utils import ensure_sermon_collection
from .storage_paths import admin_video_ingestion_dir
from .transcript_normalize import (
    TranscriptSegment,
    format_cleanup_log,
    format_segment_line,
    format_timestamp_range,
    normalize_transcript_segments,
)
from .whisper_transcribe import transcribe_video_file

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mp4v",
    ".mov",
    ".qt",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
    ".f4v",
    ".mpeg",
    ".mpg",
    ".mpe",
    ".m2v",
    ".3gp",
    ".3g2",
    ".ogv",
    ".ts",
    ".mts",
    ".m2ts",
    ".vob",
    ".asf",
    ".rm",
    ".rmvb",
    ".divx",
    ".xvid",
    ".mxf",
    ".dv",
    ".nsv",
    ".amv",
}

VIDEO_ACCEPT_ATTRIBUTE = "video/*," + ",".join(sorted(VIDEO_EXTENSIONS))


def is_video_filename(name: str) -> bool:
    return Path(name or "").suffix.lower() in VIDEO_EXTENSIONS


def _canonical_video_name(original_name: str) -> str:
    stem = _safe_upload_stem(original_name)
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        suffix = suffix if suffix else ".mp4"
    return f"{stem}{suffix}"


def _transcript_sidecar_path(video_path: Path) -> Path:
    return video_path.with_suffix(".transcript.json")


def _replace_existing_video(original_name: str) -> None:
    stem = _safe_upload_stem(original_name)
    upload_dir = admin_video_ingestion_dir()
    names = {original_name, _canonical_video_name(original_name)}
    for ext in VIDEO_EXTENSIONS:
        names.add(f"{stem}{ext}")
    for name in names:
        if not IngestedDocument.objects.filter(source_name=name).exists():
            continue
        _delete_source_from_qdrant(name)
        IngestedDocument.objects.filter(source_name=name).delete()
        path = upload_dir / name
        path.unlink(missing_ok=True)
        _transcript_sidecar_path(path).unlink(missing_ok=True)


def group_segments_into_chunks(
    segments: Sequence[TranscriptSegment],
    *,
    chunk_size: int,
    overlap_segments: int = 1,
) -> List[List[TranscriptSegment]]:
    """Pack consecutive timestamped lines into ~chunk_size character groups."""
    if not segments:
        return []
    groups: List[List[TranscriptSegment]] = []
    current: List[TranscriptSegment] = []
    current_len = 0
    for segment in segments:
        line_len = len(format_segment_line(segment)) + 1
        would_overflow = current and current_len + line_len > chunk_size
        if would_overflow:
            groups.append(current)
            if overlap_segments > 0:
                current = list(current[-overlap_segments:])
                current_len = sum(len(format_segment_line(item)) + 1 for item in current)
            else:
                current = []
                current_len = 0
        current.append(segment)
        current_len += line_len
    if current:
        groups.append(current)
    return groups


def _chunk_text_from_group(title: str, group: Sequence[TranscriptSegment]) -> str:
    body = "\n".join(format_segment_line(segment) for segment in group)
    return _to_markdown(title, body)


def _write_transcript_sidecar(
    video_path: Path,
    *,
    title: str,
    source_name: str,
    raw_segments: Sequence[TranscriptSegment],
    normalized: Sequence[TranscriptSegment],
    stats: dict,
) -> None:
    payload = {
        "title": title,
        "source_name": source_name,
        "whisper_model": os.getenv("WHISPER_MODEL") or "base",
        "stats": stats,
        "segments_raw": [
            {"start": seg.start, "end": seg.end, "text": seg.text} for seg in raw_segments
        ],
        "segments_normalized": [
            {"start": seg.start, "end": seg.end, "text": seg.text} for seg in normalized
        ],
    }
    sidecar = _transcript_sidecar_path(video_path)
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ingest_video_files(
    uploaded_files,
    replace_existing_sources: bool = False,
    log_fn: Optional[Callable[[str], None]] = None,
    job: Optional[IngestionJob] = None,
    extra_metadata_by_name: Optional[dict] = None,
    transcribe_fn: Optional[Callable[[Path], List[TranscriptSegment]]] = None,
) -> IngestionResult:
    """
    Ingest video uploads: Whisper transcript → topical normalize → Qdrant.

    ``transcribe_fn`` is a test seam; production uses ``transcribe_video_file``.
    """
    result = IngestionResult(files_received=len(uploaded_files))
    extra_metadata_by_name = extra_metadata_by_name or {}
    transcribe = transcribe_fn or (lambda path: transcribe_video_file(path, log_fn=log_fn))

    upload_dir = admin_video_ingestion_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)

    chunk_size = int(os.environ.get("VIDEO_INGEST_CHUNK_SIZE", str(DEFAULT_SPLITTER_KWARGS["chunk_size"])))
    overlap_segments = int(os.environ.get("VIDEO_INGEST_CHUNK_OVERLAP_SEGMENTS", "1"))
    embeddings = get_embeddings()
    qdrant_client = QdrantClient(url=os.getenv("QDRANT_URL", "http://qdrant:6333"))
    collection_name = os.getenv("QDRANT_COLLECTION", "sermon_brain")
    ensure_sermon_collection(qdrant_client, collection_name)

    for upload in uploaded_files:
        video_path: Optional[Path] = None
        try:
            extension = Path(upload.name).suffix.lower()
            if extension not in VIDEO_EXTENSIONS:
                if log_fn:
                    log_fn(f"Skipped unsupported video type: {upload.name}")
                continue

            if log_fn:
                log_fn(f"Processing video: {upload.name}")

            if replace_existing_sources:
                _replace_existing_video(upload.name)
                if log_fn:
                    log_fn(f"Replaced previous video source data for: {upload.name}")

            raw_content = upload.read()
            file_hash = _sha256_bytes(raw_content)
            if IngestedDocument.objects.filter(file_hash=file_hash).exists():
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"Duplicate video skipped by hash: {upload.name}")
                _persist_job_progress(job, result)
                continue

            source_name = _canonical_video_name(upload.name)
            video_path = upload_dir / source_name
            video_path.write_bytes(raw_content)
            title = _safe_upload_stem(upload.name)

            if log_fn:
                log_fn(f"Stored original video as {source_name}. Starting Whisper transcription.")

            raw_segments = transcribe(video_path)
            if job is not None:
                job.save(update_fields=["updated_at"])

            normalized = normalize_transcript_segments(raw_segments)
            if log_fn:
                log_fn(format_cleanup_log(normalized.stats, source_label=source_name))

            if not normalized.segments:
                video_path.unlink(missing_ok=True)
                _transcript_sidecar_path(video_path).unlink(missing_ok=True)
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"Video had no usable transcript after normalize and was skipped: {upload.name}")
                _persist_job_progress(job, result)
                continue

            _write_transcript_sidecar(
                video_path,
                title=title,
                source_name=source_name,
                raw_segments=raw_segments,
                normalized=normalized.segments,
                stats=normalized.stats.as_dict(),
            )

            groups = group_segments_into_chunks(
                normalized.segments,
                chunk_size=chunk_size,
                overlap_segments=overlap_segments,
            )
            chunks = [_clean_text(_chunk_text_from_group(title, group)) for group in groups]
            chunks = [chunk for chunk in chunks if chunk]
            if not chunks:
                splitter = RecursiveCharacterTextSplitter(**DEFAULT_SPLITTER_KWARGS)
                markdown_text = _to_markdown(title, normalized.text)
                chunks = [_clean_text(c) for c in splitter.split_text(markdown_text) if _clean_text(c)]
                groups = [normalized.segments for _ in chunks]

            per_chunk_metadata = []
            for group in groups:
                start_s = group[0].start if group else 0.0
                end_s = group[-1].end if group else start_s
                per_chunk_metadata.append(
                    {
                        "start_s": start_s,
                        "end_s": end_s,
                        "timestamp": format_timestamp_range(start_s, end_s),
                    }
                )
            extra_metadata = {
                "content_type": "video_transcript",
                "media_type": "video",
            }
            named = extra_metadata_by_name.get(upload.name) or extra_metadata_by_name.get(source_name)
            if named:
                extra_metadata.update(named)

            doc = IngestedDocument.objects.create(
                source_name=source_name,
                title=title,
                file_hash=file_hash,
                original_extension=extension,
                source_kind="video",
            )

            try:
                created, skipped = _upsert_chunks(
                    source_name,
                    title,
                    chunks,
                    file_hash,
                    document=doc,
                    embeddings=embeddings,
                    qdrant_client=qdrant_client,
                    collection_name=collection_name,
                    extra_metadata=extra_metadata,
                    per_chunk_metadata=per_chunk_metadata,
                )
            except Exception:
                doc.delete()
                raise

            doc.chunk_count = created
            doc.save(update_fields=["chunk_count", "updated_at"])

            result.files_processed += 1
            result.chunks_created += created
            result.chunks_skipped_as_duplicates += skipped
            if log_fn:
                log_fn(
                    f"Ingested video {upload.name} as {source_name}: "
                    f"created {created} timestamped chunks, skipped {skipped} duplicates."
                )
            _persist_job_progress(job, result)
        except Exception as exc:
            if video_path is not None:
                try:
                    video_path.unlink(missing_ok=True)
                    _transcript_sidecar_path(video_path).unlink(missing_ok=True)
                except Exception:
                    pass
            result.files_failed += 1
            if job is not None:
                IngestionJobFileFailure.objects.create(
                    job=job,
                    original_name=upload.name,
                    error_message=str(exc),
                )
            if log_fn:
                log_fn(f"Video ingestion failed for {upload.name}: {exc}")
            logger.exception("Video ingestion failed for %s", upload.name)
            _persist_job_progress(job, result)
            continue

    _persist_job_progress(job, result)
    return result
