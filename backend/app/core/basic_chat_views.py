"""POST /api/chat/ — basic retrieval plus SSE token stream."""

from __future__ import annotations

import logging

from django.db import close_old_connections
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
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

from .basic_chat import (
    retrieve_passages,
    source_titles,
    sse_keepalive,
    sse_pack,
    stream_llm_tokens,
    wants_chat_stream,
)
from .models import ChatMessage

logger = logging.getLogger(__name__)


def _sse_response(iterator):
    response = StreamingHttpResponse(iterator, content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    return response


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
        passages = retrieve_passages(query)
        answer = "".join(stream_llm_tokens(query, passages)).strip()
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
    saved = _save_message(user=user, session_id=session_id, query=query, answer=answer)
    return Response(
        {
            "answer": answer,
            "sources": source_titles(passages),
            "message_id": saved.id,
        }
    )


def _stream_events(*, query: str, session_id: str, user):
    yield sse_keepalive()
    yield sse_pack({"type": "status", "phase": "started"})
    yield sse_pack({"type": "status", "phase": "retrieving"})
    try:
        close_old_connections()
        passages = retrieve_passages(query)
        yield sse_keepalive()
        parts = []
        for text in stream_llm_tokens(query, passages):
            parts.append(text)
            yield sse_pack({"type": "delta", "text": text})
        answer = "".join(parts).strip()
        if not answer:
            yield sse_pack(
                {
                    "type": "error",
                    "error": "The model returned an empty reply. Please retry.",
                }
            )
            return
        close_old_connections()
        saved = _save_message(user=user, session_id=session_id, query=query, answer=answer)
        yield sse_pack(
            {
                "type": "done",
                "answer": answer,
                "sources": source_titles(passages),
                "message_id": saved.id,
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


def _save_message(*, user, session_id: str, query: str, answer: str) -> ChatMessage:
    return ChatMessage.objects.create(
        session_id=session_id,
        user=user if getattr(user, "is_authenticated", False) else None,
        user_query=query,
        ai_response=answer,
    )
