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
| Django | REST API (`/api/chat/`, `/api/auth/*`) + serves committed `static/` build | `source venv/bin/activate && python manage.py runserver 0.0.0.0:8000` | 8000 |
| Flutter web (dev) | Current frontend source, built for local backend | see "Running the current frontend" | 8080 |

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

### Running the current frontend (`flutter_application_1`)

The committed `static/` build is STALE: it is an older UI (no auth) hardwired to a
dead ngrok API URL, so it cannot talk to a local backend. To exercise the current
frontend source against the local Django API, build and serve it separately:

```
cd Pastor-AI-main/flutter_application_1
/opt/flutter/bin/flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=USE_MOCK_AUTH=false
cd build/web && python3 -m http.server 8080
```

Then open http://localhost:8080. API base URL is a compile-time
`String.fromEnvironment('API_BASE_URL')` (empty = same-origin). `USE_MOCK_AUTH`
defaults to `true`, so pass `--dart-define=USE_MOCK_AUTH=false` to hit the real
Django auth endpoints. Cross-origin :8080 -> :8000 works because Django sets
`CORS_ALLOW_ALL_ORIGINS = True`.

Flutter SDK is at `/opt/flutter` (add `/opt/flutter/bin` to PATH). `pubspec.yaml`
was completed with the dependencies the source already imports (`provider`,
`shared_preferences`, `flutter_secure_storage`, and `google_sign_in` pinned to `^6`
because `auth_service.dart` uses the v6 `GoogleSignIn().signIn()` API).

### Lint / test

- Backend: `python manage.py check` and `python manage.py test` (from `Pastor-AI-main/`, venv active).
- Frontend: `flutter analyze` and `flutter test` (from `flutter_application_1/`).
