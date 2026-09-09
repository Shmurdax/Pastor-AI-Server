"""Server-sent event helpers for streaming chat tokens."""

import json
import queue
import threading


def wants_chat_stream(stream_flag, accept_header: str = "") -> bool:
    if str(stream_flag).lower() in {"1", "true", "yes"}:
        return True
    return "text/event-stream" in (accept_header or "")


# Cloudflare and some browsers buffer SSE until ~4KB arrives. Tiny ": keepalive"
# comments never flush, so the UI sees the whole answer at once.
_SSE_FLUSH_PAD = " " * 4096


def sse_pack(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_keepalive() -> str:
    """Comment ping large enough to flush proxy buffers before tokens arrive."""
    return f": keepalive{_SSE_FLUSH_PAD}\n\n"


def split_stream_text(text: str, max_chars: int = 28) -> list[str]:
    """Break a model chunk so the UI can paint tokens instead of one dump."""
    raw = text or ""
    if not raw:
        return []
    if len(raw) <= max_chars:
        return [raw]
    parts: list[str] = []
    start = 0
    while start < len(raw):
        parts.append(raw[start : start + max_chars])
        start += max_chars
    return parts


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
        for piece in split_stream_text(text):
            yield piece
