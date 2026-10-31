"""POST /api/chat/ — basic retrieval plus SSE token stream."""

from __future__ import annotations

import logging
import os
import queue
import threading

from django.db import close_old_connections
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView


class EventStreamRenderer(JSONRenderer):
    """Lets clients send Accept: text/event-stream without a 406.

    Error responses that happen before the stream still render as JSON.
    """

    media_type = "text/event-stream"
    format = "event-stream"

from api.permissions import HasPremiumAccess

from .live_chat_history import upsert_live_chat_turn
from .basic_chat import (
    build_draft_plan,
    draft_gap_messages,
    draft_max_tokens,
    draft_writer_messages,
    missing_draft_refs,
    resolve_chat_route,
    retrieve_draft_passages,
    retrieve_passages,
    source_titles,
    sse_keepalive,
    sse_pack,
    stream_llm_tokens,
    stream_message_tokens,
    wants_chat_stream,
    warm_llm,
)
from .models import ChatMessage

logger = logging.getLogger(__name__)


def _sse_response(iterator):
    response = StreamingHttpResponse(iterator, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response


class ChatWarmupAPIView(APIView):
    """POST /api/chat/warmup/ — start the chat model before the user sends."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"ok": warm_llm(force=True)})


class BasicChatAPIView(APIView):
    """Premium chat: top sermon chunks, then a streamed model reply."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, HasPremiumAccess]
    renderer_classes = [JSONRenderer, EventStreamRenderer]

    def get(self, request):
        return Response(status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        query = request.data.get("query")
        if not isinstance(query, str) or not query.strip():
            return Response({"error": "query is required"}, status=status.HTTP_400_BAD_REQUEST)
        query = query.strip()
        session_id = str(request.data.get("session_id") or "default_user")[:200]
        accept = request.headers.get("Accept") or ""
        if wants_chat_stream(request.data.get("stream"), accept):
            return _sse_response(
                _stream_events(
                    query=query,
                    session_id=session_id,
                    user=request.user,
                )
            )
        return _json_reply(query=query, session_id=session_id, user=request.user)


def _json_reply(*, query: str, session_id: str, user):
    try:
        route, passages, answer = _complete_reply(query)
    except Exception:
        logger.exception("Basic chat failed")
        return Response(
            {"error": "I could not generate a reply. Please retry."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if not answer:
        return Response(
            {"error": "The model returned an empty reply. Please retry."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    saved = _save_message(
        user=user,
        session_id=session_id,
        query=query,
        answer=answer,
        sources=source_titles(passages),
    )
    return Response(
        {
            "answer": answer,
            "sources": source_titles(passages),
            "message_id": saved.id,
            "pipeline": route.pipeline,
        }
    )


def _complete_reply(query: str):
    route = resolve_chat_route(query)
    if route.is_draft:
        passages = retrieve_draft_passages(query, route)
        plan = build_draft_plan(query, route, passages)
        answer = "".join(
            stream_message_tokens(
                draft_writer_messages(query, route, passages, plan),
                max_tokens=draft_max_tokens(),
            )
        ).strip()
        missing = missing_draft_refs(answer, route)
        if missing:
            gap = "".join(
                stream_message_tokens(
                    draft_gap_messages(query, route, passages, answer, missing),
                    max_tokens=240,
                )
            ).strip()
            if gap:
                answer = f"{answer}\n\n{gap}".strip()
        return route, passages, answer
    passages = retrieve_passages(query)
    answer = "".join(stream_llm_tokens(query, passages)).strip()
    return route, passages, answer


def _keepalive_seconds() -> float:
    raw = (os.getenv("CHAT_KEEPALIVE_S") or "5").strip()
    try:
        return max(0.05, float(raw))
    except ValueError:
        return 5.0


def _call_with_keepalives(fn):
    """Run fn off the response thread and yield SSE comments until it returns."""
    done = threading.Event()
    box = {}

    def run():
        try:
            close_old_connections()
            box["value"] = fn()
        except Exception as exc:
            box["error"] = exc
        finally:
            close_old_connections()
            done.set()

    threading.Thread(target=run, daemon=True).start()
    while not done.wait(_keepalive_seconds()):
        yield sse_keepalive()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _token_stream_from(source):
    """Yield token strings. Yield None when the model has not spoken yet."""
    events = queue.Queue()

    def run():
        try:
            for text in source():
                events.put(("tok", text))
            events.put(("end", None))
        except Exception as exc:
            events.put(("err", exc))

    threading.Thread(target=run, daemon=True).start()
    while True:
        try:
            kind, payload = events.get(timeout=_keepalive_seconds())
        except queue.Empty:
            yield None
            continue
        if kind == "err":
            raise payload
        if kind == "end":
            return
        yield payload


def _stream_events(*, query: str, session_id: str, user):
    yield sse_keepalive()
    yield sse_pack({"type": "status", "phase": "started"})
    try:
        close_old_connections()
        route = yield from _call_with_keepalives(lambda: resolve_chat_route(query))
        yield sse_pack({"type": "status", "phase": "retrieving", "pipeline": route.pipeline})
        if route.is_draft:
            passages = yield from _call_with_keepalives(
                lambda: retrieve_draft_passages(query, route)
            )
            yield sse_pack({"type": "status", "phase": "planning"})
            plan = yield from _call_with_keepalives(
                lambda: build_draft_plan(query, route, passages)
            )
            messages = draft_writer_messages(query, route, passages, plan)
            token_source = lambda: stream_message_tokens(messages, max_tokens=draft_max_tokens())
        else:
            passages = yield from _call_with_keepalives(lambda: retrieve_passages(query))
            token_source = lambda: stream_llm_tokens(query, passages)
        yield sse_keepalive()
        parts = []
        for text in _token_stream_from(token_source):
            if text is None:
                yield sse_keepalive()
                continue
            parts.append(text)
            yield sse_pack({"type": "delta", "text": text})
        answer = "".join(parts).strip()
        if route.is_draft:
            missing = missing_draft_refs(answer, route)
            if missing:
                gap_parts = []
                gap_messages = draft_gap_messages(query, route, passages, answer, missing)
                if answer:
                    bridge = "\n\n"
                    gap_parts.append(bridge)
                    yield sse_pack({"type": "delta", "text": bridge})
                for text in _token_stream_from(
                    lambda: stream_message_tokens(gap_messages, max_tokens=240)
                ):
                    if text is None:
                        yield sse_keepalive()
                        continue
                    gap_parts.append(text)
                    yield sse_pack({"type": "delta", "text": text})
                answer = f"{answer}{''.join(gap_parts)}".strip()
        if not answer:
            yield sse_pack(
                {
                    "type": "error",
                    "error": "The model returned an empty reply. Please retry.",
                }
            )
            return
        close_old_connections()
        saved = _save_message(
            user=user,
            session_id=session_id,
            query=query,
            answer=answer,
            sources=source_titles(passages),
        )
        yield sse_pack(
            {
                "type": "done",
                "answer": answer,
                "sources": source_titles(passages),
                "message_id": saved.id,
                "pipeline": route.pipeline,
            }
        )
    except Exception:
        logger.exception("Basic chat stream failed")
        yield sse_pack(
            {
                "type": "error",
                "error": "I could not generate a reply. Please retry.",
            }
        )


def _save_message(*, user, session_id: str, query: str, answer: str, sources=None) -> ChatMessage:
    saved = ChatMessage.objects.create(
        session_id=session_id,
        user=user if getattr(user, "is_authenticated", False) else None,
        user_query=query,
        ai_response=answer,
    )
    try:
        upsert_live_chat_turn(
            user=user,
            client_session_id=session_id,
            user_query=query,
            answer=answer,
            sources=sources or [],
        )
    except Exception:
        logger.exception("Could not mirror this chat into the sidebar history")
    return saved
