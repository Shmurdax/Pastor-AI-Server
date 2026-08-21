import json
import mimetypes
import shutil
import uuid
from django.contrib import admin
from django.contrib import messages
from django.conf import settings
from django.http import FileResponse
from django.http import HttpResponseRedirect
from django.http import Http404
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.utils import timezone
from django.urls import path, reverse
from django.core.paginator import Paginator
from django.core.paginator import EmptyPage
from django.utils.text import get_valid_filename
from pathlib import Path

from .ingestion_service import delete_ingested_documents
from .ingestion_tasks import StagedUpload, enqueue_ingestion_job, enqueue_video_ingestion_job
from .models import (
    ChatMessage,
    IngestedChunk,
    IngestedDocument,
    IngestionJob,
    IngestionJobFileFailure,
    IngestionJobLog,
    PrayerRequest,
    ChurchEvent,
)
from .storage_paths import admin_ingestion_dir, admin_video_ingestion_dir
from .video_ingestion import MEDIA_EXTENSIONS, VIDEO_ACCEPT_ATTRIBUTE, is_video_filename
from .vimeo_titles import DEFAULT_VIMEO_FOLDER_URL, VimeoTitleError, apply_titles_from_vimeo_folder
from .website_crawl.config import ALLOWED_DOMAINS
from .website_crawl.pipeline import enqueue_website_crawl_job


STALE_INGESTION_JOB_MINUTES = 30
STALE_VIDEO_INGESTION_JOB_MINUTES = 480
# Cloudflare named tunnels drop large multipart POSTs (often ~100s / ~100MB).
# Clients split each media file into pieces well under that limit.
VIDEO_UPLOAD_MAX_CHUNK_BYTES = 6 * 1024 * 1024
VIDEO_UPLOAD_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
VIDEO_UPLOAD_MAX_CHUNKS = 1024


def _mark_stale_running_jobs_failed() -> int:
    """
    Convert orphaned 'running' ingestion jobs to 'failed'.

    This handles process crashes/restarts where request cleanup never executes.
    Video jobs get a longer idle window because Whisper transcription of a
    full-length sermon can run for hours on CPU.
    """
    now = timezone.now()
    running = IngestionJob.objects.filter(status="running", finished_at__isnull=True)
    updated_count = 0
    for job in running:
        last_activity = job.updated_at or job.created_at
        idle_minutes = (
            STALE_VIDEO_INGESTION_JOB_MINUTES
            if job.job_kind == "video"
            else STALE_INGESTION_JOB_MINUTES
        )
        if last_activity >= now - timezone.timedelta(minutes=idle_minutes):
            continue
        if not job.error_message:
            job.error_message = (
                "Job was left in running state and auto-marked failed. "
                "The server/request likely stopped before completion."
            )
        job.status = "failed"
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
        IngestionJobLog.objects.create(
            job=job,
            message="Job auto-marked failed after exceeding stale running threshold.",
        )
        updated_count += 1
    return updated_count


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('sender_email', 'session_id', 'user_query', 'timestamp')
    search_fields = ('user__email', 'user__username', 'session_id', 'user_query')
    list_filter = ('timestamp',)
    raw_id_fields = ('user',)
    readonly_fields = ('sender_email', 'timestamp')

    @admin.display(description='Sender email', ordering='user__email')
    def sender_email(self, obj):
        """Show the login email when the chatter was signed in."""
        if obj.user_id is None:
            return '—'
        # Prefer the account email; fall back to username (often the email).
        return (obj.user.email or obj.user.get_username() or '—').strip() or '—'


