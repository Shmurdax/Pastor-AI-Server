# Pastor-AI — RunPod one-command deploy

Christian theology chat: **Flutter web UI** + **Django** + **Qdrant RAG** + **vLLM (Llama 3.1 8B)**.

## One command (fresh RunPod)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GavWrecker/Pastor-AI-Server/master/install.sh)
```

Or after cloning this repo onto `/workspace`:

```bash
bash /workspace/pastor-ai/install.sh
```

Optional secrets:

```bash
HF_TOKEN=hf_xxx NGROK_AUTH_TOKEN=xxx TUNNEL=ngrok bash install.sh
```

## After pod restart (~30 seconds)

```bash
bash /workspace/pastor-ai/start.sh
```

## What gets installed

| Path | Contents |
|------|----------|
| `/workspace/pastor-ai/backend/` | `server-dev` branch (Django + ingestion) |
| `/workspace/pastor-ai/frontend/` | `front_end_backup` branch (Flutter web build) |
| `/workspace/pastor-ai/venv/` | Python env (Django, LangChain, vLLM) |
| `/workspace/pastor-ai/qdrant_storage/` | Vector DB |
| `/workspace/pastor-ai/hf_cache/` | Model cache |
| `/workspace/pastor-ai/config.env` | Secrets + ports |
| `/workspace/pastor-ai/public_url.txt` | Current public URL |

## Branches used

- Backend: `Shmurdax/Pastor-AI-Server` → `server-dev`
- Frontend: `Shmurdax/Pastor-AI-Server` → `front_end_backup`

## Notes

- Docker is **not** required (RunPod images often block nested Docker).
- Public access defaults to **Cloudflare quick tunnel**; set `TUNNEL=ngrok` for a reserved ngrok domain.
- First chat waits for the 8B model to load into GPU VRAM.

## Tokens (quick update)

```bash
cd /workspace/pastor-ai
cp tokens.env.example tokens.env
nano tokens.env          # paste HF / GitHub / ngrok tokens
bash apply-tokens.sh     # writes into config.env
bash apply-tokens.sh --restart   # also restarts services
```
