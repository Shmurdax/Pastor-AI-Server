"""Ensure a Django admin superuser exists (idempotent).

Does not use a published default password. Create the account only when
``DJANGO_SUPERUSER_PASSWORD`` is set. Existing passwords are left alone
unless ``DJANGO_SUPERUSER_RESET_PASSWORD=1``.
"""
from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

WEAK_PASSWORDS = frozenset(
    {
        "admin123",
        "admin",
        "password",
        "password123",
        "changeme",
        "secret",
        "pastor",
        "pastorai",
    }
)


def _is_weak_password(password: str) -> bool:
    stripped = (password or "").strip()
    if len(stripped) < 12:
        return True
    return stripped.lower() in WEAK_PASSWORDS


class Command(BaseCommand):
    help = "Create the Django admin superuser if it does not already exist."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME", "admin")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@localhost")
        reset = os.getenv("DJANGO_SUPERUSER_RESET_PASSWORD", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        debug = os.getenv("DJANGO_DEBUG", "false").lower() == "true"

        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if user is None:
            if not password:
                self.stderr.write(
                    "DJANGO_SUPERUSER_PASSWORD is required to create the staff account."
                )
                return
            if _is_weak_password(password) and not debug:
                self.stderr.write(
                    "Refusing to create a staff account with a short or published "
                    "default password. Set a 12+ character DJANGO_SUPERUSER_PASSWORD."
                )
                return
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
        if email and user.email != email:
            user.email = email
            changed = True

        if user.check_password("admin123") or (
            password and _is_weak_password(password) and user.check_password(password)
        ):
            self.stderr.write(
                f"WARNING: staff account '{username}' still uses a weak/default "
                "password. Set DJANGO_SUPERUSER_PASSWORD to a 12+ character value "
                "and DJANGO_SUPERUSER_RESET_PASSWORD=1, then restart."
            )

        if reset:
            if not password:
                self.stderr.write(
                    "DJANGO_SUPERUSER_RESET_PASSWORD=1 requires DJANGO_SUPERUSER_PASSWORD."
                )
            elif _is_weak_password(password) and not debug:
                self.stderr.write(
                    "Refusing DJANGO_SUPERUSER_RESET_PASSWORD with a weak password."
                )
            elif not user.check_password(password):
                user.set_password(password)
                changed = True

        if changed:
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"Updated superuser '{username}' credentials/flags.")
            )
        else:
            self.stdout.write(f"Superuser '{username}' already present.")
