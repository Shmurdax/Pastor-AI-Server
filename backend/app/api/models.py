from django.db import models
from django.contrib.auth.models import User


class PrayerRequest(models.Model):
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    prayer_text = models.TextField()
    is_anonymous = models.BooleanField(default=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.is_anonymous:
            return f'Anonymous prayer ({self.created_at:%Y-%m-%d})'
        label = self.name or self.email or 'Unknown'
        return f'Prayer from {label} ({self.created_at:%Y-%m-%d})'
