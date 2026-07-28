# Pastor-AI on RunPod

## Layout on the network volume

```
/workspace/pastor-ai/
  backend/              # Django
  frontend/             # Flutter web build
  christianai-lora/     # HF LoRA download (not in git)
  venv/
  hf_cache/
  qdrant_storage/       # persistent vectors
  postgres_data/        # pg_dump snapshots (ai_db.dump) — survives pod migrate
  config.env            # generated / secrets
  tokens.env            # paste tokens here
  onboot.sh start.sh install.sh …
  runpod-docker-command.txt
```

## Required: auto-start after migrate / new pod

Set the pod **Container Start Command** to (also in `runpod-docker-command.txt`):

```bash
bash -lc 'nohup bash /workspace/pastor-ai/onboot.sh >>/workspace/pastor-ai/logs/onboot.log 2>&1 & exec /start.sh'
```

`onboot.sh` waits for the GPU, then runs `start.sh`, which:

1. Reinstalls Postgres packages if missing (cluster stays on local disk — RunPod volumes cannot `chown` for Postgres)
2. **Restores `postgres_data/ai_db.dump` from the network volume** when app tables are missing
3. Runs `migrate` + `ensure_superuser` before gunicorn
4. Saves a fresh dump and refreshes it every 5 minutes
5. Starts Qdrant, vLLM, Django, Cloudflare tunnel

Without this start command, a full container recreate only brings up Jupyter/SSH — Pastor-AI stays down and Postgres is empty.

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

### Ghost GPU memory (~19GB used / 100% util, no processes)
Fully **Stop** the pod in RunPod (not just restart), wait 30s, Start. With the Container Start Command above, `onboot.sh` brings the stack back up automatically.

### Chat “Could not connect”
Usually means **vLLM is still loading** or **was down**. Check:

```bash
curl -s http://127.0.0.1:8010/v1/models
tail -f /workspace/pastor-ai/logs/vllm.log
tail -f /workspace/pastor-ai/logs/django.log
```

Also confirm Postgres tables exist (after an old boot without volume Postgres they would not):

```bash
bash /workspace/pastor-ai/start.sh   # migrate is part of Django start
```

Embeddings run on **CPU** so chat retrieval does not fight vLLM for the GPU.

### Port 8001
RunPod host nginx often binds **8001**. vLLM uses **8010**.

### Docker
Some RunPod images cannot run a Docker daemon (iptables/netfilter). `install.sh` still installs Docker when possible, then uses the **native** path that matches production.

### Private LoRA 404
`HF_TOKEN` must belong to an account with access to `apophaticai/qwen2.5-14b-christianai-v1`.

## Skip ingest (faster install)

```bash
SKIP_INGEST=1 bash install.sh
# later:
bash /workspace/pastor-ai/ingest_sermons.sh
```
