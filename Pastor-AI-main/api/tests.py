from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase


class AuthApiTests(APITestCase):
    def test_register_login_me_logout_flow(self):
        register = self.client.post(
            "/api/auth/register/",
            {"name": "Test User", "email": "tester@example.com", "password": "Str0ngPass!"},
            format="json",
        )
        self.assertEqual(register.status_code, 201, register.data)
        self.assertIn("token", register.data)
        self.assertEqual(register.data["user"]["email"], "tester@example.com")
        self.assertEqual(register.data["user"]["name"], "Test User")

        bad_login = self.client.post(
            "/api/auth/login/",
            {"email": "tester@example.com", "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(bad_login.status_code, 401)

        login = self.client.post(
            "/api/auth/login/",
            {"email": "tester@example.com", "password": "Str0ngPass!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200, login.data)
        token = login.data["token"]

        me = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(me.status_code, 200, me.data)
        self.assertEqual(me.data["user"]["email"], "tester@example.com")

        logout = self.client.post(
            "/api/auth/logout/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(logout.status_code, 204)
        self.assertFalse(Token.objects.filter(key=token).exists())

        me_after = self.client.get(
            "/api/auth/me/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(me_after.status_code, 401)

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(
            username="dup@example.com",
            email="dup@example.com",
            password="Str0ngPass!",
        )
        res = self.client.post(
            "/api/auth/register/",
            {"name": "Dup", "email": "dup@example.com", "password": "Str0ngPass!"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
