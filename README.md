# Pastor-AI-Server

RunPod deployment for the Pastor AI chat app with fine-tuned **Qwen2.5-14B Christian AI**.

## Quick start (RunPod)

```bash
cd /workspace
git clone https://github.com/Shmurdax/Pastor-AI-Server.git pastor-ai/Pastor-AI-Server
cd pastor-ai/Pastor-AI-Server
cp config.env.example config.env   # add HF_TOKEN
bash setup.sh
```

**After pod restart:** `bash restart.sh`

See **[RUNPOD.md](RUNPOD.md)** for full rebuild guide.

## What runs

- Django + Flutter web UI (`:8000`)
- Qdrant vector DB (`:6333`) — sermon/Bible RAG
- Fine-tuned Qwen2.5-14B via Unsloth (GPU)
- Cloudflare tunnel for public HTTPS access

## Local dev (Windows)

The `Pastor-AI-main` folder can run locally with Django + Ollama — see `Pastor-AI-main/README.md`. Production RunPod uses Qwen instead of Llama.

## RunPod one-command install

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh)
```

See [RUNPOD.md](RUNPOD.md) for details. After a pod restart: `bash /workspace/pastor-ai/start.sh`.
