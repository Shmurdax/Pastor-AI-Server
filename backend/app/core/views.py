import os
import logging
import hmac
import hashlib
import mimetypes
import re
from pathlib import Path
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Q
from django.db.utils import OperationalError
from django.http import FileResponse
from django.http import Http404
from django.http import StreamingHttpResponse
from django.urls import reverse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

from api.permissions import HasPremiumAccess

# RAG & Memory Imports
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

# Import the model
from .embeddings_utils import get_embeddings
from .models import ChatMessage, IngestedDocument, PrayerRequest, ResponseReport
from .chat_language import (
    language_generation_reminder,
    language_reply_instruction,
    normalize_chat_language,
)
from .chat_sanitize import (
    looks_like_rewrite_leak,
    recover_english_generation,
    sanitize_chat_answer,
    sanitize_history_text,
    sanitize_stream_delta,
)
from .chat_llm import (
    CHAT_FREQUENCY_PENALTY,
    CHAT_PRESENCE_PENALTY,
    CHAT_TEMPERATURE,
    CHAT_TOP_P,
    CHAT_VLLM_EXTRA_BODY,
    EMPTY_REFERENCE_NOTES,
    NOTES_MARKER,
    fit_chat_budget,
    get_chat_llm,
    select_pinned_history_rows,
)
from .chat_sse import (
    ChatGenerationError,
    EMPTY_STREAM_RETRY_TIMEOUT_S,
    EMPTY_STREAM_USER_MESSAGE,
    is_empty_generation_error,
    iter_chat_tokens,
    iter_tokens_with_retries,
    iter_with_sse_heartbeats,
    sse_keepalive,
    sse_pack,
    wants_chat_stream,
)
from .bible_refs import scripture_refs_from_metadata
from .grounding import (
    collect_allowed_nkjv,
    collect_allowed_sermon_quotes,
    ensure_topical_nkjv,
    grounded_fallback_answer,
    grounding_repair_steer,
    lookup_nkjv_verses,
    nkjv_corpus,
    nkjv_matches_query,
    pastor_quotes_match_query,
    topical_nkjv_fallback_pairs,
    repair_speaker_attributions,
    select_query_grounded_nkjv,
    select_query_grounded_quotes,
    split_docs_for_grounding,
    strip_retrieval_meta,
    strip_ungrounded_spans,
    verify_answer_grounding,
    verse_refs_for_lookup,
    weave_into_answer,
    repair_empty_nkjv_citations,
)
from .teaching_claims import (
    claim_repair_steer,
    claim_repair_token_budget,
    extract_teaching_claims,
    format_teaching_claims_block,
    repairable_claims,
)
from .chat_retrieval import (
    apply_retrieval_threshold,
    expand_search_queries,
    extract_used_quotes,
    extract_used_verse_refs,
    filter_hits_by_topic,
    format_reference_notes,
    looks_like_library_pull,
    pin_docs_to_strong_title_matches,
    restrict_docs_to_primary_source,
    retain_title_matches,
    topic_anchor_query,
    current_carries_new_topic,
    is_bible_source,
    is_video_chunk,
    search_queries_on_store,
    select_chat_source_chips,
    select_diverse_docs,
)
from .chat_system_prompt import (
    COMPLETE_ANSWER_MIN_CHARS,
    CONVERSATIONAL_STEER,
    CONTINUE_STEER,
    FINISH_STEER,
    LIBRARY_PULL_STEER,
    FOLLOWUP_STEER,
    NEW_TOPIC_STEER,
    OPENING_RECALL_STEER,
    format_opening_recall_steer,
    MAX_EXPANSION_PASSES,
    QUOTE_CONTINUE_STEER,
    answer_char_count,
    answer_looks_incomplete,
    answer_missing_required_quotes,
    answer_needs_expansion,
    build_chat_system_prompt,
    compact_teaching_answer,
    continuation_token_budget,
    quote_repair_token_budget,
    find_biblical_character_names,
    join_continuation,
    looks_like_brief_social,
    looks_like_continue_dump,
    looks_like_opening_recall,
    novel_continuation,
    skip_rewrite_repair,
)
from .chat_translate import display_reply, english_search_query, translate_texts
from .live_chat_history import LiveHistoryPublisher
from .qdrant_utils import ensure_sermon_collection, get_collection_name, get_qdrant_url
from .scope_gate import generate_out_of_scope_reply, query_in_scope
from .storage_paths import ingested_media_path

logger = logging.getLogger(__name__)
PUBLIC_API_KEY = os.getenv("PUBLIC_API_KEY", "").strip()
SESSION_SCOPE_SALT = os.getenv("SESSION_SCOPE_SALT", settings.SECRET_KEY)
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "24"))
RETRIEVAL_BIBLE_RATIO = float(os.getenv("RETRIEVAL_BIBLE_RATIO", "0.40"))
RETRIEVAL_VIDEO_RATIO = float(os.getenv("RETRIEVAL_VIDEO_RATIO", "0.45"))
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD", "0.72"))
RETRIEVAL_CANDIDATE_MULTIPLIER = int(os.getenv("RETRIEVAL_CANDIDATE_MULTIPLIER", "8"))
RETRIEVAL_MAX_PER_SOURCE = int(os.getenv("RETRIEVAL_MAX_PER_SOURCE", "2"))
RETRIEVAL_MAX_PER_BIBLE_BOOK = int(os.getenv("RETRIEVAL_MAX_PER_BIBLE_BOOK", "2"))
RETRIEVAL_SOURCE_MIN = int(os.getenv("RETRIEVAL_SOURCE_MIN", "3"))
RETRIEVAL_SOURCE_MAX = int(os.getenv("RETRIEVAL_SOURCE_MAX", "5"))
MAX_HISTORY_CHARS = int(os.getenv("CHAT_MAX_HISTORY_CHARS", "20000"))
MAX_HISTORY_TURNS = int(os.getenv("CHAT_MAX_HISTORY_TURNS", "10"))
MAX_CONTEXT_CHARS = int(os.getenv("CHAT_MAX_CONTEXT_CHARS", "40000"))
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "1024"))
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


