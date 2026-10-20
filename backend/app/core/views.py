import os
import logging
import hmac
import hashlib
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.http import FileResponse
from django.http import Http404
from django.urls import reverse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

from api.permissions import HasPremiumAccess

from .models import ChatMessage, IngestedDocument, PrayerRequest, ResponseReport
from .bible_refs import scripture_refs_from_metadata
from .storage_paths import ingested_media_path

logger = logging.getLogger(__name__)
PUBLIC_API_KEY = os.getenv("PUBLIC_API_KEY", "").strip()
SESSION_SCOPE_SALT = os.getenv("SESSION_SCOPE_SALT", settings.SECRET_KEY)
_SOURCE_TIMESTAMP_RE = re.compile(r"\s*\[[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?–[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\]\s*$")
_SOURCE_MEDIA_EXTS = {".pdf", ".md", ".docx", ".txt"} | {
    ".mp4",
    ".m4v",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
    ".3gp",
    ".ogv",
    ".ts",
    ".mts",
    ".m2ts",
}


def _strip_source_label(name: str) -> str:
    raw = (name or "").strip()
    raw = _SOURCE_TIMESTAMP_RE.sub("", raw).strip()
    suffix = Path(raw).suffix.lower()
    if suffix in _SOURCE_MEDIA_EXTS:
        return Path(raw).stem.strip()
    return raw


def _library_documents():
    """Sermon-library catalog: RAG may still use rows with in_library=False."""
    return IngestedDocument.objects.filter(in_library=True)


def hidden_library_matchers() -> tuple[set[str], set[str]]:
    """file_hashes and lowercased titles/stems that members must not see or open."""
    hashes: set[str] = set()
    names: set[str] = set()
    for file_hash, title, source_name in IngestedDocument.objects.filter(in_library=False).values_list(
        "file_hash", "title", "source_name"
    ):
        if file_hash:
            hashes.add(str(file_hash))
        for value in (title, source_name):
            raw = (value or "").strip().lower()
            if raw:
                names.add(raw)
            stem = _strip_source_label(value or "").strip().lower()
            if stem:
                names.add(stem)
    return hashes, names


def chunk_is_in_library(
    doc,
    *,
    hidden_hashes: set[str],
    hidden_names: set[str],
) -> bool:
    """True when this retrieved chunk may appear as a member-facing sermon source."""
    metadata = getattr(doc, "metadata", {}) or {}
    file_hash = str(metadata.get("file_hash") or "").strip()
    if file_hash and file_hash in hidden_hashes:
        return False
    for key in ("source", "source_name", "title", "topic_title", "original_title"):
        value = str(metadata.get(key) or "").strip()
        if not value:
            continue
        if value.lower() in hidden_names:
            return False
        stem = _strip_source_label(value).strip().lower()
        if stem and stem in hidden_names:
            return False
    return True


def visible_chat_source_docs(docs):
    """Keep RAG chunks for prompting; drop hidden books from clickable sermon sources."""
    hidden_hashes, hidden_names = hidden_library_matchers()
    if not hidden_hashes and not hidden_names:
        return list(docs or [])
    return [
        doc
        for doc in list(docs or [])
        if chunk_is_in_library(doc, hidden_hashes=hidden_hashes, hidden_names=hidden_names)
    ]


def _file_response_for_document(document: IngestedDocument, *, download: bool = False):
    source_name = document.source_name or ""
    file_path = ingested_media_path(source_name, document.source_kind)
    if not file_path.is_file():
        raise Http404("Document file was not found on disk.")
    root = file_path.parent
    try:
        file_path.relative_to(root)
    except ValueError as exc:
        raise Http404("Invalid file path.") from exc
    content_type, _ = mimetypes.guess_type(str(file_path))
    if document.source_kind != "video" and file_path.suffix.lower() == ".pdf":
        content_type = "application/pdf"
    response = FileResponse(open(file_path, "rb"), content_type=content_type or "application/octet-stream")
    view_only = bool(getattr(document, "view_only", False))
    if view_only:
        filename = "document.pdf" if file_path.suffix.lower() == ".pdf" else "document"
        response["Content-Disposition"] = f'inline; filename="{filename}"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
    else:
        disposition = "attachment" if download else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{file_path.name}"'
    return response