@admin.register(IngestedDocument)
class IngestedDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "source_name", "source_kind", "original_extension", "chunk_count", "updated_at")
    search_fields = ("title", "source_name", "file_hash")
    list_filter = ("source_kind", "original_extension", "updated_at")
    readonly_fields = ("source_name", "file_hash", "original_extension", "source_kind", "chunk_count", "created_at", "updated_at")
    actions = ("delete_selected_with_vectors",)

    @admin.action(description="Delete selected documents from Django and Qdrant")
    def delete_selected_with_vectors(self, request, queryset):
        self._delete_docs_with_feedback(request, queryset)

    def delete_model(self, request, obj):
        self._delete_docs_with_feedback(request, [obj])

    def delete_queryset(self, request, queryset):
        self._delete_docs_with_feedback(request, queryset)

    def _delete_docs_with_feedback(self, request, documents):
        try:
            result = delete_ingested_documents(documents)
        except Exception as exc:
            self.message_user(
                request,
                f"Delete failed. No changes were completed: {exc}",
                level=messages.ERROR,
            )
            return

        if result.qdrant_failures:
            self.message_user(
                request,
                (
                    f"Deleted {result.deleted_count} document(s) in Django, but "
                    f"{result.qdrant_failures} Qdrant deletion(s) failed. Check logs and retry vector cleanup."
                ),
                level=messages.WARNING,
            )
            return

        self.message_user(
            request,
            f"Deleted {result.deleted_count} ingested document(s) and matching vectors from Qdrant.",
            level=messages.SUCCESS,
        )


@admin.register(IngestedChunk)
class IngestedChunkAdmin(admin.ModelAdmin):
    list_display = ("source_name", "position", "created_at")
    search_fields = ("source_name", "chunk_hash", "qdrant_point_id")
    list_filter = ("created_at",)
    readonly_fields = ("document", "chunk_hash", "qdrant_point_id", "source_name", "position", "created_at")


@admin.register(IngestionJob)
class IngestionJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "job_kind",
        "started_by",
        "status",
        "replace_existing_sources",
        "files_received",
        "files_processed",
        "chunks_created",
        "created_at",
        "finished_at",
    )
    search_fields = ("started_by", "error_message")
    list_filter = ("job_kind", "status", "replace_existing_sources", "created_at")
    readonly_fields = (
        "started_by",
        "job_kind",
        "replace_existing_sources",
        "status",
        "files_received",
        "files_processed",
        "files_skipped_as_duplicates",
        "files_failed",
        "chunks_created",
        "chunks_skipped_as_duplicates",
        "error_message",
        "created_at",
        "updated_at",
        "finished_at",
    )


class IngestionJobFileFailureInline(admin.TabularInline):
    model = IngestionJobFileFailure
    extra = 0
    can_delete = False
    readonly_fields = ("original_name", "error_message", "created_at")
    fields = ("created_at", "original_name", "error_message")


IngestionJobAdmin.inlines = [IngestionJobFileFailureInline]


@admin.register(IngestionJobFileFailure)
class IngestionJobFileFailureAdmin(admin.ModelAdmin):
    list_display = ("job", "created_at", "original_name")
    search_fields = ("original_name", "error_message", "job__id")
    list_filter = ("created_at",)
    readonly_fields = ("job", "original_name", "error_message", "created_at")


@admin.register(IngestionJobLog)
class IngestionJobLogAdmin(admin.ModelAdmin):
    list_display = ("job", "created_at", "message")
    search_fields = ("message",)
    list_filter = ("created_at",)
    readonly_fields = ("job", "message", "created_at")


def _is_ajax(request) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _stage_uploads(job: IngestionJob, files, *, staging_subdir: str) -> list[StagedUpload]:
    staging_root = Path(settings.BASE_DIR) / "uploads" / staging_subdir
    staging_dir = staging_root / f"job_{job.id}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_uploads: list[StagedUpload] = []
    for idx, upload in enumerate(files):
        safe_name = get_valid_filename(Path(upload.name).name) or f"upload_{idx}"
        staged_path = staging_dir / f"{idx:04d}_{safe_name}"
        with open(staged_path, "wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        staged_uploads.append(
            StagedUpload(
                original_name=upload.name,
                staged_path=str(staged_path),
            )
        )
    return staged_uploads


def _video_chunk_root() -> Path:
    return Path(settings.BASE_DIR) / "uploads" / "admin_video_ingestion_chunks"


def _parse_upload_id(raw: str) -> uuid.UUID:
    return uuid.UUID(str(raw or "").strip())


