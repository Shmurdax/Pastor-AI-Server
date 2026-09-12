# Pastor-AI on RunPod

## Layout on the network volume

```
/workspace/pastor-ai/
  backend/              # Django (server-dev)
  frontend/             # Flutter web build
  christianai-lora/     # HF LoRA download (not in git)
  venv/
  hf_cache/
  qdrant_storage/
  config.env            # generated / secrets
  tokens.env            # paste tokens here
  install.sh start.sh persist_runtime.sh apply-tokens.sh ingest_sermons.sh

/workspace/persistent/          # survives container recreate + install.sh rsync
  postgres/ai_db.dump           # ingested document catalog (pg_dump)
  postgres/ingested_catalog.dump # git seed catalog (empty-volume fallback)
  uploads/admin_ingestion/      # original sermon PDFs for library links
  uploads/admin_video_ingestion/ # original sermon videos + Whisper transcript sidecars
  boot/                         # onboot.sh, start.sh, gpu_runtime.sh, vllm_runtime.sh, persist_runtime.sh
  onboot.sh                     # fallback RunPod start command
  config.env / tokens.env       # mirrored secrets (mode 600; not in git)
  bin/cloudflared bin/qdrant    # binaries restored into /usr/local/bin and /workspace/bin
  .cloudflared/tunnel.token     # named Cloudflare tunnel token
  whisper/                      # Whisper model cache
```

Live Postgres cannot use this volume as `PGDATA` (the volume cannot `chown` to user `postgres`). `start.sh` / `install.sh` keep the cluster on local disk, dump/restore `ai_db` onto `/workspace/persistent/postgres/ai_db.dump`, and symlink `backend/app/uploads/admin_ingestion` to the persistent PDF folder. After a pod stop/start or remigration, `onboot.sh` restores packages, the tunnel, boot scripts, and those bindings.

## Fresh install

```bash
export HF_TOKEN=hf_...
bash <(curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh)
```

## Restart after stop/start or remigration

Set the RunPod **container start command** to:

```bash
bash /workspace/pastor-ai/onboot.sh || bash /workspace/persistent/onboot.sh
```

`onboot.sh` reinstalls `screen` / Postgres / ffmpeg / LibreOffice, restores
`cloudflared` + the named-tunnel token, restores boot scripts and `config.env`
from `/workspace/persistent` if the pastor-ai tree was wiped, then runs
`start.sh` and **stays running** (`sleep infinity`). `start.sh` returns after
launching screens; if it is the container PID, RunPod restart-loops every
~20s. That brings back Django, Qdrant, vLLM when this host is a GPU pod
(detecting the current MIG UUID — do not hardcode it), the Whisper video
worker, and the public hostname. On a CPU web pod, local vLLM is skipped
and Django calls the RunPod Serverless OpenAI URL instead.

`start.sh` also copies `onboot.sh`, `start.sh`, `gpu_runtime.sh`, `vllm_runtime.sh`, and secrets
into `/workspace/persistent/boot` so the next remigration has a fallback.

Keep the network volume attached at `/workspace`. Sermon PDFs, videos,
transcripts, the Postgres dump, Whisper cache, Qdrant storage, venv, and LoRA
live there and survive container recreate.

```bash
bash /workspace/pastor-ai/onboot.sh
```

## Common issues

### Ghost GPU memory (~19GB used, no processes)
Fully **Stop** the pod in RunPod (not just restart), wait 30s, Start, then `start.sh`.

### Port 8001
RunPod host nginx often binds **8001**. vLLM uses **8010**.

### Docker
Some RunPod images cannot run a Docker daemon (iptables/netfilter). `install.sh` still installs Docker when possible, then uses the **native** path that matches production.

### Chat “Could not connect”
The Flutter UI maps **any** `/api/chat/` exception to `Error: Could not connect to the server.` The homepage can still load. Usual causes on the CPU web pod:

1. **vLLM serverless worker never becomes healthy.** Two current traps:
   - RunPod’s `ADA_48_PRO` pool includes `NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 2g.48gb`. `runpod/worker-v1-vllm` CUDA 12 cannot start on those slices. Pin the endpoint to `AMPERE_48` + `ADA_48_PRO` minus that MIG type (`create_runpod_endpoints.sh` does this after create). Use 48GB Ampere/Ada cards only — 24GB A5000/L4/4090 OOM with 14B AWQ + LoRA.
   - `LORA_MODULES` must be a **single JSON object** (`{"name":"christianai","path":"apophaticai/qwen2.5-14b-christianai-v1"}`), not a JSON array. worker-v1-vllm v2.26 forwards the env as one `--lora-modules` argument, and current vLLM rejects a list with `LoRAModulePath() argument after ** must be a mapping, not list`.
