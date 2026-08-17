from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "subscription_status",
        "billing_period",
        "is_premium_display",
        "has_premium_access_display",
        "stripe_customer_id",
    )
    list_filter = ("subscription_status", "billing_period")
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "stripe_subscription_id",
    )
    readonly_fields = ("stripe_customer_id", "stripe_subscription_id")

    @admin.display(boolean=True, description="Premium")
    def is_premium_display(self, obj):
        return obj.is_premium

    @admin.display(boolean=True, description="Premium access")
    def has_premium_access_display(self, obj):
        return obj.has_premium_access
