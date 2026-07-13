#!/usr/bin/env bash
# Rebuild the Flutter web app and copy it into Django's static/ folder.
# Usage: ./deploy_flutter_web.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUTTER_APP="$ROOT/flutter_application_1"
BUILD_WEB="$FLUTTER_APP/build/web"
STATIC_DIR="$ROOT/static"

if ! command -v flutter >/dev/null 2>&1; then
  echo "Flutter was not found on PATH. Install Flutter, then re-run this script." >&2
  exit 1
fi

echo "Building Flutter web (base-href=/static/)..."
(
  cd "$FLUTTER_APP"
  flutter pub get
  flutter build web --release --base-href /static/
)

if [[ ! -d "$BUILD_WEB" ]]; then
  echo "Build output missing: $BUILD_WEB" >&2
  exit 1
fi

echo "Replacing $STATIC_DIR with fresh build..."
mkdir -p "$STATIC_DIR"
# Wipe old assets so stale hashed files / service worker maps are not left behind.
find "$STATIC_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a "$BUILD_WEB"/. "$STATIC_DIR"/

echo
echo "Done. Restart Django if it is running:"
echo "  python manage.py runserver"
echo
echo "Then hard-refresh the browser (Ctrl+Shift+R / Cmd+Shift+R)."
echo "If it still looks old, unregister the Flutter service worker and clear site data."
