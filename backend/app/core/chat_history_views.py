"""Authenticated backup of Flutter sidebar chat history."""

from django.db import transaction
from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .live_chat_history import (
    MAX_HISTORY_ENTRIES,
    delete_chat_messages_for_sessions,
    merge_history_entries,
    normalize_deleted_session_ids,
    pick_active_session_id,
    remember_deleted_session_ids,
    sanitize_history_entries,
    session_is_deleted,
    visible_history_entries,
)
from .models import UserChatHistory

_MAX_ENTRIES = MAX_HISTORY_ENTRIES
_MAX_SCHEMA = 1


def _sanitize_entries(raw):
    return sanitize_history_entries(raw)


def _history_payload(user, row=None):
    stored = [] if row is None else (row.entries or [])
    deleted = [] if row is None else list(row.deleted_session_ids or [])
    active = "" if row is None else (row.active_session_id or "")
    if session_is_deleted(active, normalize_deleted_session_ids(deleted)):
        active = ""
    return {
        "entries": visible_history_entries(user, stored, deleted),
        "active_session_id": active,
        "schema_version": _MAX_SCHEMA if row is None else row.schema_version,
        "updated_at": None if row is None or not row.updated_at else row.updated_at.isoformat(),
        "deleted_session_ids": deleted,
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
        incoming_deleted = request.data.get("deleted_session_ids") or []
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
                deleted = remember_deleted_session_ids([], incoming_deleted)
                if session_is_deleted(active, set(deleted)):
                    active = ""
                row = UserChatHistory.objects.create(
                    user=request.user,
                    entries=merge_history_entries([], incoming, deleted),
                    active_session_id=active,
                    schema_version=schema,
                    deleted_session_ids=deleted,
                )
            else:
                deleted = remember_deleted_session_ids(
                    row.deleted_session_ids,
                    incoming_deleted,
                )
                if session_is_deleted(active, set(deleted)):
                    active = ""
                merged = merge_history_entries(
                    row.entries or [],
                    incoming,
                    deleted,
                )
                row.entries = merged
                row.deleted_session_ids = deleted
                row.active_session_id = pick_active_session_id(
                    merged,
                    incoming_active=active,
                    existing_active=row.active_session_id or "",
                )
                if session_is_deleted(row.active_session_id, set(deleted)):
                    row.active_session_id = ""
                row.schema_version = schema
                row.save(
                    update_fields=[
                        "entries",
                        "deleted_session_ids",
                        "active_session_id",
                        "schema_version",
                        "updated_at",
                    ]
                )
            purge = list(normalize_deleted_session_ids(incoming_deleted))
            deleted_lookup = set(deleted)
            for item in incoming:
                sid = str(item.get("sessionId") or "").strip()
                if sid and session_is_deleted(sid, deleted_lookup):
                    purge.append(sid)
            delete_chat_messages_for_sessions(request.user, purge)
        return _history_response(_history_payload(request.user, row))
