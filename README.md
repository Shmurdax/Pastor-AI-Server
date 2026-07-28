# Pastor-AI-Server (production RunPod stack)

Christian theology chat: **Flutter web UI** + **Django** + **Qdrant RAG** + **vLLM (Qwen2.5-14B AWQ + Christian LoRA)**.

## One-command install (RunPod / Ubuntu GPU host)

```bash
export HF_TOKEN=hf_your_token_here   # needs access to apophaticai/qwen2.5-14b-christianai-v1
bash <(curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh)
```

Or clone first:

```bash
git clone https://github.com/GavWrecker/Pastor-AI-Server.git
cd Pastor-AI-Server
cp tokens.env.example tokens.env   # paste HF_TOKEN (and optional ngrok/github)
bash install.sh
```

`install.sh` will:

1. Install system packages (git, Python, Postgres, screen, …)
2. Install Docker + NVIDIA Container Toolkit when possible (falls back to **native** if Docker cannot run — current RunPod production path)
3. Sync `backend/` + `frontend/` onto `/workspace/pastor-ai`
4. Create Python venv with torch cu128 + **vLLM 0.8.5**
5. Download the Christian LoRA from Hugging Face
6. Migrate Django, start Qdrant / vLLM / Django / Cloudflare tunnel
7. Ingest `backend/app/converted_markdown` into Qdrant `sermon_brain`

## After pod restart / migrate

Set the RunPod **Container Start Command** (one-time) so the stack auto-starts:

```bash
bash -lc 'nohup bash /workspace/pastor-ai/onboot.sh >>/workspace/pastor-ai/logs/onboot.log 2>&1 & exec /start.sh'
```

Or manually:

```bash
bash /workspace/pastor-ai/start.sh
```

Postgres app data is snapshotted to the network volume (`postgres_data/ai_db.dump`); Qdrant lives in `qdrant_storage/`. `start.sh` restores the dump when needed and always runs Django migrations before serving traffic.

## Django admin

Open `/admin/` on the Django host. Default credentials (created automatically by `install.sh` / `start.sh`):

- **Username:** `admin`
- **Password:** `admin123`

Override with `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD` in `config.env` if needed.

## Tokens

```bash
nano /workspace/pastor-ai/tokens.env
bash /workspace/pastor-ai/apply-tokens.sh --restart
```

## Manual RAG re-ingest

```bash
bash /workspace/pastor-ai/ingest_sermons.sh
```

## Website crawl → RAG (thenordins.org + sister ministries)

Allowlisted crawl of public ministry pages, teaching media, and book/resource descriptions into Qdrant `sermon_brain` (excludes cart/checkout/login/admin and socials):

```bash
bash /workspace/pastor-ai/crawl_websites.sh
# or: cd /workspace/pastor-ai/backend/app && python manage.py crawl_websites
```

Admin UI: **Website Crawl → RAG** under the Django admin Core section.

## Stack (current production)

| Component | Detail |
|-----------|--------|
| LLM | `Qwen/Qwen2.5-14B-Instruct-AWQ` + LoRA `apophaticai/qwen2.5-14b-christianai-v1` (served as `christianai`) |
| API | Django/gunicorn `:8000` |
| Vectors | Qdrant `:6333` collection `sermon_brain` |
| UI | Flutter web build in `frontend/` |
| Tunnel | Cloudflare quick tunnel (default) |

See [RUNPOD.md](RUNPOD.md) for troubleshooting (ghost VRAM, ports, tokens).


## Frontend (Flutter)

Source lives in `frontend/`. Production Django serves the **web build**:

```bash
cd frontend && flutter build web --release --dart-define=API_BASE_URL=
# Optional: --dart-define=USE_MOCK_AUTH=false --dart-define=USE_MOCK_PRAYER=false
```

`start.sh` / `install.sh` automatically prefer `frontend/build/web` when present.
Same-origin API calls (`API_BASE_URL` empty) talk to Django on the ngrok/public URL.