def _queue_video_job_from_path(
    *,
    started_by: str,
    original_name: str,
    source_path: Path,
    replace_existing_sources: bool,
) -> IngestionJob:
    job = IngestionJob.objects.create(
        started_by=started_by,
        job_kind="video",
        replace_existing_sources=replace_existing_sources,
        status="running",
        files_received=1,
    )
    staging_root = Path(settings.BASE_DIR) / "uploads" / "admin_video_ingestion_jobs"
    staging_dir = staging_root / f"job_{job.id}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    safe_name = get_valid_filename(Path(original_name).name) or "upload"
    staged_path = staging_dir / f"0000_{safe_name}"
    shutil.copyfile(source_path, staged_path)
    IngestionJobLog.objects.create(job=job, message="Video ingestion job queued for background processing.")
    enqueue_video_ingestion_job(
        job_id=job.id,
        staged_uploads=[StagedUpload(original_name=original_name, staged_path=str(staged_path))],
        replace_existing_sources=replace_existing_sources,
    )
    return job


def _admin_video_ingestion_chunk_view(request):
    if not request.user.is_staff:
        return JsonResponse({"ok": False, "error": "You must be an admin user to upload."}, status=403)
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required."}, status=405)

    file_name = (request.POST.get("file_name") or "").strip()
    if not is_video_filename(file_name):
        return JsonResponse({"ok": False, "error": "Only video and audio files are allowed."}, status=400)

    try:
        upload_id = _parse_upload_id(request.POST.get("upload_id") or "")
        chunk_index = int(request.POST.get("chunk_index", "-1"))
        chunk_count = int(request.POST.get("chunk_count", "-1"))
        file_size = int(request.POST.get("file_size", "-1"))
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "Invalid chunk metadata."}, status=400)

    if file_size < 0 or file_size > VIDEO_UPLOAD_MAX_FILE_BYTES:
        return JsonResponse({"ok": False, "error": "File size is missing or too large."}, status=400)
    if file_size == 0:
        return JsonResponse(
            {
                "ok": True,
                "complete": True,
                "skipped": True,
                "reason": "empty",
                "message": f"{file_name} is empty and will be skipped during ingest.",
            }
        )

    if chunk_index < 0 or chunk_count < 1 or chunk_index >= chunk_count:
        return JsonResponse({"ok": False, "error": "Invalid chunk index or count."}, status=400)
    if chunk_count > VIDEO_UPLOAD_MAX_CHUNKS:
        return JsonResponse({"ok": False, "error": "Too many chunks for one file."}, status=400)

    blob = request.FILES.get("chunk")
    if blob is None:
        return JsonResponse({"ok": False, "error": "Missing chunk payload."}, status=400)
    if blob.size > VIDEO_UPLOAD_MAX_CHUNK_BYTES:
        return JsonResponse({"ok": False, "error": "Chunk is too large for the tunnel."}, status=400)

    chunk_dir = _video_chunk_root() / str(upload_id)
    chunk_dir.mkdir(parents=True, exist_ok=True)
    meta_path = chunk_dir / "meta.json"
    done_path = chunk_dir / "done.json"
    replace_existing_sources = request.POST.get("replace_existing_sources") == "on"

    if done_path.is_file():
        try:
            done = json.loads(done_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            done = {}
        return JsonResponse({"ok": True, "complete": True, "job_id": done.get("job_id"), "duplicate": True})

    meta = {
        "file_name": file_name,
        "file_size": file_size,
        "chunk_count": chunk_count,
        "replace_existing_sources": replace_existing_sources,
    }
    if meta_path.is_file():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if (
            existing.get("file_name") != file_name
            or int(existing.get("file_size") or 0) != file_size
            or int(existing.get("chunk_count") or 0) != chunk_count
        ):
            return JsonResponse({"ok": False, "error": "Chunk metadata does not match this upload."}, status=400)
    else:
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    part_path = chunk_dir / f"{chunk_index:06d}.part"
    with open(part_path, "wb") as out:
        for block in blob.chunks():
            out.write(block)

    received = sorted(int(path.stem) for path in chunk_dir.glob("*.part") if path.stem.isdigit())
    if len(received) < chunk_count:
        return JsonResponse(
            {
                "ok": True,
                "complete": False,
                "received": chunk_index,
                "parts": len(received),
                "chunk_count": chunk_count,
            }
        )

    assembled_path = chunk_dir / "assembled.bin"
    with open(assembled_path, "wb") as out:
        for index in range(chunk_count):
            part = chunk_dir / f"{index:06d}.part"
            if not part.is_file():
                return JsonResponse({"ok": False, "error": f"Missing chunk {index}."}, status=400)
            with open(part, "rb") as src:
                shutil.copyfileobj(src, out)
    assembled_size = assembled_path.stat().st_size
    if assembled_size != file_size:
        assembled_path.unlink(missing_ok=True)
        return JsonResponse(
            {
                "ok": False,
                "error": f"Assembled size {assembled_size} does not match file_size {file_size}.",
            },
            status=400,
        )

    job = _queue_video_job_from_path(
        started_by=request.user.get_username() or "admin",
        original_name=file_name,
        source_path=assembled_path,
        replace_existing_sources=replace_existing_sources,
    )
    done_path.write_text(json.dumps({"job_id": job.id}), encoding="utf-8")
    for leftover in chunk_dir.glob("*.part"):
        leftover.unlink(missing_ok=True)
    assembled_path.unlink(missing_ok=True)
    return JsonResponse(
        {
            "ok": True,
            "complete": True,
            "job_id": job.id,
            "files_received": 1,
            "message": f"Media ingestion job #{job.id} queued for {file_name}.",
        }
    )


def _admin_ingestion_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    stale_fixed = _mark_stale_running_jobs_failed()
    if stale_fixed:
        messages.warning(
            request,
            f"Recovered {stale_fixed} stale ingestion job(s) that were stuck in running state.",
        )

    if request.method == "POST":
        ajax = _is_ajax(request)
        files = request.FILES.getlist("documents")
        replace_existing_sources = request.POST.get("replace_existing_sources") == "on"
        if not files:
            if ajax:
                return JsonResponse({"ok": False, "error": "Select at least one DOCX or PDF file."}, status=400)
            messages.warning(request, "Select at least one DOCX or PDF file.")
            return HttpResponseRedirect(request.path)

        job = IngestionJob.objects.create(
            started_by=request.user.get_username() or "admin",
            job_kind="document",
            replace_existing_sources=replace_existing_sources,
            status="running",
            files_received=len(files),
        )

        try:
            staged_uploads = _stage_uploads(job, files, staging_subdir="admin_ingestion_jobs")

            IngestionJobLog.objects.create(job=job, message="Ingestion job queued for background processing.")
            enqueue_ingestion_job(
                job_id=job.id,
                staged_uploads=staged_uploads,
                replace_existing_sources=replace_existing_sources,
            )
            messages.success(
                request,
                f"Ingestion started in background (job #{job.id}). Refresh this page to monitor progress.",
            )
            if ajax:
                return JsonResponse(
                    {
                        "ok": True,
                        "job_id": job.id,
                        "files_received": len(files),
                        "message": f"Ingestion job #{job.id} queued with {len(files)} file(s).",
                    }
                )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
            IngestionJobLog.objects.create(job=job, message=f"Ingestion failed: {exc}")
            messages.error(request, f"Ingestion failed (job #{job.id}): {exc}")
            if ajax:
                return JsonResponse(
                    {"ok": False, "error": str(exc), "job_id": job.id},
                    status=500,
                )
        return HttpResponseRedirect(request.path)

    context = {
        **admin.site.each_context(request),
        "title": "Admin Document Ingestion",
        "latest_jobs": IngestionJob.objects.exclude(job_kind="video")[:10],
    }
    return TemplateResponse(request, "admin/core/ingestion.html", context)


def _admin_video_ingestion_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    stale_fixed = _mark_stale_running_jobs_failed()
    if stale_fixed:
        messages.warning(
            request,
            f"Recovered {stale_fixed} stale ingestion job(s) that were stuck in running state.",
        )

    if request.method == "POST":
        ajax = _is_ajax(request)
        files = request.FILES.getlist("videos")
        replace_existing_sources = request.POST.get("replace_existing_sources") == "on"
        if not files:
            if ajax:
                return JsonResponse({"ok": False, "error": "Select at least one video or audio file."}, status=400)
            messages.warning(request, "Select at least one video or audio file.")
            return HttpResponseRedirect(request.path)

        unsupported = [upload.name for upload in files if not is_video_filename(upload.name)]
        if unsupported:
            shown = unsupported[:15]
            extra = "" if len(unsupported) <= 15 else f" (and {len(unsupported) - 15} more)"
            detail = "Only video and audio files are allowed. Ignored: " + ", ".join(shown) + extra
            if ajax:
                return JsonResponse({"ok": False, "error": detail}, status=400)
            messages.warning(request, detail)
            return HttpResponseRedirect(request.path)

        job = IngestionJob.objects.create(
            started_by=request.user.get_username() or "admin",
            job_kind="video",
            replace_existing_sources=replace_existing_sources,
            status="running",
            files_received=len(files),
        )

        try:
            staged_uploads = _stage_uploads(job, files, staging_subdir="admin_video_ingestion_jobs")
            IngestionJobLog.objects.create(job=job, message="Video ingestion job queued for background processing.")
            enqueue_video_ingestion_job(
                job_id=job.id,
                staged_uploads=staged_uploads,
                replace_existing_sources=replace_existing_sources,
            )
            messages.success(
                request,
                f"Video ingestion started in background (job #{job.id}). Refresh this page to monitor progress.",
            )
            if ajax:
                return JsonResponse(
                    {
                        "ok": True,
                        "job_id": job.id,
                        "files_received": len(files),
                        "message": f"Media ingestion job #{job.id} queued with {len(files)} file(s).",
                    }
                )
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
            IngestionJobLog.objects.create(job=job, message=f"Video ingestion failed: {exc}")
            messages.error(request, f"Video ingestion failed (job #{job.id}): {exc}")
            if ajax:
                return JsonResponse(
                    {"ok": False, "error": str(exc), "job_id": job.id},
                    status=500,
                )
        return HttpResponseRedirect(request.path)

    context = {
        **admin.site.each_context(request),
        "title": "Admin Video Ingestion",
        "latest_jobs": IngestionJob.objects.filter(job_kind="video")[:10],
        "video_accept": VIDEO_ACCEPT_ATTRIBUTE,
        "video_extensions": sorted(MEDIA_EXTENSIONS),
        "video_chunk_url": reverse("admin:core_video_ingestion_chunk"),
        "video_chunk_bytes": 2 * 1024 * 1024,
    }
    return TemplateResponse(request, "admin/core/video_ingestion.html", context)


def _admin_website_crawl_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    stale_fixed = _mark_stale_running_jobs_failed()
    if stale_fixed:
        messages.warning(
            request,
            f"Recovered {stale_fixed} stale ingestion job(s) that were stuck in running state.",
        )

    if request.method == "POST":
        replace_existing_sources = request.POST.get("replace_existing_sources") == "on"
        try:
            job = enqueue_website_crawl_job(
                started_by=request.user.get_username() or "admin",
                replace_existing_sources=replace_existing_sources,
            )
            messages.success(
                request,
                f"Website crawl started in background (job #{job.id}). Refresh this page to monitor progress.",
            )
        except Exception as exc:
            messages.error(request, f"Website crawl failed to start: {exc}")
        return HttpResponseRedirect(request.path)

    context = {
        **admin.site.each_context(request),
        "title": "Website Crawl → RAG",
        "latest_jobs": IngestionJob.objects.filter(job_kind="website")[:15],
        "allowlisted_domains": sorted(ALLOWED_DOMAINS),
    }
    return TemplateResponse(request, "admin/core/website_crawl.html", context)


def _admin_ingested_documents_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    upload_dir = admin_ingestion_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    search_term = request.GET.get("q", "").strip()
    allowed_page_sizes = [25, 50, 100]
    page_size_raw = request.GET.get("page_size", "50")
    try:
        page_size = int(page_size_raw)
    except ValueError:
        page_size = 50
    if page_size not in allowed_page_sizes:
        page_size = 50
    documents = []
    for file_path in upload_dir.glob("*.pdf"):
        if search_term and search_term.lower() not in file_path.name.lower():
            continue
        file_stat = file_path.stat()
        documents.append(
            {
                "name": file_path.name,
                "modified_at": timezone.datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.get_current_timezone()),
                "size_bytes": file_stat.st_size,
            }
        )
    documents.sort(key=lambda item: item["modified_at"], reverse=True)
    documents_count = len(documents)
    paginator = Paginator(documents, page_size)
    page_number = request.GET.get("page", "1")
    try:
        page_obj = paginator.get_page(page_number)
    except EmptyPage:
        page_obj = paginator.get_page(1)

    context = {
        **admin.site.each_context(request),
        "title": "Ingested Documents",
        "documents": page_obj.object_list,
        "search_term": search_term,
        "documents_count": documents_count,
        "page_obj": page_obj,
        "paginator": paginator,
        "page_size": page_size,
        "allowed_page_sizes": allowed_page_sizes,
    }
    return TemplateResponse(request, "admin/core/ingested_documents.html", context)


