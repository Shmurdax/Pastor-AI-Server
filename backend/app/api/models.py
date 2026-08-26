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
        self.save(update_fields=["subscription_status", "cancel_at_period_end"])

    @property
    def is_premium(self) -> bool:
        self.expire_canceled_subscription_if_needed()
        return self.subscription_status == self.SubscriptionStatus.ACTIVE

    @property
    def has_premium_access(self) -> bool:
        """Staff inherit every Premium entitlement, plus their staff tools."""
        return bool(self.user.is_staff or self.user.is_superuser or self.is_premium)

    def __str__(self):
        return f"Profile({self.user.username})"


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
