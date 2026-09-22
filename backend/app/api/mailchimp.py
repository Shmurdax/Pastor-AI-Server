"""Mailchimp Marketing API client for exporting Nordin's AI login emails."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

import requests
from django.conf import settings
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

NORDIN_AI_TAG = "nordin-ai"
SKIP_EMAILS = frozenset({"admin@localhost"})
SKIP_EXISTING_STATUSES = frozenset({"unsubscribed", "cleaned"})
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REQUEST_TIMEOUT_S = 15
PING_TIMEOUT_S = 8
VERIFY_SAMPLE_LIMIT = 20


class MailchimpError(Exception):
    """Raised when Mailchimp is not configured or the API key is invalid."""


@dataclass(frozen=True)
class ExportableMember:
    email: str
    first_name: str
    last_name: str
    user_id: int


@dataclass
class ExportResult:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Added {self.added}, updated {self.updated}, "
            f"skipped {self.skipped}, failed {self.failed}."
        )


@dataclass(frozen=True)
class AudienceStatus:
    configured: bool
    connected: bool
    audience_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class MemberCheck:
    email: str
    outcome: str
    status: str = ""
    tagged: bool = False
    detail: str = ""

    def label(self) -> str:
        if self.outcome == "ok":
            return "Subscribed and tagged nordin-ai"
        if self.outcome == "untagged":
            return "Subscribed, missing the nordin-ai tag"
        if self.outcome == "left_alone":
            status = self.status or "unsubscribed"
            return f"{status.capitalize()} — left alone"
        if self.outcome == "missing":
            return "Not in the audience"
        if self.outcome == "error":
            return self.detail or "Could not check"
        tag_bit = "tagged nordin-ai" if self.tagged else "missing the nordin-ai tag"
        return f"{(self.status or 'unknown').capitalize()} — {tag_bit}"


@dataclass
class AudienceCheck:
    checked: int = 0
    total: int = 0
    ok: int = 0
    untagged: int = 0
    left_alone: int = 0
    missing: int = 0
    other: int = 0
    failed: int = 0
    rows: list[MemberCheck] = field(default_factory=list)

    def summary(self) -> str:
        scope = f"Checked {self.checked}"
        if self.total and self.checked < self.total:
            scope += f" of {self.total}"
        parts = [f"{scope}."]
        if self.ok:
            parts.append(f"{self.ok} subscribed and tagged.")
        if self.untagged:
            parts.append(f"{self.untagged} missing the nordin-ai tag.")
        if self.left_alone:
            parts.append(f"{self.left_alone} unsubscribed or cleaned (left alone).")
        if self.missing:
            parts.append(f"{self.missing} not in the audience.")
        if self.other:
            parts.append(f"{self.other} with another status.")
        if self.failed:
            parts.append(f"{self.failed} could not be checked.")
        if len(parts) == 1:
            parts.append("No exportable emails to check.")
        return " ".join(parts)


def mailchimp_configured() -> bool:
    return bool(
        (getattr(settings, "MAILCHIMP_API_KEY", "") or "").strip()
        and (getattr(settings, "MAILCHIMP_AUDIENCE_ID", "") or "").strip()
    )


def datacenter_from_api_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if "-" not in key:
        raise MailchimpError(
            "MAILCHIMP_API_KEY must end with a datacenter suffix, for example ...-us21."
        )
    return key.rsplit("-", 1)[-1]


def _is_exportable_email(email: str) -> bool:
    value = (email or "").strip().lower()
    if not value or value in SKIP_EMAILS:
        return False
    return bool(EMAIL_RE.match(value))


def member_email(user: User) -> str:
    """Prefer User.email; fall back to username when it looks like an email."""
    email = (user.email or "").strip().lower()
    if _is_exportable_email(email):
        return email
    username = (user.username or "").strip().lower()
    if _is_exportable_email(username):
        return username
    return ""


def collect_exportable_members(queryset: Iterable[User] | None = None) -> list[ExportableMember]:
    if queryset is None:
        users = User.objects.filter(is_active=True).order_by("id")
    else:
        users = queryset
    seen: set[str] = set()
    members: list[ExportableMember] = []
    for user in users:
        if not getattr(user, "is_active", True):
            continue
        email = member_email(user)
        if not email or email in seen:
            continue
        seen.add(email)
        members.append(
            ExportableMember(
                email=email,
                first_name=(user.first_name or "").strip(),
                last_name=(user.last_name or "").strip(),
                user_id=int(user.pk),
            )
        )
    return members


def subscriber_hash(email: str) -> str:
    return hashlib.md5(
        email.strip().lower().encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()


def _session() -> requests.Session:
    api_key = (getattr(settings, "MAILCHIMP_API_KEY", "") or "").strip()
    if not api_key:
        raise MailchimpError("MAILCHIMP_API_KEY is not configured.")
    session = requests.Session()
    session.auth = ("anystring", api_key)
    session.headers.update({"Content-Type": "application/json"})
    return session


def _api_root() -> str:
    api_key = (getattr(settings, "MAILCHIMP_API_KEY", "") or "").strip()
    dc = datacenter_from_api_key(api_key)
    return f"https://{dc}.api.mailchimp.com/3.0"


def audience_status() -> AudienceStatus:
    if not mailchimp_configured():
        return AudienceStatus(
            configured=False,
            connected=False,
            error="Set MAILCHIMP_API_KEY and MAILCHIMP_AUDIENCE_ID in tokens.env.",
        )
    audience_id = (settings.MAILCHIMP_AUDIENCE_ID or "").strip()
    try:
        response = _session().get(
            f"{_api_root()}/lists/{audience_id}",
            timeout=PING_TIMEOUT_S,
        )
    except (MailchimpError, requests.RequestException) as exc:
        return AudienceStatus(configured=True, connected=False, error=str(exc))
    if response.status_code >= 400:
        detail = _error_detail(response)
        return AudienceStatus(configured=True, connected=False, error=detail)
    name = ""
    try:
        name = str((response.json() or {}).get("name") or "").strip()
    except ValueError:
        name = ""
    return AudienceStatus(configured=True, connected=True, audience_name=name)


def sample_members_for_check(
    members: list[ExportableMember],
    limit: int = VERIFY_SAMPLE_LIMIT,
) -> list[ExportableMember]:
    """Spread a read-back across the export list so a large audience stays quick."""
    if limit < 1 or len(members) <= limit:
        return list(members)
    if limit == 1:
        return [members[0]]
    step = (len(members) - 1) / (limit - 1)
    picked: list[ExportableMember] = []
    seen: set[int] = set()
    for i in range(limit):
        index = round(i * step)
        if index in seen:
            continue
        seen.add(index)
        picked.append(members[index])
    return picked


def check_members(
    members: list[ExportableMember],
    *,
    total: int | None = None,
) -> AudienceCheck:
    """Read members back from Mailchimp. Does not create or update contacts."""
    if not mailchimp_configured():
        raise MailchimpError(
            "Mailchimp is not configured. Set MAILCHIMP_API_KEY and MAILCHIMP_AUDIENCE_ID."
        )
    audience_id = (settings.MAILCHIMP_AUDIENCE_ID or "").strip()
    session = _session()
    root = _api_root()
    result = AudienceCheck(
        checked=len(members),
        total=len(members) if total is None else total,
    )
    for member in members:
        row = _check_one(session, root, audience_id, member)
        result.rows.append(row)
        if row.outcome == "ok":
            result.ok += 1
        elif row.outcome == "untagged":
            result.untagged += 1
        elif row.outcome == "left_alone":
            result.left_alone += 1
        elif row.outcome == "missing":
            result.missing += 1
        elif row.outcome == "error":
            result.failed += 1
        else:
            result.other += 1
    return result


def upsert_members(members: list[ExportableMember]) -> ExportResult:
    if not mailchimp_configured():
        raise MailchimpError(
            "Mailchimp is not configured. Set MAILCHIMP_API_KEY and MAILCHIMP_AUDIENCE_ID."
        )
    audience_id = (settings.MAILCHIMP_AUDIENCE_ID or "").strip()
    session = _session()
    root = _api_root()
    result = ExportResult()
    for member in members:
        _upsert_one(session, root, audience_id, member, result)
    return result


def _upsert_one(
    session: requests.Session,
    root: str,
    audience_id: str,
    member: ExportableMember,
    result: ExportResult,
) -> None:
    url = f"{root}/lists/{audience_id}/members/{subscriber_hash(member.email)}"
    try:
        existing = session.get(url, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        result.failed += 1
        result.errors.append(f"{member.email}: {exc}")
        return

    existed = existing.status_code == 200
    if existed:
        try:
            existing_status = str((existing.json() or {}).get("status") or "").lower()
        except ValueError:
            existing_status = ""
        if existing_status in SKIP_EXISTING_STATUSES:
            result.skipped += 1
            return

    payload = {
        "email_address": member.email,
        "status_if_new": "subscribed",
        "merge_fields": {
            "FNAME": member.first_name,
            "LNAME": member.last_name,
        },
    }
    try:
        put = session.put(url, json=payload, timeout=REQUEST_TIMEOUT_S)
    except requests.RequestException as exc:
        result.failed += 1
        result.errors.append(f"{member.email}: {exc}")
        return
    if put.status_code >= 400:
        result.failed += 1
        result.errors.append(f"{member.email}: {_error_detail(put)}")
        return

    _apply_nordin_ai_tag(session, url, member, result)
    if existed:
        result.updated += 1
    else:
        result.added += 1


def _check_one(
    session: requests.Session,
    root: str,
    audience_id: str,
    member: ExportableMember,
) -> MemberCheck:
    url = f"{root}/lists/{audience_id}/members/{subscriber_hash(member.email)}"
    try:
        response = session.get(url, timeout=PING_TIMEOUT_S)
    except requests.RequestException as exc:
        return MemberCheck(email=member.email, outcome="error", detail=str(exc)[:240])
    if response.status_code == 404:
        return MemberCheck(email=member.email, outcome="missing")
    if response.status_code >= 400:
        return MemberCheck(
            email=member.email,
            outcome="error",
            detail=_error_detail(response),
        )
    try:
        body = response.json() or {}
    except ValueError:
        body = {}
    status = str(body.get("status") or "").lower()
    tagged = _has_nordin_ai_tag(body.get("tags"))
    if status in SKIP_EXISTING_STATUSES:
        return MemberCheck(
            email=member.email,
            outcome="left_alone",
            status=status,
            tagged=tagged,
        )
    if status == "subscribed" and tagged:
        return MemberCheck(email=member.email, outcome="ok", status=status, tagged=True)
    if status == "subscribed":
        return MemberCheck(email=member.email, outcome="untagged", status=status, tagged=False)
    return MemberCheck(
        email=member.email,
        outcome="other",
        status=status,
        tagged=tagged,
    )


def _has_nordin_ai_tag(tags) -> bool:
    if not isinstance(tags, list):
        return False
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        if str(tag.get("name") or "").strip().lower() == NORDIN_AI_TAG:
            return True
    return False


def _apply_nordin_ai_tag(
    session: requests.Session,
    member_url: str,
    member: ExportableMember,
    result: ExportResult,
) -> None:
    try:
        tag_res = session.post(
            f"{member_url}/tags",
            json={"tags": [{"name": NORDIN_AI_TAG, "status": "active"}]},
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        result.errors.append(f"{member.email}: tagged failed ({exc})")
        return
    if tag_res.status_code >= 400:
        result.errors.append(f"{member.email}: tagged failed ({_error_detail(tag_res)})")


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json() or {}
    except ValueError:
        body = {}
    detail = body.get("detail") or body.get("title") or response.text
    text = str(detail or f"HTTP {response.status_code}").strip()
    return text[:240]
