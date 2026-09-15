"""Re-chunk existing PDFs, markdown, and video transcripts for quote-level RAG.

Does not re-run Whisper. Uses stored PDFs under the ingestion upload dir and
``.transcript.json`` sidecars for videos. NKJV files are split verse-by-verse.

Example::

    python manage.py reingest_grounded_rag
    python manage.py reingest_grounded_rag --bible-only
    python manage.py reingest_grounded_rag --videos-only --limit 5
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand

from core.ingestion_service import ingest_uploaded_files
from core.models import IngestedDocument
from core.storage_paths import admin_ingestion_dir, admin_video_ingestion_dir
from core.transcript_normalize import TranscriptSegment
from core.video_ingestion import (
    _transcript_sidecar_path,
    ingest_video_files,
)


class Command(BaseCommand):
    help = "Reingest sermons, NKJV, and videos as quote-level / verse-level chunks."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--source", default="", help="Substring match on source_name.")
        parser.add_argument("--bible-only", action="store_true")
        parser.add_argument("--videos-only", action="store_true")
        parser.add_argument("--documents-only", action="store_true")

    def handle(self, *args, **options):
        limit = int(options.get("limit") or 0)
        needle = str(options.get("source") or "").strip().lower()
        bible_only = bool(options.get("bible_only"))
        videos_only = bool(options.get("videos_only"))
        documents_only = bool(options.get("documents_only"))

        qs = IngestedDocument.objects.all().order_by("source_kind", "source_name")
        if needle:
            qs = qs.filter(source_name__icontains=needle)

        processed = 0
        skipped = 0
        failed = 0

        def log(message: str) -> None:
            self.stdout.write(message)

        for doc in qs:
            if limit and processed >= limit:
                break
            kind = doc.source_kind
            name = (doc.source_name or "").lower()
            is_bible = any(
                marker in name for marker in ("nkjv", "bible", "king james", "scripture")
            )
            if bible_only and not is_bible:
                continue
            if videos_only and kind != "video":
                continue
            if documents_only and kind == "video":
                continue
            try:
                if kind == "video":
                    ok = self._reingest_video(doc, log)
                else:
                    ok = self._reingest_document(doc, log)
            except Exception as exc:
                failed += 1
                log(f"FAILED {doc.source_name}: {exc}")
                continue
            if ok:
                processed += 1
            else:
                skipped += 1

        log(f"Done. reingested={processed} skipped={skipped} failed={failed}")

    def _reingest_document(self, doc: IngestedDocument, log) -> bool:
        path = admin_ingestion_dir() / Path(doc.source_name).name
        if not path.is_file():
            log(f"Skip {doc.source_name}: PDF not on disk at {path}")
            return False
        data = path.read_bytes()
        upload = SimpleUploadedFile(path.name, data, content_type="application/pdf")
        result = ingest_uploaded_files(
            [upload],
            replace_existing_sources=True,
            log_fn=log,
        )
        log(
            f"Document {doc.source_name}: processed={result.files_processed} "
            f"chunks={result.chunks_created} skipped={result.files_skipped_as_duplicates}"
        )
        return result.files_processed > 0 or result.chunks_created > 0

    def _reingest_video(self, doc: IngestedDocument, log) -> bool:
        upload_dir = admin_video_ingestion_dir()
        media = upload_dir / Path(doc.source_name).name
        sidecar = _transcript_sidecar_path(media)
        if not sidecar.is_file():
            log(f"Skip {doc.source_name}: no transcript sidecar")
            return False
        if not media.is_file():
            log(f"Skip {doc.source_name}: media file missing")
            return False
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        rows = payload.get("segments_normalized") or payload.get("segments_raw") or []
        segments = []
        for row in rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    start=float(row.get("start") or 0.0),
                    end=float(row.get("end") or 0.0),
                    text=text,
                )
            )
        if not segments:
            log(f"Skip {doc.source_name}: empty transcript")
            return False

        class _Upload:
            name = media.name

            def read(self):
                return media.read_bytes()

        result = ingest_video_files(
            [_Upload()],
            replace_existing_sources=True,
            log_fn=log,
            transcribe_fn=lambda _path: segments,
        )
        log(
            f"Video {doc.source_name}: processed={result.files_processed} "
            f"chunks={result.chunks_created}"
        )
        return result.files_processed > 0
