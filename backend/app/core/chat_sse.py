"""Server-sent event helpers for streaming chat tokens."""

import json
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

EMPTY_STREAM_ATTEMPTS = 3
EMPTY_STREAM_WAIT_S = 4.0
EMPTY_STREAM_USER_MESSAGE = (
    "The GPU chat worker did not return a reply. "
    "It may still be starting or unhealthy. Please retry in a moment."
)


class ChatGenerationError(RuntimeError):
    """Raised when chat streaming fails after retries; safe to show to the user."""


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


def is_empty_generation_error(exc) -> bool:
    message = str(exc or "").lower()
    return "no generation chunks were returned" in message


def is_retryable_stream_error(exc) -> bool:
    if is_empty_generation_error(exc):
        return True
    name = type(exc).__name__.lower()
    message = str(exc or "").lower()
    retryable_names = (
        "timeout",
        "connection",
        "httpx",
        "remoteprotocol",
        "apiconnection",
        "connecterror",
    )
    if any(part in name for part in retryable_names):
        return True
    retryable_text = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "temporarily unavailable",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "502",
        "503",
        "504",
        "worker is not ready",
        "no generation chunks were returned",
    )
    return any(part in message for part in retryable_text)


def iter_tokens_with_retries(
    stream_fn,
    *,
    attempts: int = EMPTY_STREAM_ATTEMPTS,
    wait_s: float = EMPTY_STREAM_WAIT_S,
    warmup=None,
    sleep=time.sleep,
):
    """Yield tokens from stream_fn, retrying empty serverless cold-starts.

    LangChain raises ValueError("No generation chunks were returned") when a
    RunPod worker is still booting. Retry the same request after kicking
    /models; do not replace a live draft that already started painting.
    """
    last_exc = None
    total = max(1, int(attempts))
    pause = max(0.0, float(wait_s))
    for attempt in range(1, total + 1):
        yielded = False
        try:
            for text in stream_fn():
                yielded = True
                yield text
            if yielded:
                return
            last_exc = ValueError("No generation chunks were returned")
        except Exception as exc:
            if yielded:
                raise
            last_exc = exc
            if not is_retryable_stream_error(exc):
                raise
            logger.warning(
                "Retryable chat stream error on attempt %s/%s: %s",
                attempt,
                total,
                exc,
            )
        else:
            logger.warning(
                "Empty chat stream on attempt %s/%s (no generation chunks)",
                attempt,
                total,
            )
        if attempt >= total:
            break
        if warmup is not None:
            try:
                warmup()
            except Exception:
                logger.info("vLLM warmup before empty-stream retry failed")
        if pause:
            sleep(pause)
    if last_exc is not None:
        raise last_exc
