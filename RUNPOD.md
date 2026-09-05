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
Usually empty `PUBLIC_API_KEY` gate or Postgres down. Keep `PUBLIC_API_KEY=` empty for the public Flutter UI, and ensure Postgres is running (`start.sh` reinstalls/starts it if needed).

### Private LoRA 404
`HF_TOKEN` must belong to an account with access to `apophaticai/qwen2.5-14b-christianai-v1`.
On a CPU web pod the token is only required on the **serverless worker**, not on Django.

### Chat 401 / empty model list after moving vLLM to Serverless
Django must send your RunPod API key. Set `RUNPOD_API_KEY` and
`RUNPOD_VLLM_ENDPOINT_ID` in `tokens.env`, then `bash apply-tokens.sh --restart`.
Check: `bash /workspace/pastor-ai/scripts/check_vllm.sh`

## CPU web pod + serverless vLLM

Yes — keep Postgres, Qdrant, Django, Cloudflare, and Whisper on a **CPU pod**,
and run only the 14B chat model on **RunPod Serverless**. Django already speaks
OpenAI `/v1/chat/completions` (including SSE streaming). The serverless vLLM
worker exposes the same API at:

```
https://api.runpod.ai/v2/<ENDPOINT_ID>/openai/v1
```

### 1) Create the serverless endpoint

1. In RunPod: **Hub → worker-vllm → Deploy** (or Serverless → New Endpoint).
2. Pick a **24GB+** GPU. 14B AWQ + LoRA + 8k context needs ~20GB+.
3. Paste env vars from [`serverless/vllm.env.example`](serverless/vllm.env.example).
   `HF_TOKEN` must be able to read `apophaticai/qwen2.5-14b-christianai-v1`.
4. Attach a network volume at `/runpod-volume` so weights survive scale-to-zero.
5. Worker settings that actually save money without wrecking chat:
   - **Active workers:** `0` (scale to zero when idle)
   - **Max workers:** `1`
   - **Idle timeout:** `120–300` seconds (default ~5s reloads the 14B model after every pause)
   - **Execution timeout:** `600` seconds (cold start + long pastoral replies)
   - **FlashBoot:** on
6. Copy the endpoint ID (not a GPU pod ID).

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

1. In RunPod Hub deploy **worker-faster_whisper** (not worker-vllm).
2. Use a small GPU (T4 / L4 / 8–16GB). Whisper `base` does not need 24GB.
3. Active workers `0`, max workers `1`, idle timeout `60–120s`,
   execution timeout `600s`. See [`serverless/whisper.env.example`](serverless/whisper.env.example).
4. Set on the CPU pod (same `RUNPOD_API_KEY` as chat is fine):

```bash
export WHISPER_MODE=serverless
export RUNPOD_WHISPER_ENDPOINT_ID=your_whisper_endpoint_id
bash apply-tokens.sh --restart
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
idle timeout can take **1–3 minutes** (cold start). Consecutive messages
inside the idle window are fast. If overnight silence is fine but daytime
chat must be instant, set **active workers = 1** (that is close to GPU-pod
pricing) or a longer idle timeout.

Streaming still works: LangChain `ChatOpenAI.stream` hits the worker's
OpenAI SSE path (`RAW_OPENAI_OUTPUT=1`).

## Skip ingest (faster install)

```bash
SKIP_INGEST=1 bash install.sh
# later:
bash /workspace/pastor-ai/ingest_sermons.sh
```
