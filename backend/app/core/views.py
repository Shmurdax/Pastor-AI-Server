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
from django.http import StreamingHttpResponse
from django.urls import reverse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny

# RAG & Memory Imports
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

# Import the model
from .embeddings_utils import get_embeddings
from .models import ChatMessage, IngestedDocument, PrayerRequest, ResponseReport
from .chat_language import language_reply_instruction, normalize_chat_language
from .chat_llm import (
    EMPTY_REFERENCE_NOTES,
    NOTES_MARKER,
    fit_chat_budget,
    get_chat_llm,
    parse_context_length_error,
    remember_worker_max_model_len,
)
from .chat_sse import iter_chat_tokens, iter_with_sse_heartbeats, sse_keepalive, sse_pack, wants_chat_stream
from .chat_system_prompt import (
    CONTINUE_STEER,
    LENGTH_STEER,
    MAX_EXPANSION_PASSES,
    answer_needs_expansion,
    answer_word_count,
    build_chat_system_prompt,
    find_biblical_character_names,
    query_expects_long_answer,
)
from .chat_translate import translate_texts
from .qdrant_utils import ensure_sermon_collection, get_collection_name, get_qdrant_url
from .scope_gate import generate_out_of_scope_reply, query_in_scope
from .storage_paths import ingested_media_path