2. **Gunicorn missing `RUNPOD_API_KEY`.** RunPod Serverless then returns `401 invalid api key`. `get_chat_llm` loads `config.env` / `tokens.env` so this does not depend on the worker process environment.
3. Empty `PUBLIC_API_KEY` gate or Postgres down. Keep `PUBLIC_API_KEY=` empty for the public Flutter UI, and ensure Postgres is running (`start.sh` reinstalls/starts it if needed).

### Account create / Google Sign-In fails (403 or disabled button)
1. **403 on Create account / Google.** Auth APIs must not use Django session CSRF. After pulling a fix that sets `authentication_classes = []` on register/login/google, restart Django (`bash start.sh` or `deploy_update.sh`).
2. **Google button disabled / “not configured”.** Set `GOOGLE_CLIENT_ID` in `tokens.env`, run `bash apply-tokens.sh`, then rebuild Flutter (`bash deploy_update.sh` or `flutter build web --release --dart-define=API_BASE_URL=`). The web UI also loads the client ID from `GET /api/auth/config/` at runtime once rebuilt.
3. **Google popup / origin errors.** In Google Cloud Console → Credentials → your OAuth **Web** client, add the public site origin (Cloudflare tunnel or custom domain) under **Authorized JavaScript origins** (scheme + host only, no path). COOP is already `same-origin-allow-popups` for GIS.

### Private LoRA 404
`HF_TOKEN` must belong to an account that can open
[apophaticai/qwen2.5-14b-christianai-v1](https://huggingface.co/apophaticai/qwen2.5-14b-christianai-v1)
without a 404. The token currently on the worker (`gjonesar`) cannot; the
vLLM endpoint stays unhealthy and chat hangs after auth.

**How to get a working token**

1. Log into Hugging Face as an `apophaticai` org member (or the user who
   owns that private repo).
2. Confirm the model page loads (not 404).
3. Create a **Read** token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).
4. Put it in `tokens.env` as `HF_TOKEN=hf_...` and also on the **vLLM
   Serverless template** (`HF_TOKEN`). Django on the CPU pod does not need it.
5. Or: model page → Settings → Collaborators → add `gjonesar`, then the
   existing token can download the LoRA.

On a CPU web pod the token is only required on the **serverless worker**, not on Django.

### Chat 401 / empty model list after moving vLLM to Serverless
Django must send your RunPod API key. Set `RUNPOD_API_KEY` and
`RUNPOD_VLLM_ENDPOINT_ID` in `tokens.env`, then `bash apply-tokens.sh --restart`.
Check: `bash /workspace/pastor-ai/scripts/check_vllm.sh` and
`bash /workspace/pastor-ai/scripts/check_whisper.sh`

## Create the two serverless GPU endpoints

You need **two** endpoints, not one. Chat (14B vLLM + LoRA) and sermon
transcription (Faster-Whisper) cannot share a worker — Whisper would steal
the 14B model's VRAM.

| Endpoint | Image | GPU | What Django calls |
|----------|--------|-----|-------------------|
| Chat vLLM | `runpod/worker-v1-vllm` | 24GB+ (A5000 / L4 / 4090) | `/openai/v1/chat/completions` |
| Whisper | `runpod/ai-api-faster-whisper` | 8–16GB (T4 / A4000 / L4) | `/runsync` |

