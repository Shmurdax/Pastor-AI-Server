from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase


class EnsureSuperuserCommandTests(TestCase):
    def test_creates_superuser_from_env_password(self):
        env = {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "StrongStaffPass1!",
            "DJANGO_SUPERUSER_EMAIL": "admin@localhost",
            "DJANGO_DEBUG": "false",
        }
        out = StringIO()
        with patch.dict("os.environ", env, clear=False):
            call_command("ensure_superuser", stdout=out)

        user = get_user_model().objects.get(username="admin")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("StrongStaffPass1!"))
        self.assertIn("Created superuser", out.getvalue())

    def test_does_not_reset_existing_password_without_flag(self):
        User = get_user_model()
        User.objects.create_user(username="admin", password="KeepThisPass1!")

        env = {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "DifferentPass1!",
            "DJANGO_SUPERUSER_RESET_PASSWORD": "",
            "DJANGO_DEBUG": "false",
        }
        out = StringIO()
        with patch.dict("os.environ", env, clear=False):
            call_command("ensure_superuser", stdout=out)

        user = User.objects.get(username="admin")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("KeepThisPass1!"))
        self.assertFalse(user.check_password("DifferentPass1!"))

    def test_reset_flag_updates_password(self):
        User = get_user_model()
        User.objects.create_superuser(
            username="admin",
            email="admin@localhost",
            password="KeepThisPass1!",
        )
        env = {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "RotatedStaffPass1!",
            "DJANGO_SUPERUSER_RESET_PASSWORD": "1",
            "DJANGO_DEBUG": "false",
        }
        out = StringIO()
        with patch.dict("os.environ", env, clear=False):
            call_command("ensure_superuser", stdout=out)

        user = User.objects.get(username="admin")
        self.assertTrue(user.check_password("RotatedStaffPass1!"))
        self.assertIn("Updated superuser", out.getvalue())

    def test_refuses_published_default_password_in_production(self):
        env = {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "admin123",
            "DJANGO_DEBUG": "false",
        }
        err = StringIO()
        with patch.dict("os.environ", env, clear=False):
            call_command("ensure_superuser", stdout=StringIO(), stderr=err)

        self.assertFalse(get_user_model().objects.filter(username="admin").exists())
        self.assertIn("Refusing", err.getvalue())

    def test_is_idempotent_when_account_already_matches(self):
        User = get_user_model()
        User.objects.create_superuser(
            username="admin",
            email="admin@localhost",
            password="StrongStaffPass1!",
        )
        env = {
            "DJANGO_SUPERUSER_USERNAME": "admin",
            "DJANGO_SUPERUSER_PASSWORD": "StrongStaffPass1!",
            "DJANGO_SUPERUSER_EMAIL": "admin@localhost",
            "DJANGO_DEBUG": "false",
        }
        out = StringIO()
        with patch.dict("os.environ", env, clear=False):
            call_command("ensure_superuser", stdout=out)

        self.assertEqual(User.objects.filter(username="admin").count(), 1)
        self.assertIn("already present", out.getvalue())
