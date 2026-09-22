from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User
from django.forms.models import BaseInlineFormSet

from core.persist_db import dump_persistent_postgres

from .mailchimp import MailchimpError, collect_exportable_members
from .mailchimp_admin import export_members_to_mailchimp
from .models import MediaVideo, Profile
from .token_quota import admin_adjust_tokens


class ProfileInlineFormSet(BaseInlineFormSet):
    """Update the signal-created Profile instead of inserting a second row."""

    def save_new(self, form, commit=True):
        existing = Profile.objects.filter(user_id=self.instance.pk).first()
        if existing is None:
            return super().save_new(form, commit=commit)
        for name, value in form.cleaned_data.items():
            if name in {"id", "user", "DELETE", "adjust_tokens"}:
                continue
            if hasattr(existing, name):
                setattr(existing, name, value)
        if commit:
            existing.save()
            delta = form.cleaned_data.get("adjust_tokens") or 0
            if delta:
                admin_adjust_tokens(existing, int(delta))
        form.instance = existing
        return existing

    def save_existing(self, form, instance, commit=True):
        obj = super().save_existing(form, instance, commit=commit)
        if commit:
            delta = form.cleaned_data.get("adjust_tokens") or 0
            if delta:
                admin_adjust_tokens(obj, int(delta))
        return obj


class ProfileAdminForm(forms.ModelForm):
    adjust_tokens = forms.IntegerField(
        required=False,
        initial=0,
        help_text=(
            "Add tokens (positive) or remove tokens (negative) from Remaining. "
            "Leave 0 to leave the balance unchanged."
        ),
        label="Adjust tokens",
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
        "token_balance",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
        "token_cooldown_until",
        "token_period_key",
        "token_cycle_anchor",
        "adjust_tokens",
        "stripe_customer_id",
        "stripe_subscription_id",
        "avatar_url",
    )
    readonly_fields = (
        "stripe_customer_id",
        "stripe_subscription_id",
        "token_balance",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
        "token_cooldown_until",
        "token_period_key",
        "token_cycle_anchor",
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
        "token_remaining_display",
        "token_spent_display",
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
    actions = list(DjangoUserAdmin.actions) + ["export_selected_to_mailchimp"]

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

    @admin.display(description="Tokens left", ordering="profile__token_balance")
    def token_remaining_display(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None:
            return "—"
        return profile.token_balance

    @admin.display(description="Tokens spent", ordering="profile__tokens_spent")
    def token_spent_display(self, obj):
        profile = getattr(obj, "profile", None)
        if profile is None:
            return "—"
        return profile.tokens_spent

    def get_inline_instances(self, request, obj=None):
        # The add view saves the User first; api.signals then creates Profile.
        # Showing the OneToOne inline on add POSTs a second INSERT for the same
        # user_id and 500s (api_profile_user_id_key). Edit the profile after save.
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
        "pending_billing_period",
        "is_premium_display",
        "has_premium_access_display",
        "token_balance",
        "tokens_spent",
        "email_verified",
        "cancel_at_period_end",
        "current_period_end",
        "stripe_customer_id",
    )
    list_filter = (
        "subscription_status",
        "billing_period",
        "pending_billing_period",
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
        "token_balance",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
        "token_cooldown_until",
        "token_period_key",
        "token_cycle_anchor",
    )
    fields = (
        "user",
        "subscription_status",
        "billing_period",
        "pending_billing_period",
        "cancel_at_period_end",
        "current_period_end",
        "email_verified",
        "token_balance",
        "tokens_spent",
        "tokens_used_today",
        "token_usage_day",
        "token_cooldown_until",
        "token_period_key",
        "token_cycle_anchor",
        "adjust_tokens",
        "stripe_customer_id",
        "stripe_subscription_id",
        "avatar_url",
    )
    list_select_related = ("user",)

    @admin.display(boolean=True, description="Premium")
    def is_premium_display(self, obj):
        return obj.is_premium

    @admin.display(boolean=True, description="Premium access")
    def has_premium_access_display(self, obj):
        return obj.has_premium_access

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        delta = form.cleaned_data.get("adjust_tokens") or 0
        if delta:
            admin_adjust_tokens(obj, int(delta))
            self.message_user(
                request,
                f"Token balance is now {obj.token_balance}.",
                level=messages.SUCCESS,
            )
        dump_persistent_postgres()


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
