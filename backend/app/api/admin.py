from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.forms.models import BaseInlineFormSet
from django.utils import timezone
from django.utils.html import format_html

from core.persist_db import dump_persistent_postgres

from .mailchimp import MailchimpError, collect_exportable_members
from .mailchimp_admin import export_members_to_mailchimp
from .models import MediaVideo, PlatformTokenMeter, Profile
from .token_quota import (
    admin_adjust_platform_tokens,
    admin_clear_chat_restriction,
    admin_set_chat_restriction,
    platform_monthly_token_budget,
    platform_usage_snapshot,
)


def _apply_restriction_form_fields(profile, cleaned_data) -> str | None:
    if cleaned_data.get("clear_chat_restriction"):
        admin_clear_chat_restriction(profile)
        return "Chat restriction cleared."
    hours = cleaned_data.get("restrict_chat_hours")
    days = cleaned_data.get("restrict_chat_days")
    if hours or days:
        total_hours = int(hours or 0) + int(days or 0) * 24
        if total_hours > 0:
            until = admin_set_chat_restriction(profile, hours=total_hours)
            local = timezone.localtime(until) if until else None
            stamp = local.strftime("%Y-%m-%d %H:%M %Z") if local else ""
            return f"Chat restricted until {stamp}."
    return None


class ProfileInlineFormSet(BaseInlineFormSet):
    """Update the signal-created Profile instead of inserting a second row."""

    def save_new(self, form, commit=True):
        existing = Profile.objects.filter(user_id=self.instance.pk).first()
        if existing is None:
            return super().save_new(form, commit=commit)
        skip = {
            "id",
            "user",
            "DELETE",
            "clear_chat_restriction",
            "restrict_chat_hours",
            "restrict_chat_days",
        }
        for name, value in form.cleaned_data.items():
            if name in skip:
                continue
            if hasattr(existing, name):
                setattr(existing, name, value)
        if commit:
            existing.save()
            _apply_restriction_form_fields(existing, form.cleaned_data)
        form.instance = existing
        return existing

    def save_existing(self, form, instance, commit=True):
        obj = super().save_existing(form, instance, commit=commit)
        if commit:
            _apply_restriction_form_fields(obj, form.cleaned_data)
        return obj


class ProfileAdminForm(forms.ModelForm):
    clear_chat_restriction = forms.BooleanField(
        required=False,
        initial=False,
        label="Clear chat restriction",
        help_text="Remove any active admin chat restriction immediately.",
    )
    restrict_chat_hours = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        label="Restrict chat for (hours)",
        help_text="Optional. Starts a restriction this many hours from save.",
    )
    restrict_chat_days = forms.IntegerField(
        required=False,
        min_value=0,
        initial=0,
        label="Restrict chat for (days)",
        help_text="Optional. Combined with hours.",
    )

    class Meta:
        model = Profile
        fields = "__all__"


class ProfileInline(admin.StackedInline):
    model = Profile
    form = ProfileAdminForm
    formset = ProfileInlineFormSet
    can_delete = False
    extra = 0
    max_num = 1
    fk_name = "user"
    fields = (
        "subscription_status",
        "billing_period",
        "pending_billing_period",
        "cancel_at_period_end",
        "current_period_end",
        "email_verified",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
        "token_cooldown_until",
        "clear_chat_restriction",
        "restrict_chat_days",
        "restrict_chat_hours",
        "stripe_customer_id",
        "stripe_subscription_id",
        "avatar_url",
    )
    readonly_fields = (
        "stripe_customer_id",
        "stripe_subscription_id",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
    )


