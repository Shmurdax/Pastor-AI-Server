"""Mirror in-flight chat turns into UserChatHistory so other open clients can poll."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from django.db import close_old_connections, transaction

from .models import UserChatHistory

logger = logging.getLogger(__name__)

MAX_HISTORY_ENTRIES = 40
_LIBRARY_SOURCE_LIMIT = 5
_PREVIOUS_SERMON_LIMIT = 25

_VIDEO_TIMESTAMP_SUFFIX = re.compile(r"\s*\[[0-9:]{4,8}[–-][0-9:]{4,8}\]\s*$")
_DOCUMENT_EXTENSIONS = (".md", ".docx", ".pdf", ".txt")
_VIDEO_EXTENSIONS = (
    ".mp4",
    ".m4v",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
    ".3gp",
    ".ogv",
)


def sanitize_history_entries(raw) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[:MAX_HISTORY_ENTRIES]:
        if not isinstance(item, dict):
            continue
        session_id = item.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            continue
        cleaned.append(item)
    return cleaned


def _messages_of(entry: dict[str, Any]) -> list[dict[str, Any]]:
    msgs = entry.get("messages") or []
    return [item for item in msgs if isinstance(item, dict)]


def _last_ai(entry: dict[str, Any]) -> dict[str, Any]:
    for item in reversed(_messages_of(entry)):
        if item.get("role") == "ai":
            return item
    return {}


def entry_is_streaming(entry: Optional[dict[str, Any]]) -> bool:
    if not isinstance(entry, dict):
        return False
    return bool(_last_ai(entry).get("streaming"))


def _last_ai_len(entry: dict[str, Any]) -> int:
    return len(str(_last_ai(entry).get("text") or ""))


def _msg_count(entry: dict[str, Any]) -> int:
    return len(_messages_of(entry))


def _is_video_sermon_source(title: str) -> bool:
    value = (title or "").strip()
    if not value:
        return False
    if _VIDEO_TIMESTAMP_SUFFIX.search(value):
        return True
    lower = value.lower()
    if any(lower.endswith(ext) for ext in _VIDEO_EXTENSIONS):
        return True
    return "[" in value


def _normalize_sermon_label(raw: str) -> str:
    value = (raw or "").strip()
    lower = value.lower()
    for ext in (*_DOCUMENT_EXTENSIONS, *_VIDEO_EXTENSIONS):
        if lower.endswith(ext):
            return value[: -len(ext)].strip()
    return value


def library_sermon_sources(raw, limit: int = _LIBRARY_SOURCE_LIMIT) -> list[str]:
    """Document titles for the sermon library. Videos stay out of the sidebar."""
    seen: set[str] = set()
    out: list[str] = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        original = str(item or "").strip()
        if not original or _is_video_sermon_source(original):
            continue
        display = _normalize_sermon_label(original)
        if not display or _is_video_sermon_source(display):
            continue
        key = display.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(display)
        if len(out) >= limit:
            break
    return out


def _without_video_sermon_sources(titles) -> list[str]:
    cleaned: list[str] = []
    for title in titles or []:
        text = str(title or "").strip()
        if text and not _is_video_sermon_source(text):
            cleaned.append(text)
    return cleaned


def advance_library_sermons(library, previous, sources) -> tuple[list[str], list[str]]:
    """Same sidebar shift the Flutter client applies when an answer completes."""
    next_library = _without_video_sermon_sources(library)
    next_previous = _without_video_sermon_sources(previous)
    if next_library:
        merged: list[str] = []
        seen: set[str] = set()
        for title in [*next_library, *next_previous]:
            if title in seen:
                continue
            seen.add(title)
            merged.append(title)
            if len(merged) >= _PREVIOUS_SERMON_LIMIT:
                break
        next_previous = merged
    new_sources = library_sermon_sources(sources)
    if new_sources:
        next_library = new_sources
        next_previous = [title for title in next_previous if title not in next_library]
    return next_library, next_previous


def _sermon_name_list(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str) and item.strip()]


def _with_preserved_library_sermons(
    winner: dict[str, Any], loser: dict[str, Any]
) -> dict[str, Any]:
    """Keep sermon-library names when the richer text snapshot never recorded them."""
    winner_library = _sermon_name_list(winner.get("librarySermons"))
    winner_previous = _sermon_name_list(winner.get("previousSermons"))
    loser_library = _sermon_name_list(loser.get("librarySermons"))
    loser_previous = _sermon_name_list(loser.get("previousSermons"))
    if winner_library or winner_previous or not (loser_library or loser_previous):
        return winner
    merged = dict(winner)
    merged["librarySermons"] = loser_library
    merged["previousSermons"] = loser_previous
    return merged


def richer_history_entry(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Prefer the snapshot that still has the live draft or more complete text."""
    chosen = _choose_richer_history_entry(existing, incoming)
    other = incoming if chosen is existing else existing
    return _with_preserved_library_sermons(chosen, other)