Get an API key from [RunPod API keys](https://www.runpod.io/console/user/settings).
The Hugging Face token must be able to read
`apophaticai/qwen2.5-14b-christianai-v1` (vLLM worker only).

### Option A — one command (REST API)

Run this on any machine with `curl` and `python3` (your laptop is fine).
It creates two **serverless templates** and two **endpoints**, then prints
IDs for `tokens.env`:

```bash
export RUNPOD_API_KEY=rpa_...
export HF_TOKEN=hf_...

bash serverless/create_runpod_endpoints.sh --write-tokens
```

To tune an **existing** chat endpoint (idle 15 min, host cache, eager boot):

```bash
bash serverless/apply_vllm_coldstart.sh
```

`--write-tokens` upserts into `tokens.env`:

```
CPU_ONLY=1
VLLM_MODE=serverless
RUNPOD_VLLM_ENDPOINT_ID=...
WHISPER_MODE=serverless
RUNPOD_WHISPER_ENDPOINT_ID=...
RUNPOD_API_KEY=rpa_...
```

Preview payloads without creating anything: `bash serverless/create_runpod_endpoints.sh --dry-run`.
List what you already have: `bash serverless/create_runpod_endpoints.sh --list`.

Then on the CPU web pod:

```bash
bash apply-tokens.sh --restart
bash scripts/check_vllm.sh
bash scripts/check_whisper.sh
```

First smoke test on each endpoint can take **1–3 minutes** (worker pull + model load).

### Option B — RunPod console (Hub)

**Chat (endpoint A)**

1. Open [worker-vllm Hub](https://console.runpod.io/hub/runpod-workers/worker-vllm) → **Deploy**.
2. GPU: **48GB Ampere/Ada** (A40 / A6000 / L40S / 6000 Ada). Active workers `0`, max workers `1`, idle timeout `900` seconds, execution timeout `600` seconds, **FlashBoot** on, scaler delay `1` second. Exclude Blackwell MIG 2g.48gb from `ADA_48_PRO`.
3. Paste env from [`serverless/vllm.env.example`](serverless/vllm.env.example).
   Set `HF_TOKEN` to a token that can read the private Christian LoRA.
   Set the endpoint **Model** field to `Qwen/Qwen2.5-14B-Instruct-AWQ` so RunPod can cache the base weights.
4. Do **not** attach a user network volume for chat. Set `DOWNLOAD_DIR` and
   `HF_HOME` to `/runpod-volume/huggingface-cache` so the worker uses RunPod's
   host-side cached `MODEL_NAME`. A user volume pins one DC and workers
   sit `THROTTLED` waiting for that region's 48GB cards.
5. Copy the **endpoint ID** (the serverless id, not a GPU pod id).

**Whisper (endpoint B)**

1. Open [worker-faster_whisper Hub](https://console.runpod.io/hub/runpod-workers/worker-faster_whisper) → **Deploy**.
2. GPU: **8–16GB** (T4 / L4 / A4000). Do **not** reuse the vLLM endpoint.
3. Active workers `0`, max workers `1`, idle timeout `60–120` seconds,
   execution timeout `600` seconds. See [`serverless/whisper.env.example`](serverless/whisper.env.example).
4. Copy that endpoint ID into `RUNPOD_WHISPER_ENDPOINT_ID`.

Paste both IDs plus `RUNPOD_API_KEY` into `tokens.env` on the CPU pod, then
`bash apply-tokens.sh --restart`.

## Production CPU pod

The always-on GPU pod (`6pf27d8080515x`, `christian-ai-prd`) was **terminated**.
Production is a CPU-only Secure Cloud pod on the same network volume
(`int0elzo4l` at `/workspace`):

| | |
|--|--|
| Pod id | `rv1ttmvj5xy02k` |
| Name | `christian-ai-prd` |
| Git channel | `master` (`/workspace/pastor-ai/.git_channel`) |
| Flavor | `cpu3g` (2 vCPU / 8 GB, **no GPU**) |
| Cost | **$0.08/hr** (the old GPU pod was $0.59/hr) |
| SSH | `ssh rv1ttmvj5xy02k-644120e4@ssh.runpod.io -i ~/.ssh/id_ed25519` |

Dev replica (`christian-ai-dev`, pod `msu5t1sxykgvpj`, volume `7rrkr3iexe` in US-IL-1) tracks Git **`development`**. All new code lands there first. Promote with `bash scripts/promote_to_master.sh`, then `bash deploy_update.sh` on production.

The SSH username is `{podHostId}@ssh.runpod.io`, not `{podId}-644122c4`.
If proxy SSH says `container not found`, read `machine.podHostId` from the
RunPod GraphQL `myself { pods { machine { podHostId } } }` query and use that.

Serverless GPU endpoints (`pastor-ai-chat-vllm`, `pastor-ai-whisper`) keep
`workersMin = 0`, so they bill only while a request is running (plus idle
timeout), not 24/7. Chat cold starts are shortened by a 15-minute idle
timeout, `scalerValue=1`, RunPod host-cached `MODEL_NAME`, homepage
`/api/chat/warmup/`, `ENFORCE_EAGER`, and SSE keepalives.
Whisper stays `workersMin = 0`.

## CPU web pod + serverless vLLM

Keep Postgres, Qdrant, Django, Cloudflare, and ffmpeg on a **CPU pod**.
Chat hits RunPod Serverless OpenAI:

```
https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1
```

### 1) Create the GPU endpoints

Use [Create the two serverless GPU endpoints](#create-the-two-serverless-gpu-endpoints) above.

### 2) Install Pastor-AI on a CPU pod

Same network volume layout as today (`/workspace` + `/workspace/persistent`).
Do **not** install vLLM on this machine:

```bash
export CPU_ONLY=1
export VLLM_MODE=serverless
export RUNPOD_VLLM_ENDPOINT_ID=your_vllm_endpoint_id
export WHISPER_MODE=serverless
export RUNPOD_WHISPER_ENDPOINT_ID=your_whisper_endpoint_id
export RUNPOD_API_KEY=rpa_...
SKIP_INGEST=1 bash install.sh
```

Or put those keys in `tokens.env` and run `bash apply-tokens.sh --restart`.
`start.sh` will skip `screen` session `vllm` and point Gunicorn at the
serverless OpenAI base URL. MiniLM embeddings stay on the CPU pod. Video
ingest still runs ffmpeg locally, then calls a **second** serverless GPU
endpoint for Whisper (do not put Whisper on the 14B vLLM worker).

### 2b) Serverless Whisper for video ingest

Same setup as [Create the two serverless GPU endpoints](#create-the-two-serverless-gpu-endpoints)
(Hub or `create_runpod_endpoints.sh`). Smoke test:

```bash
bash /workspace/pastor-ai/scripts/check_whisper.sh
```

A 20-minute sermon is typically **about 1–3 minutes** of GPU Whisper time
(plus a few seconds of local ffmpeg + MiniLM). Without this endpoint the
CPU pod falls back to local Whisper (~10–15 minutes).

Long audio is compressed to mp3 on the CPU pod. If the payload is still
too large for one `/runsync` request, ingest splits it into overlapping
chunks and stitches timestamps.

### 3) What still runs on the CPU pod

| Service | Where |
|---------|--------|
| Django / Flutter web | CPU pod `:8000` |
| Postgres + Qdrant | CPU pod |
| ffmpeg audio extract + MiniLM embeddings | CPU pod |
| Cloudflare tunnel | CPU pod |
| Chat LLM (vLLM + Christian LoRA) | Serverless GPU endpoint A |
| Whisper video ingest | Serverless GPU endpoint B |

### Cost / UX tradeoff

A always-on GPU pod bills even at 3am. Serverless with `active workers = 0`
only bills while a worker is up, including model load. First chat after the
idle timeout can still take **1–3 minutes** if weights are not cached.

Keep `workersMin = 0` unless you explicitly want a 24/7 GPU bill. Speed the
first request instead:

1. **Warmup** — opening the homepage POSTs `/api/chat/warmup/`, which GETs
   `{vLLM}/models` so RunPod starts a worker while the user types.
2. **Idle timeout 15 minutes** (`idleTimeout=900`) so a second visit after a
   short gap reuses the same worker.
3. **`scalerValue=1`** so scale-up waits 1 second, not 4.
4. **RunPod cached model** `Qwen/Qwen2.5-14B-Instruct-AWQ` on the **host
   cache** (`DOWNLOAD_DIR=/runpod-volume/huggingface-cache`) plus
   `ENFORCE_EAGER=true` so vLLM skips CUDA-graph capture. Do **not** attach
   a user network volume for chat: it pins the endpoint to one DC (workers
   sit `THROTTLED` waiting for that region's 48GB GPUs) and shadows the
   faster host cache. Leave CPU volume `int0elzo4l` (US-NE-1) off serverless.
5. **SSE keepalives** every 8 seconds so Cloudflare does not drop the stream
   during MiniLM + GPU boot.

Whisper can remain at 0. Setting `workersMin = 1` is the instant-chat option
and costs roughly a dedicated 48GB GPU around the clock.

Streaming still works: LangChain `ChatOpenAI.stream` hits the worker's
OpenAI SSE path (`RAW_OPENAI_OUTPUT=1`). Django also sends SSE keepalives
every few seconds while waiting so Cloudflare does not drop the stream.

## Skip ingest (faster install)

```bash
SKIP_INGEST=1 bash install.sh
# later:
bash /workspace/pastor-ai/ingest_sermons.sh
```
