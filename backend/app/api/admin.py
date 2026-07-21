from django.contrib import admin
from django.utils.html import format_html

from .models import PrayerRequest, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'avatar_url')
    search_fields = ('user__username', 'user__email')


@admin.register(PrayerRequest)
class PrayerRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'display_name',
        'contact_email',
        'phone',
        'prayer_preview',
        'is_anonymous',
        'followed_up',
        'created_at',
    )
    list_filter = ('is_anonymous', 'followed_up', 'created_at')
    search_fields = ('name', 'email', 'phone', 'prayer_text', 'pastor_notes')
    date_hierarchy = 'created_at'
    list_editable = ('followed_up',)
    readonly_fields = (
        'created_at',
        'linked_account',
    )
    fieldsets = (
        (
            'Contact',
            {
                'fields': (
                    'name',
                    'email',
                    'phone',
                    'is_anonymous',
                    'linked_account',
                ),
            },
        ),
        (
            'Prayer request',
            {
                'fields': ('prayer_text', 'created_at'),
            },
        ),
        (
            'Follow-up',
            {
                'fields': ('followed_up', 'contacted_at', 'pastor_notes'),
            },
        ),
        (
            'Submission meta',
            {
                'classes': ('collapse',),
                'fields': ('user',),
            },
        ),
    )

    @admin.display(description='Name')
    def display_name(self, obj):
        if obj.is_anonymous:
            return 'Anonymous'
        return obj.name or '—'

    @admin.display(description='Email')
    def contact_email(self, obj):
        if obj.email:
            return format_html('<a href="mailto:{}">{}</a>', obj.email, obj.email)
        if obj.user_id:
            return format_html(
                '<a href="mailto:{}">{} (account)</a>',
                obj.user.email,
                obj.user.email,
            )
        return '—'

    @admin.display(description='Request preview')
    def prayer_preview(self, obj):
        text = (obj.prayer_text or '').replace('\n', ' ').strip()
        if len(text) > 80:
            text = f'{text[:77]}...'
        return text or '—'

    @admin.display(description='Linked sign-in account')
    def linked_account(self, obj):
        if obj.user_id is None:
            return '—'
        label = obj.user.get_full_name() or obj.user.username
        return format_html('{} &lt;{}&gt;', label, obj.user.email)
