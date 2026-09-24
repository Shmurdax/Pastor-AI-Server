from django.test import SimpleTestCase

from pastor_ai.dev_isolation import (
    assert_development_isolated,
    development_isolation_problems,
)


def _dev(**overrides):
    env = {
        "PASTOR_ENV": "development",
        "STRIPE_SECRET_KEY": "sk_test_abc",
        "STRIPE_PUBLISHABLE_KEY": "pk_test_abc",
        "PUBLIC_APP_URL": "https://dev.example.test",
        "DJANGO_ALLOWED_HOSTS": "dev.example.test",
        "CLOUDFLARE_TUNNEL_TOKEN": "",
        "POSTGRES_HOST": "127.0.0.1",
        "QDRANT_URL": "http://127.0.0.1:6333",
        "VLLM_URL": "https://api.runpod.ai/v2/dev-endpoint/openai/v1",
        "RUNPOD_VLLM_ENDPOINT_ID": "dev-endpoint",
        "GMAIL_SANDBOX_SENDERS": "",
        "GMAIL_SENDER": "",
        "MAILCHIMP_AUDIENCE_ID": "",
    }
    env.update(overrides)
    return env


class DevelopmentIsolationTests(SimpleTestCase):
    def test_production_mode_is_unchecked(self):
        self.assertEqual(
            development_isolation_problems({"PASTOR_ENV": "", "STRIPE_SECRET_KEY": "sk_live_x"}),
            [],
        )

    def test_live_stripe_key_is_refused(self):
        problems = development_isolation_problems(_dev(STRIPE_SECRET_KEY="sk_live_secret"))
        self.assertTrue(any("STRIPE_SECRET_KEY" in item for item in problems))
        with self.assertRaises(RuntimeError):
            assert_development_isolated(_dev(STRIPE_SECRET_KEY="sk_live_secret"))

    def test_production_hostname_is_refused(self):
        problems = development_isolation_problems(
            _dev(PUBLIC_APP_URL="https://christianaiapophatictestdomain.com")
        )
        self.assertTrue(any("christianaiapophatictestdomain.com" in item for item in problems))

    def test_non_loopback_database_is_refused(self):
        problems = development_isolation_problems(_dev(POSTGRES_HOST="10.0.0.8"))
        self.assertTrue(any("POSTGRES_HOST" in item for item in problems))

    def test_clean_dev_env_boots(self):
        self.assertEqual(development_isolation_problems(_dev()), [])
