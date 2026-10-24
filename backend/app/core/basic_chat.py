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
_SSE_FLUSH_PAD = " " * 4096


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


def retrieve_passages(query: str, *, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    """Embed the question and return the nearest sermon chunks."""
    from qdrant_client import QdrantClient

    from .embeddings_utils import get_embeddings

    vector = get_embeddings().embed_query(query)
    client = QdrantClient(url=_env("QDRANT_URL", "http://127.0.0.1:6333"), timeout=30)
    collection = _env("QDRANT_COLLECTION", "sermon_brain")
    hits = _search_qdrant(client, collection, vector, top_k)
    passages = []
    for hit in hits:
        payload = getattr(hit, "payload", None) or {}
        text = _passage_text(payload)
        if not text:
            continue
        passages.append({"title": _passage_title(payload), "text": text})
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


def _prompt(query: str, passages: list[dict]) -> list[dict]:
    blocks = []
    for index, passage in enumerate(passages, start=1):
        blocks.append(f"[{index}] {passage['title']}\n{passage['text']}")
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
    timeout = float(_env("CHAT_TIMEOUT_S", "180") or "180")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"LLM request failed ({exc.code}): {detail}") from exc
    with response:
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