def _admin_ingested_document_file_view(request, file_name: str):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this file.")
        return HttpResponseRedirect("../")

    upload_dir = admin_ingestion_dir()
    file_path = (upload_dir / file_name).resolve()

    if not file_path.is_file():
        raise Http404("Document file was not found.")

    try:
        file_path.relative_to(upload_dir)
    except ValueError as exc:
        raise Http404("Invalid file path.") from exc

    if file_path.suffix.lower() != ".pdf":
        raise Http404("Only PDF files are available from this endpoint.")

    return FileResponse(open(file_path, "rb"), content_type="application/pdf")


def _admin_ingested_videos_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    if request.method == "POST" and request.POST.get("action") == "apply_vimeo_titles":
        folder_url = (request.POST.get("vimeo_folder_url") or DEFAULT_VIMEO_FOLDER_URL).strip()
        token = (request.POST.get("vimeo_access_token") or "").strip()
        dry_run = request.POST.get("dry_run") == "on"
        try:
            _mapping, result = apply_titles_from_vimeo_folder(
                folder_url=folder_url,
                token=token,
                dry_run=dry_run,
                update_qdrant=not dry_run,
            )
        except VimeoTitleError as exc:
            messages.error(request, str(exc))
        else:
            prefix = "Dry run — would update" if dry_run else "Updated"
            messages.success(
                request,
                f"{prefix} {result.updated} video title(s). "
                f"Already matched: {result.already_matched}. "
                f"No Vimeo name for {result.unmatched} file(s).",
            )
            for source_name, old_title, new_title in result.sample_updates:
                messages.info(request, f"{source_name}: {old_title} → {new_title}")
        return HttpResponseRedirect(request.path)

    upload_dir = admin_video_ingestion_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    search_term = request.GET.get("q", "").strip()
    allowed_page_sizes = [25, 50, 100]
    page_size_raw = request.GET.get("page_size", "50")
    try:
        page_size = int(page_size_raw)
    except ValueError:
        page_size = 50
    if page_size not in allowed_page_sizes:
        page_size = 50
    videos = []
    for file_path in upload_dir.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() == ".json":
            continue
        if file_path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        if search_term and search_term.lower() not in file_path.name.lower():
            continue
        file_stat = file_path.stat()
        sidecar = file_path.with_suffix(".transcript.json")
        videos.append(
            {
                "name": file_path.name,
                "modified_at": timezone.datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.get_current_timezone()),
                "size_bytes": file_stat.st_size,
                "has_transcript": sidecar.is_file(),
                "transcript_name": sidecar.name,
            }
        )
    videos.sort(key=lambda item: item["modified_at"], reverse=True)
    videos_count = len(videos)
    paginator = Paginator(videos, page_size)
    page_number = request.GET.get("page", "1")
    try:
        page_obj = paginator.get_page(page_number)
    except EmptyPage:
        page_obj = paginator.get_page(1)

    context = {
        **admin.site.each_context(request),
        "title": "Ingested Videos",
        "videos": page_obj.object_list,
        "search_term": search_term,
        "videos_count": videos_count,
        "page_obj": page_obj,
        "paginator": paginator,
        "page_size": page_size,
        "allowed_page_sizes": allowed_page_sizes,
        "vimeo_folder_url": DEFAULT_VIMEO_FOLDER_URL,
    }
    return TemplateResponse(request, "admin/core/ingested_videos.html", context)


