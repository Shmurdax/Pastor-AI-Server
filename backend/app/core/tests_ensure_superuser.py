from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings


class EnsureSuperuserCommandTests(TestCase):
    @override_settings()
    def test_creates_default_admin_superuser(self):
        out = StringIO()
        call_command("ensure_superuser", stdout=out)

        user = get_user_model().objects.get(username="admin")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("admin123"))
        self.assertIn("Created superuser", out.getvalue())

    def test_updates_existing_user_to_match_credentials(self):
        User = get_user_model()
        User.objects.create_user(username="admin", password="old-password")

        out = StringIO()
        call_command("ensure_superuser", stdout=out)

        user = User.objects.get(username="admin")
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("admin123"))
        self.assertIn("Updated superuser", out.getvalue())

    def test_is_idempotent_when_credentials_already_match(self):
        User = get_user_model()
        User.objects.create_superuser(
            username="admin",
            email="admin@localhost",
            password="admin123",
        )

        out = StringIO()
        call_command("ensure_superuser", stdout=out)

        self.assertEqual(User.objects.filter(username="admin").count(), 1)
        self.assertIn("already present", out.getvalue())
