"""Minimal sermon retrieval plus a streamed Gemma reply.

This is a fresh path for response_testing. It does not restore the old
prompt, grounding, rerank, or refusal stack.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Iterable, Iterator

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 6
PASSAGE_PROMPT_CHARS = 1200
HYDE_MAX_WORDS = 120
_SSE_FLUSH_PAD = " " * 4096
_HYDE_SYSTEM = (
    "Write one short sermon-note paragraph that would answer the question. "
    "Use the words a pastor would actually preach: names, doctrines, and phrases. "
    "Do not address the reader. Do not say this is hypothetical. "
    "Do not invent a sermon title. Stay under 120 words."
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
    timeout = float(_env("CHAT_HYDE_TIMEOUT_S", "60") or "60")
    with _post_llm(body, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    return _clip_words(_message_text(payload))


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
    query_hits = _search_with_vector(client, collection, embeddings.embed_query(query), top_k)
    hyde_text = ""
    hyde_hits: list[dict] = []
    if hyde_enabled():
        try:
            hyde_text = generate_hyde_document(query)
        except Exception:
            logger.warning("HyDE generation failed; using the question search only", exc_info=True)
            hyde_text = ""
        if hyde_text:
            try:
                hyde_hits = _search_with_vector(
                    client,
                    collection,
                    embeddings.embed_query(hyde_text),
                    top_k,
                )
            except Exception:
                logger.warning("HyDE search failed; using the question search only", exc_info=True)
                hyde_hits = []
    passages = _merge_ranked(hyde_hits, query_hits, top_k)
    logger.info(
        "Retrieval titles query=%s hyde=%s merged=%s",
        _titles(query_hits),
        _titles(hyde_hits),
        _titles(passages),
    )
    if hyde_text:
        logger.info("HyDE document: %s", hyde_text)
    if include_debug:
        return {
            "passages": passages,
            "hyde_text": hyde_text,
            "query_titles": _titles(query_hits),
            "hyde_titles": _titles(hyde_hits),
        }
    return passages


def _search_qdrant(client, collection: str, vector, top_k: int):
    if hasattr(client, "query_points"):
        result = client.query_points(
            collection_name=collection,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
        return list(getattr(result, "points", None) or [])
    return list(
        client.search(
            collection_name=collection,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
        )
    )


def _truncate_for_prompt(text: str) -> str:
    raw = _env("CHAT_PASSAGE_CHARS", str(PASSAGE_PROMPT_CHARS)) or str(PASSAGE_PROMPT_CHARS)
    try:
        limit = max(200, int(raw))
    except ValueError:
        limit = PASSAGE_PROMPT_CHARS
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if len(clipped) < limit // 2:
        clipped = text[:limit].rstrip()
    return f"{clipped}…"


def _prompt(query: str, passages: list[dict]) -> list[dict]:
    blocks = []
    for index, passage in enumerate(passages, start=1):
        blocks.append(f"[{index}] {passage['title']}\n{_truncate_for_prompt(passage['text'])}")
    context = "\n\n".join(blocks) if blocks else "(no sermon excerpts found)"
    return [
        {
            "role": "system",
            "content": (
                "You answer from the sermon excerpts. Quote or paraphrase them. "
                "If they do not cover the question, say that briefly. "
                "Do not invent sermon titles."
            ),
        },
        {
            "role": "user",
            "content": f"Sermon excerpts:\n{context}\n\nQuestion: {query}",
        },
    ]


def stream_llm_tokens(query: str, passages: list[dict]) -> Iterator[str]:
    """Yield text deltas from the OpenAI-compatible vLLM endpoint."""
    body = {
        "model": vllm_model(),
        "messages": _prompt(query, passages),
        "temperature": 0.2,
        "max_tokens": int(_env("CHAT_MAX_TOKENS", "800") or "800"),
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
