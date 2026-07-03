# Pastor-AI on RunPod

Christian theology chat app: **Flutter web UI** + **Django API** + **Qdrant RAG** + **fine-tuned Qwen2.5-14B** (Unsloth LoRA).

## New pod (first time)

1. Create a RunPod pod with:
   - **GPU:** RTX 4090 or similar (24 GB+ VRAM)
   - **Network volume:** attach your volume (e.g. 200 GB) mounted at `/workspace`

2. SSH in and run:

```bash
cd /workspace
git clone https://github.com/Shmurdax/Pastor-AI-Server.git pastor-ai/Pastor-AI-Server
cd pastor-ai/Pastor-AI-Server
cp config.env.example config.env
nano config.env   # set HF_TOKEN=hf_...
bash setup.sh
```

3. When setup finishes, open the **Cloudflare URL** printed at the end (also saved to `/workspace/pastor-ai/public_url.txt`).

**First chat message takes 1–3 minutes** while the 14B model loads into GPU memory.

## Pod restart (fast — ~30 seconds)

Everything important lives on the **network volume** at `/workspace/pastor-ai/`:

| Path | What |
|------|------|
| `christianai-lora/` | Fine-tuned LoRA weights (~150 MB) |
| `qdrant/storage/` | Sermon vector database |
| `venv/` | Python environment |
| `.cache/huggingface/` | Base model cache |
| `logs/` | Service logs |

```bash
cd /workspace/pastor-ai/Pastor-AI-Server
bash restart.sh
```

The Cloudflare URL **changes** each restart — check `public_url.txt` or `logs/cloudflared.log`.

## Configuration (`config.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `HF_TOKEN` | Yes | Hugging Face token with read access to your private LoRA |
| `CHRISTIANAI_HF_REPO` | No | Default: `apophaticai/qwen2.5-14b-christianai-v1` |
| `TUNNEL` | No | `cloudflared` (default) or `ngrok` |
| `NGROK_AUTH_TOKEN` | If ngrok | Only if using ngrok tunnel |
| `NGROK_DOMAIN` | If ngrok | Reserved ngrok domain |

## Useful commands

```bash
screen -list                          # running services
tail -f /workspace/pastor-ai/logs/django.log
tail -f /workspace/pastor-ai/logs/cloudflared.log
curl -s -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"query":"What is faith?"}'
```

## Reinstall from scratch

```bash
rm /workspace/pastor-ai/.setup_complete
FORCE_SETUP=1 bash setup.sh
```

## Stack

- **LLM:** Qwen2.5-14B-Instruct + Christian AI LoRA (Unsloth, 4-bit)
- **RAG:** Qdrant + `all-MiniLM-L6-v2` embeddings over sermon markdown
- **Tunnel:** Cloudflare quick tunnel (works when ngrok is blocked)
- **UI:** Flutter web app served by Django on port 8000