def prefer_library_sermon_hits(scored_hits):
    """When sermon-library notes exist, drop hidden knowledge books from RAG."""
    hidden_hashes, hidden_names = hidden_library_matchers()
    if not hidden_hashes and not hidden_names:
        return list(scored_hits or [])
    library = []
    bible = []
    for item in scored_hits or []:
        doc = item[0]
        if _is_bible_source(_doc_source_name(doc)):
            bible.append(item)
        elif chunk_is_in_library(
            doc, hidden_hashes=hidden_hashes, hidden_names=hidden_names
        ):
            library.append(item)
    if library:
        return library + bible
    return list(scored_hits or [])


def prefer_library_sermon_docs(docs):
    """Keep hidden books only when no sermon-library notes were retrieved."""
    hits = prefer_library_sermon_hits([(doc, 1.0) for doc in list(docs or [])])
    return [doc for doc, _score in hits]


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

# Keep retrieval embeddings on CPU via shared helper (vLLM owns GPU VRAM).
_get_embeddings = get_embeddings


def _is_bible_source(source_name: str) -> bool:
    return is_bible_source(source_name, BIBLE_SOURCE_MARKERS)


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


def _continuation_messages(messages, first_answer: str, steer: str | None = None):
    if not steer:
        steer = FINISH_STEER if answer_looks_incomplete(first_answer) else CONTINUE_STEER
    reminder = language_generation_reminder()
    return list(messages) + [
        AIMessage(content=sanitize_chat_answer(first_answer)),
        HumanMessage(content=steer + reminder),
    ]


def _join_continuation(answer: str, extra: str) -> str:
    return join_continuation(answer, extra)


def _usable_extra(answer: str, extra: str) -> str:
    """Keep finish-the-sentence extras; drop a second teaching dump."""
    raw = (extra or "").strip()
    if not raw:
        return ""
    if looks_like_rewrite_leak(raw):
        logger.info("Dropped a continuation that leaked CJK or rewrite notes")
        return ""
    extra = novel_continuation(answer, sanitize_chat_answer(raw))
    if raw and not extra:
        logger.info("Dropped a second-pass continue dump after a finished answer")
        return ""
    if looks_like_continue_dump(answer, extra):
        logger.info("Dropped a second-pass continue dump after a finished answer")
        return ""
    return extra


def _claim_repair_plan(prepared, answer: str, *, query: str = "") -> tuple[str | None, int]:
    # A finished teaching answer already had required points in the first pass.
    # Repairing leftover notes is what concatenates "Certainly, let's continue".
    if (
        not answer_looks_incomplete(answer)
        and answer_char_count(answer) >= COMPLETE_ANSWER_MIN_CHARS
    ):
        return None, 0
    missing = repairable_claims(
        answer, prepared.get("teaching_claims") or [], query=query
    )
    if not missing:
        return None, 0
    budget = claim_repair_token_budget(
        completion_tokens=prepared.get("completion_tokens") or 0
    )
    if budget <= 0:
        return None, 0
    logger.info("Claim coverage missed %s retrieved teaching point(s)", len(missing))
    return claim_repair_steer(missing), budget


def _quote_repair_plan(prepared, answer: str, *, query: str = "") -> tuple[str | None, int]:
    """Add a quote pass when notes were retrieved but quotes or NKJV are missing."""
    if skip_rewrite_repair(answer):
        return None, 0
    docs = prepared.get("docs") or []
    if not docs:
        return None, 0
    has_bible_notes = any(
        _is_bible_source(_doc_source_name(doc)) for doc in docs
    )
    if not answer_missing_required_quotes(
        answer,
        query=query,
        has_reference_notes=True,
        has_bible_notes=has_bible_notes,
    ):
        return None, 0
    budget = quote_repair_token_budget(
        answer, completion_tokens=prepared.get("completion_tokens") or 0
    )
    if budget <= 0:
        return None, 0
    logger.info("Quote repair: retrieved notes were not quoted in the answer")
    return QUOTE_CONTINUE_STEER, budget


def _rag_check_report(prepared, answer: str):
    docs = prepared.get("docs") or []
    sermon, bible = split_docs_for_grounding(docs)
    report = verify_answer_grounding(answer, sermon_docs=sermon, nkjv_docs=bible)
    logger.warning(
        "RAG check: ok=%s invented_quotes=%s invented_scripture=%s missing_nkjv=%s "
        "misattributed=%s sample_quotes=%s sample_refs=%s sample_misattributed=%s",
        report.ok,
        len(report.invented_quotes),
        len(report.invented_scripture),
        len(report.missing_nkjv_refs),
        len(report.misattributed_quotes),
        report.invented_quotes[:2],
        report.missing_nkjv_refs[:5],
        report.misattributed_quotes[:2],
    )
    return report, sermon, bible


def _prepared_query(prepared) -> str:
    return str(prepared.get("topic_query") or prepared.get("user_query") or "").strip()


def _grounding_snippets(prepared):
    docs = prepared.get("docs") or []
    sermon, bible = split_docs_for_grounding(docs)
    query = _prepared_query(prepared)
    bible_text = nkjv_corpus(bible)
    quotes = select_query_grounded_quotes(
        collect_allowed_sermon_quotes(sermon, bible_corpus=bible_text, query=query),
        query,
        allow_topic_pool_fallback=True,
    )
    nkjv = select_query_grounded_nkjv(collect_allowed_nkjv(bible), query)
    if not nkjv:
        nkjv = topical_nkjv_fallback_pairs(query)
    return quotes[:2], nkjv[:1]


def _grounding_repair_plan(prepared, answer: str) -> tuple[str | None, int]:
    """Follow each teaching reply with a RAG check against retrieved notes."""
    if skip_rewrite_repair(answer):
        return None, 0
    docs = prepared.get("docs") or []
    if not docs:
        return None, 0
    report, _sermon, _bible = _rag_check_report(prepared, answer)
    if report.ok:
        return None, 0
    quotes, nkjv = _grounding_snippets(prepared)
    if not quotes and not nkjv:
        return None, 0
    budget = quote_repair_token_budget(
        answer, completion_tokens=prepared.get("completion_tokens") or 0
    )
    if budget <= 0:
        return None, 0
    return grounding_repair_steer(report, quotes, nkjv), budget


