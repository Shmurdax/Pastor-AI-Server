from django.conf import settings
from django.db import models


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

    @property
    def is_premium(self) -> bool:
        return self.subscription_status == self.SubscriptionStatus.ACTIVE

    def __str__(self):
        return f"Profile({self.user.username})"