def _admin_ingested_video_file_view(request, file_name: str):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this file.")
        return HttpResponseRedirect("../")

    upload_dir = admin_video_ingestion_dir()
    file_path = (upload_dir / file_name).resolve()

    if not file_path.is_file():
        raise Http404("Video file was not found.")

    try:
        file_path.relative_to(upload_dir)
    except ValueError as exc:
        raise Http404("Invalid file path.") from exc

    suffix = file_path.suffix.lower()
    if suffix not in MEDIA_EXTENSIONS and suffix != ".json":
        raise Http404("Only ingested media files and transcripts are available from this endpoint.")

    content_type, _ = mimetypes.guess_type(str(file_path))
    if suffix == ".json":
        content_type = "application/json"
    return FileResponse(
        open(file_path, "rb"),
        content_type=content_type or "application/octet-stream",
    )


def _get_urls():
    custom_urls = [
        path(
            "core/ingestion/",
            admin.site.admin_view(_admin_ingestion_view),
            name="core_ingestion",
        ),
        path(
            "core/video-ingestion/",
            admin.site.admin_view(_admin_video_ingestion_view),
            name="core_video_ingestion",
        ),
        path(
            "core/video-ingestion/chunk/",
            admin.site.admin_view(_admin_video_ingestion_chunk_view),
            name="core_video_ingestion_chunk",
        ),
        path(
            "core/website-crawl/",
            admin.site.admin_view(_admin_website_crawl_view),
            name="core_website_crawl",
        ),
        path(
            "core/ingested-documents/",
            admin.site.admin_view(_admin_ingested_documents_view),
            name="core_ingested_documents",
        ),
        path(
            "core/ingested-documents/file/<path:file_name>/",
            admin.site.admin_view(_admin_ingested_document_file_view),
            name="core_ingested_document_file",
        ),
        path(
            "core/ingested-videos/",
            admin.site.admin_view(_admin_ingested_videos_view),
            name="core_ingested_videos",
        ),
        path(
            "core/ingested-videos/file/<path:file_name>/",
            admin.site.admin_view(_admin_ingested_video_file_view),
            name="core_ingested_video_file",
        ),
    ]
    return custom_urls + _original_get_urls()


