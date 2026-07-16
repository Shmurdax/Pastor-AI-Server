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
#
# Optional overrides:
#   FLUTTER_BIN=/path/to/flutter ./scripts/publish_frontend.sh
#   EXTRA_DART_DEFINES='--dart-define=GOOGLE_CLIENT_ID=...' ./scripts/publish_frontend.sh

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

echo "==> Using Flutter: $FLUTTER_BIN"
echo "==> Building web UI from: $FLUTTER_APP"
cd "$FLUTTER_APP"

"$FLUTTER_BIN" pub get
# Intentionally omit API_BASE_URL so the bundle uses same-origin relative API paths.
# Do NOT bake temporary ngrok/tunnel hosts into the published static/ build.
# shellcheck disable=SC2086
"$FLUTTER_BIN" build web --release \
  --base-href=/static/ \
  --dart-define=USE_MOCK_AUTH=false \
  --dart-define=USE_MOCK_PRAYER=true \
  ${EXTRA_DART_DEFINES:-}

if [[ ! -f "$BUILD_DIR/index.html" ]]; then
  echo "error: build output missing at $BUILD_DIR/index.html" >&2
  exit 1
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
