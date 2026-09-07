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

Open `/admin/` on the Django host. Default credentials (created automatically by `install.sh` / `start.sh`):

- **Username:** `admin`
- **Password:** `admin123`

Override with `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD` in `config.env` if needed.

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

## Stripe Premium (Embedded Checkout)

Premium subscriptions use **Stripe Embedded Checkout**. Keys live in `tokens.env` and are applied into `config.env` by `apply-tokens.sh`.

**First-time setup**

1. Open Stripe in **Test mode** and copy keys from [API keys](https://dashboard.stripe.com/test/apikeys).
2. Set in `tokens.env` then `bash /workspace/pastor-ai/apply-tokens.sh --validate-stripe`:

```bash
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
BILLING_MOCK_CHECKOUT=false
# Optional:
# STRIPE_WEBHOOK_SECRET=whsec_...
# PUBLIC_APP_URL=https://your-public-domain
# STRIPE_PRICE_MONTHLY=price_...
# STRIPE_PRICE_YEARLY=price_...
```

3. Start the stack:

```bash
bash /workspace/pastor-ai/start.sh
# Local auth + billing only (no vLLM / Qdrant):
# bash /workspace/pastor-ai/scripts/start-minimal.sh
```

4. Smoke-test: sign in → **Subscribe** → Embedded Checkout. Test card `4242 4242 4242 4242` (any future expiry / CVC / ZIP).

Optional local webhook forwarding:

```bash
stripe listen --forward-to localhost:8000/api/billing/webhook/
# Paste the printed whsec_… into tokens.env as STRIPE_WEBHOOK_SECRET, then:
bash /workspace/pastor-ai/apply-tokens.sh --restart
```

Production webhook endpoint: `POST https://your-domain/api/billing/webhook/`. Without a webhook, Premium still unlocks via checkout session confirmation, or **Subscribe → Already subscribed? Restore access**.

**Subsequent times** (keys already in `tokens.env`):

```bash
bash /workspace/pastor-ai/apply-tokens.sh --restart
# or local billing-only:
# bash /workspace/pastor-ai/scripts/start-minimal.sh
```

`start-minimal.sh` re-applies `tokens.env` when present. After editing keys (rotate, add webhook secret, set `PUBLIC_APP_URL`), run `apply-tokens.sh` again before restarting. If a Stripe payment succeeded but Premium did not unlock, use **Subscribe → Already subscribed? Restore access** while signed in with the same email used at checkout.

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

