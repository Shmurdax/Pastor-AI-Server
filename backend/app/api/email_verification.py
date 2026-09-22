"""Issue, email, and check 6-digit post-signup verification codes."""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from datetime import timedelta
from typing import NamedTuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import connection, transaction
from django.utils import timezone

from .gmail_send import (
    GmailSendError,
    email_delivery_mode,
    formatted_from_header,
    gmail_is_configured,
    send_via_gmail_api,
)
from .models import EmailVerificationCode, Profile

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=45)
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 8
_send_locks: dict[int, threading.Lock] = {}
_send_locks_guard = threading.Lock()


class IssuedVerificationCode(NamedTuple):
    code: str
    emailed: bool


class EmailVerificationError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _hash_code(user_id: int, code: str) -> str:
    payload = f"{user_id}:{code}:{settings.SECRET_KEY}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _active_code(user) -> EmailVerificationCode | None:
    return (
        EmailVerificationCode.objects.filter(user=user, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )


def _from_email() -> str:
    configured = getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""
    if configured:
        return formatted_from_header(configured)
    return formatted_from_header()


def _django_mail_delivers() -> bool:
    """True when Django mail will actually leave the process (SMTP or test locmem)."""
    backend = str(getattr(settings, "EMAIL_BACKEND", "") or "")
    if "locmem" in backend:
        return True
    return bool(str(getattr(settings, "EMAIL_HOST", "") or "").strip())


def _user_send_lock(user_id: int) -> threading.Lock:
    with _send_locks_guard:
        lock = _send_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _send_locks[user_id] = lock
        return lock


def _reserve_verification_code(user, *, force: bool) -> str:
    """Create one active code. Overlapping requests wait, then hit the cooldown."""
    user_model = get_user_model()
    with transaction.atomic():
        locked = user_model.objects.filter(pk=user.pk)
        if getattr(connection.features, "has_select_for_update", False):
            locked = locked.select_for_update()
        locked.get()
        now = timezone.now()
        latest = _active_code(user)
        if latest is not None and not force and now - latest.created_at < RESEND_COOLDOWN:
            wait = int((RESEND_COOLDOWN - (now - latest.created_at)).total_seconds()) + 1
            raise EmailVerificationError(
                f"Please wait {wait} seconds before requesting another code.",
                status=429,
            )

        hour_ago = now - timedelta(hours=1)
        recent_sends = EmailVerificationCode.objects.filter(
            user=user, created_at__gte=hour_ago
        ).count()
        if recent_sends >= MAX_SENDS_PER_HOUR:
            raise EmailVerificationError(
                "Too many verification emails. Try again in an hour.",
                status=429,
            )

        EmailVerificationCode.objects.filter(user=user, consumed_at__isnull=True).update(
            consumed_at=now
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        EmailVerificationCode.objects.create(
            user=user,
            code_hash=_hash_code(user.id, code),
            expires_at=now + CODE_TTL,
        )
        return code


def issue_and_send_verification_code(user, *, force: bool = False) -> IssuedVerificationCode:
    """Create a fresh code and email it through Gmail (or SMTP in tests)."""
    profile = getattr(user, "profile", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(user=user)
    if profile.email_verified:
        return IssuedVerificationCode("", emailed=True)

    with _user_send_lock(user.pk):
        code = _reserve_verification_code(user, force=force)

    name = user.get_full_name() or user.email
    subject = "Your Nordin's AI verification code"
    body = (
        f"Hi {name},\n\n"
        "Enter this code to verify your email for Nordin's AI:\n\n"
        f"    {code}\n\n"
        "This code expires in 10 minutes. After you verify, you can continue to payment.\n"
        "If you did not create an account, you can ignore this email.\n"
    )
    send_error = (
        "We could not send the verification email. Please try again in a moment."
    )
    try:
        if gmail_is_configured():
            send_via_gmail_api(to_email=user.email, subject=subject, body=body)
        elif _django_mail_delivers():
            send_mail(
                subject,
                body,
                _from_email(),
                [user.email],
                fail_silently=False,
            )
        else:
            logger.error(
                "Gmail is not configured; verification email not sent to %s",
                user.email,
            )
            raise EmailVerificationError(send_error, status=503)
    except EmailVerificationError:
        raise
    except GmailSendError:
        logger.exception("Gmail API failed to send verification email to %s", user.email)
        raise EmailVerificationError(send_error, status=503) from None
    except Exception:
        logger.exception("Failed to send verification email to %s", user.email)
        raise EmailVerificationError(send_error, status=503) from None
    logger.info(
        "Sent email verification code to %s via %s",
        user.email,
        email_delivery_mode(),
    )
    return IssuedVerificationCode(code, emailed=True)


def verify_email_code(user, raw_code: str) -> Profile:
    profile = getattr(user, "profile", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(user=user)
    if profile.email_verified:
        return profile

    code = "".join(ch for ch in (raw_code or "") if ch.isdigit())
    if len(code) != 6:
        raise EmailVerificationError("Enter the 6-digit code from your email.")

    record = _active_code(user)
    if record is None:
        raise EmailVerificationError("Request a new code, then try again.")
    if record.expires_at <= timezone.now():
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
        raise EmailVerificationError("That code expired. Request a new one.")
    if record.attempt_count >= MAX_ATTEMPTS:
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
        raise EmailVerificationError("Too many attempts. Request a new code.")

    record.attempt_count += 1
    if record.code_hash != _hash_code(user.id, code):
        record.save(update_fields=["attempt_count"])
        remaining = MAX_ATTEMPTS - record.attempt_count
        if remaining <= 0:
            record.consumed_at = timezone.now()
            record.save(update_fields=["consumed_at"])
            raise EmailVerificationError("Too many attempts. Request a new code.")
        raise EmailVerificationError("That code is incorrect. Please try again.")

    record.consumed_at = timezone.now()
    record.save(update_fields=["attempt_count", "consumed_at"])
    profile.email_verified = True
    profile.save(update_fields=["email_verified"])
    return profile
