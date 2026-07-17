from django.contrib import admin
from .models import PrayerRequest, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'avatar_url')
    search_fields = ('user__username', 'user__email')


@admin.register(PrayerRequest)
class PrayerRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'display_name', 'email', 'phone', 'is_anonymous', 'created_at')
    list_filter = ('is_anonymous', 'created_at')
    search_fields = ('name', 'email', 'phone', 'prayer_text')
    readonly_fields = ('created_at',)

    @admin.display(description='Name')
    def display_name(self, obj):
        if obj.is_anonymous:
            return 'Anonymous'
        return obj.name or '—'
