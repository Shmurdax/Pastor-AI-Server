"""Public website banner: downtime sentence or a custom message."""

from __future__ import annotations

import logging
from datetime import datetime, timezone as datetime_timezone
from types import SimpleNamespace

from django.contrib import admin, messages
from django.db.utils import OperationalError, ProgrammingError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import escape
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core.persist_db import dump_persistent_postgres

from .models import SiteBanner

logger = logging.getLogger(__name__)

_PREVIEW_PLACEHOLDER = "Fill in the message to preview the banner."


class BannerFormError(Exception):
    def __init__(self, message: str, draft: dict | None = None):
        super().__init__(message)
        self.draft = draft or {}


def _as_bool(value) -> bool:
    return str(value or "").strip().lower() in {"on", "true", "1", "yes"}


def _clean_line(value, max_len: int) -> str:
    text = str(value or "").replace("\u202f", " ").replace("\u00a0", " ")
    text = " ".join(text.split())
    return text[:max_len]


def _has_timezone(value: str) -> bool:
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        return True
    time_sep = raw.find("T")
    if time_sep == -1:
        return False
    clock = raw[time_sep + 1 :]
    return "+" in clock or "-" in clock


def _parse_dt(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise BannerFormError("Enter a valid start and end time.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime_timezone.utc)
    return parsed


def _choose_dt(iso_value, local_value) -> datetime | None:
    iso_value = str(iso_value or "").strip()
    local_value = str(local_value or "").strip()
    if iso_value and _has_timezone(iso_value):
        return _parse_dt(iso_value)
    if local_value:
        return _parse_dt(local_value)
    if iso_value:
        return _parse_dt(iso_value)
    return None


_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_banner_time(dt: datetime) -> str:
    """Clock time in UTC, e.g. ``Oct 3, 2026, 2:00 PM``."""
    local = timezone.localtime(dt, datetime_timezone.utc)
    hour = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    month = _MONTHS[local.month - 1]
    return f"{month} {local.day}, {local.year}, {hour}:{local.minute:02d} {suffix}"


def datetime_local_value(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = timezone.localtime(dt, datetime_timezone.utc)
    return local.strftime("%Y-%m-%dT%H:%M")


def compose_banner_message(banner) -> str:
    if getattr(banner, "mode", "") == SiteBanner.MODE_CUSTOM:
        return (getattr(banner, "custom_message", "") or "").strip()
    reason = (getattr(banner, "reason", "") or "").strip()
    start = (getattr(banner, "starts_label", "") or "").strip()
    end = (getattr(banner, "ends_label", "") or "").strip()
    starts_at = getattr(banner, "starts_at", None)
    ends_at = getattr(banner, "ends_at", None)
    if not start and starts_at is not None:
        start = format_banner_time(starts_at)
    if not end and ends_at is not None:
        end = format_banner_time(ends_at)
    if not reason or not start or not end:
        return ""
    return f"Due to {reason} the service will be down from {start} to {end}."


def banner_payload(banner) -> dict:
    if not banner.enabled:
        return {"enabled": False, "message": ""}
    message = compose_banner_message(banner)
    if not message:
        return {"enabled": False, "message": ""}
    return {"enabled": True, "message": message}


def public_banner_payload() -> dict:
    try:
        banner = SiteBanner.load()
    except (OperationalError, ProgrammingError):
        logger.warning("Site banner is unavailable", exc_info=True)
        return {"enabled": False, "message": ""}
    return banner_payload(banner)


def site_banner_html() -> str:
    """Hazard-yellow bar for standalone HTML pages such as subscription terms."""
    payload = public_banner_payload()
    if not payload["enabled"]:
        return ""
    message = escape(payload["message"])
    return (
        '<div role="status" style="background:#FFD100;color:#475569;'
        "margin:0;padding:12px 16px;text-align:center;font-weight:600;"
        'line-height:1.4;font-family:system-ui,sans-serif;">'
        f"{message}</div>"
    )


def _status_label(enabled: bool, message: str) -> str:
    if enabled and message:
        return "Currently showing on the website"
    return "Currently hidden on the website"


def form_values_from_banner(banner) -> dict:
    message = compose_banner_message(banner)
    return {
        "enabled": banner.enabled,
        "mode": banner.mode or SiteBanner.MODE_DOWNTIME,
        "reason": banner.reason,
        "custom_message": banner.custom_message,
        "starts_local": datetime_local_value(banner.starts_at),
        "ends_local": datetime_local_value(banner.ends_at),
        "starts_iso": banner.starts_at.isoformat() if banner.starts_at else "",
        "ends_iso": banner.ends_at.isoformat() if banner.ends_at else "",
        "preview": message or _PREVIEW_PLACEHOLDER,
        "status_label": _status_label(banner.enabled, message),
    }


def _preview_banner(draft: dict):
    return SimpleNamespace(
        enabled=bool(draft.get("enabled")),
        mode=draft.get("mode") or SiteBanner.MODE_DOWNTIME,
        reason=draft.get("reason") or "",
        custom_message=draft.get("custom_message") or "",
        starts_at=draft.get("starts_at"),
        ends_at=draft.get("ends_at"),
        starts_label=draft.get("starts_label") or "",
        ends_label=draft.get("ends_label") or "",
    )


def read_banner_form(data) -> dict:
    mode = str(data.get("mode") or "").strip()
    draft = {
        "enabled": _as_bool(data.get("enabled")),
        "mode": mode if mode in {SiteBanner.MODE_DOWNTIME, SiteBanner.MODE_CUSTOM} else SiteBanner.MODE_DOWNTIME,
        "reason": _clean_line(data.get("reason"), 300),
        "custom_message": _clean_line(data.get("custom_message"), 500),
        "starts_local": str(data.get("starts_local") or "").strip(),
        "ends_local": str(data.get("ends_local") or "").strip(),
        "starts_iso": str(data.get("starts_at") or "").strip(),
        "ends_iso": str(data.get("ends_at") or "").strip(),
        "starts_at": None,
        "ends_at": None,
        "starts_label": "",
        "ends_label": "",
    }
    if mode not in {SiteBanner.MODE_DOWNTIME, SiteBanner.MODE_CUSTOM}:
        raise BannerFormError("Choose a downtime notice or a custom message.", draft)

    try:
        starts_at = _choose_dt(draft["starts_iso"], draft["starts_local"])
        ends_at = _choose_dt(draft["ends_iso"], draft["ends_local"])
    except BannerFormError as exc:
        raise BannerFormError(str(exc), draft) from exc

    starts_label = _clean_line(data.get("starts_label"), 80)
    ends_label = _clean_line(data.get("ends_label"), 80)
    if starts_at is not None and not starts_label:
        starts_label = format_banner_time(starts_at)
    if ends_at is not None and not ends_label:
        ends_label = format_banner_time(ends_at)
    if starts_at is not None:
        draft["starts_iso"] = starts_at.isoformat()
    if ends_at is not None:
        draft["ends_iso"] = ends_at.isoformat()
    draft["starts_at"] = starts_at
    draft["ends_at"] = ends_at
    draft["starts_label"] = starts_label
    draft["ends_label"] = ends_label

    if draft["enabled"] and mode == SiteBanner.MODE_DOWNTIME:
        if not draft["reason"]:
            raise BannerFormError("Fill in why the service will be down.", draft)
        if starts_at is None or ends_at is None:
            raise BannerFormError("Fill in both the start time and the end time.", draft)
        if ends_at <= starts_at:
            raise BannerFormError("The end time must be after the start time.", draft)
    if draft["enabled"] and mode == SiteBanner.MODE_CUSTOM and not draft["custom_message"]:
        raise BannerFormError("Fill in the banner message.", draft)

    message = compose_banner_message(_preview_banner(draft))
    draft["preview"] = message or _PREVIEW_PLACEHOLDER
    draft["status_label"] = _status_label(draft["enabled"], message)
    return draft


def apply_banner_form(banner: SiteBanner, data) -> dict:
    parsed = read_banner_form(data)
    banner.enabled = parsed["enabled"]
    banner.mode = parsed["mode"]
    banner.reason = parsed["reason"]
    banner.custom_message = parsed["custom_message"]
    banner.starts_at = parsed["starts_at"]
    banner.ends_at = parsed["ends_at"]
    banner.starts_label = parsed["starts_label"]
    banner.ends_label = parsed["ends_label"]
    return parsed


def site_banner_admin_view(request):
    if not request.user.is_staff:
        messages.error(request, "You must be an admin user to access this page.")
        return HttpResponseRedirect("../")

    banner = SiteBanner.load()
    form = form_values_from_banner(banner)
    if request.method == "POST":
        try:
            apply_banner_form(banner, request.POST)
        except BannerFormError as exc:
            messages.error(request, str(exc))
            form = {**form, **(exc.draft or {})}
            message = compose_banner_message(_preview_banner(form))
            form["preview"] = message or _PREVIEW_PLACEHOLDER
            form["status_label"] = "Not saved"
        else:
            banner.save()
            dump_persistent_postgres()
            if banner.enabled:
                messages.success(request, "Website banner is on.")
            else:
                messages.success(request, "Website banner is off.")
            return HttpResponseRedirect(request.path)

    context = {
        **admin.site.each_context(request),
        "title": "Website banner",
        "form": form,
    }
    return TemplateResponse(request, "admin/core/site_banner.html", context)


class SiteBannerAPIView(APIView):
    """Public banner copy for the website. Hidden when the admin toggle is off."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        response = Response(public_banner_payload())
        response["Cache-Control"] = "no-store"
        return response
