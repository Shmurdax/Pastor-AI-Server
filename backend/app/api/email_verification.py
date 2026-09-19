"""Issue, email, and check 6-digit post-subscription verification codes."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import EmailVerificationCode, Profile

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=45)
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 8


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
    return getattr(settings, "DEFAULT_FROM_EMAIL", "") or "Nordin's AI <noreply@thenordins.org>"


def issue_and_send_verification_code(user, *, force: bool = False) -> str:
    """Create a fresh code and email it. Returns the plaintext code."""
    profile = getattr(user, "profile", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(user=user)
    if profile.email_verified:
        return ""

    now = timezone.now()
    latest = _active_code(user)
    if latest is not None and not force:
        if now - latest.created_at < RESEND_COOLDOWN:
            wait = int((RESEND_COOLDOWN - (now - latest.created_at)).total_seconds()) + 1
            raise EmailVerificationError(
                f"Please wait {wait} seconds before requesting another code.",
                status=429,
            )

    hour_ago = now - timedelta(hours=1)
    recent_sends = EmailVerificationCode.objects.filter(user=user, created_at__gte=hour_ago).count()
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

    name = user.get_full_name() or user.email
    subject = "Your Nordin's AI verification code"
    body = (
        f"Hi {name},\n\n"
        "Enter this code to verify your email for Nordin's AI:\n\n"
        f"    {code}\n\n"
        "This code expires in 10 minutes. If you did not subscribe, you can ignore this email.\n"
    )
    try:
        send_mail(
            subject,
            body,
            _from_email(),
            [user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Failed to send verification email to %s", user.email)
        raise EmailVerificationError(
            "We could not send the email. Please try again in a moment.",
            status=503,
        )
    logger.info("Sent email verification code to %s", user.email)
    return code


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
