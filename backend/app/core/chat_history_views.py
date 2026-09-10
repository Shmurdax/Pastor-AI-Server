"""Authenticated backup of Flutter sidebar chat history."""

from rest_framework import permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserChatHistory

# Hard ceiling so a buggy client cannot flood the DB.
_MAX_ENTRIES = 40
_MAX_SCHEMA = 1


def _sanitize_entries(raw):
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[:_MAX_ENTRIES]:
        if not isinstance(item, dict):
            continue
        session_id = item.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            continue
        cleaned.append(item)
    return cleaned


class ChatHistoryAPIView(APIView):
    """GET/PUT durable chat history for the signed-in user."""

    authentication_classes = [TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        row = UserChatHistory.objects.filter(user=request.user).first()
        if row is None:
            return Response(
                {
                    "entries": [],
                    "active_session_id": "",
                    "schema_version": _MAX_SCHEMA,
                    "updated_at": None,
                }
            )
        return Response(
            {
                "entries": row.entries or [],
                "active_session_id": row.active_session_id or "",
                "schema_version": row.schema_version,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )

    def put(self, request):
        entries = _sanitize_entries(request.data.get("entries"))
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

        row, _ = UserChatHistory.objects.update_or_create(
            user=request.user,
            defaults={
                "entries": entries,
                "active_session_id": active,
                "schema_version": schema,
            },
        )
        return Response(
            {
                "entries": row.entries or [],
                "active_session_id": row.active_session_id or "",
                "schema_version": row.schema_version,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            },
            status=status.HTTP_200_OK,
        )
