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