def _doc_source_name(doc) -> str:
    metadata = getattr(doc, "metadata", {}) or {}
    file_hash = metadata.get("file_hash")
    if file_hash:
        matched = IngestedDocument.objects.filter(file_hash=file_hash).first()
        if matched:
            return matched.title

    source = (
        metadata.get("title")
        or metadata.get("source")
        or metadata.get("source_name")
    )
    if source:
        source_str = str(source)
        stem = Path(source_str).stem
        matched = (
            IngestedDocument.objects.filter(
                Q(title__iexact=source_str)
                | Q(source_name__iexact=source_str)
                | Q(title__iexact=stem)
                | Q(source_name__istartswith=f"{stem}.")
            )
            .order_by("-updated_at")
            .first()
        )
        if matched:
            return matched.title
        return source_str
    # Compatibility with flattened payloads that may be promoted onto metadata.
    for key in ("file_name", "filename", "path"):
        if metadata.get(key):
            return str(metadata[key])
    return "Unknown"


def _doc_source_label(doc) -> str:
    name = _doc_source_name(doc)
    metadata = getattr(doc, "metadata", {}) or {}
    topic_title = str(metadata.get("topic_title") or "").strip()
    if topic_title and topic_title.lower() not in name.lower():
        # Prefer topical label when payload still has a date-only DB title.
        original = str(metadata.get("original_title") or "").strip()
        if original and original.lower() == name.lower():
            name = topic_title
        elif not name or name == "Unknown":
            name = topic_title
    timestamp = metadata.get("timestamp")
    content_type = str(metadata.get("content_type") or metadata.get("media_type") or "")
    chunk_kind = str(metadata.get("chunk_kind") or "")
    if timestamp and ("video" in content_type or chunk_kind.startswith("video")):
        return f"{name} [{timestamp}]"
    return name


