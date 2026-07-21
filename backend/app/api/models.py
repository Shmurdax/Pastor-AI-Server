from django.conf import settings
from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    """Extra fields for a user that django.contrib.auth.User doesn't have.

    Created automatically for every new user via the post_save signal in
    api/signals.py.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    avatar_url = models.URLField(blank=True, null=True)

    def __str__(self):
        return f"Profile({self.user.username})"


class PrayerRequest(models.Model):
    name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    prayer_text = models.TextField()
    is_anonymous = models.BooleanField(default=False)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    followed_up = models.BooleanField(default=False)
    pastor_notes = models.TextField(blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        if self.is_anonymous:
            return f'Anonymous prayer ({self.created_at:%Y-%m-%d})'
        label = self.name or self.email or 'Unknown'
        return f'Prayer from {label} ({self.created_at:%Y-%m-%d})'
