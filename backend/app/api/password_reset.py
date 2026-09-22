"""Email a 6-digit code and let the account owner set a new password."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from .gmail_send import (
    GmailSendError,
    email_delivery_mode,
    formatted_from_header,
    gmail_is_configured,
    send_via_gmail_api,
)
from .models import PasswordResetCode, Profile

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=45)
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 8

GENERIC_DETAIL = (
    "If an account with that email exists, we sent password reset instructions."
)


class PasswordResetError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def _hash_code(user_id: int, code: str) -> str:
    payload = f"reset:{user_id}:{code}:{settings.SECRET_KEY}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _from_email() -> str:
    configured = getattr(settings, "DEFAULT_FROM_EMAIL", "") or ""
    if configured:
        return formatted_from_header(configured)
    return formatted_from_header()


def _django_mail_delivers() -> bool:
    backend = str(getattr(settings, "EMAIL_BACKEND", "") or "")
    if "locmem" in backend:
        return True
    return bool(str(getattr(settings, "EMAIL_HOST", "") or "").strip())


def _find_user(email: str) -> User | None:
    normalized = (email or "").lower().strip()
    if not normalized:
        return None
    user = User.objects.filter(username=normalized).first()
    if user is None:
        user = User.objects.filter(email__iexact=normalized).first()
    if user is None or not user.is_active:
        return None
    return user


def _active_code(user) -> PasswordResetCode | None:
    return (
        PasswordResetCode.objects.filter(user=user, consumed_at__isnull=True)
        .order_by("-created_at")
        .first()
    )


def _enforce_send_limits(user) -> None:
    now = timezone.now()
    latest = (
        PasswordResetCode.objects.filter(user=user).order_by("-created_at").first()
    )
    if latest is not None and now - latest.created_at < RESEND_COOLDOWN:
        wait = int((RESEND_COOLDOWN - (now - latest.created_at)).total_seconds()) + 1
        raise PasswordResetError(
            f"Please wait {wait} seconds before requesting another code.",
            status=429,
        )

    hour_ago = now - timedelta(hours=1)
    recent_sends = PasswordResetCode.objects.filter(
        user=user,
        created_at__gte=hour_ago,
    ).count()
    if recent_sends >= MAX_SENDS_PER_HOUR:
        raise PasswordResetError(
            "Too many reset emails. Try again in an hour.",
            status=429,
        )


def _deliver(user, subject: str, body: str) -> None:
    send_error = "We could not send the reset email. Please try again in a moment."
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
            logger.error("Password reset email not sent; mail is not configured for %s", user.email)
            raise PasswordResetError(send_error, status=503)
    except PasswordResetError:
        raise
    except GmailSendError:
        logger.exception("Gmail API failed to send password reset email to %s", user.email)
        raise PasswordResetError(send_error, status=503) from None
    except Exception:
        logger.exception("Failed to send password reset email to %s", user.email)
        raise PasswordResetError(send_error, status=503) from None


def request_password_reset(email: str) -> None:
    """Send reset instructions when the email belongs to an active account.

    Unknown addresses return without sending so the public response can stay
    the same either way.
    """
    user = _find_user(email)
    if user is None:
        return

    _enforce_send_limits(user)
    name = user.get_full_name() or user.email
    now = timezone.now()

    if not user.has_usable_password():
        subject = "Nordin's AI sign-in"
        body = (
            f"Hi {name},\n\n"
            "Someone asked to reset the password for this Nordin's AI account.\n"
            "This account signs in with Google, so there is no password to reset.\n"
            'Use the "Sign in with Google" button on the sign-in page.\n\n'
            "If you did not request this, you can ignore this email.\n"
        )
        _deliver(user, subject, body)
        PasswordResetCode.objects.create(
            user=user,
            code_hash=_hash_code(user.id, secrets.token_hex(8)),
            expires_at=now,
            consumed_at=now,
        )
        logger.info("Sent Google sign-in reminder to %s via %s", user.email, email_delivery_mode())
        return

    code = f"{secrets.randbelow(1_000_000):06d}"
    subject = "Your Nordin's AI password reset code"
    body = (
        f"Hi {name},\n\n"
        "Use this code to reset your Nordin's AI password:\n\n"
        f"    {code}\n\n"
        "This code expires in 10 minutes. If you did not request a reset, "
        "you can ignore this email.\n"
    )
    _deliver(user, subject, body)
    PasswordResetCode.objects.filter(user=user, consumed_at__isnull=True).update(
        consumed_at=now
    )
    PasswordResetCode.objects.create(
        user=user,
        code_hash=_hash_code(user.id, code),
        expires_at=now + CODE_TTL,
    )
    logger.info("Sent password reset code to %s via %s", user.email, email_delivery_mode())


def reset_password(*, email: str, code: str, new_password: str) -> None:
    user = _find_user(email)
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if user is None or not user.has_usable_password() or len(digits) != 6:
        raise PasswordResetError("That code is incorrect. Please try again.")

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        message = " ".join(exc.messages) if exc.messages else "Choose a stronger password."
        raise PasswordResetError(message) from None

    record = _active_code(user)
    if record is None:
        raise PasswordResetError("That code is incorrect. Please try again.")
    if record.expires_at <= timezone.now():
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
        raise PasswordResetError("That code expired. Request a new one.")
    if record.attempt_count >= MAX_ATTEMPTS:
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
        raise PasswordResetError("Too many attempts. Request a new code.")

    record.attempt_count += 1
    if not hmac.compare_digest(record.code_hash, _hash_code(user.id, digits)):
        record.save(update_fields=["attempt_count"])
        remaining = MAX_ATTEMPTS - record.attempt_count
        if remaining <= 0:
            record.consumed_at = timezone.now()
            record.save(update_fields=["consumed_at"])
            raise PasswordResetError("Too many attempts. Request a new code.")
        raise PasswordResetError("That code is incorrect. Please try again.")

    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        record.consumed_at = timezone.now()
        record.save(update_fields=["attempt_count", "consumed_at"])
        Token.objects.filter(user=user).delete()
        profile = getattr(user, "profile", None)
        if profile is None:
            profile, _ = Profile.objects.get_or_create(user=user)
        if not profile.email_verified:
            profile.email_verified = True
            profile.save(update_fields=["email_verified"])
