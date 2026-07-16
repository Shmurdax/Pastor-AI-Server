# AGENTS.md

## Cursor Cloud specific instructions

Pastor-AI is a Django backend that serves a Flutter web UI plus a RAG chatbot and
token-auth API. Everything lives under `Pastor-AI-main/`.

### Services & how to run them

All commands assume the Python virtualenv at `Pastor-AI-main/venv` (created by the
startup update script).

| Service | Purpose | Start command (from `Pastor-AI-main/`) | Port |
| --- | --- | --- | --- |
| Ollama | Local LLM (`llama3.2`) used by the chat endpoint | `ollama serve` (see AVX512 caveat below) | 11434 |
| Django | REST API (`/api/chat/`, `/api/auth/*`) + serves published `static/` frontend artifact (refresh via `./scripts/publish_frontend.sh`) | `source venv/bin/activate && python manage.py runserver 0.0.0.0:8000` | 8000 |
| Flutter web (dev) | Current frontend source, built for local backend without publishing | see "Frontend: hybrid source + published static/" | 8080 |

`ngrok` and `qdrant` are NOT needed for local development. `setup.sh` is a RunPod
deployment script that rewrites `views.py`/`settings.py` to a Qdrant+ngrok setup —
do not run it locally; the repo code uses Chroma.

### Ollama AVX512/AMX segfault caveat (important, non-obvious)

On this VM the CPU advertises AVX512/AMX, but Ollama's optimized ggml CPU kernels
(`sapphirerapids`, `icelake`, `cascadelake`, `cooperlake`, `skylakex`, `cannonlake`,
`zen4`, `alderlake`) segfault at model load ("llama-server process has terminated:
signal: segmentation fault"). Those `.so` files have been moved to
`/usr/local/lib/ollama/_disabled_variants/` so ggml falls back to the AVX2 `haswell`
kernel, which works. Do NOT reinstall Ollama or restore those files without
re-disabling them, or chat will start segfaulting again. Chat inference on CPU takes
~30-90s per request; this is expected.

### Backend one-time data setup (persisted in the VM snapshot)

These are already done and persist in the snapshot; only redo them if the data is
missing:
- Django DB: `python manage.py migrate` (SQLite at `db.sqlite3`, gitignored).
- Ollama model: `ollama pull llama3.2`.
- Chroma vector DB `Pastor-AI-main/sermon_brain_db/` (gitignored): built by embedding
  the 551 markdown files in `converted_markdown/` with `all-MiniLM-L6-v2`. The
  committed `sermon_indexer.py` has a hardcoded Windows path; to rebuild, point a
  copy of it at `./converted_markdown` and `./sermon_brain_db`. Chat retrieval
  returns empty context if this DB is missing.

Note: `api/views.py` builds the RAG chain (embeddings + Chroma + ChatOllama) at
module import, so the embedding model loads during Django's system checks — the very
first `manage.py` command after a fresh model cache is slow.

### Frontend: hybrid source + published static/

| Role | Path | When to use |
| --- | --- | --- |
| Source of truth | `flutter_application_1/` | Day-to-day UI edits, analyze/test, local iteration |
| Published artifact | `static/` | What Django serves at `http://localhost:8000/` |

**Rule:** edit Flutter source freely; refresh `static/` only when intentionally publishing a new frontend.

#### Publish a new frontend into `static/`

From `Pastor-AI-main/`:

```bash
./scripts/publish_frontend.sh
```

This builds Flutter web with:
- `--base-href=/static/` (Django asset path)
- empty `API_BASE_URL` (same-origin `/api/*` — do **not** bake temporary ngrok hosts)
- `USE_MOCK_AUTH=false` (also the Flutter source default; mock auth is opt-in only)
- `USE_MOCK_PRAYER=true`

Then syncs `flutter_application_1/build/web/` → `static/`.

After publishing, restart/reload Django and open `http://localhost:8000/`.

Optional override example:

```bash
EXTRA_DART_DEFINES='--dart-define=GOOGLE_CLIENT_ID=...' ./scripts/publish_frontend.sh
```

#### Local frontend iteration without publishing

If you only need to try UI changes against the local Django API without updating `static/`:

```bash
cd Pastor-AI-main/flutter_application_1
/opt/flutter/bin/flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=USE_MOCK_AUTH=false
cd build/web && python3 -m http.server 8080
```

Then open `http://localhost:8080`. Cross-origin `:8080` → `:8000` works because Django sets
`CORS_ALLOW_ALL_ORIGINS = True`.

Flutter SDK is at `/opt/flutter` (add `/opt/flutter/bin` to PATH). `pubspec.yaml`
was completed with the dependencies the source already imports (`provider`,
`shared_preferences`, `flutter_secure_storage`, and `google_sign_in` pinned to `^6`
because `auth_service.dart` uses the v6 `GoogleSignIn().signIn()` API).

### Google Sign-In

Flutter already has the Google buttons and posts `{ "id_token" }` to `POST /api/auth/google/`.
Django verifies the token with `google-auth` and issues a DRF `Token`.

Required configuration (same Web client ID on both sides):
1. Create an OAuth 2.0 **Web** client in Google Cloud Console.
2. Add Authorized JavaScript origins for the hosts you use (`http://localhost:8000`, etc.).
3. Export `GOOGLE_CLIENT_ID` for Django (`export GOOGLE_CLIENT_ID=....apps.googleusercontent.com`) before `runserver`.
4. Publish the frontend with the same ID: `GOOGLE_CLIENT_ID=... ./scripts/publish_frontend.sh`.

Without `GOOGLE_CLIENT_ID`, the UI reports Google Sign-In as unconfigured and the API returns 503.

### Lint / test

- Backend: `python manage.py check` and `python manage.py test` (from `Pastor-AI-main/`, venv active).
- Frontend: `flutter analyze` and `flutter test` (from `flutter_application_1/`).
