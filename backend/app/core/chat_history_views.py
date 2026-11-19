"""Authenticated backup of Flutter sidebar chat history."""

from django.db import transaction
from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .live_chat_history import (
    MAX_HISTORY_ENTRIES,
    merge_history_entries,
    normalize_deleted_session_ids,
    pick_active_session_id,
    sanitize_history_entries,
    visible_history_entries,
)
from .models import ChatMessage, UserChatHistory

_MAX_ENTRIES = MAX_HISTORY_ENTRIES
_MAX_SCHEMA = 1


def _sanitize_entries(raw):
    return sanitize_history_entries(raw)


def _history_payload(user, row=None):
    stored = [] if row is None else (row.entries or [])
    return {
        "entries": visible_history_entries(user, stored),
        "active_session_id": "" if row is None else (row.active_session_id or ""),
        "schema_version": _MAX_SCHEMA if row is None else row.schema_version,
        "updated_at": None if row is None or not row.updated_at else row.updated_at.isoformat(),
    }


def _history_response(payload, *, status_code=status.HTTP_200_OK):
    response = Response(payload, status=status_code)
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    return response


class ChatHistoryAPIView(APIView):
    """GET/PUT durable chat history for the signed-in user."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        row = UserChatHistory.objects.filter(user=request.user).first()
        return _history_response(_history_payload(request.user, row))

    def put(self, request):
        incoming = sanitize_history_entries(request.data.get("entries"))
        deleted_ids = request.data.get("deleted_session_ids") or []
        active = request.data.get("active_session_id") or ""
        if not isinstance(active, str):
            active = ""
        active = active.strip()[:64]
        schema = request.data.get("schema_version", _MAX_SCHEMA)
        try:
            schema = int(schema)
        except (TypeError, ValueError):
            schema = _MAX_SCHEMA
        schema = max(1, min(schema, _MAX_SCHEMA))

        with transaction.atomic():
            row = (
                UserChatHistory.objects.select_for_update()
                .filter(user=request.user)
                .first()
            )
            if row is None:
                row = UserChatHistory.objects.create(
                    user=request.user,
                    entries=merge_history_entries([], incoming, deleted_ids),
                    active_session_id=active,
                    schema_version=schema,
                )
            else:
                merged = merge_history_entries(
                    row.entries or [],
                    incoming,
                    deleted_ids,
                )
                row.entries = merged
                row.active_session_id = pick_active_session_id(
                    merged,
                    incoming_active=active,
                    existing_active=row.active_session_id or "",
                )
                row.schema_version = schema
                row.save(
                    update_fields=[
                        "entries",
                        "active_session_id",
                        "schema_version",
                        "updated_at",
                    ]
                )
            removed = normalize_deleted_session_ids(deleted_ids)
            if removed:
                query = Q()
                for sid in removed:
                    query |= Q(session_id=sid)
                    if len(sid) == 64:
                        query |= Q(session_id__startswith=sid)
                ChatMessage.objects.filter(user=request.user).filter(query).delete()
        return _history_response(_history_payload(request.user, row))
