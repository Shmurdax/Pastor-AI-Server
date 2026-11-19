"""Minimal sermon retrieval plus a streamed Gemma reply.

This is a fresh path for response_testing. It does not restore the old
prompt, grounding, rerank, or refusal stack.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Iterable, Iterator

from .study_draft import (
    CLASSIFIER_SYSTEM,
    DraftRoute,
    chat_fallback,
    continued_draft_route,
    decision_from_classifier,
    draft_system_prompt,
    draft_user_content,
    gap_messages,
    missing_scripture_refs,
    parse_plan_text,
    plan_messages,
    render_plan,
    rule_route,
)

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 6
_LAST_LLM_WARM = 0.0
HYDE_CANDIDATES = 32
SERMON_CHUNK_KIND = "sermon_quote"
_LEXICAL_BOOST = 0.12
_QUERY_TERM_STOP = {
    "about",
    "could",
    "should",
    "there",
    "their",
    "these",
    "those",
    "which",
    "where",
    "would",
}
# Words that show up in almost every sermon. They must not count as the subject
# of a whole-collection text search, or the first hits are unrelated notes.
_GENERIC_TERMS = _QUERY_TERM_STOP | {
    "already",
    "answer",
    "answers",
    "assisted",
    "believe",
    "believes",
    "believer",
    "believers",
    "bible",
    "biblical",
    "calls",
    "carrying",
    "choose",
    "chosen",
    "choice",
    "christian",
    "christians",
    "church",
    "congregation",
    "considering",
    "culture",
    "follow",
    "follows",
    "gospel",
    "jesus",
    "kindness",
    "living",
    "member",
    "members",
    "outside",
    "pastor",
    "pastors",
    "people",
    "permitted",
    "respond",
    "person",
    "persons",
    "practice",
    "explain",
    "question",
    "questions",
    "scripture",
    "scriptures",
    "shame",
    "someone",
    "something",
    "teach",
    "teaching",
    "teachings",
    "together",
    "trapped",
    "woman",
    "still",
    "other",
    "every",
    "after",
    "under",
    "again",
    "being",
    "while",
    "first",
    "before",
}
SEARCH_CHUNK_KINDS = ("sermon_quote", "video_transcript", "video_topic_overview")
_TEXT_INDEXED: set[str] = set()
PASSAGE_PROMPT_CHARS = 1200
HYDE_MAX_WORDS = 120
_SSE_FLUSH_PAD = " " * 4096
_HYDE_SYSTEM = (
    "Write one short sermon-note paragraph that would answer the question. "
    "Use the words a pastor would actually preach: names, doctrines, and phrases. "
    "Do not address the reader. Do not say this is hypothetical. "
    "Do not invent a sermon title. Stay under 120 words."
)
_PHRASE_SYSTEM = (
    "List up to 6 short search phrases a sermon note would use for this question. "
    "Include the pastor's own wording and the biblical terms for that same subject. "
    "One phrase per line. No sentences. No sermon titles. Each phrase is 1 to 5 words."
)
_FUNCTION_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "be",
    "can",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "should",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "who",
    "with",
}
_DRAFT_HYDE_SYSTEM = (
    "Write one short Bible-study or sermon-note paragraph a pastor would preach "
    "for this request. Include the topic, any named scriptures, and two or three "
    "teaching points in sermon-note wording. Do not address the reader. "
    "Do not say this is hypothetical. Do not invent a sermon title. Stay under 140 words."
)


def sse_pack(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_keepalive() -> str:
    return f": keepalive{_SSE_FLUSH_PAD}\n\n"


def wants_chat_stream(stream_flag, accept_header: str = "") -> bool:
    if str(stream_flag).lower() in {"1", "true", "yes"}:
        return True
    return "text/event-stream" in (accept_header or "")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def vllm_base_url() -> str:
    endpoint_id = _env("RUNPOD_VLLM_ENDPOINT_ID")
    if endpoint_id:
        return f"https://api.runpod.ai/v2/{endpoint_id}/openai/v1"
    url = _env("VLLM_URL", "http://127.0.0.1:8010/v1").rstrip("/")
    if url.endswith("/openai/v1") or url.endswith("/v1"):
        return url
    return f"{url}/v1"


def vllm_api_key() -> str:
    for name in ("VLLM_API_KEY", "RUNPOD_API_KEY"):
        value = _env(name)
        if value and value.lower() not in {"not-needed", "empty", "paste_here"}:
            return value
    return ""


def vllm_model() -> str:
    return _env("VLLM_MODEL", "christianai") or "christianai"


def _passage_title(payload: dict) -> str:
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for key in ("title", "source", "source_name"):
        value = payload.get(key) or meta.get(key)
        if value:
            return str(value).strip()
    return "Sermon"


def _passage_text(payload: dict) -> str:
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for key in ("text", "page_content", "content"):
        value = payload.get(key) or meta.get(key)
        if value:
            return str(value).strip()
    return ""


def hyde_enabled() -> bool:
    return _env("CHAT_HYDE", "1").lower() not in {"0", "false", "no", "off"}


def _clip_words(text: str, limit: int = HYDE_MAX_WORDS) -> str:
    words = " ".join((text or "").split()).strip("\"'").split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit])


def _message_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts).strip()
    return ""


def _post_llm(body: dict, *, timeout: float | None = None):
    headers = {"Content-Type": "application/json"}
    key = vllm_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        f"{vllm_base_url()}/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    if timeout is None:
        timeout = float(_env("CHAT_TIMEOUT_S", "180") or "180")
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LLM request failed ({exc.code}): {detail}") from exc


def warm_llm(*, force: bool = False) -> bool:
    """Ping the same chat endpoint HyDE uses so a cold worker can start.

    A successful warm is remembered for ten minutes so a chat that follows
    the Flutter warmup call does not pay for a second ping.
    """
    global _LAST_LLM_WARM
    now = time.monotonic()
    cooldown = float(_env("CHAT_WARM_COOLDOWN_S", "600") or "600")
    if not force and _LAST_LLM_WARM and now - _LAST_LLM_WARM < cooldown:
        return True
    body = {
        "model": vllm_model(),
        "messages": [{"role": "user", "content": "ok"}],
        "temperature": 0,
        "max_tokens": 1,
        "stream": False,
    }
    timeout = float(_env("CHAT_WARM_TIMEOUT_S", "45") or "45")
    try:
        with _post_llm(body, timeout=timeout):
            pass
    except Exception:
        logger.warning("LLM warm failed", exc_info=True)
        return False
    _LAST_LLM_WARM = time.monotonic()
    return True


def generate_hyde_document(query: str) -> str:
    """Ask Gemma for a short sermon paragraph to embed as the search query."""
    body = {
        "model": vllm_model(),
        "messages": [
            {"role": "system", "content": _HYDE_SYSTEM},
            {"role": "user", "content": (query or "").strip()},
        ],
        "temperature": 0.2,
        "max_tokens": 180,
        "stream": False,
    }
    timeout = float(_env("CHAT_HYDE_TIMEOUT_S", "180") or "180")
    with _post_llm(body, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return _clip_words(_message_text(payload))


def _parse_search_phrases(raw: str) -> list[str]:
    phrases = []
    seen = set()
    for line in (raw or "").splitlines():
        cleaned = line.strip().lstrip("-*0123456789.) ").strip(" \"'`")
        words = cleaned.split()
        if not cleaned or not 1 <= len(words) <= 5:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(key)
        if len(phrases) >= 6:
            break
    return phrases


def generate_search_phrases(query: str) -> list[str]:
    """Ask for sermon search phrases. A paragraph would widen the search."""
    body = {
        "model": vllm_model(),
        "messages": [
            {"role": "system", "content": _PHRASE_SYSTEM},
            {"role": "user", "content": (query or "").strip()},
        ],
        "temperature": 0,
        "max_tokens": 80,
        "stream": False,
    }
    timeout = float(_env("CHAT_HYDE_TIMEOUT_S", "180") or "180")
    with _post_llm(body, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return _parse_search_phrases(_message_text(payload))


def generate_search_phrases_with_retry(query: str) -> tuple[list[str], str]:
    """Return (phrases, status). Status is ok, retried, empty, or failed."""
    warm_llm()
    try:
        phrases = generate_search_phrases(query)
    except Exception:
        logger.warning("Search phrase generation failed; retrying once", exc_info=True)
        phrases = None
    if phrases:
        return phrases, "ok"
    try:
        phrases = generate_search_phrases(query)
    except Exception:
        logger.warning("Search phrase retry failed; using the question phrases only", exc_info=True)
        return [], "failed"
    if phrases:
        return phrases, "retried"
    return [], "empty"


def generate_hyde_with_retry(query: str) -> tuple[str, str]:
    """Return (paragraph, status). Status is ok, retried, empty, or failed."""
    warm_llm()
    try:
        text = generate_hyde_document(query)
    except Exception:
        logger.warning("HyDE generation failed; retrying once", exc_info=True)
        text = None
    if text:
        return text, "ok"
    try:
        text = generate_hyde_document(query)
    except Exception:
        logger.warning("HyDE retry failed; using the question search only", exc_info=True)
        return "", "failed"
    if text:
        return text, "retried"
    return "", "empty"


def _hit_score(hit) -> float:
    score = getattr(hit, "score", None)
    try:
        return float(score or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _fingerprint(text: str) -> str:
    return " ".join((text or "").lower().split())[:500]


def _titles(passages: Iterable[dict]) -> list[str]:
    return source_titles(passages)


def _passages_from_hits(hits) -> list[dict]:
    passages = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        text = _passage_text(payload)
        if not text:
            continue
        passages.append(
            {
                "title": _passage_title(payload),
                "text": text,
                "score": _hit_score(hit),
                "file_hash": str(payload.get("file_hash") or "").strip(),
            }
        )
    return passages


def _merge_ranked(hyde_hits: list[dict], query_hits: list[dict], top_k: int) -> list[dict]:
    """Interleave HyDE hits with question hits and drop duplicate chunks.

    Cosine scores from two different query vectors are not comparable, so
    rank order is used. HyDE takes the odd slots so a wording mismatch can
    still surface the sermon that answers it.
    """
    merged = []
    seen = set()

    def push(passage: dict) -> None:
        if len(merged) >= top_k:
            return
        text = (passage.get("text") or "").strip()
        key = _fingerprint(text)
        if not key or key in seen:
            return
        seen.add(key)
        merged.append(_passage_record(passage, text))

    hyde_i = 0
    query_i = 0
    while len(merged) < top_k and (hyde_i < len(hyde_hits) or query_i < len(query_hits)):
        if hyde_i < len(hyde_hits):
            push(hyde_hits[hyde_i])
            hyde_i += 1
        if len(merged) >= top_k:
            break
        if query_i < len(query_hits):
            push(query_hits[query_i])
            query_i += 1
    return merged


def _search_with_vector(client, collection: str, vector, top_k: int) -> list[dict]:
    return _passages_from_hits(_search_qdrant(client, collection, vector, top_k))


def retrieve_passages(query: str, *, top_k: int = DEFAULT_TOP_K, include_debug: bool = False):
    """Search sermons by the question's narrow phrases, then rerank against the question."""
    from qdrant_client import QdrantClient

    from .embeddings_utils import get_embeddings

    embeddings = get_embeddings()
    client = QdrantClient(url=_env("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    collection = _env("QDRANT_COLLECTION", "sermon_brain")
    candidate_k = max(top_k, HYDE_CANDIDATES)
    started = time.monotonic()
    local_phrases = _query_phrases(query)
    model_phrases: list[str] = []
    hyde_status = "off"
    if hyde_enabled():
        model_phrases, hyde_status = generate_search_phrases_with_retry(query)
    phrases = _dedupe_phrases(local_phrases + model_phrases)
    terms = _anchor_terms(query) | set(phrases)
    try:
        query_hits = _search_with_vector(
            client, collection, embeddings.embed_query(query), candidate_k
        )
    except Exception:
        logger.warning("Question search failed", exc_info=True)
        query_hits = []
    query_hits = _promote_lexical(query_hits, terms)
    term_hits = _subject_windows(client, collection, query, terms)
    matched_phrases = [
        phrase
        for phrase in phrases
        if any(phrase in (item.get("text") or "").lower() for item in term_hits)
    ]
    phrase_hits: list[dict] = []
    for phrase in matched_phrases[:4]:
        try:
            phrase_hits.extend(
                _search_with_vector(
                    client, collection, embeddings.embed_query(phrase), min(8, candidate_k)
                )
            )
        except Exception:
            logger.warning("Phrase search failed for %s", phrase, exc_info=True)
    hyde_text = " | ".join(phrases)
    term_fallback = bool(term_hits)
    passages = _order_passages(
        query,
        _dedupe_passages(term_hits + query_hits + phrase_hits),
        top_k,
        terms,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.warning(
        "hyde_request status=%s elapsed_ms=%s terms=%s term_fallback=%s "
        "query_titles=%s hyde_titles=%s merged=%s hyde_text=%s",
        hyde_status,
        elapsed_ms,
        sorted(terms),
        term_fallback,
        _titles(query_hits)[:8],
        _titles(phrase_hits)[:8],
        _titles(passages),
        (hyde_text or "")[:240],
    )
    if include_debug:
        return {
            "passages": passages,
            "hyde_text": hyde_text,
            "hyde_status": hyde_status,
            "term_fallback": term_fallback,
            "query_titles": _titles(query_hits),
            "hyde_titles": _titles(phrase_hits),
        }
    return passages


def _passage_record(passage: dict, text: str) -> dict:
    return {
        "title": passage.get("title") or "Sermon",
        "text": text,
        "score": float(passage.get("score") or 0.0),
        "file_hash": str(passage.get("file_hash") or "").strip(),
    }


def _question_words(query: str) -> list[str]:
    words = []
    for word in re.findall(r"[a-z0-9']{2,}", (query or "").lower()):
        word = word.strip("'")
        if word.endswith("'s"):
            word = word[:-2]
        if word:
            words.append(word)
    return words


def _query_phrases(query: str) -> list[str]:
    """Two- and three-word stretches, including a short or generic word beside a subject."""
    words = _question_words(query)
    phrases = []
    for size in (2, 3):
        for start in range(0, len(words) - size + 1):
            window = words[start : start + size]
            if all(word in _FUNCTION_WORDS for word in window):
                continue
            trimmed = list(window)
            while trimmed and trimmed[0] in _FUNCTION_WORDS:
                trimmed = trimmed[1:]
            while trimmed and trimmed[-1] in _FUNCTION_WORDS:
                trimmed = trimmed[:-1]
            if len(trimmed) < 2:
                continue
            dropped = any(len(word) < 5 or word in _GENERIC_TERMS for word in trimmed)
            if not dropped:
                continue
            phrases.append(" ".join(trimmed))
    return _dedupe_phrases(phrases)[:8]


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    kept = []
    seen = set()
    for phrase in phrases:
        key = " ".join((phrase or "").lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(key)
    return kept


def _anchor_terms(query: str) -> set[str]:
    """Subject words for a whole-collection search.

    Alias lists supply "homosexuality" when the pastor says "gay". Generic
    sermon words such as "christian" are left out so they cannot crowd out
    the note that names the subject.
    """
    from .sermon_catalog import TOPIC_ALIASES

    anchors: set[str] = set()
    words = []
    for word in re.findall(r"[a-z0-9']{3,}", (query or "").lower()):
        word = word.strip("'")
        if word.endswith("'s"):
            word = word[:-2]
        if word:
            words.append(word)
    for word in words:
        linked = False
        for key, aliases in TOPIC_ALIASES.items():
            if word == key or word in aliases:
                anchors.update(
                    alias.lower() for alias in aliases if alias.lower() not in _GENERIC_TERMS
                )
                linked = True
        if not linked and len(word) >= 5 and word not in _GENERIC_TERMS:
            anchors.add(word)
    return anchors


def _dedupe_passages(passages: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for passage in passages:
        text = (passage.get("text") or "").strip()
        key = _fingerprint(text)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(_passage_record(passage, text))
    return merged


def _ensure_text_index(client, collection: str) -> None:
    if collection in _TEXT_INDEXED:
        return
    try:
        from .qdrant_utils import ensure_payload_indexes

        ensure_payload_indexes(client, collection)
    except Exception:
        logger.warning("Sermon text index was not created", exc_info=True)
    _TEXT_INDEXED.add(collection)


def _chunk_kind_filter():
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    return Filter(
        must=[FieldCondition(key="chunk_kind", match=MatchAny(any=list(SEARCH_CHUNK_KINDS)))]
    )


def _subject_windows(client, collection: str, query: str, terms: set[str]) -> list[dict]:
    """Every indexed note that states a subject word, then the best window of that file."""
    if not terms:
        return []
    try:
        matches = _match_text_terms(client, collection, terms)
    except Exception as exc:
        logger.warning("Text match failed (%s); scanning sermon notes", exc)
        try:
            matches = _scroll_term_matches(client, collection, terms, 24)
        except Exception:
            logger.warning("Subject scan failed", exc_info=True)
            return []
    hashed = []
    ranked_matches = sorted(
        matches,
        key=lambda item: max(
            (len(term) for term in terms if term in (item.get("text") or "").lower()),
            default=0,
        ),
        reverse=True,
    )
    for item in ranked_matches:
        file_hash = item.get("file_hash")
        if file_hash and file_hash not in hashed:
            hashed.append(file_hash)
    if not hashed:
        return matches
    try:
        from .sermon_catalog import lookup_chunks_by_file_hashes

        docs = lookup_chunks_by_file_hashes(
            client, collection, hashed, query=query, limit_per_file=2
        )
    except Exception:
        logger.warning("File window lookup failed", exc_info=True)
        return matches
    windows = []
    for doc in docs:
        meta = doc.metadata or {}
        text = str(getattr(doc, "page_content", "") or "").strip()
        if not text:
            continue
        windows.append(
            {
                "title": str(meta.get("title") or "Sermon"),
                "text": text,
                "score": 1.0,
                "file_hash": str(meta.get("file_hash") or "").strip(),
            }
        )
    # Keep the chunk that actually contained the subject word. The file lookup
    # adds the teaching window; it must not replace the matching chunk.
    return _dedupe_passages(matches + windows)


def _match_text_terms(client, collection: str, terms: set[str]) -> list[dict]:
    from qdrant_client.models import FieldCondition, Filter, MatchText

    _ensure_text_index(client, collection)
    kind_filter = _chunk_kind_filter()
    found = []
    seen = set()
    for term in sorted(terms):
        text_filter = Filter(
            must=[
                kind_filter.must[0],
                FieldCondition(key="text", match=MatchText(text=term)),
            ]
        )
        points = _scroll_filtered(client, collection, text_filter, limit=8)
        for point in points:
            payload = getattr(point, "payload", None) or {}
            text = _passage_text(payload)
            if not text or term not in text.lower():
                continue
            key = _fingerprint(text)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                {
                    "title": _passage_title(payload),
                    "text": text,
                    "score": 1.0,
                    "file_hash": str(payload.get("file_hash") or "").strip(),
                }
            )
    if not found:
        raise RuntimeError("text match returned nothing")
    return found


def _scroll_filtered(client, collection: str, query_filter, limit: int) -> list:
    points = []
    offset = None
    while len(points) < limit:
        batch, offset = client.scroll(
            collection_name=collection,
            scroll_filter=query_filter,
            limit=min(64, limit - len(points)),
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not batch:
            break
        points.extend(batch)
        if offset is None:
            break
    return points


def _order_passages(query: str, passages: list[dict], top_k: int, terms: set[str]) -> list[dict]:
    """Prefer notes that state the subject, then a cross-encoder when one is running."""
    from .note_priority import chunk_thesis_score

    rerank_scores = _rerank_scores(query, passages)
    decorated = []
    for index, passage in enumerate(passages):
        text = passage.get("text") or ""
        lowered = text.lower()
        hits = sum(1 for term in terms if term in lowered)
        thesis = chunk_thesis_score(text)
        vector = float(passage.get("score") or 0.0)
        rerank = rerank_scores[index] if rerank_scores is not None else 0.0
        if rerank_scores is not None:
            key = (rerank, hits, thesis, vector, -index)
        else:
            key = (hits, thesis, vector, -index)
        decorated.append((key, passage))
    decorated.sort(key=lambda item: item[0], reverse=True)
    return [passage for _key, passage in decorated[:top_k]]


def _rerank_scores(query: str, passages: list[dict]) -> list[float] | None:
    if not passages or not _flag_enabled("CHAT_RERANK", "1"):
        return None
    try:
        from .search_sidecar import SidecarReranker, sidecar_url
    except Exception:
        return None
    url = sidecar_url()
    if not url:
        return None
    try:
        reranker = SidecarReranker(url, timeout=30.0)
        scores: list[float] = []
        for start in range(0, len(passages), 32):
            batch = passages[start : start + 32]
            pairs = [(query, (item.get("text") or "")[:1500]) for item in batch]
            scores.extend(float(score) for score in reranker.predict(pairs))
        if len(scores) != len(passages):
            return None
        return scores
    except Exception:
        logger.warning("Cross-encoder rerank failed; keeping subject order", exc_info=True)
        return None


def _passages_contain_terms(passages: list[dict], terms: set[str]) -> bool:
    if not terms:
        return True
    blob = "\n".join((passage.get("text") or "") for passage in passages).lower()
    return any(term in blob for term in terms)


def _scroll_term_matches(client, collection: str, terms: set[str], top_k: int) -> list[dict]:
    """Find notes that contain a subject word, including ones past the first pages.

    ``CHAT_TERM_SCAN_MAX`` defaults to a full scan. Set it to a positive
    number to stop early.
    """
    matches = []
    offset = None
    scanned = 0
    try:
        raw_cap = int(_env("CHAT_TERM_SCAN_MAX", "0") or "0")
    except ValueError:
        raw_cap = 0
    hard_cap = raw_cap if raw_cap > 0 else 100000
    try:
        query_filter = _chunk_kind_filter()
    except Exception:
        query_filter = _sermon_filter()
    while len(matches) < top_k and scanned < hard_cap:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=query_filter,
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        scanned += len(points)
        for point in points:
            payload = getattr(point, "payload", None) or {}
            text = _passage_text(payload)
            if not text or not any(term in text.lower() for term in terms):
                continue
            matches.append(
                {
                    "title": _passage_title(payload),
                    "text": text,
                    "score": 1.0,
                    "file_hash": str(payload.get("file_hash") or "").strip(),
                }
            )
            if len(matches) >= top_k:
                break
        if offset is None:
            break
    return matches


def _sermon_filter():
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return Filter(
        must=[FieldCondition(key="chunk_kind", match=MatchValue(value=SERMON_CHUNK_KIND))]
    )


def _search_qdrant(client, collection: str, vector, top_k: int):
    sermon_filter = _sermon_filter()
    if hasattr(client, "query_points"):
        result = client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=sermon_filter,
            limit=top_k,
            with_payload=True,
        )
        return list(getattr(result, "points", None) or [])
    return list(
        client.search(
            collection_name=collection,
            query_vector=vector,
            query_filter=sermon_filter,
            limit=top_k,
            with_payload=True,
        )
    )


def _query_terms(query: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9']{6,}", (query or "").lower())
        if word not in _QUERY_TERM_STOP
    }


def _lexical_boost(text: str, terms: set[str]) -> float:
    if not terms:
        return 0.0
    lowered = (text or "").lower()
    if any(term in lowered for term in terms):
        return _LEXICAL_BOOST
    return 0.0


def _promote_lexical(passages: list[dict], terms: set[str]) -> list[dict]:
    """Raise sermons that use the question's own words.

    Vector neighbors often miss the note that actually says the term.
    Scores here come from a single query vector, so they can be compared.
    """
    decorated = []
    for index, passage in enumerate(passages):
        score = float(passage.get("score") or 0.0) + _lexical_boost(passage.get("text") or "", terms)
        decorated.append((score, -index, passage))
    decorated.sort(reverse=True)
    return [passage for _score, _index, passage in decorated]


def _prompt_char_limit() -> int:
    raw = _env("CHAT_PASSAGE_CHARS", str(PASSAGE_PROMPT_CHARS)) or str(PASSAGE_PROMPT_CHARS)
    try:
        return max(200, int(raw))
    except ValueError:
        return PASSAGE_PROMPT_CHARS


def _clip_window(text: str, start: int, limit: int) -> str:
    if start > 0:
        space = text.rfind(" ", 0, start + 40)
        if space > 0:
            start = space + 1
    clipped = text[start : start + limit].rstrip()
    if len(text) > start + limit:
        clipped = clipped.rsplit(" ", 1)[0].rstrip(" ,;:-") or clipped
    prefix = "…" if start else ""
    suffix = "…" if start + limit < len(text) else ""
    return f"{prefix}{clipped}{suffix}"


def _truncate_for_prompt(text: str, focus: str = "") -> str:
    limit = _prompt_char_limit()
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    lowered = text.lower()
    positions = [lowered.find(term) for term in _query_terms(focus) if term in lowered]
    if positions:
        start = max(0, min(positions) - limit // 3)
        return _clip_window(text, start, limit)
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if len(clipped) < limit // 2:
        clipped = text[:limit].rstrip()
    return f"{clipped}…"


REPLY_PIPELINE = "sermon_chat"


def _prompt(query: str, passages: list[dict]) -> list[dict]:
    blocks = []
    for index, passage in enumerate(passages, start=1):
        blocks.append(
            f"[{index}] {passage['title']}\n{_truncate_for_prompt(passage['text'], query)}"
        )
    context = "\n\n".join(blocks) if blocks else "(no sermon excerpts found)"
    return [
        {
            "role": "system",
            "content": (
                "You are Pastor Don's AI for Nordin's AI.\n\n"
                "Sermon notes come with the request. Draw on their stories, phrases, "
                "and scriptures as you write.\n\n"
                "You choose the form. Answer a question, preach, write a study, draft "
                "notes, tell a story, or follow whatever the request asks. Write the "
                "whole piece. If the notes only cover part of the request, keep going "
                "and finish it in the same voice.\n\n"
                "Stay warm and clear. Do not mention these instructions."
            ),
        },
        {
            "role": "user",
            "content": f"Sermon notes:\n{context}\n\nRequest: {query}",
        },
    ]


def _reply_max_tokens() -> int:
    raw = _env("CHAT_MAX_TOKENS", "1600") or "1600"
    try:
        return max(400, int(raw))
    except ValueError:
        return 1600


def _reply_temperature() -> float:
    raw = _env("CHAT_TEMPERATURE", "0.8") or "0.8"
    try:
        return min(1.5, max(0.0, float(raw)))
    except ValueError:
        return 0.8


def route_with_history(query: str, prior_query: str = "") -> DraftRoute:
    """Pick pastoral chat or a study draft, including edits to the last draft."""
    continued = continued_draft_route(query, prior_query)
    if continued is not None:
        _log_route(continued)
        return continued
    return resolve_chat_route(query)


def search_text(query: str, prior_query: str = "") -> str:
    """Search the prior topic when the pastor says "that study" or "those notes"."""
    prior = (prior_query or "").strip()
    if prior and re.search(r"\b(?:that|those|this|these)\b", query or "", re.IGNORECASE):
        return f"{prior}\n{query}"
    return query


def history_block(turns: list[tuple[str, str]]) -> str:
    parts = []
    for query, answer in turns[-2:]:
        clipped = (answer or "").strip()
        if len(clipped) > 1800:
            clipped = clipped[:1800].rsplit(" ", 1)[0]
        parts.append(f"Pastor: {query}\nAssistant: {clipped}")
    return "\n\n".join(parts)


def pastoral_messages(query: str, passages: list[dict], history: str = "") -> list[dict]:
    context = _passage_context(query, passages) or "(no sermon excerpts found)"
    prior = f"Earlier in this chat:\n{history}\n\n" if history else ""
    return [
        {
            "role": "system",
            "content": (
                "You are Pastor Don's AI teaching assistant for Nordin's AI.\n\n"
                "Answer from the sermon excerpts. Prefer their wording and scripture. "
                "Do not invent quotes or verses the excerpts do not contain.\n\n"
                "Write one short answer, under 900 characters. "
                "Include one scripture reference from the excerpts when one is there. "
                "If this continues an earlier reply, name that same topic in the answer.\n\n"
                "Keep the tone warm and clear."
            ),
        },
        {
            "role": "user",
            "content": f"{prior}Sermon excerpts:\n{context}\n\nQuestion: {query}",
        },
    ]


def fit_pastoral_length(answer: str, limit: int = 1100) -> str:
    """Keep a pastoral reply inside the short-answer limit."""
    text = (answer or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    dot = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("?"))
    if dot >= 200:
        return cut[: dot + 1].strip()
    return cut.strip()


def public_passages(passages: Iterable[dict]) -> list[dict]:
    return [
        {"title": item.get("title") or "", "text": item.get("text") or ""}
        for item in passages
    ]


def stream_llm_tokens(
    query: str,
    passages: list[dict],
    history: str = "",
) -> Iterator[str]:
    """Yield a short pastoral reply from the sermon excerpts."""
    yield from stream_message_tokens(
        pastoral_messages(query, passages, history),
        max_tokens=260,
        temperature=0.2,
    )


def stream_message_tokens(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float = 0.2,
) -> Iterator[str]:
    body = {
        "model": vllm_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    with _post_llm(body) as response:
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                if data == "[DONE]":
                    break
                continue
            payload = json.loads(data)
            choices = payload.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content") or ""
            if text:
                yield text


def source_titles(passages: Iterable[dict]) -> list[str]:
    seen = []
    for passage in passages:
        title = (passage.get("title") or "").strip()
        if title and title not in seen:
            seen.append(title)
    return seen


def _flag_enabled(name: str, default: str = "1") -> bool:
    return _env(name, default).lower() not in {"0", "false", "no", "off"}


def draft_pipeline_enabled() -> bool:
    return _flag_enabled("CHAT_DRAFT", "1")


def draft_classifier_enabled() -> bool:
    return _flag_enabled("CHAT_DRAFT_CLASSIFIER", "1")


def draft_verify_enabled() -> bool:
    return _flag_enabled("CHAT_DRAFT_VERIFY", "1")


def draft_max_tokens() -> int:
    raw = _env("CHAT_DRAFT_MAX_TOKENS", "1600") or "1600"
    try:
        return max(400, int(raw))
    except ValueError:
        return 1600


def _log_route(route: DraftRoute) -> None:
    logger.warning("chat_route %s", route.log_fields())


def resolve_chat_route(query: str) -> DraftRoute:
    """Pick pastoral chat or a study/sermon draft without a user-facing mode."""
    if not draft_pipeline_enabled():
        route = chat_fallback(query, source="disabled", reason="draft pipeline off", confidence=1.0)
        _log_route(route)
        return route
    ruled = rule_route(query)
    if ruled is not None:
        _log_route(ruled)
        return ruled
    if not draft_classifier_enabled():
        route = chat_fallback(query, source="classifier_off", reason="classifier off")
        _log_route(route)
        return route
    try:
        warm_llm()
        raw = complete_llm_text(
            [
                {"role": "system", "content": CLASSIFIER_SYSTEM},
                {"role": "user", "content": (query or "").strip()},
            ],
            max_tokens=320,
            temperature=0.0,
            timeout=float(_env("CHAT_DRAFT_CLASSIFIER_TIMEOUT_S", "60") or "60"),
        )
        route = decision_from_classifier(query, raw)
    except Exception:
        logger.warning("Draft classifier failed; staying on pastoral chat", exc_info=True)
        route = chat_fallback(query, source="classifier_failed", reason="classifier error")
    _log_route(route)
    return route


def complete_llm_text(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float = 0.0,
    timeout: float | None = None,
) -> str:
    body = {
        "model": vllm_model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    with _post_llm(body, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return _message_text(payload)


def generate_draft_hyde_document(query: str) -> str:
    body = {
        "model": vllm_model(),
        "messages": [
            {"role": "system", "content": _DRAFT_HYDE_SYSTEM},
            {"role": "user", "content": (query or "").strip()},
        ],
        "temperature": 0.2,
        "max_tokens": 220,
        "stream": False,
    }
    timeout = float(_env("CHAT_HYDE_TIMEOUT_S", "180") or "180")
    with _post_llm(body, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return _clip_words(_message_text(payload), limit=140)


def generate_draft_hyde_with_retry(query: str) -> tuple[str, str]:
    warm_llm()
    try:
        text = generate_draft_hyde_document(query)
    except Exception:
        logger.warning("Draft HyDE generation failed; retrying once", exc_info=True)
        text = None
    if text:
        return text, "ok"
    try:
        text = generate_draft_hyde_document(query)
    except Exception:
        logger.warning("Draft HyDE retry failed; using the question search only", exc_info=True)
        return "", "failed"
    if text:
        return text, "retried"
    return "", "empty"


def _passage_context(query: str, passages: list[dict]) -> str:
    blocks = []
    for index, passage in enumerate(passages, start=1):
        blocks.append(
            f"[{index}] {passage['title']}\n{_truncate_for_prompt(passage['text'], query)}"
        )
    return "\n\n".join(blocks)


def draft_writer_messages(
    query: str,
    route: DraftRoute,
    passages: list[dict],
    plan: dict | None,
    history: str = "",
) -> list[dict]:
    content = draft_user_content(
        route,
        _passage_context(query, passages),
        render_plan(plan),
        query,
    )
    if history:
        content = f"Earlier in this chat:\n{history}\n\n{content}"
    return [
        {"role": "system", "content": draft_system_prompt(route)},
        {"role": "user", "content": content},
    ]


def build_draft_plan(query: str, route: DraftRoute, passages: list[dict]) -> dict:
    if not _flag_enabled("CHAT_DRAFT_PLAN", "1"):
        return {}
    try:
        raw = complete_llm_text(
            plan_messages(query, route, _passage_context(query, passages)),
            max_tokens=400,
            temperature=0.1,
            timeout=float(_env("CHAT_DRAFT_PLAN_TIMEOUT_S", "90") or "90"),
        )
    except Exception:
        logger.warning("Draft plan failed; writing from the excerpts", exc_info=True)
        return {}
    return parse_plan_text(raw)


def draft_gap_messages(
    query: str,
    route: DraftRoute,
    passages: list[dict],
    answer: str,
    missing: list[str],
) -> list[dict]:
    return gap_messages(query, route, _passage_context(query, passages), answer, missing)


def _draft_top_k(top_k: int | None) -> int:
    if top_k is not None:
        return top_k
    raw = _env("CHAT_DRAFT_TOP_K", "8") or "8"
    try:
        return max(DEFAULT_TOP_K, int(raw))
    except ValueError:
        return 8


def _merge_ranked_many(groups: list[list[dict]], top_k: int) -> list[dict]:
    merged = []
    seen = set()
    indexes = [0] * len(groups)
    while len(merged) < top_k and any(indexes[i] < len(groups[i]) for i in range(len(groups))):
        for index, group in enumerate(groups):
            if len(merged) >= top_k:
                break
            while indexes[index] < len(group):
                passage = group[indexes[index]]
                indexes[index] += 1
                text = (passage.get("text") or "").strip()
                key = _fingerprint(text)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(_passage_record(passage, text))
                break
    return merged


def _draft_search_texts(query: str, route: DraftRoute, hyde_text: str) -> list[tuple[str, str]]:
    searches = [("query", query)]
    if hyde_text:
        searches.append(("hyde", hyde_text))
    topic = (route.topic or "").strip()
    if topic and topic.lower() != query.strip().lower() and len(topic) >= 8:
        searches.append(("topic", topic))
    for ref in route.requested_texts[:4]:
        searches.append(("scripture", f"{ref} {topic}".strip()))
    return searches


def retrieve_draft_passages(
    query: str,
    route: DraftRoute,
    *,
    top_k: int | None = None,
    include_debug: bool = False,
):
    """Retrieve sermon notes for a study or sermon draft.

    HyDE uses a hypothetical teaching paragraph. Named scriptures and the
    topic are extra searches so a long drafting prompt does not hide them.
    """
    from qdrant_client import QdrantClient

    from .embeddings_utils import get_embeddings

    limit = _draft_top_k(top_k)
    embeddings = get_embeddings()
    client = QdrantClient(url=_env("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    collection = _env("QDRANT_COLLECTION", "sermon_brain")
    candidate_k = max(limit, HYDE_CANDIDATES)
    started = time.monotonic()
    hyde_text = ""
    hyde_status = "off"
    if hyde_enabled():
        hyde_text, hyde_status = generate_draft_hyde_with_retry(query)
    searches = _draft_search_texts(query, route, hyde_text)
    groups = []
    titles_by_kind: dict[str, list[str]] = {}
    term_source = " ".join([route.topic, hyde_text, " ".join(route.requested_texts)])
    terms = _query_terms(term_source) or _query_terms(route.topic or query)
    for kind, text in searches:
        try:
            hits = _search_with_vector(client, collection, embeddings.embed_query(text), candidate_k)
        except Exception:
            logger.warning("Draft search failed for %s", kind, exc_info=True)
            hits = []
            if kind == "hyde":
                hyde_status = "search_failed"
        hits = _promote_lexical(hits, terms)
        titles_by_kind[kind] = _titles(hits)
        groups.append(hits)
    vector_passages = _merge_ranked_many(groups, candidate_k)
    focus_terms = _anchor_terms(" ".join(part for part in (query, route.topic) if part))
    term_hits = _subject_windows(client, collection, query, focus_terms)
    term_fallback = bool(term_hits)
    passages = _order_passages(
        query, _dedupe_passages(term_hits + vector_passages), limit, focus_terms
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.warning(
        "draft_retrieval status=%s elapsed_ms=%s term_fallback=%s searches=%s merged=%s hyde_text=%s",
        hyde_status,
        elapsed_ms,
        term_fallback,
        [kind for kind, _text in searches],
        _titles(passages),
        (hyde_text or "")[:240],
    )
    if include_debug:
        return {
            "passages": passages,
            "hyde_text": hyde_text,
            "hyde_status": hyde_status,
            "term_fallback": term_fallback,
            "searches": [kind for kind, _text in searches],
            "titles_by_kind": titles_by_kind,
        }
    return passages


def missing_draft_refs(answer: str, route: DraftRoute) -> list[str]:
    if not draft_verify_enabled():
        return []
    return missing_scripture_refs(answer, route.requested_texts)
