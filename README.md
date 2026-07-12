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

## After pod restart

```bash
bash /workspace/pastor-ai/start.sh
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

## Stack (current production)

| Component | Detail |
|-----------|--------|
| LLM | `Qwen/Qwen2.5-14B-Instruct-AWQ` + LoRA `apophaticai/qwen2.5-14b-christianai-v1` (served as `christianai`) |
| API | Django/gunicorn `:8000` |
| Vectors | Qdrant `:6333` collection `sermon_brain` |
| UI | Flutter web build in `frontend/` |
| Tunnel | Cloudflare quick tunnel (default) |

See [RUNPOD.md](RUNPOD.md) for troubleshooting (ghost VRAM, ports, tokens).
