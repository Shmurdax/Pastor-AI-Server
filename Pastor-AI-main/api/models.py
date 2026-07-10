from django.conf import settings
from django.db import models


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
