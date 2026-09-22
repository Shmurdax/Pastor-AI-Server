"""Shared monthly chat token pool for Premium members only.

Premium chat generations share one calendar-month pool (default 34,000,000
tokens), sized to keep RunPod spend near the ~$530 GPU slice of a $750 ops
envelope. Superusers are never gated or metered. Staff who are not Premium
are not gated by this pool. Admins may still impose per-user chat cooldowns
via ``Profile.token_cooldown_until`` for moderation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone


def platform_monthly_token_budget() -> int:
    raw = (os.getenv("PLATFORM_MONTHLY_TOKEN_BUDGET") or "34000000").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 34000000


def token_limits_enabled() -> bool:
    return (os.getenv("TOKEN_LIMIT_ENFORCE") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def calendar_period_key(when: Optional[datetime] = None) -> str:
    local = timezone.localtime(when or timezone.now())
    return f"{local.year:04d}-{local.month:02d}"


def next_calendar_month_start(when: Optional[datetime] = None) -> datetime:
    """Local midnight of the first day of next calendar month."""
    local = timezone.localtime(when or timezone.now())
    if local.month == 12:
        nxt = date(local.year + 1, 1, 1)
    else:
        nxt = date(local.year, local.month + 1, 1)
    return timezone.make_aware(datetime.combine(nxt, time.min), timezone.get_current_timezone())


def should_enforce_token_limits(user) -> bool:
    """Gate only Premium members; superusers are never limited."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return False
    if not token_limits_enabled():
        return False
    profile = getattr(user, "profile", None)
    if profile is None:
        return False
    return bool(profile.is_premium)


def should_meter_usage(user) -> bool:
    """Count only Premium (non-superuser) chat toward the shared monthly pool."""
    return should_enforce_token_limits(user)


@dataclass(frozen=True)
class TokenGateResult:
    allowed: bool
    error: str = ""
    code: str = ""
    retry_after_seconds: int = 0
    retry_at: Optional[str] = None
    platform_tokens_used: Optional[int] = None
    platform_tokens_remaining: Optional[int] = None

    def as_response_dict(self) -> dict:
        payload = {
            "error": self.error,
            "code": self.code,
            "detail": self.error,
        }
        if self.retry_after_seconds > 0:
            payload["retry_after_seconds"] = self.retry_after_seconds
        if self.retry_at:
            payload["retry_at"] = self.retry_at
        if self.platform_tokens_used is not None:
            payload["platform_tokens_used"] = self.platform_tokens_used
        if self.platform_tokens_remaining is not None:
            payload["platform_tokens_remaining"] = self.platform_tokens_remaining
        return payload


