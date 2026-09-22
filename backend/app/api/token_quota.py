"""Premium chat token budgets: monthly grant, daily pacing, secret rollover.

Superusers are never limited. Only Premium (paid) members are enforced.
Unused monthly balance rolls into the next month silently — clients never see
the bank or rollover; they only see wait-until copy when exhausted.

Monthly grants land on the member's subscription anniversary day (the calendar
day they first became Premium), every month — independent of monthly vs yearly
billing.
"""

from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def monthly_token_limit() -> int:
    raw = (os.getenv("MONTHLY_TOKEN_LIMIT_PER_USER") or "100000").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 100000


def daily_token_budget() -> int:
    """Max tokens a Premium user may spend in one calendar day before cooldown.

    Default is 1/10 of the full monthly allotment so binge use trips the
    multi-day cooldown before the whole month is gone.
    """
    raw = (os.getenv("DAILY_TOKEN_BUDGET") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return max(1, monthly_token_limit() // 10)


def token_cooldown_days() -> int:
    raw = (os.getenv("TOKEN_COOLDOWN_DAYS") or "2").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def token_limits_enabled() -> bool:
    return (os.getenv("TOKEN_LIMIT_ENFORCE") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def add_calendar_months(value: date, months: int) -> date:
    """Advance ``value`` by ``months``, clamping the day for short months."""
    month_index = value.month - 1 + int(months)
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def current_allotment_start(anchor: date, today: Optional[date] = None) -> date:
    """Most recent anniversary date on or before ``today``."""
    today = today or timezone.localdate()
    if today < anchor:
        return anchor
    start = anchor
    while True:
        nxt = add_calendar_months(start, 1)
        if nxt > today:
            return start
        start = nxt


def next_allotment_date(profile, *, today: Optional[date] = None) -> Optional[date]:
    """Next monthly token grant date for this profile."""
    today = today or timezone.localdate()
    anchor = profile.token_cycle_anchor
    if anchor is None:
        return None
    key = (profile.token_period_key or "").strip()
    if _ISO_DATE.match(key):
        last = date.fromisoformat(key)
        return add_calendar_months(last, 1)
    return add_calendar_months(current_allotment_start(anchor, today), 1)


def next_allotment_at(profile, *, today: Optional[date] = None) -> Optional[datetime]:
    """Timezone-aware local midnight of the next allotment date."""
    nxt = next_allotment_date(profile, today=today)
    if nxt is None:
        return None
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(nxt, time.min), tz)


def period_key_for(profile, when: Optional[datetime] = None) -> str:
    """Anniversary period start (YYYY-MM-DD) for ``when``."""
    local = timezone.localtime(when or timezone.now()).date()
    anchor = profile.token_cycle_anchor
    if anchor is None:
        return local.isoformat()
    return current_allotment_start(anchor, local).isoformat()


def should_enforce_token_limits(user) -> bool:
    """Premium members only; superusers are exempt."""
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


@dataclass(frozen=True)
class TokenGateResult:
    allowed: bool
    error: str = ""
    code: str = ""
    retry_after_seconds: int = 0
    retry_at: Optional[str] = None
    tokens_remaining_today: Optional[int] = None

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
        if self.tokens_remaining_today is not None:
            payload["tokens_remaining_today"] = self.tokens_remaining_today
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


def _empty_balance_message(profile) -> tuple[str, int, Optional[str]]:
    """User-facing copy when the monthly bank is empty (until next allotment)."""
    until = next_allotment_at(profile)
    if until is None:
        return (
            "You have used up your allotted responses currently. "
            "Please wait until your allotment renews.",
            0,
            None,
        )
    seconds = max(1, int((until - timezone.now()).total_seconds()))
    return _format_wait_message(until), seconds, until.isoformat()


@transaction.atomic
def admin_set_chat_restriction(profile, *, until: Optional[datetime] = None, hours: Optional[int] = None) -> Optional[datetime]:
    """Impose or clear a chat restriction (token_cooldown_until).

    Pass ``until=None`` and ``hours=None`` to clear. ``hours`` sets a restriction
    that many hours from now. ``until`` sets an absolute end time.
    """
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


def ensure_token_cycle_anchor(profile, *, when: Optional[datetime] = None, save: bool = False) -> Optional[date]:
    """Pin the first-subscribe anniversary day once; never move it afterward."""
    if profile.token_cycle_anchor is not None:
        return profile.token_cycle_anchor
    if not profile.is_premium:
        return None
    local = timezone.localtime(when or timezone.now()).date()
    profile.token_cycle_anchor = local
    if save:
        profile.save(update_fields=["token_cycle_anchor"])
    return local


def ensure_monthly_grant(profile, *, save: bool = True) -> bool:
    """Add due monthly grants on the subscription anniversary; unused rolls over."""
    ensure_token_cycle_anchor(profile, save=False)
    anchor = profile.token_cycle_anchor
    if anchor is None:
        return False

    today = timezone.localdate()
    key = (profile.token_period_key or "").strip()
    # Legacy calendar-month keys (YYYY-MM) from the first ship — re-anchor once.
    if key and not _ISO_DATE.match(key):
        key = ""

    grant = monthly_token_limit()
    granted = False

    if not key:
        start = current_allotment_start(anchor, today)
        profile.token_balance = int(profile.token_balance or 0) + grant
        profile.token_period_key = start.isoformat()
        granted = True
    else:
        last = date.fromisoformat(key)
        while True:
            nxt = add_calendar_months(last, 1)
            if nxt > today:
                break
            profile.token_balance = int(profile.token_balance or 0) + grant
            last = nxt
            granted = True
        if granted:
            profile.token_period_key = last.isoformat()

    if save:
        profile.save(
            update_fields=["token_balance", "token_period_key", "token_cycle_anchor"]
        )
    return granted


def _reset_daily_counters_if_needed(profile, today: date) -> None:
    usage_day = profile.token_usage_day
    if usage_day is not None and usage_day == today:
        return
    profile.tokens_used_today = 0
    profile.token_usage_day = today


def _active_cooldown_until(profile) -> Optional[datetime]:
    until = profile.token_cooldown_until
    if until is None:
        return None
    if timezone.is_naive(until):
        until = timezone.make_aware(until, timezone.get_current_timezone())
    if until <= timezone.now():
        return None
    return until


@transaction.atomic
def check_chat_allowed(user) -> TokenGateResult:
    """Return whether this Premium user may start a chat turn."""
    if not should_enforce_token_limits(user):
        return TokenGateResult(allowed=True)

    profile = user.profile
    # Lock the row so concurrent chat posts cannot race the daily budget.
    profile = type(profile).objects.select_for_update().get(pk=profile.pk)
    ensure_monthly_grant(profile, save=True)

    today = timezone.localdate()
    _reset_daily_counters_if_needed(profile, today)

    cooldown = _active_cooldown_until(profile)
    if cooldown is not None:
        seconds = max(1, int((cooldown - timezone.now()).total_seconds()))
        profile.save(
            update_fields=[
                "tokens_used_today",
                "token_usage_day",
                "token_balance",
                "token_period_key",
                "token_cycle_anchor",
            ]
        )
        return TokenGateResult(
            allowed=False,
            error=_format_wait_message(cooldown),
            code="token_cooldown",
            retry_after_seconds=seconds,
            retry_at=cooldown.isoformat(),
            tokens_remaining_today=0,
        )

    # Clear stale cooldown once it has passed.
    if profile.token_cooldown_until is not None:
        profile.token_cooldown_until = None

    balance = int(profile.token_balance or 0)
    if balance <= 0:
        error, seconds, retry_at = _empty_balance_message(profile)
        profile.save(
            update_fields=[
                "tokens_used_today",
                "token_usage_day",
                "token_balance",
                "token_period_key",
                "token_cycle_anchor",
                "token_cooldown_until",
            ]
        )
        return TokenGateResult(
            allowed=False,
            error=error,
            code="token_balance_exhausted",
            retry_after_seconds=seconds,
            retry_at=retry_at,
            tokens_remaining_today=0,
        )

    used_today = int(profile.tokens_used_today or 0)
    daily = daily_token_budget()
    remaining_today = max(0, daily - used_today)
    if remaining_today <= 0:
        until = timezone.now() + timedelta(days=token_cooldown_days())
        profile.token_cooldown_until = until
        profile.save(
            update_fields=[
                "tokens_used_today",
                "token_usage_day",
                "token_balance",
                "token_period_key",
                "token_cycle_anchor",
                "token_cooldown_until",
            ]
        )
        seconds = max(1, int((until - timezone.now()).total_seconds()))
        return TokenGateResult(
            allowed=False,
            error=_format_wait_message(until),
            code="token_daily_limit",
            retry_after_seconds=seconds,
            retry_at=until.isoformat(),
            tokens_remaining_today=0,
        )

    profile.save(
        update_fields=[
            "tokens_used_today",
            "token_usage_day",
            "token_balance",
            "token_period_key",
            "token_cycle_anchor",
            "token_cooldown_until",
        ]
    )
    return TokenGateResult(
        allowed=True,
        tokens_remaining_today=remaining_today,
    )


@transaction.atomic
def record_token_usage(user, tokens: int) -> Optional[TokenGateResult]:
    """Deduct tokens after a successful generation. May start a cooldown."""
    if not should_enforce_token_limits(user):
        return None
    amount = max(0, int(tokens or 0))
    if amount <= 0:
        return None

    profile = type(user.profile).objects.select_for_update().get(pk=user.profile.pk)
    ensure_monthly_grant(profile, save=False)
    today = timezone.localdate()
    _reset_daily_counters_if_needed(profile, today)

    profile.token_balance = max(0, int(profile.token_balance or 0) - amount)
    profile.tokens_spent = int(profile.tokens_spent or 0) + amount
    profile.tokens_used_today = int(profile.tokens_used_today or 0) + amount
    profile.token_usage_day = today

    gate = None
    daily = daily_token_budget()
    if profile.tokens_used_today >= daily and _active_cooldown_until(profile) is None:
        until = timezone.now() + timedelta(days=token_cooldown_days())
        profile.token_cooldown_until = until
        seconds = max(1, int((until - timezone.now()).total_seconds()))
        gate = TokenGateResult(
            allowed=False,
            error=_format_wait_message(until),
            code="token_daily_limit",
            retry_after_seconds=seconds,
            retry_at=until.isoformat(),
            tokens_remaining_today=0,
        )

    profile.save(
        update_fields=[
            "token_balance",
            "tokens_spent",
            "tokens_used_today",
            "token_usage_day",
            "token_period_key",
            "token_cycle_anchor",
            "token_cooldown_until",
        ]
    )
    return gate


@transaction.atomic
def admin_adjust_tokens(profile, delta: int) -> int:
    """Add (positive) or remove (negative) tokens from a user's remaining balance."""
    locked = type(profile).objects.select_for_update().get(pk=profile.pk)
    ensure_monthly_grant(locked, save=False)
    new_balance = int(locked.token_balance or 0) + int(delta)
    locked.token_balance = max(0, new_balance)
    locked.save(
        update_fields=["token_balance", "token_period_key", "token_cycle_anchor"]
    )
    profile.token_balance = locked.token_balance
    profile.token_period_key = locked.token_period_key
    profile.token_cycle_anchor = locked.token_cycle_anchor
    return locked.token_balance


def estimate_chat_charge(*, prompt_tokens: int = 0, answer: str = "", overhead: int = 800) -> int:
    """Billable estimate for one chat turn (prompt + completion + aux LLM calls)."""
    from core.chat_llm import estimate_chat_tokens

    completion = estimate_chat_tokens(answer or "")
    return max(1, int(prompt_tokens or 0) + completion + max(0, int(overhead)))
