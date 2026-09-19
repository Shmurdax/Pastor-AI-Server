"""Shared DRF permissions for paid-only product APIs."""

from rest_framework.permissions import BasePermission


class HasPremiumAccess(BasePermission):
    """Allow only signed-in Premium members and staff/superusers."""

    message = "A Premium subscription is required."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        profile = getattr(user, "profile", None)
        if profile is not None:
            allowed = bool(profile.has_premium_access)
            if (
                not allowed
                and profile.is_premium
                and not profile.email_verified
                and not getattr(user, "is_staff", False)
                and not getattr(user, "is_superuser", False)
            ):
                self.message = "Verify your email to continue."
            return allowed
        return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
