#!/usr/bin/env bash
# Publish the current Flutter web UI into Pastor-AI-main/static/ for Django to serve.
#
# Source of truth: flutter_application_1/
# Published artifact: static/
#
# Use this only when intentionally shipping a new frontend build.
# Day-to-day frontend work should edit flutter_application_1/ and run/build from there.
#
# The published build uses:
#   - --base-href=/static/     (Django serves assets under /static/)
#   - empty API_BASE_URL       (same-origin /api/* against the Django host)
#   - USE_MOCK_AUTH=false      (hit real Django auth endpoints)
#   - USE_MOCK_PRAYER=true     (prayer form stays mock until backend exists)
#   - GOOGLE_CLIENT_ID from env (when set) for Google Sign-In on web
#
# Optional overrides:
#   FLUTTER_BIN=/path/to/flutter ./scripts/publish_frontend.sh
#   GOOGLE_CLIENT_ID=....apps.googleusercontent.com ./scripts/publish_frontend.sh
#   EXTRA_DART_DEFINES='--dart-define=FOO=bar' ./scripts/publish_frontend.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_APP="$ROOT/flutter_application_1"
STATIC_DIR="$ROOT/static"
BUILD_DIR="$FLUTTER_APP/build/web"

if [[ -n "${FLUTTER_BIN:-}" ]]; then
  :
elif [[ -x /opt/flutter/bin/flutter ]]; then
  FLUTTER_BIN=/opt/flutter/bin/flutter
elif command -v flutter >/dev/null 2>&1; then
  FLUTTER_BIN="$(command -v flutter)"
else
  echo "error: flutter not found. Install Flutter or set FLUTTER_BIN." >&2
  exit 1
fi

if [[ ! -f "$FLUTTER_APP/pubspec.yaml" ]]; then
  echo "error: Flutter app not found at $FLUTTER_APP" >&2
  exit 1
fi

# Prefer process env; fall back to Pastor-AI-main/.env (gitignored).
if [[ -z "${GOOGLE_CLIENT_ID:-}" && -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  # Only load GOOGLE_CLIENT_ID from .env (ignore unrelated keys).
  GOOGLE_CLIENT_ID="$(grep -E '^GOOGLE_CLIENT_ID=' "$ROOT/.env" | head -n1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//")"
  set +a
  export GOOGLE_CLIENT_ID
fi

DART_DEFINES=(
  --dart-define=USE_MOCK_AUTH=false
  --dart-define=USE_MOCK_PRAYER=true
)

if [[ -n "${GOOGLE_CLIENT_ID:-}" ]]; then
  DART_DEFINES+=(--dart-define="GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}")
  echo "==> Including GOOGLE_CLIENT_ID for Google Sign-In (len=${#GOOGLE_CLIENT_ID})"
else
  echo "==> WARNING: GOOGLE_CLIENT_ID unset; Google Sign-In button will report unconfigured."
fi

# Allow additional defines without clobbering the ones above.
# shellcheck disable=SC2206
if [[ -n "${EXTRA_DART_DEFINES:-}" ]]; then
  EXTRA_ARR=( ${EXTRA_DART_DEFINES} )
  DART_DEFINES+=("${EXTRA_ARR[@]}")
fi

echo "==> Using Flutter: $FLUTTER_BIN"
echo "==> Building web UI from: $FLUTTER_APP"
cd "$FLUTTER_APP"

"$FLUTTER_BIN" pub get
# Intentionally omit API_BASE_URL so the bundle uses same-origin relative API paths.
# Do NOT bake temporary ngrok/tunnel hosts into the published static/ build.
"$FLUTTER_BIN" build web --release \
  --base-href=/static/ \
  "${DART_DEFINES[@]}"

if [[ ! -f "$BUILD_DIR/index.html" ]]; then
  echo "error: build output missing at $BUILD_DIR/index.html" >&2
  exit 1
fi

# google_sign_in_web also looks for this meta tag as a client-id source.
if [[ -n "${GOOGLE_CLIENT_ID:-}" ]]; then
  if grep -q 'google-signin-client_id' "$BUILD_DIR/index.html"; then
    sed -i "s|content=\"[^\"]*\"\\(.*google-signin-client_id\\)|content=\"${GOOGLE_CLIENT_ID}\"\\1|" "$BUILD_DIR/index.html" 2>/dev/null || true
  else
    sed -i "s|<meta name=\"description\"|<meta name=\"google-signin-client_id\" content=\"${GOOGLE_CLIENT_ID}\">\\n  <meta name=\"description\"|" "$BUILD_DIR/index.html"
  fi
  echo "==> Injected google-signin-client_id meta into index.html"
fi

echo "==> Syncing build/web -> $STATIC_DIR"
mkdir -p "$STATIC_DIR"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "$BUILD_DIR/" "$STATIC_DIR/"
else
  find "$STATIC_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  cp -a "$BUILD_DIR"/. "$STATIC_DIR/"
fi

echo "==> Published frontend to $STATIC_DIR"
echo "    Open http://localhost:8000/ after starting Django to verify."
if [[ -n "${GOOGLE_CLIENT_ID:-}" ]]; then
  echo "    Remember to authorize JS origins in Google Cloud Console for this host."
fi
