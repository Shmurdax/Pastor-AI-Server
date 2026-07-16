# Pastor-AI Server

Django backend + Flutter web UI for a sermon-trained AI assistant (RAG over sermon notes via Chroma + Ollama).

App code lives in `Pastor-AI-main/`.

## Local development (recommended)

You need:
- Python 3.12+
- Ollama with `llama3.2`
- Flutter SDK (only if editing/publishing the UI)

### Backend

```bash
cd Pastor-AI-main
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
```

Start Ollama, then Django:

```bash
ollama serve                 # separate terminal
ollama pull llama3.2         # first time only
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000/

### Vector DB (sermon brain)

Chat needs `sermon_brain_db/` (gitignored). Build once from `converted_markdown/`.
`sermon_indexer.py` currently has a Windows path — point it at local dirs before running, or use an equivalent ingestion script.

### Frontend

Hybrid model:
- **Edit:** `Pastor-AI-main/flutter_application_1/`
- **Published artifact Django serves:** `Pastor-AI-main/static/`
- **Publish a new UI:**

```bash
cd Pastor-AI-main
./scripts/publish_frontend.sh
```

Do **not** bake temporary ngrok hosts into published builds. The publish script uses same-origin `/api/*`.

### Useful API endpoints

- `POST /api/chat/`
- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `GET  /api/auth/me/`
- `POST /api/auth/logout/`

## Production / tunnel (optional)

Ngrok is optional for exposing a local/RunPod server publicly:

```bash
ngrok http 8000
```

`setup.sh` is a **RunPod deployment helper**. It installs Qdrant/ngrok and rewrites app files for that environment. Do **not** use it for normal local Chroma-based development.

## Tips

- Use browser DevTools (F12) when the UI fails to call the API.
- Cloud-agent notes: see `AGENTS.md`.
