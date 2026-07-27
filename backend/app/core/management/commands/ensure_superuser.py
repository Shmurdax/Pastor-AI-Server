"""Ensure a Django admin superuser exists (idempotent).

Defaults: username=admin, password=admin123.
Override with DJANGO_SUPERUSER_USERNAME / DJANGO_SUPERUSER_PASSWORD /
DJANGO_SUPERUSER_EMAIL.
"""
from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the default Django admin superuser if it does not already exist."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "admin123")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@localhost")

        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if user is None:
            User.objects.create_superuser(
                username=username,
                email=email,
                password=password,
            )
            self.stdout.write(self.style.SUCCESS(f"Created superuser '{username}'."))
            return

        changed = False
        if not user.is_staff:
            user.is_staff = True
            changed = True
        if not user.is_superuser:
            user.is_superuser = True
            changed = True
        if not user.has_usable_password() or not user.check_password(password):
            user.set_password(password)
            changed = True
        if email and user.email != email:
            user.email = email
            changed = True

        if changed:
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"Updated superuser '{username}' credentials/flags.")
            )
        else:
            self.stdout.write(f"Superuser '{username}' already present.")
