#!/usr/bin/env bash
# Production hardening: no published passwords, no secret cmdline interpolation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

grep -q 'DJANGO_DEBUG=false' "$ROOT/install.sh" || fail "install.sh must default DJANGO_DEBUG=false"
grep -q 'DJANGO_CORS_ALLOW_ALL_ORIGINS=false' "$ROOT/install.sh" \
  || fail "install.sh must default CORS_ALLOW_ALL_ORIGINS=false"
grep -q 'DJANGO_SESSION_COOKIE_SECURE=true' "$ROOT/install.sh" \
  || fail "install.sh must default secure session cookies"
grep -q 'BILLING_MOCK_CHECKOUT=false' "$ROOT/install.sh" \
  || fail "install.sh must default BILLING_MOCK_CHECKOUT=false"
grep -q 'admin123' "$ROOT/install.sh" || fail "install.sh should still reject/replace admin123"
if grep -nE 'DJANGO_SUPERUSER_PASSWORD=\$\{DJANGO_SUPERUSER_PASSWORD:-admin123\}' "$ROOT/install.sh"; then
  fail "install.sh must not default the published admin123 password"
fi
if grep -nE "login: .*admin123" "$ROOT/install.sh" "$ROOT/start.sh"; then
  fail "must not print admin123 in install/start logs"
fi

grep -q 'QDRANT__SERVICE__HOST=127.0.0.1' "$ROOT/start.sh" \
  || fail "start.sh must bind Qdrant to localhost"
grep -q 'warn_insecure_runtime_config' "$ROOT/start.sh" \
  || fail "start.sh must warn about insecure runtime config"

# Parent-shell interpolation of secrets (unescaped ${SECRET}) leaks them in `ps`.
secret_assign_re="(RUNPOD_API_KEY|WHISPER_API_KEY|DJANGO_SECRET_KEY|POSTGRES_PASSWORD|STRIPE_SECRET_KEY|STRIPE_WEBHOOK_SECRET|DJANGO_SUPERUSER_PASSWORD|HF_TOKEN|HUGGING_FACE_HUB_TOKEN)="
if grep -nE "export ${secret_assign_re}'\\\$\{" "$ROOT/start.sh"; then
  fail "start.sh must not interpolate secrets into screen command lines"
fi
if grep -A90 'dmS django' "$ROOT/start.sh" | grep -q 'DJANGO_DEBUG=.*true'; then
  fail "django screen must not force DJANGO_DEBUG=true"
fi
if grep -A90 'dmS django' "$ROOT/start.sh" | grep -q 'DJANGO_CORS_ALLOW_ALL_ORIGINS=.*true'; then
  fail "django screen must not force CORS_ALLOW_ALL_ORIGINS=true"
fi
if grep -A90 'dmS django' "$ROOT/start.sh" | grep -q 'DJANGO_SESSION_COOKIE_SECURE=false'; then
  fail "django screen must not force insecure session cookies"
fi
if grep -A90 'dmS video-ingest' "$ROOT/start.sh" | grep -q "RUNPOD_API_KEY="; then
  fail "video-ingest screen must source RUNPOD_API_KEY from config.env, not argv"
fi

echo "OK start/install production security defaults"