def _format_wait_message(until: datetime) -> str:
    local = timezone.localtime(until)
    now = timezone.localtime(timezone.now())
    seconds = max(0, int((until - timezone.now()).total_seconds()))
    if seconds <= 0:
        return (
            "You have used up your allotted responses currently. "
            "Please try again in a moment."
        )
    hours = max(1, (seconds + 3599) // 3600)
    if hours < 48:
        wait = f"about {hours} hour{'s' if hours != 1 else ''}"
    else:
        days = max(1, (seconds + 86399) // 86400)
        wait = f"about {days} day{'s' if days != 1 else ''}"
    stamp = local.strftime("%b %d at %I:%M %p").lstrip("0").replace(" 0", " ")
    if local.date() == now.date():
        stamp = local.strftime("%I:%M %p").lstrip("0")
    elif local.hour == 0 and local.minute == 0:
        stamp = local.strftime("%b %d").lstrip("0").replace(" 0", " ")
    return (
        f"You have used up your allotted responses currently. "
        f"Please wait {wait} (until {stamp})."
    )


def _active_cooldown_until(profile) -> Optional[datetime]:
    until = getattr(profile, "token_cooldown_until", None)
    if until is None:
        return None
    if timezone.is_naive(until):
        until = timezone.make_aware(until, timezone.get_current_timezone())
    if until <= timezone.now():
        return None
    return until


def get_or_create_platform_meter(period_key: Optional[str] = None):
    from api.models import PlatformTokenMeter

    key = period_key or calendar_period_key()
    meter, _created = PlatformTokenMeter.objects.get_or_create(
        period_key=key,
        defaults={"tokens_used": 0},
    )
    return meter


@transaction.atomic
def platform_usage_snapshot() -> tuple[int, int, int]:
    """Return (used, budget, remaining) for the current calendar month."""
    from api.models import PlatformTokenMeter

    key = calendar_period_key()
    meter = (
        PlatformTokenMeter.objects.select_for_update()
        .filter(period_key=key)
        .first()
    )
    used = int(meter.tokens_used) if meter else 0
    budget = platform_monthly_token_budget()
    remaining = max(0, budget - used)
    return used, budget, remaining


@transaction.atomic
def check_chat_allowed(user) -> TokenGateResult:
    """Allow chat unless the user is admin-restricted or the platform pool is empty."""
    if not should_enforce_token_limits(user):
        return TokenGateResult(allowed=True)

    profile = getattr(user, "profile", None)
    if profile is not None:
        profile = type(profile).objects.select_for_update().get(pk=profile.pk)
        cooldown = _active_cooldown_until(profile)
        if cooldown is not None:
            seconds = max(1, int((cooldown - timezone.now()).total_seconds()))
            return TokenGateResult(
                allowed=False,
                error=_format_wait_message(cooldown),
                code="token_cooldown",
                retry_after_seconds=seconds,
                retry_at=cooldown.isoformat(),
            )
        # Clear expired admin restrictions.
        if profile.token_cooldown_until is not None:
            profile.token_cooldown_until = None
            profile.save(update_fields=["token_cooldown_until"])

    used, budget, remaining = platform_usage_snapshot()
    if remaining <= 0:
        until = next_calendar_month_start()
        seconds = max(1, int((until - timezone.now()).total_seconds()))
        return TokenGateResult(
            allowed=False,
            error=_format_wait_message(until),
            code="platform_token_budget_exhausted",
            retry_after_seconds=seconds,
            retry_at=until.isoformat(),
            platform_tokens_used=used,
            platform_tokens_remaining=0,
        )

    return TokenGateResult(
        allowed=True,
        platform_tokens_used=used,
        platform_tokens_remaining=remaining,
    )


@transaction.atomic
def record_token_usage(user, tokens: int) -> Optional[TokenGateResult]:
    """Add tokens to the platform monthly meter (and optional per-user spent)."""
    if not should_meter_usage(user):
        return None
    amount = max(0, int(tokens or 0))
    if amount <= 0:
        return None

    from api.models import PlatformTokenMeter

    key = calendar_period_key()
    meter, _ = PlatformTokenMeter.objects.select_for_update().get_or_create(
        period_key=key,
        defaults={"tokens_used": 0},
    )
    meter.tokens_used = int(meter.tokens_used or 0) + amount
    meter.save(update_fields=["tokens_used", "updated_at"])

    profile = getattr(user, "profile", None)
    if profile is not None:
        locked = type(profile).objects.select_for_update().get(pk=profile.pk)
        locked.tokens_spent = int(locked.tokens_spent or 0) + amount
        locked.tokens_used_today = int(locked.tokens_used_today or 0) + amount
        locked.token_usage_day = timezone.localdate()
        locked.save(
            update_fields=["tokens_spent", "tokens_used_today", "token_usage_day"]
        )

    budget = platform_monthly_token_budget()
    remaining = max(0, budget - int(meter.tokens_used))
    if remaining <= 0:
        until = next_calendar_month_start()
        seconds = max(1, int((until - timezone.now()).total_seconds()))
        return TokenGateResult(
            allowed=False,
            error=_format_wait_message(until),
            code="platform_token_budget_exhausted",
            retry_after_seconds=seconds,
            retry_at=until.isoformat(),
            platform_tokens_used=int(meter.tokens_used),
            platform_tokens_remaining=0,
        )
    return None


@transaction.atomic
def admin_adjust_platform_tokens(delta: int, *, period_key: Optional[str] = None) -> int:
    """Add (positive) or remove (negative) from this month's platform usage counter."""
    from api.models import PlatformTokenMeter

    key = period_key or calendar_period_key()
    meter, _ = PlatformTokenMeter.objects.select_for_update().get_or_create(
        period_key=key,
        defaults={"tokens_used": 0},
    )
    meter.tokens_used = max(0, int(meter.tokens_used or 0) + int(delta))
    meter.save(update_fields=["tokens_used", "updated_at"])
    return int(meter.tokens_used)


@transaction.atomic
def admin_set_chat_restriction(profile, *, until: Optional[datetime] = None, hours: Optional[int] = None) -> Optional[datetime]:
    """Impose or clear a per-user chat restriction (moderation only)."""
    locked = type(profile).objects.select_for_update().get(pk=profile.pk)
    if hours is not None:
        hrs = max(0, int(hours))
        locked.token_cooldown_until = (
            timezone.now() + timedelta(hours=hrs) if hrs > 0 else None
        )
    else:
        locked.token_cooldown_until = until
    locked.save(update_fields=["token_cooldown_until"])
    profile.token_cooldown_until = locked.token_cooldown_until
    return locked.token_cooldown_until


def admin_clear_chat_restriction(profile) -> None:
    admin_set_chat_restriction(profile, until=None)


def estimate_chat_charge(*, prompt_tokens: int = 0, answer: str = "", overhead: int = 800) -> int:
    """Billable estimate for one chat turn (prompt + completion + aux LLM calls)."""
    from core.chat_llm import estimate_chat_tokens

    completion = estimate_chat_tokens(answer or "")
    return max(1, int(prompt_tokens or 0) + completion + max(0, int(overhead)))