def _missing_required_quotes(prepared, answer: str) -> bool:
    docs = prepared.get("docs") or []
    if not docs:
        return False
    query = _prepared_query(prepared)
    sermon, bible = split_docs_for_grounding(docs)
    has_bible_notes = bool(bible) or any(
        _is_bible_source(_doc_source_name(doc)) for doc in docs
    )
    if answer_missing_required_quotes(
        answer,
        query=query,
        has_reference_notes=True,
        has_bible_notes=has_bible_notes,
    ):
        return True
    from .chat_retrieval import has_quoted_nkjv

    if not has_quoted_nkjv(answer or "") and collect_allowed_nkjv(bible):
        return True
    if collect_allowed_nkjv(bible) and not nkjv_matches_query(answer or "", query):
        return True
    if not pastor_quotes_match_query(answer or "", query):
        retrieved = select_query_grounded_quotes(
            collect_allowed_sermon_quotes(
                sermon, bible_corpus=nkjv_corpus(bible), query=query
            ),
            query,
        )
        if retrieved:
            return True
    return False


def _rag_grounding_fallback(prepared, answer: str, *, force: bool = False) -> str:
    docs = prepared.get("docs") or []
    if not docs:
        return ""
    report, _sermon, _bible = _rag_check_report(prepared, answer)
    if report.ok and not force:
        return ""
    quotes, nkjv = _grounding_snippets(prepared)
    from .chat_retrieval import has_quoted_nkjv

    query = _prepared_query(prepared)
    if pastor_quotes_match_query(answer or "", query):
        quotes = []
    if has_quoted_nkjv(answer or "") and nkjv_matches_query(answer or "", query):
        nkjv = []
    if not quotes and not nkjv:
        return ""
    logger.warning("RAG check still failing; weaving on-topic Pastor Don excerpts into the reply")
    return grounded_fallback_answer(quotes, nkjv)


def _speaker_repaired(prepared, answer: str) -> str:
    """Always strip Pastor Don / Susan wraps of Scripture, even with no notes."""
    docs = prepared.get("docs") or []
    _sermon, bible = split_docs_for_grounding(docs)
    return repair_speaker_attributions(answer or "", nkjv_docs=bible)


def _quoted_nkjv_sentence(ref: str, wording: str) -> str:
    clipped = " ".join(str(wording or "").split())
    if len(clipped) > 240:
        clipped = clipped[:237].rsplit(" ", 1)[0] + "..."
    return f'{ref} (NKJV) says, "{clipped}"'


def _ensure_quoted_nkjv(prepared, answer: str) -> str:
    """Last step: a teaching reply with notes must quote NKJV for this question."""
    from .chat_retrieval import has_quoted_nkjv

    text = answer or ""
    query = _prepared_query(prepared)
    docs = prepared.get("docs") or []
    _sermon, bible = split_docs_for_grounding(docs)
    pairs = collect_allowed_nkjv(bible)
    for candidate in (query, str(prepared.get("user_query") or "")):
        candidate = str(candidate or "").strip()
        if not candidate:
            continue
        text = ensure_topical_nkjv(text, candidate, pairs)
        if has_quoted_nkjv(text) and nkjv_matches_query(text, candidate):
            return text
    if has_quoted_nkjv(text):
        return text
    fallback = topical_nkjv_fallback_pairs(query) or topical_nkjv_fallback_pairs(
        str(prepared.get("user_query") or "")
    ) or pairs
    if fallback:
        ref, wording = fallback[0]
        snippet = _quoted_nkjv_sentence(ref, wording)
        if snippet not in text:
            text = f"{text.rstrip()}\n\n{snippet}"
    return text


def _finalize_teaching_answer(prepared, answer: str) -> str:
    """Collapse duplicate outlines, drop invented quotes, weave Pastor Don into the reply."""
    answer = compact_teaching_answer(strip_retrieval_meta(answer))
    docs = prepared.get("docs") or []
    sermon, bible = split_docs_for_grounding(docs)
    query = _prepared_query(prepared)
    answer = repair_empty_nkjv_citations(answer, collect_allowed_nkjv(bible))
    answer = _speaker_repaired(prepared, answer)
    if not docs:
        return _ensure_quoted_nkjv(prepared, answer)
    report, _sermon, _bible = _rag_check_report(prepared, answer)
    missing_quotes = _missing_required_quotes(prepared, answer)
    if report.ok and not missing_quotes:
        answer = ensure_topical_nkjv(
            repair_empty_nkjv_citations(answer, collect_allowed_nkjv(bible)),
            query,
            collect_allowed_nkjv(bible),
        )
        return _speaker_repaired(
            prepared, compact_teaching_answer(_ensure_quoted_nkjv(prepared, answer))
        )
    if not report.ok:
        stripped = strip_ungrounded_spans(answer, report)
        if stripped:
            answer = compact_teaching_answer(stripped)
        missing_quotes = True
        answer = repair_speaker_attributions(answer, nkjv_docs=bible)
    fallback = _rag_grounding_fallback(prepared, answer, force=missing_quotes)
    if fallback and fallback not in (answer or ""):
        answer = weave_into_answer(answer, fallback)
    answer = repair_empty_nkjv_citations(answer, collect_allowed_nkjv(bible))
    answer = compact_teaching_answer(
        repair_speaker_attributions(answer, nkjv_docs=bible)
    )
    if _missing_required_quotes(prepared, answer):
        fallback = _rag_grounding_fallback(prepared, answer, force=True)
        if fallback and fallback not in (answer or ""):
            answer = weave_into_answer(answer, fallback)
    answer = repair_empty_nkjv_citations(answer, collect_allowed_nkjv(bible))
    answer = ensure_topical_nkjv(
        answer,
        query,
        collect_allowed_nkjv(bible),
    )
    answer = _ensure_quoted_nkjv(prepared, answer)
    return _speaker_repaired(prepared, compact_teaching_answer(answer))


