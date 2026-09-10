"""
Admin video/audio ingestion pipeline:

1. Store the original file under ``uploads/admin_video_ingestion``.
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

from .document_titles import normalize_title_key, prettify_title
from .embeddings_utils import get_embeddings
from .ingestion_service import (
    DEFAULT_SPLITTER_KWARGS,
    IngestionResult,
    _clean_text,
    _delete_source_from_qdrant,
    _find_near_duplicate,
    _near_duplicate_reason,
    _persist_job_progress,
    _safe_upload_stem,
    _sha256_bytes,
    _sha256_text,
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
from .video_topic_metadata import (
    VideoTopicMetadata,
    build_topic_overview_chunk,
    build_video_topic_metadata,
    display_title_for_document,
    format_searchable_header,
    prepend_searchable_header,
    qdrant_metadata_from_topic,
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

AUDIO_EXTENSIONS = {
    ".m4a",
    ".m4b",
    ".mp3",
    ".mpga",
    ".mp2",
    ".wav",
    ".wave",
    ".aac",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".wma",
    ".aiff",
    ".aif",
    ".amr",
    ".ac3",
    ".mka",
    ".weba",
    ".caf",
    ".3ga",
}

MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

VIDEO_ACCEPT_ATTRIBUTE = (
    "video/*,audio/*," + ",".join(sorted(MEDIA_EXTENSIONS))
)


def is_media_filename(name: str) -> bool:
    return Path(name or "").suffix.lower() in MEDIA_EXTENSIONS


def is_audio_filename(name: str) -> bool:
    return Path(name or "").suffix.lower() in AUDIO_EXTENSIONS


def is_video_filename(name: str) -> bool:
    """True for video or audio containers accepted by Whisper ingest."""
    return is_media_filename(name)


def _canonical_video_name(original_name: str) -> str:
    stem = _safe_upload_stem(original_name)
    suffix = Path(original_name).suffix.lower()
    if suffix not in MEDIA_EXTENSIONS:
        suffix = suffix if suffix else ".mp4"
    return f"{stem}{suffix}"


def _transcript_sidecar_path(video_path: Path) -> Path:
    return video_path.with_suffix(".transcript.json")


def _replace_existing_video(original_name: str) -> None:
    stem = _safe_upload_stem(original_name)
    upload_dir = admin_video_ingestion_dir()
    names = {original_name, _canonical_video_name(original_name)}
    for ext in MEDIA_EXTENSIONS:
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
    topic_metadata: Optional[dict] = None,
) -> None:
    payload = {
        "title": title,
        "source_name": source_name,
        "whisper_model": os.getenv("WHISPER_MODEL") or "base",
        "stats": stats,
        "topic_metadata": topic_metadata or {},
        "segments_raw": [
            {"start": seg.start, "end": seg.end, "text": seg.text} for seg in raw_segments
        ],
        "segments_normalized": [
            {"start": seg.start, "end": seg.end, "text": seg.text} for seg in normalized
        ],
    }
    sidecar = _transcript_sidecar_path(video_path)
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_video_chunks_with_topic_metadata(
    *,
    original_title: str,
    normalized_segments: Sequence[TranscriptSegment],
    normalized_text: str,
    chunk_size: int,
    overlap_segments: int = 1,
    topic_metadata: Optional[VideoTopicMetadata] = None,
) -> tuple[VideoTopicMetadata, str, List[str], List[dict]]:
    """Build embeddable chunks + per-chunk metadata with a searchable topic header."""
    meta = topic_metadata or build_video_topic_metadata(
        normalized_text,
        original_title=original_title,
    )
    display_title = display_title_for_document(meta, original_title)
    header = format_searchable_header(meta, display_title=display_title)

    groups = group_segments_into_chunks(
        normalized_segments,
        chunk_size=chunk_size,
        overlap_segments=overlap_segments,
    )
    chunks = [
        _clean_text(prepend_searchable_header(_chunk_text_from_group(display_title, group), header))
        for group in groups
    ]
    chunks = [chunk for chunk in chunks if chunk]
    if not chunks:
        splitter = RecursiveCharacterTextSplitter(**DEFAULT_SPLITTER_KWARGS)
        markdown_text = prepend_searchable_header(_to_markdown(display_title, normalized_text), header)
        chunks = [_clean_text(c) for c in splitter.split_text(markdown_text) if _clean_text(c)]
        groups = [list(normalized_segments) for _ in chunks]

    per_chunk_metadata: List[dict] = []
    for group in groups:
        start_s = group[0].start if group else 0.0
        end_s = group[-1].end if group else start_s
        per_chunk_metadata.append(
            {
                "start_s": start_s,
                "end_s": end_s,
                "timestamp": format_timestamp_range(start_s, end_s),
                "chunk_kind": "video_transcript",
            }
        )

    overview = _clean_text(build_topic_overview_chunk(meta))
    if overview:
        # Put the overview first so topic-only queries can hit it strongly.
        chunks.insert(0, overview)
        end_s = normalized_segments[-1].end if normalized_segments else 0.0
        per_chunk_metadata.insert(
            0,
            {
                "start_s": 0.0,
                "end_s": end_s,
                "timestamp": format_timestamp_range(0.0, end_s),
                "chunk_kind": "video_topic_overview",
            },
        )

    return meta, display_title, chunks, per_chunk_metadata


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
            if extension not in MEDIA_EXTENSIONS:
                if log_fn:
                    log_fn(f"Skipped unsupported media type: {upload.name}")
                continue

            if log_fn:
                kind = "audio" if extension in AUDIO_EXTENSIONS else "video"
                log_fn(f"Processing {kind}: {upload.name}")
            _persist_job_progress(job, result, current_file=upload.name)

            if replace_existing_sources:
                _replace_existing_video(upload.name)
                if log_fn:
                    log_fn(f"Replaced previous video source data for: {upload.name}")

            raw_content = upload.read()
            if not raw_content:
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(f"Empty media file skipped (0 bytes): {upload.name}")
                _persist_job_progress(job, result, current_file=upload.name)
                continue

            file_hash = _sha256_bytes(raw_content)
            title = prettify_title(upload.name)
            normalized_title = normalize_title_key(upload.name)
            existing = _find_near_duplicate(
                file_hash=file_hash,
                normalized_title=normalized_title,
            )
            if existing is not None:
                reason = _near_duplicate_reason(
                    existing,
                    file_hash=file_hash,
                    content_hash="",
                    normalized_title=normalized_title,
                )
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(
                        f"Near-duplicate media skipped ({reason}): {upload.name} "
                        f"matches existing “{existing.title}” ({existing.source_name})."
                    )
                _persist_job_progress(job, result, current_file=upload.name)
                continue

            source_name = _canonical_video_name(upload.name)
            video_path = upload_dir / source_name
            video_path.write_bytes(raw_content)

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
                _persist_job_progress(job, result, current_file=upload.name)
                continue

            content_hash = _sha256_text(normalized.text)
            existing_content = _find_near_duplicate(
                file_hash=file_hash,
                normalized_title=normalized_title,
                content_hash=content_hash,
            )
            if existing_content is not None:
                reason = _near_duplicate_reason(
                    existing_content,
                    file_hash=file_hash,
                    content_hash=content_hash,
                    normalized_title=normalized_title,
                )
                video_path.unlink(missing_ok=True)
                _transcript_sidecar_path(video_path).unlink(missing_ok=True)
                result.files_skipped_as_duplicates += 1
                if log_fn:
                    log_fn(
                        f"Near-duplicate media skipped ({reason}): {upload.name} "
                        f"matches existing “{existing_content.title}” ({existing_content.source_name})."
                    )
                _persist_job_progress(job, result, current_file=upload.name)
                continue

            if log_fn:
                log_fn(f"Building topic metadata for {source_name}…")
            topic_meta, display_title, chunks, per_chunk_metadata = build_video_chunks_with_topic_metadata(
                original_title=title,
                normalized_segments=normalized.segments,
                normalized_text=normalized.text,
                chunk_size=chunk_size,
                overlap_segments=overlap_segments,
            )
            topic_payload = topic_meta.as_dict()
            _write_transcript_sidecar(
                video_path,
                title=display_title,
                source_name=source_name,
                raw_segments=raw_segments,
                normalized=normalized.segments,
                stats=normalized.stats.as_dict(),
                topic_metadata=topic_payload,
            )

            extra_metadata = {
                "content_type": "video_transcript",
                "media_type": "video",
                **qdrant_metadata_from_topic(topic_meta),
            }
            named = extra_metadata_by_name.get(upload.name) or extra_metadata_by_name.get(source_name)
            if named:
                extra_metadata.update(named)

            doc = IngestedDocument.objects.create(
                source_name=source_name,
                title=display_title,
                normalized_title=normalized_title,
                file_hash=file_hash,
                content_hash=content_hash,
                original_extension=extension,
                source_kind="video",
                topic_metadata=topic_payload,
            )

            try:
                created, skipped = _upsert_chunks(
                    source_name,
                    display_title,
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
                    f"Ingested video {upload.name} as {source_name} "
                    f"(title “{display_title}”, topics={topic_meta.topics[:4]}): "
                    f"created {created} timestamped chunks, skipped {skipped} duplicates."
                )
            _persist_job_progress(job, result, current_file=upload.name)
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
            _persist_job_progress(job, result, current_file=upload.name)
            continue

    if job is not None:
        _persist_job_progress(job, result, current_file="")
    return result