class PastorUserAdmin(DjangoUserAdmin):
    """Show membership on the Users list so paid signups are visible in admin."""

    inlines = [ProfileInline]
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "plan_tier",
        "subscription_status_display",
        "is_premium_display",
        "token_spent_display",
        "chat_restriction_display",
        "is_active",
    )
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "profile__subscription_status",
        "profile__billing_period",
        "profile__email_verified",
    )
    list_select_related = ("profile",)
    search_fields = ("username", "email", "first_name", "last_name")
    actions = list(DjangoUserAdmin.actions) + [
        "export_selected_to_mailchimp",
        "clear_chat_restrictions",
    ]

    @admin.action(description="Export selected users to Mailchimp")
    def export_selected_to_mailchimp(self, request, queryset):
        members = collect_exportable_members(queryset)
        if not members:
            self.message_user(
                request,
                "None of the selected users have an exportable AI login email.",
                level=messages.WARNING,
            )
            return
        try:
            result = export_members_to_mailchimp(
                members,
                started_by=request.user.get_username() or "admin",
            )
        except MailchimpError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        level = messages.WARNING if result.failed else messages.SUCCESS
        self.message_user(request, result.summary(), level=level)

    @admin.action(description="Clear chat restrictions on selected users")
    def clear_chat_restrictions(self, request, queryset):
        cleared = 0
        for user in queryset.select_related("profile"):
            profile = getattr(user, "profile", None)
            if profile is None or profile.token_cooldown_until is None:
                continue
            admin_clear_chat_restriction(profile)
            cleared += 1
        if cleared:
            dump_persistent_postgres()
        self.message_user(
            request,
            f"Cleared chat restrictions on {cleared} user(s).",
            level=messages.SUCCESS if cleared else messages.WARNING,
        )

    @admin.display(description="Plan", ordering="profile__billing_period")
    def plan_tier(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None:
            return "—"
        return profile.get_billing_period_display() or "—"

    @admin.display(description="Subscription", ordering="profile__subscription_status")
    def subscription_status_display(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None:
            return "—"
        return profile.get_subscription_status_display()

    @admin.display(boolean=True, description="Premium")
    def is_premium_display(self, obj):
        profile = getattr(obj, "profile", None)
        return bool(profile and profile.is_premium)

    @admin.display(description="Tokens spent", ordering="profile__tokens_spent")
    def token_spent_display(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None:
            return "—"
        return profile.tokens_spent

    @admin.display(description="Chat restriction", ordering="profile__token_cooldown_until")
    def chat_restriction_display(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None or profile.token_cooldown_until is None:
            return "—"
        until = profile.token_cooldown_until
        if timezone.is_naive(until):
            until = timezone.make_aware(until, timezone.get_current_timezone())
        if until <= timezone.now():
            return "—"
        local = timezone.localtime(until)
        return format_html(
            '<span style="color:#b45309;font-weight:600;">Until {}</span>',
            local.strftime("%Y-%m-%d %H:%M"),
        )

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    def save_model(self, request, obj, form, change):
        if not (obj.email or "").strip() and "@" in (obj.username or ""):
            obj.email = obj.username
        super().save_model(request, obj, form, change)
        dump_persistent_postgres()

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        dump_persistent_postgres()


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    form = ProfileAdminForm
    list_display = (
        "id",
        "user",
        "subscription_status",
        "billing_period",
        "is_premium_display",
        "tokens_spent",
        "chat_restriction_display",
        "email_verified",
        "current_period_end",
    )
    list_filter = (
        "subscription_status",
        "billing_period",
        "email_verified",
        "cancel_at_period_end",
    )
    search_fields = (
        "user__username",
        "user__email",
        "stripe_customer_id",
        "stripe_subscription_id",
    )
    readonly_fields = (
        "stripe_customer_id",
        "stripe_subscription_id",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
    )
    fields = (
        "user",
        "subscription_status",
        "billing_period",
        "pending_billing_period",
        "cancel_at_period_end",
        "current_period_end",
        "email_verified",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
        "token_cooldown_until",
        "clear_chat_restriction",
        "restrict_chat_days",
        "restrict_chat_hours",
        "stripe_customer_id",
        "stripe_subscription_id",
        "avatar_url",
    )
    list_select_related = ("user",)
    actions = ["clear_chat_restrictions"]

    @admin.action(description="Clear chat restrictions on selected profiles")
    def clear_chat_restrictions(self, request, queryset):
        cleared = 0
        for profile in queryset:
            if profile.token_cooldown_until is None:
                continue
            admin_clear_chat_restriction(profile)
            cleared += 1
        if cleared:
            dump_persistent_postgres()
        self.message_user(
            request,
            f"Cleared chat restrictions on {cleared} profile(s).",
            level=messages.SUCCESS if cleared else messages.WARNING,
        )

    @admin.display(boolean=True, description="Premium")
    def is_premium_display(self, obj):
        return obj.is_premium

    @admin.display(description="Chat restriction", ordering="token_cooldown_until")
    def chat_restriction_display(self, obj):
        if obj.token_cooldown_until is None:
            return "—"
        until = obj.token_cooldown_until
        if timezone.is_naive(until):
            until = timezone.make_aware(until, timezone.get_current_timezone())
        if until <= timezone.now():
            return "—"
        local = timezone.localtime(until)
        return format_html(
            '<span style="color:#b45309;font-weight:600;">Until {}</span>',
            local.strftime("%Y-%m-%d %H:%M"),
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        note = _apply_restriction_form_fields(obj, form.cleaned_data)
        if note:
            self.message_user(request, note, level=messages.SUCCESS)
        dump_persistent_postgres()


class PlatformTokenMeterAdminForm(forms.ModelForm):
    adjust_tokens = forms.IntegerField(
        required=False,
        initial=0,
        label="Adjust tokens used",
        help_text="Add (positive) or subtract (negative) from this month's Premium pool usage.",
    )

    class Meta:
        model = PlatformTokenMeter
        fields = ("period_key", "tokens_used")


@admin.register(PlatformTokenMeter)
class PlatformTokenMeterAdmin(admin.ModelAdmin):
    form = PlatformTokenMeterAdminForm
    list_display = (
        "period_key",
        "tokens_used",
        "budget_display",
        "remaining_display",
        "updated_at",
    )
    readonly_fields = ("period_key", "tokens_used", "created_at", "updated_at", "budget_display", "remaining_display")
    fields = (
        "period_key",
        "tokens_used",
        "budget_display",
        "remaining_display",
        "adjust_tokens",
        "created_at",
        "updated_at",
    )
    ordering = ("-period_key",)

    def has_add_permission(self, request):
        return False

    @admin.display(description="Monthly budget")
    def budget_display(self, obj):
        return platform_monthly_token_budget()

    @admin.display(description="Remaining")
    def remaining_display(self, obj):
        return max(0, platform_monthly_token_budget() - int(obj.tokens_used or 0))

    def changelist_view(self, request, extra_context=None):
        # Ensure the current month row exists so staff can see live usage.
        used, budget, remaining = platform_usage_snapshot()
        extra_context = extra_context or {}
        extra_context["platform_pool_summary"] = {
            "used": used,
            "budget": budget,
            "remaining": remaining,
        }
        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        delta = form.cleaned_data.get("adjust_tokens") or 0
        if delta:
            new_used = admin_adjust_platform_tokens(int(delta), period_key=obj.period_key)
            obj.tokens_used = new_used
            self.message_user(
                request,
                f"Platform tokens used for {obj.period_key} is now {new_used}.",
                level=messages.SUCCESS,
            )
        dump_persistent_postgres()


# Prefer Pastoral User admin (with Profile inline) over Django's default.
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, PastorUserAdmin)


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
        dump_persistent_postgres()
