# Pastor-AI

Django API + published Flutter web UI for the Nordin's AI sermon assistant.

## Setup

Prefer the root [README](../README.md). Quick version:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
# ensure ollama is running with llama3.2
python manage.py runserver 0.0.0.0:8000
```

## Frontend

- Source: `flutter_application_1/`
- Published bundle served by Django: `static/`
- Publish: `./scripts/publish_frontend.sh`

## Notes

- Local RAG uses **Chroma** (`sermon_brain_db/`) + Ollama `llama3.2`.
- Root `setup.sh` is for RunPod/Qdrant/ngrok deploys, not local Chroma setup.