_original_get_urls = admin.site.get_urls
admin.site.get_urls = _get_urls


def _get_app_list(request, app_label=None):
    app_list = _original_get_app_list(request, app_label=app_label)
    for app_dict in app_list:
        if app_dict.get("app_label") != "core":
            continue

        existing_object_names = {model.get("object_name") for model in app_dict.get("models", [])}
        custom_entries = []
        if "CoreIngestionTool" not in existing_object_names:
            custom_entries.append(
                {
                    "name": "Document Ingestion",
                    "object_name": "CoreIngestionTool",
                    "admin_url": reverse("admin:core_ingestion"),
                    "add_url": None,
                    "view_only": True,
                    "perms": {"add": False, "change": True, "delete": False, "view": True},
                }
            )
        if "CoreVideoIngestionTool" not in existing_object_names:
            custom_entries.append(
                {
                    "name": "Video Ingestion",
                    "object_name": "CoreVideoIngestionTool",
                    "admin_url": reverse("admin:core_video_ingestion"),
                    "add_url": None,
                    "view_only": True,
                    "perms": {"add": False, "change": True, "delete": False, "view": True},
                }
            )
        if "CoreWebsiteCrawlTool" not in existing_object_names:
            custom_entries.append(
                {
                    "name": "Website Crawl → RAG",
                    "object_name": "CoreWebsiteCrawlTool",
                    "admin_url": reverse("admin:core_website_crawl"),
                    "add_url": None,
                    "view_only": True,
                    "perms": {"add": False, "change": True, "delete": False, "view": True},
                }
            )
        if "CoreIngestedDocumentsTool" not in existing_object_names:
            custom_entries.append(
                {
                    "name": "Ingested Documents Browser",
                    "object_name": "CoreIngestedDocumentsTool",
                    "admin_url": reverse("admin:core_ingested_documents"),
                    "add_url": None,
                    "view_only": True,
                    "perms": {"add": False, "change": True, "delete": False, "view": True},
                }
            )
        if "CoreIngestedVideosTool" not in existing_object_names:
            custom_entries.append(
                {
                    "name": "Ingested Videos Browser",
                    "object_name": "CoreIngestedVideosTool",
                    "admin_url": reverse("admin:core_ingested_videos"),
                    "add_url": None,
                    "view_only": True,
                    "perms": {"add": False, "change": True, "delete": False, "view": True},
                }
            )

        app_dict.setdefault("models", []).extend(custom_entries)
        app_dict["models"].sort(key=lambda model: model.get("name", "").lower())
        break

    return app_list


