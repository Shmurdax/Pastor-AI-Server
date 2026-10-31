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
PASSAGE_PROMPT_CHARS = 1200
HYDE_MAX_WORDS = 120
_SSE_FLUSH_PAD = " " * 4096
_HYDE_SYSTEM = (
    "Write one short sermon-note paragraph that would answer the question. "
    "Use the words a pastor would actually preach: names, doctrines, and phrases. "
    "Do not address the reader. Do not say this is hypothetical. "
    "Do not invent a sermon title. Stay under 120 words."
)
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
        merged.append({"title": passage.get("title") or "Sermon", "text": text})

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
    """Search sermons with the question and, when enabled, a HyDE paragraph."""
    from qdrant_client import QdrantClient

    from .embeddings_utils import get_embeddings

    embeddings = get_embeddings()
    client = QdrantClient(url=_env("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    collection = _env("QDRANT_COLLECTION", "sermon_brain")
    candidate_k = max(top_k, HYDE_CANDIDATES)
    query_hits = _search_with_vector(
        client, collection, embeddings.embed_query(query), candidate_k
    )
    started = time.monotonic()
    hyde_text = ""
    hyde_status = "off"
    hyde_hits: list[dict] = []
    if hyde_enabled():
        hyde_text, hyde_status = generate_hyde_with_retry(query)
        if hyde_text:
            try:
                hyde_hits = _search_with_vector(
                    client,
                    collection,
                    embeddings.embed_query(hyde_text),
                    candidate_k,
                )
            except Exception:
                logger.warning("HyDE search failed; using the question search only", exc_info=True)
                hyde_hits = []
                hyde_status = "search_failed"
    terms = _query_terms(query)
    query_hits = _promote_lexical(query_hits, terms)
    hyde_hits = _promote_lexical(hyde_hits, terms)
    passages = _merge_ranked(hyde_hits, query_hits, top_k)
    term_fallback = False
    if terms and not _passages_contain_terms(passages, terms):
        try:
            fallback_hits = _scroll_term_matches(client, collection, terms, top_k)
        except Exception:
            logger.warning("Term fallback failed", exc_info=True)
            fallback_hits = []
        if fallback_hits:
            term_fallback = True
            passages = _merge_ranked(fallback_hits, passages, top_k)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.warning(
        "hyde_request status=%s elapsed_ms=%s terms=%s term_fallback=%s "
        "query_titles=%s hyde_titles=%s merged=%s hyde_text=%s",
        hyde_status,
        elapsed_ms,
        sorted(terms),
        term_fallback,
        _titles(query_hits)[:8],
        _titles(hyde_hits)[:8],
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
            "hyde_titles": _titles(hyde_hits),
        }
    return passages


def _passages_contain_terms(passages: list[dict], terms: set[str]) -> bool:
    if not terms:
        return True
    blob = "\n".join((passage.get("text") or "") for passage in passages).lower()
    return any(term in blob for term in terms)


def _scroll_term_matches(client, collection: str, terms: set[str], top_k: int) -> list[dict]:
    """Find sermon quotes that contain a rare question term.

    Used only after the vector merge missed every rare term. Stops at top_k
    matches so a miss does not read the whole collection into the prompt.
    """
    matches = []
    offset = None
    scanned = 0
    limit = int(_env("CHAT_TERM_SCAN_MAX", "2500") or "2500")
    while len(matches) < top_k and scanned < limit:
        points, offset = client.scroll(
            collection_name=collection,
            scroll_filter=_sermon_filter(),
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
                "You are Pastor Don's AI teaching assistant for Nordin's AI.\n\n"
                "Answer from the sermon excerpts provided below. Prefer their wording, "
                "examples, and scripture references. You may paraphrase and organize them "
                "into a clear teaching response. Do not invent sermon titles, quotes, or "
                "claims that are not supported by the excerpts.\n\n"
                "Write like a pastor teaching a sincere believer:\n"
                "- Open with a direct answer to the question.\n"
                "- Develop the teaching in 2–4 short paragraphs, or short bullets when that "
                "is clearer.\n"
                "- Include relevant scripture already present in the excerpts.\n"
                "- Close with a brief practical takeaway when the excerpts support one.\n\n"
                "If the excerpts only partly cover the question, answer what they do cover, "
                "then say briefly what is missing. If they do not cover the question at all, "
                "say that plainly in one or two sentences. Do not fill gaps with outside "
                "theology.\n\n"
                "Keep the tone warm, clear, and reverent. Avoid chatbot filler, hedging "
                "lists of possibilities, and invented personal stories."
            ),
        },
        {
            "role": "user",
            "content": f"Sermon excerpts:\n{context}\n\nQuestion: {query}",
        },
    ]


def stream_llm_tokens(query: str, passages: list[dict]) -> Iterator[str]:
    """Yield text deltas from the OpenAI-compatible vLLM endpoint."""
    yield from stream_message_tokens(
        _prompt(query, passages),
        max_tokens=int(_env("CHAT_MAX_TOKENS", "800") or "800"),
    )


def stream_message_tokens(messages: list[dict], *, max_tokens: int) -> Iterator[str]:
    body = {
        "model": vllm_model(),
        "messages": messages,
        "temperature": 0.2,
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


def draft_writer_messages(query: str, route: DraftRoute, passages: list[dict], plan: dict | None) -> list[dict]:
    return [
        {"role": "system", "content": draft_system_prompt(route)},
        {
            "role": "user",
            "content": draft_user_content(
                route,
                _passage_context(query, passages),
                render_plan(plan),
                query,
            ),
        },
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
                merged.append({"title": passage.get("title") or "Sermon", "text": text})
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
    passages = _merge_ranked_many(groups, limit)
    term_fallback = False
    focus_terms = _query_terms(query) | _query_terms(route.topic)
    if focus_terms and not _passages_contain_terms(passages, focus_terms):
        try:
            fallback_hits = _scroll_term_matches(client, collection, focus_terms, limit)
        except Exception:
            logger.warning("Draft term fallback failed", exc_info=True)
            fallback_hits = []
        if fallback_hits:
            term_fallback = True
            passages = _merge_ranked_many([fallback_hits, passages], limit)
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
