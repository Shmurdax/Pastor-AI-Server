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
  uploads/admin_ingestion/      # original sermon PDFs for library links
```

Live Postgres cannot use this volume as `PGDATA` (the volume cannot `chown` to user `postgres`). `start.sh` / `install.sh` keep the cluster on local disk, dump/restore `ai_db` onto `/workspace/persistent/postgres/ai_db.dump`, and symlink `backend/app/uploads/admin_ingestion` to the persistent PDF folder. Re-run `start.sh` after a pod stop/start or a full remigration so those bindings are restored.

## Fresh install

```bash
export HF_TOKEN=hf_...
bash <(curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh)
```

## Restart after stop/start

```bash
bash /workspace/pastor-ai/start.sh
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
