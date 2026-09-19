from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Profile(models.Model):
    """Extra fields for a user that django.contrib.auth.User doesn't have.

    Created automatically for every new user via the post_save signal in
    api/signals.py.
    """

    class SubscriptionStatus(models.TextChoices):
        FREE = "free", "Free"
        ACTIVE = "active", "Active"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    class BillingPeriod(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    avatar_url = models.URLField(blank=True, null=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, default="")
    stripe_subscription_id = models.CharField(max_length=255, blank=True, default="")
    subscription_status = models.CharField(
        max_length=32,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.FREE,
    )
    billing_period = models.CharField(
        max_length=16,
        choices=BillingPeriod.choices,
        blank=True,
        default="",
    )
    cancel_at_period_end = models.BooleanField(default=False)
    current_period_end = models.DateTimeField(blank=True, null=True)
    pending_billing_period = models.CharField(
        max_length=16,
        choices=BillingPeriod.choices,
        blank=True,
        default="",
        help_text="Scheduled monthly/yearly switch that takes effect at current_period_end.",
    )
    email_verified = models.BooleanField(
        default=True,
        help_text="Email/password signups start unverified and must enter a code after subscribing.",
    )

    def expire_canceled_subscription_if_needed(self) -> None:
        """Drop Premium after a scheduled cancel once the paid period ends."""
        if self.subscription_status != self.SubscriptionStatus.ACTIVE:
            return
        if not self.cancel_at_period_end or self.current_period_end is None:
            return
        if timezone.now() < self.current_period_end:
            return
        self.subscription_status = self.SubscriptionStatus.CANCELED
        self.cancel_at_period_end = False
        self.pending_billing_period = ""
        self.save(
            update_fields=[
                "subscription_status",
                "cancel_at_period_end",
                "pending_billing_period",
            ]
        )

    def apply_pending_plan_change_if_needed(self) -> None:
        """Apply a scheduled monthly/yearly switch after the current period.

        Stripe-backed subscriptions are updated by webhooks when the schedule
        rolls. This covers mock checkout and admin-granted Premium.
        """
        if self.stripe_subscription_id:
            return
        if self.subscription_status != self.SubscriptionStatus.ACTIVE:
            return
        if self.cancel_at_period_end:
            return
        pending = (self.pending_billing_period or "").strip().lower()
        if pending not in {self.BillingPeriod.MONTHLY, self.BillingPeriod.YEARLY}:
            return
        if pending == (self.billing_period or "").strip().lower():
            self.pending_billing_period = ""
            self.save(update_fields=["pending_billing_period"])
            return
        if self.current_period_end is None or timezone.now() < self.current_period_end:
            return
        now = timezone.now()
        if pending == self.BillingPeriod.YEARLY:
            try:
                next_end = now.replace(year=now.year + 1)
            except ValueError:
                next_end = now + timedelta(days=365)
        else:
            month = now.month + 1
            year = now.year
            if month > 12:
                month = 1
                year += 1
            try:
                next_end = now.replace(year=year, month=month)
            except ValueError:
                next_end = now + timedelta(days=30)
        self.billing_period = pending
        self.pending_billing_period = ""
        self.current_period_end = next_end
        self.save(
            update_fields=[
                "billing_period",
                "pending_billing_period",
                "current_period_end",
            ]
        )

    @property
    def is_premium(self) -> bool:
        self.expire_canceled_subscription_if_needed()
        self.apply_pending_plan_change_if_needed()
        return self.subscription_status == self.SubscriptionStatus.ACTIVE

    @property
    def has_premium_access(self) -> bool:
        """Staff inherit every Premium entitlement, plus their staff tools."""
        if self.user.is_staff or self.user.is_superuser:
            return True
        if not self.is_premium:
            return False
        return bool(self.email_verified)

    def __str__(self):
        return f"Profile({self.user.username})"


class EmailVerificationCode(models.Model):
    """One-time 6-digit email confirmation sent after a Premium purchase."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verification_codes",
    )
    code_hash = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"EmailVerificationCode({self.user_id})"


class MediaVideo(models.Model):
    """Daily Devotional video synced from a Vimeo Folder."""

    class AccessTier(models.TextChoices):
        FREE_PREVIEW = "free_preview", "Free preview"
        PREMIUM = "premium", "Premium"

    vimeo_id = models.CharField(max_length=64, unique=True, db_index=True)
    privacy_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Unlisted privacy hash from Vimeo URI (/videos/{id}:{hash}).",
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(db_index=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    thumbnail_url = models.URLField(blank=True, default="")
    access_tier = models.CharField(
        max_length=32,
        choices=AccessTier.choices,
        default=AccessTier.PREMIUM,
        db_index=True,
    )
    access_tier_manual = models.BooleanField(
        default=False,
        help_text="If set, Vimeo sync will not overwrite access_tier.",
    )
    is_published = models.BooleanField(default=True, db_index=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "title"]

    def __str__(self):
        return f"{self.title} ({self.vimeo_id})"

    @property
    def duration_label(self) -> str:
        total = int(self.duration_seconds or 0)
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class MailchimpExportRun(models.Model):
    """One staff export of AI login emails into the Mailchimp audience."""

    started_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    candidate_count = models.PositiveIntegerField(default=0)
    added = models.PositiveIntegerField(default=0)
    updated = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    error_summary = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Mailchimp export {self.created_at:%Y-%m-%d %H:%M} ({self.started_by})"
