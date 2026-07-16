# Pastor-AI Flutter UI

Source of truth for the Pastor-AI web frontend.

Django serves a published copy from `../static/`. Edit this package; publish only when shipping a new UI.

## Local iteration (without publishing)

```bash
flutter pub get
flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=USE_MOCK_AUTH=false
cd build/web && python3 -m http.server 8080
```

Open http://localhost:8080 (Django API on :8000).

## Publish into Django `static/`

From `Pastor-AI-main/`:

```bash
./scripts/publish_frontend.sh
```

## Key dart-defines

| Define | Default | Notes |
| --- | --- | --- |
| `API_BASE_URL` | empty (same-origin) | Set to `http://localhost:8000` for separate :8080 serving |
| `USE_MOCK_AUTH` | `false` | Real Django auth by default; set `true` only for UI-only work without a backend |
| `USE_MOCK_PRAYER` | `true` | Keep true until prayer API exists |
| `GOOGLE_CLIENT_ID` | empty | OAuth 2.0 **Web** client ID; required for Google Sign-In |

Google Sign-In also needs:
1. The same Web client ID set as Django env `GOOGLE_CLIENT_ID`
2. Authorized JavaScript origins in Google Cloud Console for your app hosts (e.g. `http://localhost:8000`)
3. A republish with that ID baked in: `GOOGLE_CLIENT_ID=... ./scripts/publish_frontend.sh`

## Lint / test

```bash
flutter analyze
flutter test
```
