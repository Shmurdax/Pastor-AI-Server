"""Premium chat token budgets: monthly grant, daily pacing, secret rollover.

Superusers are never limited. Only Premium (paid) members are enforced.
Unused monthly balance rolls into the next month silently — clients never see
the bank or rollover; they only see daily exhaustion wait copy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.utils import timezone


def monthly_token_limit() -> int:
    raw = (os.getenv("MONTHLY_TOKEN_LIMIT_PER_USER") or "100000").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 100000


def daily_token_budget() -> int:
    """Max tokens a Premium user may spend in one calendar day before cooldown."""
    raw = (os.getenv("DAILY_TOKEN_BUDGET") or "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    # ~one day of an equal monthly split (100k / 30).
    return max(1, monthly_token_limit() // 30)


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


def period_key_for(when: Optional[datetime] = None) -> str:
    """Calendar month key for secret monthly grants (YYYY-MM)."""
    now = when or timezone.now()
    local = timezone.localtime(now)
    return f"{local.year:04d}-{local.month:02d}"


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
            "You've run out of responses for now. "
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
    return (
        f"You've run out of responses for now. "
        f"Please wait {wait} (until {stamp}) before asking again."
    )


def _empty_balance_message() -> str:
    return (
        "You've run out of responses for now. "
        "Please wait until your allotment renews before asking again."
    )


def ensure_monthly_grant(profile, *, save: bool = True) -> bool:
    """Add this month's grant once; unused balance rolls over silently."""
    key = period_key_for()
    if (profile.token_period_key or "") == key:
        return False
    grant = monthly_token_limit()
    profile.token_balance = int(profile.token_balance or 0) + grant
    profile.token_period_key = key
    if save:
        profile.save(update_fields=["token_balance", "token_period_key"])
    return True


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
            update_fields=["tokens_used_today", "token_usage_day", "token_balance", "token_period_key"]
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
        profile.save(
            update_fields=[
                "tokens_used_today",
                "token_usage_day",
                "token_balance",
                "token_period_key",
                "token_cooldown_until",
            ]
        )
        return TokenGateResult(
            allowed=False,
            error=_empty_balance_message(),
            code="token_balance_exhausted",
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
    locked.save(update_fields=["token_balance", "token_period_key"])
    profile.token_balance = locked.token_balance
    profile.token_period_key = locked.token_period_key
    return locked.token_balance


def estimate_chat_charge(*, prompt_tokens: int = 0, answer: str = "", overhead: int = 800) -> int:
    """Billable estimate for one chat turn (prompt + completion + aux LLM calls)."""
    from core.chat_llm import estimate_chat_tokens

    completion = estimate_chat_tokens(answer or "")
    return max(1, int(prompt_tokens or 0) + completion + max(0, int(overhead)))