def _choose_richer_history_entry(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    existing_stream = entry_is_streaming(existing)
    incoming_stream = entry_is_streaming(incoming)
    existing_len = _last_ai_len(existing)
    incoming_len = _last_ai_len(incoming)
    existing_n = _msg_count(existing)
    incoming_n = _msg_count(incoming)
    existing_at = int(existing.get("updatedAt") or 0)
    incoming_at = int(incoming.get("updatedAt") or 0)

    if existing_stream and not incoming_stream and incoming_n <= existing_n and incoming_len <= existing_len:
        return existing
    if incoming_stream and not existing_stream and existing_n <= incoming_n and existing_len <= incoming_len:
        return incoming
    if existing_n != incoming_n:
        return incoming if incoming_n > existing_n else existing
    if existing_len != incoming_len:
        return incoming if incoming_len > existing_len else existing
    if existing_stream != incoming_stream:
        return existing if existing_stream else incoming
    return incoming if incoming_at >= existing_at else existing


def normalize_deleted_session_ids(raw) -> set[str]:
    if not isinstance(raw, list):
        return set()
    deleted: set[str] = set()
    for item in raw:
        sid = str(item or "").strip()[:64]
        if sid:
            deleted.add(sid)
    return deleted


def merge_history_entries(existing, incoming, deleted_ids=None) -> list[dict[str, Any]]:
    deleted = normalize_deleted_session_ids(deleted_ids)
    by_id: dict[str, dict[str, Any]] = {}

    def consider(entry) -> None:
        if not isinstance(entry, dict):
            return
        sid = str(entry.get("sessionId") or "").strip()
        if not sid or sid in deleted:
            return
        current = by_id.get(sid)
        if current is None:
            by_id[sid] = dict(entry)
            return
        by_id[sid] = richer_history_entry(current, dict(entry))

    for item in sanitize_history_entries(existing):
        consider(item)
    for item in sanitize_history_entries(incoming):
        consider(item)

    merged = list(by_id.values())
    merged.sort(key=lambda item: int(item.get("updatedAt") or 0), reverse=True)
    return merged[:MAX_HISTORY_ENTRIES]


def pick_active_session_id(
    merged: list[dict[str, Any]],
    *,
    incoming_active: str = "",
    existing_active: str = "",
) -> str:
    by_id = {
        str(item.get("sessionId") or ""): item
        for item in merged
        if str(item.get("sessionId") or "").strip()
    }
    for candidate in (incoming_active, existing_active):
        sid = str(candidate or "").strip()
        entry = by_id.get(sid)
        if entry is not None and entry_is_streaming(entry):
            return sid
    for candidate in (incoming_active, existing_active):
        sid = str(candidate or "").strip()
        if sid in by_id:
            return sid
    return incoming_active or existing_active or ""


def _title_for(user_query: str) -> str:
    text = " ".join((user_query or "").split())
    if not text:
        return "New conversation"
    return text[:48] + ("…" if len(text) > 48 else "")


def upsert_live_chat_turn(
    *,
    user,
    client_session_id: str,
    user_query: str,
    answer: str,
    sources: Optional[list] = None,
    streaming: bool = False,
) -> None:
    """Write the current user prompt + AI draft into durable sidebar history."""
    if user is None or not getattr(user, "is_authenticated", False):
        return
    sid = str(client_session_id or "").strip()[:64]
    query = str(user_query or "").strip()
    if not sid or not query:
        return
    close_old_connections()
    now_ms = int(time.time() * 1000)
    ai_message: dict[str, Any] = {
        "role": "ai",
        "text": answer or "",
        "sources": list(sources or []),
        "reported": False,
    }
    if streaming:
        ai_message["streaming"] = True
    user_message = {"role": "user", "text": query}
    with transaction.atomic():
        row, _ = UserChatHistory.objects.select_for_update().get_or_create(
            user=user,
            defaults={
                "entries": [],
                "active_session_id": sid,
                "schema_version": 1,
            },
        )
        entries = sanitize_history_entries(list(row.entries or []))
        match_idx = next(
            (i for i, item in enumerate(entries) if str(item.get("sessionId") or "") == sid),
            None,
        )
        if match_idx is None:
            messages = [user_message, ai_message]
            entry = {
                "sessionId": sid,
                "title": _title_for(query),
                "updatedAt": now_ms,
                "messages": messages,
                "librarySermons": [],
                "previousSermons": [],
            }
            entries = [entry, *entries]
        else:
            entry = dict(entries[match_idx])
            messages = [
                dict(item)
                for item in (entry.get("messages") or [])
                if isinstance(item, dict)
            ]
            if (
                messages
                and messages[-1].get("role") == "ai"
                and len(messages) >= 2
                and messages[-2].get("role") == "user"
                and str(messages[-2].get("text") or "").strip() == query
            ):
                messages[-1] = ai_message
            elif messages and messages[-1].get("role") == "user" and str(
                messages[-1].get("text") or ""
            ).strip() == query:
                messages.append(ai_message)
            else:
                messages.extend([user_message, ai_message])
            entry["messages"] = messages
            entry["title"] = entry.get("title") or _title_for(query)
            entry["updatedAt"] = now_ms
            entries.pop(match_idx)
            entries.insert(0, entry)
        if not streaming:
            library, previous = advance_library_sermons(
                entry.get("librarySermons") or [],
                entry.get("previousSermons") or [],
                sources or [],
            )
            entry["librarySermons"] = library
            entry["previousSermons"] = previous
        row.entries = entries[:MAX_HISTORY_ENTRIES]
        row.active_session_id = sid
        row.save(update_fields=["entries", "active_session_id", "updated_at"])


class LiveHistoryPublisher:
    """Throttle live history writes during token streaming."""

    def __init__(
        self,
        *,
        user,
        client_session_id: str,
        user_query: str,
        min_interval_s: float = 0.35,
    ):
        self.user = user
        self.client_session_id = client_session_id
        self.user_query = user_query
        self.min_interval_s = max(0.2, float(min_interval_s))
        self._last = 0.0
        self._last_len = -1

    def publish(
        self,
        answer: str,
        *,
        streaming: bool,
        sources: Optional[list] = None,
        force: bool = False,
    ) -> None:
        text = answer or ""
        grew_from_empty = self._last_len <= 0 and len(text) > 0
        now = time.monotonic()
        if (
            not force
            and not grew_from_empty
            and streaming
            and (now - self._last) < self.min_interval_s
        ):
            return
        self._last = now
        self._last_len = len(text)
        try:
            upsert_live_chat_turn(
                user=self.user,
                client_session_id=self.client_session_id,
                user_query=self.user_query,
                answer=text,
                sources=sources,
                streaming=streaming,
            )
        except Exception:
            logger.exception("Live chat history publish failed")