logger = logging.getLogger(__name__)
PUBLIC_API_KEY = os.getenv("PUBLIC_API_KEY", "").strip()
SESSION_SCOPE_SALT = os.getenv("SESSION_SCOPE_SALT", settings.SECRET_KEY)
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "16"))
RETRIEVAL_BIBLE_RATIO = float(os.getenv("RETRIEVAL_BIBLE_RATIO", "0.45"))
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD", "0.7"))
MAX_HISTORY_CHARS = int(os.getenv("CHAT_MAX_HISTORY_CHARS", "3000"))
MAX_CONTEXT_CHARS = int(os.getenv("CHAT_MAX_CONTEXT_CHARS", "40000"))
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "6144"))
CHAT_TIMEOUT_S = float(os.getenv("CHAT_TIMEOUT_S", "360"))
BIBLE_SOURCE_MARKERS = tuple(
    marker.strip().lower()
    for marker in os.environ.get(
        "BIBLE_SOURCE_MARKERS",
        "bible,nkjv,king james,new testament,old testament,scripture",
    ).split(",")
    if marker.strip()
)
_SOURCE_TIMESTAMP_RE = re.compile(r"\s*\[[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?–[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\]\s*$")
_SOURCE_MEDIA_EXTS = {".pdf", ".md", ".docx"} | {
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


def _file_response_for_document(document: IngestedDocument):
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
    response["Content-Disposition"] = f'inline; filename="{file_path.name}"'
    return response

# Keep retrieval embeddings on CPU via shared helper (vLLM owns GPU VRAM).
_get_embeddings = get_embeddings


def _is_bible_source(source_name: str) -> bool:
    normalized = (source_name or "").lower()
    return any(marker in normalized for marker in BIBLE_SOURCE_MARKERS)


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
    timestamp = metadata.get("timestamp")
    content_type = str(metadata.get("content_type") or metadata.get("media_type") or "")
    if timestamp and ("video" in content_type):
        return f"{name} [{timestamp}]"
    return name


def _weighted_docs(docs, total_k: int):
    """
    Keep retrieval mix close to 55/45 (default/bible) with fallback fill.
    """
    if total_k <= 0:
        return []
    bible_target = max(1, min(total_k - 1, int(round(total_k * RETRIEVAL_BIBLE_RATIO)))) if total_k > 1 else 0
    default_target = total_k - bible_target

    bible_docs = []
    default_docs = []
    for doc in docs:
        source_name = _doc_source_name(doc)
        if _is_bible_source(source_name):
            bible_docs.append(doc)
        else:
            default_docs.append(doc)

    selected = default_docs[:default_target] + bible_docs[:bible_target]
    remaining = total_k - len(selected)
    if remaining > 0:
        selected_sources = {id(doc) for doc in selected}
        extras = [doc for doc in (default_docs + bible_docs) if id(doc) not in selected_sources]
        selected.extend(extras[:remaining])
    return selected


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


def _wants_chat_stream(request) -> bool:
    return wants_chat_stream(
        request.data.get("stream", False),
        request.META.get("HTTP_ACCEPT", ""),
    )


def _sse(payload: dict) -> str:
    return sse_pack(payload)


def _sse_response(iterator):
    response = StreamingHttpResponse(iterator, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Connection"] = "keep-alive"
    return response


def _iter_chat_tokens(bound_llm, messages):
    return iter_chat_tokens(bound_llm, messages)


def _refit_prepared(prepared, window: int):
    messages = prepared["messages"]
    system = getattr(messages[0], "content", "") or ""
    history = list(messages[1:-1])
    question = getattr(messages[-1], "content", "") or ""
    fitted, hist, completion, used = fit_chat_budget(
        system,
        history,
        question,
        min(int(prepared["completion_tokens"]), max(128, window - 256)),
        window=window,
    )
    prepared["messages"] = [SystemMessage(content=fitted), *hist, HumanMessage(content=question)]
    prepared["completion_tokens"] = completion
    prepared["bound"] = prepared["llm"].bind(max_tokens=completion)
    logger.warning(
        "Refit chat to worker window=%s prompt≈%s completion=%s history=%s",
        window,
        used,
        completion,
        len(hist),
    )
    return prepared


def _continuation_messages(messages, first_answer: str):
    return list(messages) + [
        AIMessage(content=first_answer),
        HumanMessage(content=CONTINUE_STEER),
    ]


def _join_continuation(answer: str, extra: str) -> str:
    extra = (extra or "").strip()
    if not extra:
        return answer
    return answer.rstrip() + "\n\n" + extra


def _trim_continuation_messages(messages):
    """Drop history and clip notes so a continue turn still fits a short worker."""
    system = None
    last_human = None
    last_ai = None
    for msg in messages:
        if isinstance(msg, SystemMessage):
            system = msg
        elif isinstance(msg, HumanMessage):
            last_human = msg
        elif isinstance(msg, AIMessage):
            last_ai = msg
    trimmed = []
    if system is not None:
        content = getattr(system, "content", "") or ""
        if len(content) > 2400:
            idx = content.find(NOTES_MARKER)
            if idx >= 0:
                prefix = content[: idx + len(NOTES_MARKER)]
                notes = content[idx + len(NOTES_MARKER) :]
                keep_notes = notes[: max(1200, min(len(notes), 2200))]
                keep_prefix = prefix
                budget = 3200
                if len(keep_prefix) + len(keep_notes) > budget:
                    keep_prefix = keep_prefix[: max(900, budget - len(keep_notes))]
                content = keep_prefix + keep_notes
            else:
                content = content[:2400]
        trimmed.append(SystemMessage(content=content))
    if last_ai is not None:
        trimmed.append(last_ai)
    if last_human is not None:
        trimmed.append(last_human)
    return trimmed


def _iter_continuation_tokens(prepared, answer: str):
    full = _continuation_messages(prepared["messages"], answer)
    trimmed = _trim_continuation_messages(full)
    smaller = prepared["llm"].bind(max_tokens=max(1200, int(prepared["completion_tokens"]) // 2))
    attempts = (
        (prepared["bound"], full),
        (smaller, trimmed),
    )
    for bound, messages in attempts:
        yielded = False
        try:
            for text in _iter_chat_tokens(bound, messages):
                yielded = True
                yield text
            if yielded:
                return
        except Exception:
            if yielded:
                return
            logger.exception("Continuation attempt failed")
    logger.warning("Continuation produced no extra text")


def _save_ai_response(
    *,
    regenerate: bool,
    target_message,
    session_id: str,
    chat_user,
    user_query_stored: str,
    answer: str,
    allow_create: bool = True,
):
    if regenerate and target_message is not None:
        target_message.ai_response = answer
        if chat_user and target_message.user_id is None:
            target_message.user = chat_user
            target_message.save(update_fields=["ai_response", "user"])
        else:
            target_message.save(update_fields=["ai_response"])
        return target_message
    if not allow_create:
        return None
    return ChatMessage.objects.create(
        session_id=session_id,
        user=chat_user,
        user_query=user_query_stored,
        ai_response=answer,
    )


def _chat_payload(answer: str, sources=None, message_id=None) -> dict:
    payload = {"answer": answer, "sources": list(sources or [])}
    if message_id is not None:
        payload["message_id"] = message_id
    return payload


def _immediate_sse(payload: dict):
    if payload.get("answer"):
        yield _sse({"type": "delta", "text": payload["answer"]})
    done = {"type": "done", "answer": payload.get("answer", ""), "sources": payload.get("sources", [])}
    if payload.get("message_id") is not None:
        done["message_id"] = payload["message_id"]
    yield _sse(done)


def _client_fingerprint(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR", "")
    user_agent = request.headers.get("User-Agent", "")
    return f"{client_ip}|{user_agent}"


def _scoped_session_id(request, provided_session_id: str) -> str:
    """
    Scope client-provided session IDs to request fingerprint.
    This reduces cross-user session guessing on public endpoints.
    """
    raw_session = (provided_session_id or "default_user").strip()[:256]
    digest = hmac.new(
        SESSION_SCOPE_SALT.encode("utf-8"),
        f"{_client_fingerprint(request)}|{raw_session}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"s:{digest}"


class IngestedDocumentsAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

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

        documents_qs = IngestedDocument.objects.all().order_by("-updated_at")
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

        documents = []
        for document in documents_qs:
            file_relative_url = reverse("ingested_document_file_api", args=[document.id])
            file_absolute_url = request.build_absolute_uri(file_relative_url)
            stored_ext = Path(document.source_name or "").suffix or document.original_extension or ".pdf"
            if not stored_ext.startswith("."):
                stored_ext = f".{stored_ext}"
            title_source_name = f"{(document.title or '').strip()}{stored_ext}"
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
                }
            )
        return Response({"documents": documents}, status=status.HTTP_200_OK)


class IngestedDocumentFileAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, document_id: int):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        document = IngestedDocument.objects.filter(id=document_id).first()
        if not document:
            raise Http404("Document was not found.")
        return _file_response_for_document(document)


class SermonPdfByNameAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

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
            IngestedDocument.objects.filter(
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

class ChatAPIView(APIView):
    # Token auth links messages to the signed-in account when Flutter sends Authorization.
    # Do not enable SessionAuthentication: an active Django admin cookie would require CSRF
    # on POST and Flutter fetch does not send one → 403. Anonymous chat remains allowed.
    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]
    # No browsable API HTML — JSON only (clients must POST with Accept: application/json).
    renderer_classes = [JSONRenderer]

    def get(self, request):
        # Hide endpoint from casual browser visits (`/api/chat/` and legacy `/chat/`).
        return Response(status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        raw_query = request.data.get("query")
        client_session_id = request.data.get("session_id", "default_user")
        session_id = _scoped_session_id(request, client_session_id)
        regenerate = bool(request.data.get("regenerate", False))
        want_stream = _wants_chat_stream(request)
        chat_language = normalize_chat_language(
            request.data.get("language") or request.data.get("locale")
        )
        chat_user = request.user if getattr(request.user, "is_authenticated", False) else None

        if not raw_query:
            return Response({"error": "No query provided"}, status=status.HTTP_400_BAD_REQUEST)

        user_query_stored = str(raw_query).strip()
        user_query_llm = user_query_stored

        def prepare_chat():
            llm = get_chat_llm(
                temperature=0.8,
                max_tokens=CHAT_MAX_TOKENS,
                timeout=CHAT_TIMEOUT_S,
                presence_penalty=0.25,
                frequency_penalty=0.15,
            )
            target_message = None
            if regenerate:
                target_message = (
                    ChatMessage.objects
                    .filter(session_id=session_id, user_query=user_query_stored)
                    .order_by("-timestamp")
                    .first()
                )

            if not query_in_scope(llm, user_query_llm):
                out_of_scope_reply = generate_out_of_scope_reply(
                    llm, user_query_llm, language=chat_language
                )
                saved_message = _save_ai_response(
                    regenerate=regenerate,
                    target_message=target_message,
                    session_id=session_id,
                    chat_user=chat_user,
                    user_query_stored=user_query_stored,
                    answer=out_of_scope_reply,
                    allow_create=not regenerate,
                )
                payload = _chat_payload(
                    out_of_scope_reply,
                    message_id=None if saved_message is None else saved_message.id,
                )
                return {"kind": "final", "payload": payload}

            embeddings = _get_embeddings()
            collection_name = get_collection_name()
            client = QdrantClient(url=get_qdrant_url())
            ensure_sermon_collection(client, collection_name)
            vectorstore = QdrantVectorStore(
                client=client,
                collection_name=collection_name,
                embedding=embeddings,
                content_payload_key="text",
                metadata_payload_key="metadata",
            )

            logger.debug("Searching Qdrant for incoming chat request.")

            candidate_k = max(RETRIEVAL_K * 3, 15)
            retriever = vectorstore.as_retriever(
                search_type="similarity_score_threshold",
                search_kwargs={"k": candidate_k, "score_threshold": RETRIEVAL_THRESHOLD}
            )
            candidates = retriever.invoke(user_query_llm)
            docs = _weighted_docs(candidates, RETRIEVAL_K)
            context = "\n\n".join([doc.page_content for doc in docs])[:MAX_CONTEXT_CHARS]

            bible_count = sum(1 for doc in docs if _is_bible_source(_doc_source_name(doc)))
            logger.debug(
                "Selected retrieval chunks: total=%s default=%s bible=%s",
                len(docs),
                len(docs) - bible_count,
                bible_count,
            )

            db_messages = ChatMessage.objects.filter(session_id=session_id).order_by('-timestamp')
            if regenerate and target_message:
                db_messages = db_messages.exclude(id=target_message.id)

            history_messages = []
            current_chars = 0

            for msg in db_messages:
                exchange = f"{msg.user_query} {msg.ai_response}"
                if current_chars + len(exchange) > MAX_HISTORY_CHARS:
                    break
                history_messages.insert(0, AIMessage(content=msg.ai_response))
                history_messages.insert(0, HumanMessage(content=msg.user_query))
                current_chars += len(exchange)

            biblical_names = find_biblical_character_names(user_query_llm)
            if biblical_names:
                logger.debug("Biblical character names detected: %s", biblical_names)
            system_content = (
                build_chat_system_prompt(biblical_names=biblical_names)
                + language_reply_instruction(chat_language)
                + "\nREFERENCE NOTES:\n{context}"
            )
            system_filled = system_content.replace(
                "{context}",
                context if context.strip() else EMPTY_REFERENCE_NOTES,
            )
            human_content = user_query_llm
            if query_expects_long_answer(user_query_llm):
                human_content = f"{LENGTH_STEER}{user_query_llm.strip()}"
            system_filled, history_messages, completion_tokens, used_tokens = fit_chat_budget(
                system_filled,
                history_messages,
                human_content,
                CHAT_MAX_TOKENS,
                safety=int(os.getenv("CHAT_TOKEN_SAFETY", "192")),
            )
            logger.warning(
                "Chat token budget: prompt≈%s completion=%s history_msgs=%s",
                used_tokens,
                completion_tokens,
                len(history_messages),
            )
            messages = (
                [SystemMessage(content=system_filled)]
                + history_messages
                + [HumanMessage(content=human_content)]
            )
            bound = llm.bind(max_tokens=completion_tokens)
            return {
                "kind": "generate",
                "llm": llm,
                "bound": bound,
                "messages": messages,
                "docs": docs,
                "completion_tokens": completion_tokens,
                "target_message": target_message,
            }

        def _unique_sources(docs):
            return sorted(
                {
                    name
                    for name in (_doc_source_label(doc) for doc in docs)
                    if name and name != "Unknown"
                }
            )

        def _generate_tokens(prepared):
            bound = prepared["bound"]
            messages = prepared["messages"]
            yielded = False
            try:
                for text in _iter_chat_tokens(bound, messages):
                    yielded = True
                    yield text
                return
            except Exception as exc:
                if yielded:
                    raise
                worker_len = parse_context_length_error(exc)
                if worker_len:
                    remember_worker_max_model_len(worker_len)
                    logger.warning(
                        "vLLM worker max context is %s tokens; refitting the prompt",
                        worker_len,
                    )
                    _refit_prepared(prepared, worker_len)
                    yield from _iter_chat_tokens(prepared["bound"], prepared["messages"])
                    return
                logger.exception("Error while streaming chat tokens; retrying with a smaller budget")
            smaller = max(1200, int(prepared["completion_tokens"]) // 2)
            trimmed = []
            for msg in messages:
                content = getattr(msg, "content", "") or ""
                if isinstance(msg, SystemMessage) and len(content) > 2400:
                    idx = content.find(NOTES_MARKER)
                    if idx >= 0:
                        prefix = content[: idx + len(NOTES_MARKER)]
                        notes = content[idx + len(NOTES_MARKER) :]
                        keep_notes = notes[: max(1600, min(len(notes), 2800))]
                        keep_prefix = prefix
                        budget = 3600
                        if len(keep_prefix) + len(keep_notes) > budget:
                            keep_prefix = keep_prefix[: max(900, budget - len(keep_notes))]
                        content = keep_prefix + keep_notes
                    else:
                        content = content[:2400]
                    trimmed.append(SystemMessage(content=content))
                else:
                    trimmed.append(msg)
            retry_bound = prepared["llm"].bind(max_tokens=smaller)
            prepared["messages"] = trimmed
            prepared["bound"] = retry_bound
            yield from _iter_chat_tokens(retry_bound, trimmed)

        if want_stream:
            def produce_events():
                yield _sse({"type": "status", "phase": "started"})
                prepared = prepare_chat()
                if prepared["kind"] == "final":
                    yield from _immediate_sse(prepared["payload"])
                    return
                assembled = []
                for text in _generate_tokens(prepared):
                    assembled.append(text)
                    yield _sse({"type": "delta", "text": text})
                answer = "".join(assembled)
                if not answer.strip():
                    raise ValueError("No generation chunks were returned")
                expansion_pass = 0
                while (
                    answer_needs_expansion(answer, query=user_query_llm)
                    and expansion_pass < MAX_EXPANSION_PASSES
                ):
                    expansion_pass += 1
                    logger.warning(
                        "Chat answer was short (%s words); requesting continuation %s/%s",
                        answer_word_count(answer),
                        expansion_pass,
                        MAX_EXPANSION_PASSES,
                    )
                    extra_parts = []
                    separator_sent = False
                    try:
                        for text in _iter_continuation_tokens(prepared, answer):
                            if not separator_sent:
                                yield _sse({"type": "delta", "text": "\n\n"})
                                separator_sent = True
                            extra_parts.append(text)
                            yield _sse({"type": "delta", "text": text})
                    except Exception:
                        logger.exception("Continuation failed; keeping the first answer")
                        break
                    extra = "".join(extra_parts).strip()
                    if not extra:
                        break
                    answer = _join_continuation(answer, extra)
                saved_message = _save_ai_response(
                    regenerate=regenerate,
                    target_message=prepared["target_message"],
                    session_id=session_id,
                    chat_user=chat_user,
                    user_query_stored=user_query_stored,
                    answer=answer,
                )
                done = {
                    "type": "done",
                    "answer": answer,
                    "sources": _unique_sources(prepared["docs"]) if prepared["docs"] else [],
                }
                if saved_message is not None:
                    done["message_id"] = saved_message.id
                logger.debug("Chat response generated successfully.")
                yield _sse(done)

            def token_events():
                yield sse_keepalive()
                try:
                    yield from iter_with_sse_heartbeats(produce_events, interval_s=2.0)
                except Exception:
                    logger.exception("Error while streaming chat tokens")
                    yield _sse({
                        "type": "error",
                        "error": "I encountered a processing error while generating this answer. Please retry.",
                    })

            return _sse_response(token_events())

        try:
            prepared = prepare_chat()
            if prepared["kind"] == "final":
                return Response(prepared["payload"], status=status.HTTP_200_OK)
            try:
                response = prepared["bound"].invoke(prepared["messages"])
            except Exception as exc:
                worker_len = parse_context_length_error(exc)
                if not worker_len:
                    raise
                remember_worker_max_model_len(worker_len)
                logger.warning(
                    "vLLM worker max context is %s tokens; refitting the prompt",
                    worker_len,
                )
                _refit_prepared(prepared, worker_len)
                response = prepared["bound"].invoke(prepared["messages"])
            answer = response.content or ""
            expansion_pass = 0
            while (
                answer_needs_expansion(answer, query=user_query_llm)
                and expansion_pass < MAX_EXPANSION_PASSES
            ):
                expansion_pass += 1
                logger.warning(
                    "Chat answer was short (%s words); requesting continuation %s/%s",
                    answer_word_count(answer),
                    expansion_pass,
                    MAX_EXPANSION_PASSES,
                )
                try:
                    extra = prepared["bound"].invoke(
                        _continuation_messages(prepared["messages"], answer)
                    )
                    extra_text = (getattr(extra, "content", "") or "").strip()
                except Exception:
                    logger.exception("Continuation failed; retrying with a trimmed prompt")
                    try:
                        extra = prepared["llm"].bind(
                            max_tokens=max(1200, int(prepared["completion_tokens"]) // 2)
                        ).invoke(
                            _trim_continuation_messages(
                                _continuation_messages(prepared["messages"], answer)
                            )
                        )
                        extra_text = (getattr(extra, "content", "") or "").strip()
                    except Exception:
                        logger.exception("Continuation failed; keeping the first answer")
                        break
                if not extra_text:
                    break
                answer = _join_continuation(answer, extra_text)
            saved_message = _save_ai_response(
                regenerate=regenerate,
                target_message=prepared["target_message"],
                session_id=session_id,
                chat_user=chat_user,
                user_query_stored=user_query_stored,
                answer=answer,
            )
            logger.debug("Chat response generated successfully.")
            return Response(
                _chat_payload(
                    answer,
                    sources=_unique_sources(prepared["docs"]) if prepared["docs"] else [],
                    message_id=None if saved_message is None else saved_message.id,
                ),
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.exception("Error in Memory-RAG loop: %s", str(e))
            return Response({"error": "I encountered a processing error while generating this answer. Please retry."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChatWarmupAPIView(APIView):
    """POST/GET /api/chat/warmup/ — start the serverless GPU while the user is still typing."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    def get(self, request):
        return self.post(request)

    def post(self, request):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error
        from .vllm_warmup import warmup_vllm_worker

        payload = warmup_vllm_worker()
        return Response(payload, status=status.HTTP_200_OK)


class TranslateAPIView(APIView):
    """POST /api/translate/ — retranslate visible AI replies when the UI language changes."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]
    renderer_classes = [JSONRenderer]

    def get(self, request):
        return Response(status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        auth_error = _require_api_key(request)
        if auth_error:
            return auth_error

        language = normalize_chat_language(
            request.data.get("language") or request.data.get("locale")
        )
        texts = request.data.get("texts")
        if texts is None and request.data.get("text") is not None:
            texts = [request.data.get("text")]
        if not isinstance(texts, list) or not texts:
            return Response(
                {"error": "Provide texts: [..] or text"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(texts) > 40:
            return Response(
                {"error": "Too many texts (max 40)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            translated = translate_texts(texts, language)
        except Exception:
            logger.exception("TranslateAPIView failed")
            return Response(
                {"error": "Translation failed. Please retry."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response(
            {"texts": translated, "language": language},
            status=status.HTTP_200_OK,
        )


class PrayerRequestAPIView(APIView):
    """GET/POST /api/prayer-requests/ — public submit + staff inbox list."""

    renderer_classes = [JSONRenderer]

    def get_authenticators(self):
        # Public POST stays key/session-light; staff GET uses DRF Token auth.
        if self.request.method == "GET":
            return super().get_authenticators()
        return []

    def get_permissions(self):
        from rest_framework.permissions import IsAdminUser

        if self.request.method == "GET":
            return [IsAdminUser()]
        return [AllowAny()]

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
    """GET/POST /api/response-reports/ — public submit + staff inbox list."""

    renderer_classes = [JSONRenderer]

    def get_permissions(self):
        from rest_framework.permissions import IsAdminUser

        if self.request.method == "GET":
            return [IsAdminUser()]
        return [AllowAny()]

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