_original_get_app_list = admin.site.get_app_list
admin.site.get_app_list = _get_app_list
admin.site.index_template = "admin/core_home.html"


@admin.register(PrayerRequest)
class PrayerRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'display_name',
        'contact_email',
        'phone',
        'prayer_preview',
        'is_anonymous',
        'followed_up',
        'created_at',
    )
    list_filter = ('is_anonymous', 'followed_up', 'created_at')
    search_fields = ('name', 'email', 'phone', 'prayer_text', 'pastor_notes')
    date_hierarchy = 'created_at'
    list_editable = ('followed_up',)
    readonly_fields = (
        'created_at',
        'linked_account',
    )
    fieldsets = (
        (
            'Contact',
            {
                'fields': (
                    'name',
                    'email',
                    'phone',
                    'is_anonymous',
                    'linked_account',
                ),
            },
        ),
        (
            'Prayer request',
            {
                'fields': ('prayer_text', 'created_at'),
            },
        ),
        (
            'Follow-up',
            {
                'fields': ('followed_up', 'contacted_at', 'pastor_notes'),
            },
        ),
        (
            'Submission meta',
            {
                'classes': ('collapse',),
                'fields': ('user',),
            },
        ),
    )

    @admin.display(description='Name')
    def display_name(self, obj):
        if obj.is_anonymous:
            return 'Anonymous'
        return obj.name or '—'

    @admin.display(description='Email')
    def contact_email(self, obj):
        from django.utils.html import format_html

        if obj.email:
            return format_html('<a href="mailto:{}">{}</a>', obj.email, obj.email)
        if obj.user_id:
            return format_html(
                '<a href="mailto:{}">{} (account)</a>',
                obj.user.email,
                obj.user.email,
            )
        return '—'

    @admin.display(description='Request preview')
    def prayer_preview(self, obj):
        text = (obj.prayer_text or '').replace('\n', ' ').strip()
        if len(text) > 80:
            text = f'{text[:77]}...'
        return text or '—'

    @admin.display(description='Linked sign-in account')
    def linked_account(self, obj):
        from django.utils.html import format_html

        if obj.user_id is None:
            return '—'
        label = obj.user.get_full_name() or obj.user.username
        return format_html('{} &lt;{}&gt;', label, obj.user.email)


@admin.register(ChurchEvent)
class ChurchEventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "starts_at",
        "location",
        "host_name",
        "is_published",
        "updated_at",
    )
    list_filter = ("is_published", "starts_at")
    search_fields = ("title", "location", "host_name", "description")
    date_hierarchy = "starts_at"
    list_editable = ("is_published",)
