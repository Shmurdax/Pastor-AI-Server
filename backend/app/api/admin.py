from django.contrib import admin
from .models import PrayerRequest


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