def _finish_incomplete_extra(prepared, answer: str) -> str:
    """If a continue/repair pass was token-capped mid-sentence, finish that sentence."""
    if not answer_looks_incomplete(answer):
        return ""
    budget = continuation_token_budget(
        answer, completion_tokens=prepared.get("completion_tokens") or 0
    )
    if budget <= 0:
        budget = 160
    budget = min(max(budget, 96), 256)
    extra_parts = []
    try:
        for text in _iter_continuation_tokens(
            prepared,
            answer,
            steer=FINISH_STEER,
            token_budget=budget,
        ):
            extra_parts.append(text)
    except Exception:
        logger.exception("Finish-cut-off pass failed; keeping the truncated answer")
        return ""
    return _usable_extra(answer, "".join(extra_parts).strip())


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


def _iter_continuation_tokens(prepared, answer: str, steer: str | None = None, *, token_budget: int | None = None):
    budget = (
        token_budget
        if token_budget is not None
        else continuation_token_budget(
            answer, completion_tokens=prepared["completion_tokens"]
        )
    )
    if budget <= 0:
        return
        yield
    full = _continuation_messages(prepared["messages"], answer, steer=steer)
    trimmed = _trim_continuation_messages(full)
    bound = prepared["llm"].bind(max_tokens=budget)
    attempts = (
        (bound, full),
        (bound, trimmed),
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
    last_error = None
    answer = sanitize_chat_answer(answer)
    for attempt in range(2):
        close_old_connections()
        try:
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
        except OperationalError as exc:
            last_error = exc
            logger.warning(
                "Chat save lost the database connection (attempt %s/2); retrying",
                attempt + 1,
            )
            close_old_connections()
    raise last_error


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

class ChatAPIView(APIView):
    # Token auth only — SessionAuthentication would CSRF-fail Flutter POSTs when an
    # admin cookie is present. Product chat requires a paid (or staff) account.
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, HasPremiumAccess]
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
        # Search and generate in English; translate the displayed answer after.
        user_query_llm = english_search_query(user_query_stored, chat_language)
        live_history = None
        if chat_user is not None:
            live_history = LiveHistoryPublisher(
                user=chat_user,
                client_session_id=str(client_session_id or "").strip(),
                user_query=user_query_stored,
            )
            live_history.publish("", streaming=True, force=True)

        def prepare_chat():
            llm = get_chat_llm(
                # Qwen2.5-14B-Instruct-AWQ: official Instruct sampling, not
                # OpenAI frequency_penalty (that pushes unused Chinese tokens).
                temperature=CHAT_TEMPERATURE,
                max_tokens=CHAT_MAX_TOKENS,
                timeout=CHAT_TIMEOUT_S,
                top_p=CHAT_TOP_P,
                presence_penalty=CHAT_PRESENCE_PENALTY,
                frequency_penalty=CHAT_FREQUENCY_PENALTY,
                extra_body=CHAT_VLLM_EXTRA_BODY,
            )
            target_message = None
            if regenerate:
                target_message = (
                    ChatMessage.objects
                    .filter(session_id=session_id, user_query=user_query_stored)
                    .order_by("-timestamp")
                    .first()
                )

            # Follow-ups in an existing thread skip the LLM scope classifier.
            # "Recap the original Joseph teaching" and "How does the great fish
            # complete the lesson?" have no Bible/church keywords, so the gate
            # sometimes answers NO and the redirect skips RAG.
            has_prior_turns = ChatMessage.objects.filter(session_id=session_id).exists()
            if not has_prior_turns and not query_in_scope(llm, user_query_llm):
                out_of_scope_reply = sanitize_chat_answer(
                    generate_out_of_scope_reply(
                        llm, user_query_llm, language="en"
                    )
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
                    display_reply(out_of_scope_reply, chat_language),
                    message_id=None if saved_message is None else saved_message.id,
                )
                return {"kind": "final", "payload": payload}

            db_messages = ChatMessage.objects.filter(session_id=session_id).order_by("-timestamp")
            if regenerate and target_message:
                db_messages = db_messages.exclude(id=target_message.id)

            history_rows = list(db_messages[:MAX_HISTORY_TURNS])
            first_row = (
                ChatMessage.objects.filter(session_id=session_id)
                .order_by("timestamp")
                .first()
            )
            if regenerate and target_message and first_row and first_row.id == target_message.id:
                first_row = (
                    ChatMessage.objects.filter(session_id=session_id)
                    .exclude(id=target_message.id)
                    .order_by("timestamp")
                    .first()
                )
            if first_row and all(row.id != first_row.id for row in history_rows):
                history_rows.append(first_row)
            prior_user_queries = [row.user_query for row in reversed(history_rows)]
            prior_ai_texts = [row.ai_response for row in reversed(history_rows)]
            if regenerate and target_message and target_message.ai_response:
                prior_ai_texts.append(target_message.ai_response)
            used_quotes = extract_used_quotes(prior_ai_texts)
            used_verses = extract_used_verse_refs(prior_ai_texts)
            topic_query = topic_anchor_query(user_query_llm, prior_user_queries)

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

            brief_social = looks_like_brief_social(user_query_llm)
            opening_recall = looks_like_opening_recall(user_query_llm)
            # Pure greetings should not pull sermon notes—those notes trigger
            # quote/timestamp dumps. Informational questions keep full RAG.
            # "What did we start this chat with?" must not retrieve an unrelated
            # sermon theme (parenting, generic wisdom) that then becomes the recap.
            if brief_social or opening_recall:
                search_queries = [user_query_llm]
                docs = []
                context = ""
                teaching_claims = []
                logger.warning(
                    "Skipping Qdrant for brief social message (session=%s)"
                    if brief_social
                    else "Skipping Qdrant for opening-recall (session=%s)",
                    session_id[:18],
                )
            else:
                search_queries = expand_search_queries(
                    user_query_llm,
                    prior_user_queries,
                    prior_ai_texts=prior_ai_texts,
                    limit=7,
                )
                candidate_k = max(RETRIEVAL_K * RETRIEVAL_CANDIDATE_MULTIPLIER, 24)
                logger.debug(
                    "Searching Qdrant with %s queries (k=%s each, session=%s): %s",
                    len(search_queries),
                    candidate_k,
                    session_id[:18],
                    search_queries,
                )
                scored_hits = search_queries_on_store(
                    vectorstore,
                    search_queries,
                    k_per_query=candidate_k,
                )
                # Lexical topic filter first so a 0.93 intro cannot bury a 0.74
                # Cain/Abel clip under the similarity threshold.
                scored_hits = filter_hits_by_topic(
                    scored_hits,
                    topic_query,
                    retrieval_k=RETRIEVAL_K,
                )
                scored_hits = prefer_library_sermon_hits(scored_hits)
                before_threshold = scored_hits
                scored_hits = apply_retrieval_threshold(
                    scored_hits,
                    threshold=RETRIEVAL_THRESHOLD,
                    retrieval_k=RETRIEVAL_K,
                )
                scored_hits = retain_title_matches(
                    before_threshold, scored_hits, topic_query
                )
                docs = select_diverse_docs(
                    scored_hits,
                    k=RETRIEVAL_K,
                    bible_ratio=RETRIEVAL_BIBLE_RATIO,
                    video_ratio=RETRIEVAL_VIDEO_RATIO,
                    max_per_source=RETRIEVAL_MAX_PER_SOURCE,
                    max_per_bible_book=RETRIEVAL_MAX_PER_BIBLE_BOOK,
                    used_quotes=used_quotes,
                    used_verses=used_verses,
                    is_bible=lambda doc: _is_bible_source(_doc_source_name(doc)),
                    is_video=is_video_chunk,
                    source_key=lambda doc: (
                        str((getattr(doc, "metadata", None) or {}).get("file_hash") or "")
                        or _doc_source_name(doc)
                    ),
                    query=topic_query,
                    pin_query=user_query_llm,
                )
                if looks_like_library_pull(user_query_llm):
                    docs = restrict_docs_to_primary_source(
                        docs,
                        topic=topic_query,
                        is_bible=lambda doc: _is_bible_source(_doc_source_name(doc)),
                        source_key=lambda doc: (
                            str((getattr(doc, "metadata", None) or {}).get("file_hash") or "")
                            or _doc_source_name(doc)
                        ),
                    )
                docs = pin_docs_to_strong_title_matches(
                    docs,
                    topic_query,
                    pin_query=user_query_llm,
                    candidate_hits=scored_hits,
                    is_bible=lambda doc: _is_bible_source(_doc_source_name(doc)),
                    source_key=lambda doc: (
                        str((getattr(doc, "metadata", None) or {}).get("file_hash") or "")
                        or _doc_source_name(doc)
                    ),
                )
                docs = prefer_library_sermon_docs(docs)
                refs = verse_refs_for_lookup(topic_query, docs)
                nkjv_docs = lookup_nkjv_verses(
                    client,
                    collection_name,
                    refs,
                    retrieved_docs=docs,
                )
                seen_nkjv = {
                    (getattr(doc, "page_content", None) or "")[:120]
                    for doc in docs
                    if _is_bible_source(_doc_source_name(doc))
                }
                for extra in nkjv_docs:
                    key = (getattr(extra, "page_content", None) or "")[:120]
                    if key and key not in seen_nkjv:
                        docs.append(extra)
                        seen_nkjv.add(key)
                context = format_reference_notes(
                    docs,
                    _doc_source_label,
                    max_chars=MAX_CONTEXT_CHARS,
                )
                teaching_claims = extract_teaching_claims(
                    docs,
                    query=user_query_llm,
                )

            bible_count = sum(1 for doc in docs if _is_bible_source(_doc_source_name(doc)))
            video_count = sum(1 for doc in docs if is_video_chunk(doc))
            note_count = max(0, len(docs) - bible_count - video_count)
            logger.debug(
                "Selected retrieval chunks: total=%s notes=%s video=%s bible=%s queries=%s",
                len(docs),
                note_count,
                video_count,
                bible_count,
                search_queries,
            )

            selected_rows = select_pinned_history_rows(
                history_rows,
                first_row=first_row,
                max_turns=MAX_HISTORY_TURNS,
                max_chars=MAX_HISTORY_CHARS,
            )
            last_prior = prior_user_queries[-1] if prior_user_queries else ""
            new_topic = bool(last_prior) and current_carries_new_topic(
                user_query_llm, last_prior
            )
            history_messages = []
            history_chars = 0
            for msg in selected_rows:
                history_messages.append(HumanMessage(content=msg.user_query))
                ai_text = sanitize_history_text(msg.ai_response or "")
                if new_topic:
                    ai_text = (
                        "I already taught a different topic in this chat. "
                        "Do not copy that outline. Use the current REFERENCE NOTES "
                        "for this new question."
                    )
                history_messages.append(AIMessage(content=ai_text))
                history_chars += len(f"{msg.user_query} {ai_text}")
            logger.warning(
                "Chat history pinned opening=%r turns=%s chars=%s session=%s",
                (selected_rows[0].user_query[:120] if selected_rows else ""),
                len(selected_rows),
                history_chars,
                session_id[:18],
            )

            biblical_names = find_biblical_character_names(user_query_llm)
            if biblical_names:
                logger.debug("Biblical character names detected: %s", biblical_names)
            opening_text = (first_row.user_query or "").strip() if first_row else ""
            if looks_like_opening_recall(user_query_llm) and opening_text:
                followup_block = format_opening_recall_steer(opening_text)
            elif new_topic:
                followup_block = NEW_TOPIC_STEER
            elif prior_user_queries:
                followup_block = FOLLOWUP_STEER
            else:
                followup_block = ""
            system_content = (
                build_chat_system_prompt(biblical_names=biblical_names)
                + (LIBRARY_PULL_STEER if looks_like_library_pull(user_query_llm) else "")
                + followup_block
                + format_teaching_claims_block(teaching_claims)
                + language_reply_instruction("en")
                + "\nREFERENCE NOTES:\n{context}"
            )
            system_filled = system_content.replace(
                "{context}",
                context if context.strip() else EMPTY_REFERENCE_NOTES,
            )
            system_filled, history_messages, completion_tokens, used_tokens = fit_chat_budget(
                system_filled,
                history_messages,
                user_query_llm,
                CHAT_MAX_TOKENS,
                safety=int(os.getenv("CHAT_TOKEN_SAFETY", "96")),
            )
            logger.debug(
                "Chat token budget: prompt≈%s completion=%s history_msgs=%s",
                used_tokens,
                completion_tokens,
                len(history_messages),
            )

            human_content = user_query_llm
            if brief_social:
                human_content = f"{CONVERSATIONAL_STEER}{user_query_llm.strip()}"
            elif opening_recall and opening_text:
                human_content = (
                    format_opening_recall_steer(opening_text)
                    + "\nUser question:\n"
                    + user_query_llm.strip()
                )
            human_content = f"{human_content}{language_generation_reminder()}"
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
                "teaching_claims": teaching_claims,
                "topic_query": topic_query,
                "user_query": user_query_llm,
            }

        def _response_sources(docs, answer: str, query: str = ""):
            """3–5 distinct sources: cited first, then a relevant weighted sample.

            Knowledge-only books stay in REFERENCE NOTES but never in this list, so
            members cannot open those files from chat sermon sources. Uncited
            leftovers are not filled A–Z — that buried Prayer Barriers under
            Community / Contagious / NKJV.
            """
            public_docs = visible_chat_source_docs(docs)
            if not public_docs:
                return []
            return select_chat_source_chips(
                public_docs,
                answer,
                _doc_source_label,
                is_video=is_video_chunk,
                min_count=RETRIEVAL_SOURCE_MIN,
                limit=RETRIEVAL_SOURCE_MAX,
                query=query,
            )

        def _kick_worker():
            from .vllm_warmup import warmup_vllm_worker

            warmup_vllm_worker(wait=False, force=True, timeout_s=3.0)

        def _short_timeout_bound(max_tokens):
            timeout_s = min(EMPTY_STREAM_RETRY_TIMEOUT_S, float(CHAT_TIMEOUT_S))
            llm = get_chat_llm(
                temperature=CHAT_TEMPERATURE,
                max_tokens=max_tokens,
                timeout=timeout_s,
                top_p=CHAT_TOP_P,
                presence_penalty=CHAT_PRESENCE_PENALTY,
                frequency_penalty=CHAT_FREQUENCY_PENALTY,
                extra_body=CHAT_VLLM_EXTRA_BODY,
            )
            return llm.bind(max_tokens=max_tokens)

        def _generate_tokens(prepared):
            bound = prepared["bound"]
            messages = prepared["messages"]
            yielded = False
            try:
                for text in iter_tokens_with_retries(
                    lambda: _iter_chat_tokens(bound, messages),
                    attempts=1,
                ):
                    yielded = True
                    yield text
                return
            except Exception as exc:
                if yielded:
                    raise
                logger.warning(
                    "Chat stream failed before tokens (%s); retrying once with a %ss timeout",
                    exc,
                    int(min(EMPTY_STREAM_RETRY_TIMEOUT_S, float(CHAT_TIMEOUT_S))),
                )
            _kick_worker()
            retry_bound = _short_timeout_bound(prepared["completion_tokens"])
            try:
                for text in iter_tokens_with_retries(
                    lambda: _iter_chat_tokens(retry_bound, messages),
                    attempts=1,
                ):
                    yielded = True
                    yield text
                if yielded:
                    return
            except Exception as exc:
                if yielded:
                    raise
                if is_empty_generation_error(exc):
                    raise ChatGenerationError(EMPTY_STREAM_USER_MESSAGE) from exc
                logger.exception(
                    "Error while streaming chat tokens; retrying with a smaller budget"
                )
            smaller = max(256, int(prepared["completion_tokens"]) // 2)
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
            small_bound = _short_timeout_bound(smaller)
            prepared["messages"] = trimmed
            prepared["bound"] = small_bound
            try:
                yielded = False
                for text in iter_tokens_with_retries(
                    lambda: _iter_chat_tokens(small_bound, trimmed),
                    attempts=1,
                ):
                    yielded = True
                    yield text
                if yielded:
                    return
            except ChatGenerationError:
                raise
            except Exception:
                logger.exception("Smaller-budget chat stream also failed")
            raise ChatGenerationError(EMPTY_STREAM_USER_MESSAGE)

        def _retry_if_cjk_leak(prepared, first_raw: str) -> tuple[str, bool]:
            answer, leaked = recover_english_generation(first_raw)
            if not leaked:
                return answer, False
            logger.warning("Chat reply leaked CJK or rewrite notes; retrying once")
            try:
                retry_raw = "".join(_generate_tokens(prepared))
            except Exception:
                logger.exception("CJK leak retry failed; sanitizing the first answer")
                retry_raw = ""
            recovered, still_leaked = recover_english_generation(first_raw, retry_raw)
            if still_leaked:
                logger.warning(
                    "CJK leak retry still mixed scripts; keeping the English lead-in"
                )
            return recovered, still_leaked

        if want_stream:
            def produce_events():
                emit_live = chat_language == "en"
                yield _sse({"type": "status", "phase": "started"})
                prepared = prepare_chat()
                if prepared["kind"] == "final":
                    yield from _immediate_sse(prepared["payload"])
                    return
                first_raw_parts = []
                painted_parts = []
                leak_started = False
                for text in _generate_tokens(prepared):
                    first_raw_parts.append(text)
                    raw_so_far = "".join(first_raw_parts)
                    if leak_started:
                        if live_history:
                            live_history.publish(
                                sanitize_chat_answer(raw_so_far), streaming=True
                            )
                        continue
                    if looks_like_rewrite_leak(raw_so_far):
                        leak_started = True
                        recovered_now = sanitize_chat_answer(raw_so_far)
                        painted_parts = [recovered_now]
                        if emit_live:
                            yield _sse({"type": "replace", "text": recovered_now})
                        if live_history:
                            live_history.publish(recovered_now, streaming=True)
                        continue
                    visible = sanitize_stream_delta(text)
                    if visible:
                        painted_parts.append(visible)
                        if emit_live:
                            yield _sse({"type": "delta", "text": visible})
                    if live_history:
                        live_history.publish("".join(painted_parts), streaming=True)
                first_raw = "".join(first_raw_parts)
                if not first_raw.strip():
                    raise ChatGenerationError(EMPTY_STREAM_USER_MESSAGE)
                answer, leaked = _retry_if_cjk_leak(prepared, first_raw)
                answer = _speaker_repaired(prepared, answer)
                painted = "".join(painted_parts)
                if emit_live and answer != painted:
                    yield _sse({"type": "replace", "text": answer})
                if live_history:
                    live_history.publish(answer, streaming=True)
                expansion_pass = 0
                while (
                    not leaked
                    and answer_needs_expansion(answer, query=user_query_llm)
                    and expansion_pass < MAX_EXPANSION_PASSES
                ):
                    expansion_pass += 1
                    logger.warning(
                        "Chat answer was short (%s chars); requesting continuation %s/%s",
                        answer_char_count(answer),
                        expansion_pass,
                        MAX_EXPANSION_PASSES,
                    )
                    extra_parts = []
                    try:
                        for text in _iter_continuation_tokens(prepared, answer):
                            extra_parts.append(text)
                    except Exception:
                        logger.exception("Continuation failed; keeping the first answer")
                        break
                    extra = _speaker_repaired(
                        prepared, _usable_extra(answer, "".join(extra_parts))
                    )
                    if not extra:
                        break
                    if emit_live:
                        yield _sse({"type": "delta", "text": "\n\n" + extra})
                    answer = _speaker_repaired(
                        prepared, _join_continuation(answer, extra)
                    )
                    if live_history:
                        live_history.publish(answer, streaming=True)
                repair_steer, repair_budget = (
                    (None, 0) if leaked else _claim_repair_plan(
                        prepared, answer, query=user_query_llm
                    )
                )
                if repair_steer:
                    extra_parts = []
                    try:
                        for text in _iter_continuation_tokens(
                            prepared,
                            answer,
                            steer=repair_steer,
                            token_budget=repair_budget,
                        ):
                            extra_parts.append(text)
                    except Exception:
                        logger.exception("Claim-coverage repair failed; keeping the first answer")
                    extra = _speaker_repaired(
                        prepared, _usable_extra(answer, "".join(extra_parts))
                    )
                    if extra:
                        if emit_live:
                            yield _sse({"type": "delta", "text": "\n\n" + extra})
                        answer = _speaker_repaired(
                            prepared, _join_continuation(answer, extra)
                        )
                        if live_history:
                            live_history.publish(answer, streaming=True)
                quote_steer, quote_budget = (
                    (None, 0) if leaked else _quote_repair_plan(
                        prepared, answer, query=user_query_llm
                    )
                )
                if quote_steer:
                    extra_parts = []
                    try:
                        for text in _iter_continuation_tokens(
                            prepared,
                            answer,
                            steer=quote_steer,
                            token_budget=quote_budget,
                        ):
                            extra_parts.append(text)
                    except Exception:
                        logger.exception("Quote repair failed; keeping the first answer")
                    extra = _speaker_repaired(
                        prepared, _usable_extra(answer, "".join(extra_parts))
                    )
                    if extra:
                        if emit_live:
                            yield _sse({"type": "delta", "text": "\n\n" + extra})
                        answer = _speaker_repaired(
                            prepared, _join_continuation(answer, extra)
                        )
                        if live_history:
                            live_history.publish(answer, streaming=True)
                grounding_steer, grounding_budget = (
                    (None, 0) if leaked else _grounding_repair_plan(
                        prepared, answer
                    )
                )
                if grounding_steer:
                    extra_parts = []
                    try:
                        for text in _iter_continuation_tokens(
                            prepared,
                            answer,
                            steer=grounding_steer,
                            token_budget=grounding_budget,
                        ):
                            extra_parts.append(text)
                    except Exception:
                        logger.exception("RAG grounding repair failed; keeping the first answer")
                    extra = _speaker_repaired(
                        prepared, _usable_extra(answer, "".join(extra_parts))
                    )
                    if extra:
                        if emit_live:
                            yield _sse({"type": "delta", "text": "\n\n" + extra})
                        answer = _speaker_repaired(
                            prepared, _join_continuation(answer, extra)
                        )
                        if live_history:
                            live_history.publish(answer, streaming=True)
                finish_extra = "" if leaked else _finish_incomplete_extra(prepared, answer)
                if finish_extra:
                    finish_extra = _speaker_repaired(prepared, finish_extra)
                    if emit_live:
                        prefix = "" if answer.endswith((" ", "\n")) else " "
                        yield _sse({"type": "delta", "text": prefix + finish_extra})
                    answer = _speaker_repaired(
                        prepared, _join_continuation(answer, finish_extra)
                    )
                final_answer = sanitize_chat_answer(
                    _finalize_teaching_answer(prepared, answer)
                )
                if emit_live:
                    prefix = (answer or "").rstrip()
                    if final_answer.startswith(prefix):
                        extra = final_answer[len(prefix) :].strip()
                        if extra:
                            yield _sse({"type": "delta", "text": "\n\n" + extra})
                    elif final_answer != prefix:
                        yield _sse({"type": "replace", "text": final_answer})
                answer = final_answer
                response_sources = _response_sources(
                    prepared["docs"],
                    answer,
                    query=prepared.get("topic_query") or user_query_llm,
                )
                if live_history:
                    live_history.publish(
                        answer, streaming=False, sources=response_sources, force=True
                    )
                saved_message = _save_ai_response(
                    regenerate=regenerate,
                    target_message=prepared["target_message"],
                    session_id=session_id,
                    chat_user=chat_user,
                    user_query_stored=user_query_stored,
                    answer=answer,
                )
                display = display_reply(answer, chat_language)
                if not emit_live:
                    yield _sse({"type": "delta", "text": display})
                done = {
                    "type": "done",
                    "answer": display,
                    "sources": response_sources,
                }
                if saved_message is not None:
                    done["message_id"] = saved_message.id
                logger.debug("Chat response generated successfully.")
                yield _sse(done)

            def token_events():
                yield sse_keepalive()
                try:
                    yield from iter_with_sse_heartbeats(produce_events, interval_s=2.0)
                except ChatGenerationError as exc:
                    logger.exception("Chat generation failed after retries")
                    yield _sse({
                        "type": "error",
                        "error": str(exc) or EMPTY_STREAM_USER_MESSAGE,
                    })
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
            response = prepared["bound"].invoke(prepared["messages"])
            answer = response.content or ""
            answer, leaked = _retry_if_cjk_leak(prepared, answer)
            answer = _speaker_repaired(prepared, answer)
            if live_history:
                live_history.publish(answer, streaming=True)
            expansion_pass = 0
            while (
                not leaked
                and answer_needs_expansion(answer, query=user_query_llm)
                and expansion_pass < MAX_EXPANSION_PASSES
            ):
                expansion_pass += 1
                logger.warning(
                    "Chat answer was short (%s chars); requesting continuation %s/%s",
                    answer_char_count(answer),
                    expansion_pass,
                    MAX_EXPANSION_PASSES,
                )
                continue_tokens = continuation_token_budget(
                    answer, completion_tokens=prepared["completion_tokens"]
                )
                if continue_tokens <= 0:
                    break
                try:
                    extra = prepared["llm"].bind(max_tokens=continue_tokens).invoke(
                        _continuation_messages(prepared["messages"], answer)
                    )
                    extra_text = (getattr(extra, "content", "") or "").strip()
                except Exception:
                    logger.exception("Continuation failed; retrying with a trimmed prompt")
                    try:
                        extra = prepared["llm"].bind(
                            max_tokens=continue_tokens
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
                extra_text = _usable_extra(answer, extra_text)
                if not extra_text:
                    break
                answer = _join_continuation(answer, extra_text)
            repair_steer, repair_budget = (
                (None, 0) if leaked else _claim_repair_plan(
                    prepared, answer, query=user_query_llm
                )
            )
            if repair_steer:
                try:
                    extra = prepared["llm"].bind(max_tokens=repair_budget).invoke(
                        _continuation_messages(
                            prepared["messages"], answer, steer=repair_steer
                        )
                    )
                    extra_text = (getattr(extra, "content", "") or "").strip()
                except Exception:
                    logger.exception("Claim-coverage repair failed; retrying with a trimmed prompt")
                    try:
                        extra = prepared["llm"].bind(max_tokens=repair_budget).invoke(
                            _trim_continuation_messages(
                                _continuation_messages(
                                    prepared["messages"], answer, steer=repair_steer
                                )
                            )
                        )
                        extra_text = (getattr(extra, "content", "") or "").strip()
                    except Exception:
                        logger.exception("Claim-coverage repair failed; keeping the first answer")
                        extra_text = ""
                extra_text = _usable_extra(answer, extra_text)
                if extra_text:
                    answer = _join_continuation(answer, extra_text)
            quote_steer, quote_budget = (
                (None, 0) if leaked else _quote_repair_plan(
                    prepared, answer, query=user_query_llm
                )
            )
            if quote_steer:
                try:
                    extra = prepared["llm"].bind(max_tokens=quote_budget).invoke(
                        _continuation_messages(
                            prepared["messages"], answer, steer=quote_steer
                        )
                    )
                    extra_text = (getattr(extra, "content", "") or "").strip()
                except Exception:
                    logger.exception("Quote repair failed; retrying with a trimmed prompt")
                    try:
                        extra = prepared["llm"].bind(max_tokens=quote_budget).invoke(
                            _trim_continuation_messages(
                                _continuation_messages(
                                    prepared["messages"], answer, steer=quote_steer
                                )
                            )
                        )
                        extra_text = (getattr(extra, "content", "") or "").strip()
                    except Exception:
                        logger.exception("Quote repair failed; keeping the first answer")
                        extra_text = ""
                extra_text = _usable_extra(answer, extra_text)
                if extra_text:
                    answer = _join_continuation(answer, extra_text)
            grounding_steer, grounding_budget = (
                (None, 0) if leaked else _grounding_repair_plan(prepared, answer)
            )
            if grounding_steer:
                try:
                    extra = prepared["llm"].bind(max_tokens=grounding_budget).invoke(
                        _continuation_messages(
                            prepared["messages"], answer, steer=grounding_steer
                        )
                    )
                    extra_text = (getattr(extra, "content", "") or "").strip()
                except Exception:
                    logger.exception("RAG grounding repair failed; retrying with a trimmed prompt")
                    try:
                        extra = prepared["llm"].bind(max_tokens=grounding_budget).invoke(
                            _trim_continuation_messages(
                                _continuation_messages(
                                    prepared["messages"], answer, steer=grounding_steer
                                )
                            )
                        )
                        extra_text = (getattr(extra, "content", "") or "").strip()
                    except Exception:
                        logger.exception("RAG grounding repair failed; keeping the first answer")
                        extra_text = ""
                extra_text = _usable_extra(answer, extra_text)
                if extra_text:
                    answer = _join_continuation(answer, extra_text)
            finish_extra = "" if leaked else _finish_incomplete_extra(prepared, answer)
            if finish_extra:
                answer = _join_continuation(answer, finish_extra)
            answer = sanitize_chat_answer(_finalize_teaching_answer(prepared, answer))
            response_sources = _response_sources(
                prepared["docs"],
                answer,
                query=prepared.get("topic_query") or user_query_llm,
            )
            if live_history:
                live_history.publish(
                    answer, streaming=False, sources=response_sources, force=True
                )
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
                    display_reply(answer, chat_language),
                    sources=response_sources,
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
    permission_classes = [IsAuthenticated, HasPremiumAccess]
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
    permission_classes = [IsAuthenticated, HasPremiumAccess]
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

