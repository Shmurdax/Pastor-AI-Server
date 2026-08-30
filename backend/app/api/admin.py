from django.contrib import admin

from .models import MediaVideo, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "subscription_status",
        "billing_period",
        "is_premium_display",
        "has_premium_access_display",
        "cancel_at_period_end",
        "current_period_end",
        "stripe_customer_id",
    )
    list_filter = ("subscription_status", "billing_period", "cancel_at_period_end")
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


@admin.register(MediaVideo)
class MediaVideoAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "vimeo_id",
        "access_tier",
        "access_tier_manual",
        "is_published",
        "published_at",
        "synced_at",
    )
    list_filter = ("access_tier", "is_published", "access_tier_manual")
    search_fields = ("title", "vimeo_id", "description")
    readonly_fields = ("synced_at", "created_at", "updated_at")
    ordering = ("-published_at",)

    def save_model(self, request, obj, form, change):
        if change and "access_tier" in form.changed_data:
            obj.access_tier_manual = True
        super().save_model(request, obj, form, change)