def _require_api_key(request):
    """
    Optional shared-secret gate for public APIs.
    If PUBLIC_API_KEY is unset, endpoints remain public.
    """
    if not PUBLIC_API_KEY:
        return None

    payload = request.data if request.method not in {"GET", "HEAD", "OPTIONS"} else {}
    provided = (
        request.headers.get("X-API-Key")
        or request.query_params.get("api_key")
        or payload.get("api_key")
    )
    if not provided or not hmac.compare_digest(str(provided), PUBLIC_API_KEY):
        return Response({"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)
    return None


def _client_fingerprint(request) -> str:
    """Stable-ish anon fingerprint.

    Prefer User-Agent over client IP so mobile IP churn does not orphan an
    in-progress chat's server history mid-thread.
    """
    user_agent = (request.headers.get("User-Agent") or "")[:240]
    return f"ua:{user_agent}"


def _scoped_session_id(request, provided_session_id: str) -> str:
    """
    Isolate each Flutter chat UUID under a stable identity key.

    Authenticated users are scoped by user id so chats never cross accounts.
    Guests are scoped by User-Agent + chat UUID (not IP) so each New Chat stays
    separate without losing history when the phone IP changes.
    """
    raw_session = (provided_session_id or "default_user").strip()[:256]
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        identity = f"u:{user.pk}"
    else:
        identity = f"a:{_client_fingerprint(request)}"
    digest = hmac.new(
        SESSION_SCOPE_SALT.encode("utf-8"),
        f"{identity}|{raw_session}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"s:{digest}"


class IngestedDocumentsAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, HasPremiumAccess]

    def get(self, request):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        # Frontend source lookup may need older sermons, not only most recent uploads.
        # Default high enough to cover the full corpus for stable source-to-file resolution.
        limit_param = request.query_params.get("limit", "1000")
        try:
            limit = max(1, min(int(limit_param), 5000))
        except ValueError:
            limit = 1000

        documents_qs = _library_documents().order_by("-updated_at")
        match = (request.query_params.get("match") or "").strip()
        if match:
            stem = _strip_source_label(match)
            documents_qs = documents_qs.filter(
                Q(title__icontains=match)
                | Q(source_name__icontains=match)
                | Q(title__iexact=stem)
                | Q(source_name__istartswith=f"{stem}.")
            )
        source_kind = (request.query_params.get("source_kind") or "").strip().lower()
        if source_kind in {"document", "video", "website"}:
            documents_qs = documents_qs.filter(source_kind=source_kind)
        documents_qs = documents_qs[:limit]

        catalog = None
        date_index = None
        documents = []
        for document in documents_qs:
            file_relative_url = reverse("ingested_document_file_api", args=[document.id])
            file_absolute_url = request.build_absolute_uri(file_relative_url)
            stored_ext = Path(document.source_name or "").suffix or document.original_extension or ".pdf"
            if not stored_ext.startswith("."):
                stored_ext = f".{stored_ext}"
            title_source_name = f"{(document.title or '').strip()}{stored_ext}"
            vimeo_id = ""
            privacy_hash = ""
            media_title = ""
            if document.source_kind == "video":
                if catalog is None:
                    from .embedded_videos import match_source_to_catalog, _load_catalog

                    catalog, date_index = _load_catalog()
                entry = match_source_to_catalog(
                    document.source_name or "", catalog, date_index
                ) or match_source_to_catalog(
                    document.title or "", catalog, date_index
                )
                if entry is not None:
                    vimeo_id = entry.vimeo_id or ""
                    privacy_hash = entry.privacy_hash or ""
                    media_title = entry.title or ""
            documents.append(
                {
                    "id": document.id,
                    "title": document.title,
                    "source_name": title_source_name or document.source_name,
                    "stored_source_name": document.source_name,
                    "original_extension": document.original_extension,
                    "source_kind": document.source_kind,
                    "chunk_count": document.chunk_count,
                    "updated_at": document.updated_at.isoformat(),
                    "file_url": file_absolute_url,
                    # Keep legacy key for older frontends that read `file_path`.
                    # Return URL (not server filesystem path) so link opening works
                    # regardless of where the frontend is hosted.
                    "file_path": file_absolute_url,
                    "vimeo_id": vimeo_id,
                    "privacy_hash": privacy_hash,
                    "media_title": media_title,
                    "topic_metadata": document.topic_metadata or {},
                    "scripture_refs": scripture_refs_from_metadata(document.topic_metadata),
                    "view_only": bool(document.view_only),
                    "in_library": bool(document.in_library),
                }
            )
        return Response({"documents": documents}, status=status.HTTP_200_OK)


class IngestedDocumentFileAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, HasPremiumAccess]

    def get(self, request, document_id: int):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        document = _library_documents().filter(id=document_id).first()
        if not document:
            raise Http404("Document was not found.")
        download = str(request.query_params.get("download") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        return _file_response_for_document(document, download=download)


class SermonPdfByNameAPIView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, HasPremiumAccess]

    def get(self, request, sermon_name: str):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        requested_name = (sermon_name or "").strip()
        if not requested_name:
            raise Http404("Document was not found.")

        normalized_stem = _strip_source_label(requested_name)
        if not normalized_stem:
            raise Http404("Document was not found.")

        document = (
            _library_documents()
            .filter(
                Q(title__iexact=normalized_stem)
                | Q(source_name__iexact=f"{normalized_stem}.pdf")
                | Q(source_name__istartswith=f"{normalized_stem}.")
                | Q(source_name__iexact=requested_name)
            )
            .order_by("-updated_at")
            .first()
        )
        if not document:
            raise Http404("Document was not found.")
        return _file_response_for_document(document)

class PrayerRequestAPIView(APIView):
    """GET/POST /api/prayer-requests/ — Premium submit + staff inbox list."""

    authentication_classes = [TokenAuthentication]
    renderer_classes = [JSONRenderer]

    def get_permissions(self):
        from rest_framework.permissions import IsAdminUser

        if self.request.method == "GET":
            return [IsAdminUser()]
        return [IsAuthenticated(), HasPremiumAccess()]

    def get(self, request):
        from api.serializers import PrayerRequestSerializer

        qs = PrayerRequest.objects.all()
        followed_up = request.query_params.get("followed_up")
        if followed_up is not None:
            flag = followed_up.lower() in ("true", "1", "yes")
            qs = qs.filter(followed_up=flag)
        data = PrayerRequestSerializer(qs, many=True).data
        return Response({"results": data})

    def post(self, request):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        prayer_text = (request.data.get('prayer_text') or '').strip()
        if len(prayer_text) < 10:
            return Response(
                {'detail': 'Prayer request must be at least 10 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_anonymous = bool(request.data.get('is_anonymous', False))
        name = '' if is_anonymous else (request.data.get('name') or '').strip()
        email = '' if is_anonymous else (request.data.get('email') or '').strip()
        phone = (request.data.get('phone') or '').strip()

        if not is_anonymous and (not name or not email):
            return Response(
                {'detail': 'Name and email are required unless submitting anonymously.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user if getattr(request.user, 'is_authenticated', False) else None
        prayer = PrayerRequest.objects.create(
            name=name,
            email=email,
            phone=phone,
            prayer_text=prayer_text,
            is_anonymous=is_anonymous,
            user=user if user and user.is_authenticated else None,
        )

        return Response(
            {
                'success': True,
                'id': prayer.id,
                'message': 'Prayer request received.',
            },
            status=status.HTTP_201_CREATED,
        )


class ResponseReportAPIView(APIView):
    """GET/POST /api/response-reports/ — Premium submit + staff inbox list."""

    authentication_classes = [TokenAuthentication]
    renderer_classes = [JSONRenderer]

    def get_permissions(self):
        from rest_framework.permissions import IsAdminUser

        if self.request.method == "GET":
            return [IsAdminUser()]
        return [IsAuthenticated(), HasPremiumAccess()]

    def get(self, request):
        from api.serializers import ResponseReportSerializer

        qs = ResponseReport.objects.select_related("user", "chat_message").all()
        status_filter = (request.query_params.get("status") or "").strip().lower()
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = ResponseReportSerializer(qs, many=True).data
        return Response({"results": data})

    def post(self, request):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        try:
            message_id = int(request.data.get("message_id"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "message_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = (request.data.get("reason") or "").strip()
        valid_reasons = {c.value for c in ResponseReport.Reason}
        if reason not in valid_reasons:
            return Response(
                {
                    "detail": "Invalid reason.",
                    "allowed": sorted(valid_reasons),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        details = (request.data.get("details") or "").strip()
        if len(details) > 2000:
            return Response(
                {"detail": "details must be 2000 characters or fewer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        message = ChatMessage.objects.filter(pk=message_id).first()
        if message is None:
            return Response(
                {"detail": "Chat message not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        client_session_id = request.data.get("session_id") or ""
        session_id = (
            _scoped_session_id(request, client_session_id)
            if str(client_session_id).strip()
            else message.session_id
        )

        existing = ResponseReport.objects.filter(
            chat_message=message,
            session_id=session_id,
            status=ResponseReport.Status.NEW,
        ).first()
        if existing is not None:
            return Response(
                {
                    "success": True,
                    "id": existing.id,
                    "message": "Report already submitted for this response.",
                    "already_reported": True,
                },
                status=status.HTTP_200_OK,
            )

        user = request.user if getattr(request.user, "is_authenticated", False) else None
        report = ResponseReport.objects.create(
            chat_message=message,
            user_query_snapshot=message.user_query,
            ai_response_snapshot=message.ai_response,
            reason=reason,
            details=details,
            session_id=session_id,
            user=user,
        )

        return Response(
            {
                "success": True,
                "id": report.id,
                "message": "Report received. Thank you.",
                "already_reported": False,
            },
            status=status.HTTP_201_CREATED,
        )

