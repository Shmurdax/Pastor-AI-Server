"""Server-sent event helpers for streaming chat tokens."""

import json
import queue
import threading


def wants_chat_stream(stream_flag, accept_header: str = "") -> bool:
    if str(stream_flag).lower() in {"1", "true", "yes"}:
        return True
    return "text/event-stream" in (accept_header or "")


def sse_pack(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_keepalive() -> str:
    """Comment ping so proxies flush headers before retrieval/generation."""
    return ": keepalive\n\n"


def iter_with_sse_heartbeats(producer, interval_s: float = 8.0):
    """Yield producer chunks, inserting SSE comments while it is blocked.

    Cloudflare and browsers drop chat if Django goes silent during a GPU cold
    start or embedding model load. Keepalives keep the stream alive until tokens arrive.
    """
    items = queue.Queue()
    done = object()

    def run():
        try:
            try:
                from django.db import close_old_connections

                close_old_connections()
            except Exception:
                pass
            try:
                for item in producer():
                    items.put(("ok", item))
            except Exception as exc:
                items.put(("err", exc))
            else:
                items.put(("ok", done))
        finally:
            try:
                from django.db import close_old_connections

                close_old_connections()
            except Exception:
                pass

    thread = threading.Thread(target=run, name="chat-sse-work", daemon=True)
    thread.start()
    timeout = max(0.05, float(interval_s))
    while True:
        try:
            kind, payload = items.get(timeout=timeout)
        except queue.Empty:
            yield sse_keepalive()
            continue
        if kind == "err":
            thread.join(timeout=5)
            raise payload
        if payload is done:
            thread.join(timeout=5)
            return
        yield payload


def chunk_text(chunk) -> str:
    content = getattr(chunk, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text") or "")
        return "".join(parts)
    return str(content)


def iter_chat_tokens(bound_llm, messages):
    for chunk in bound_llm.stream(messages):
        text = chunk_text(chunk)
        if text:
            yield text
