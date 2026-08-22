"""Staff broadcast email helpers — notify every account email."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import get_connection, send_mail


def account_recipient_emails() -> list[str]:
    """Unique, non-blank emails for active accounts (login email preferred)."""
    emails: list[str] = []
    seen: set[str] = set()
    qs = (
        User.objects.filter(is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
        .order_by("id")
    )
    for raw in qs:
        email = (raw or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    # Some older rows may only have username=email with a blank email field.
    for raw in (
        User.objects.filter(is_active=True, email="")
        .values_list("username", flat=True)
        .order_by("id")
    ):
        email = (raw or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        emails.append(email)
    return emails


def email_delivery_configured() -> bool:
    """True when mail will go out via SMTP (or an explicit non-console backend)."""
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if backend.endswith("console.EmailBackend") or backend.endswith("dummy.EmailBackend"):
        return False
    if backend.endswith("locmem.EmailBackend"):
        # Used in tests — treat as deliverable so staff flows can be exercised.
        return True
    return bool(getattr(settings, "EMAIL_HOST", "") or backend)


def send_account_notification(*, subject: str, body: str, fail_silently: bool = False) -> dict:
    """
    Send ``subject`` / ``body`` to every account email individually.

    Individual messages keep recipient addresses private (no shared To/CC list).
    """
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject:
        raise ValueError("Subject is required.")
    if not body:
        raise ValueError("Message body is required.")

    recipients = account_recipient_emails()
    if not recipients:
        return {
            "success": True,
            "sent": 0,
            "failed": 0,
            "recipient_count": 0,
            "from_email": settings.DEFAULT_FROM_EMAIL,
        }

    connection = get_connection()
    sent = 0
    failed = 0
    for recipient in recipients:
        try:
            n = send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=fail_silently,
                connection=connection,
            )
            if n:
                sent += 1
            else:
                failed += 1
        except Exception:
            if not fail_silently:
                raise
            failed += 1

    return {
        "success": failed == 0,
        "sent": sent,
        "failed": failed,
        "recipient_count": len(recipients),
        "from_email": settings.DEFAULT_FROM_EMAIL,
    }
