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
  boot/                         # onboot.sh, start.sh, gpu_runtime.sh, persist_runtime.sh
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
`start.sh`. That brings back Django, Qdrant, vLLM (detecting the current MIG
UUID — do not hardcode it), the Whisper video worker, and the public hostname.

`start.sh` also copies `onboot.sh`, `start.sh`, `gpu_runtime.sh`, and secrets
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

## Skip ingest (faster install)

```bash
SKIP_INGEST=1 bash install.sh
# later:
bash /workspace/pastor-ai/ingest_sermons.sh
```
