# Pastor-AI-Server (production RunPod stack)

Christian theology chat: **Flutter web UI** + **Django** + **Qdrant RAG** + **vLLM (Qwen2.5-14B AWQ + Christian LoRA)**.

**Working with the live site (users, sermons, subscriptions, prayer, events)?** Start with the [Operator and Staff Guide](docs/STAFF_AND_OPERATOR_GUIDE.md). This README is the install / restart path.

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
4. Create Python venv with **vLLM** (CUDA 12.8 on Ada/Hopper, CUDA 12.9+ on Blackwell / RTX PRO 6000 MIG)
5. Download the Christian LoRA from Hugging Face
6. Migrate Django, start Qdrant / vLLM / Django / Cloudflare tunnel
7. Ingest `backend/app/converted_markdown` into Qdrant `sermon_brain`

## After pod restart

```bash
bash /workspace/pastor-ai/start.sh
```

## Django admin

The staff control panel is **not** at `/admin/` (that path returns 404 so visitors cannot find it). Use the private path stored as `DJANGO_ADMIN_URL` in `config.env`. `start.sh` prints `Admin (private — share only with staff): https://…/<path>/`. Share that URL only with people who should have access.

`install.sh` generates a random `DJANGO_ADMIN_URL` and a random `DJANGO_SUPERUSER_PASSWORD` on first install and writes them to `config.env` (mode 600). There is no published default password. To rotate later:

```bash
# on the pod
nano /workspace/pastor-ai/config.env   # set DJANGO_SUPERUSER_PASSWORD and optionally DJANGO_ADMIN_URL
# add: DJANGO_SUPERUSER_RESET_PASSWORD=1
bash /workspace/pastor-ai/start.sh
```

**Document Ingestion** stores original PDFs on the persistent volume (`/workspace/persistent/uploads/admin_ingestion` on RunPod; local default `uploads/admin_ingestion`) so sermon library links survive pod restarts. Extracted text is run through structured cleanup before chunking into Qdrant so page numbers, repeating headers/footers, and boilerplate do not confuse retrieval.

**Video Ingestion** (alongside Document Ingestion in Django admin) accepts common video containers, transcribes them with OpenAI Whisper on CPU (timestamps kept for citation), then normalizes the script to drop fillers, channel CTAs, and isolated talk that is not about Christianity, the Bible, or social ideas and issues. Original videos persist at `/workspace/persistent/uploads/admin_video_ingestion`.

```bash
# Preview cleanup on sample / extracted text (does not modify PDFs)
bash /workspace/pastor-ai/cleanup_ingested_text.sh --demo
python manage.py cleanup_ingested_text --file /path/to/extracted.txt
python manage.py ingest_videos /path/to/sermon.mp4
```

## Tokens

```bash
nano /workspace/pastor-ai/tokens.env
bash /workspace/pastor-ai/apply-tokens.sh --restart
```

## Manual RAG re-ingest

```bash
bash /workspace/pastor-ai/ingest_sermons.sh
```

## Website scraping → RAG (thenordins.org + sister ministries)

Allowlisted crawl of public ministry pages, teaching media, and book/resource descriptions into Qdrant `sermon_brain` (excludes cart/checkout/login/admin and socials):

```bash
bash /workspace/pastor-ai/crawl_websites.sh
# or: cd /workspace/pastor-ai/backend/app && python manage.py crawl_websites
```

Admin UI: **Website Scraping** under the Django admin Content tools section.

## Stack (current production)

| Component | Detail |
|-----------|--------|
| LLM | `Qwen/Qwen2.5-14B-Instruct-AWQ` + LoRA `apophaticai/qwen2.5-14b-christianai-v1` (served as `christianai`) — local GPU **or** [RunPod Serverless](RUNPOD.md#cpu-web-pod--serverless-vllm) |
| Whisper | Local CUDA leftover, local CPU, **or** a separate [serverless Faster-Whisper](RUNPOD.md#2b-serverless-whisper-for-video-ingest) GPU endpoint |
| API | Django/gunicorn `:8000` (CPU) |
| Vectors | Qdrant `:6333` collection `sermon_brain` |
| DB | Postgres `ai_db` |
| UI | Flutter web build in `frontend/` |
| Tunnel | Cloudflare quick tunnel (default) |

See [RUNPOD.md](RUNPOD.md) to create the two serverless GPU endpoints (chat vLLM + Faster-Whisper) and keep Django/Postgres/Qdrant on a cheaper CPU pod:

```bash
export RUNPOD_API_KEY=rpa_... HF_TOKEN=hf_...
bash serverless/create_runpod_endpoints.sh --write-tokens
bash apply-tokens.sh --restart
```


## Frontend (Flutter)

Source lives in `frontend/`. Production Django serves the **web build**:

```bash
cd frontend && flutter build web --release --dart-define=API_BASE_URL=
# Optional: --dart-define=USE_MOCK_AUTH=false --dart-define=USE_MOCK_PRAYER=false
```

`start.sh` / `install.sh` automatically prefer `frontend/build/web` when present.
Same-origin API calls (`API_BASE_URL` empty) talk to Django on the ngrok/public URL.

## Before production

On the CPU web pod:

```bash
bash /workspace/pastor-ai/scripts/check_production_security.sh
```

Set `DJANGO_DEBUG=false`, `DJANGO_CORS_ALLOW_ALL_ORIGINS=false`, secure cookies, a unique `DJANGO_ADMIN_URL`, a 12+ character staff password with `DJANGO_SUPERUSER_RESET_PASSWORD=1`, `BILLING_MOCK_CHECKOUT=false`, and real Stripe keys. Restart with `bash /workspace/pastor-ai/start.sh`. Rotate the RunPod API key if it has ever appeared in `ps` output.

## Vimeo Daily Devotionals

Media gallery videos sync from a **Vimeo Folder** (unlisted videos supported).

Example folder: `https://vimeo.com/user/21759939/folder/24205069`

1. Keep devotionals in that folder; allow embedding on each video (add your site domain if required).
2. Create an API token with `public` + `private` scopes (token user must be able to read the folder).
3. Set in `tokens.env` then `bash apply-tokens.sh`:

```bash
VIMEO_ACCESS_TOKEN=...
VIMEO_FOLDER_ID=24205069
VIMEO_USER_ID=21759939
VIMEO_FREE_PREVIEW_ID=...      # optional: one free intro video id
```

4. Sync:

```bash
cd backend/app && python manage.py sync_vimeo_media
```

`deploy_update.sh` runs this sync after migrate when the token and folder id are set.
Public catalog: `GET /api/media/`.

