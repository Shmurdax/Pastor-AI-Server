#!/bin/bash

# =============================================================================
# Pastor-AI Setup Script — RunPod Edition
# Compatible with: RunPod containers (Ubuntu, runs as root, no systemd)
# Usage: bash setup.sh
# =============================================================================

set -e

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()     { echo -e "${GREEN}[✔]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✘]${NC} $1"; exit 1; }
section() { echo -e "\n${BLUE}═══════════════════════════════════════${NC}"; echo -e "${BLUE}  $1${NC}"; echo -e "${BLUE}═══════════════════════════════════════${NC}\n"; }

# =============================================================================
# CONFIGURATION — Edit these 4 values before running
# =============================================================================

GITHUB_REPO="https://github.com/Shmurdax/Pastor-AI-Server.git"
NGROK_AUTH_TOKEN="3BBwXFtXN20YwmdvLq6s0apaAlI_6rDod8NKbttomTLaqGHYw"
NGROK_DOMAIN="intimiste-qualified-emeline.ngrok-free.dev"
PROJECT_DIR="Pastor-AI-main"

# =============================================================================
# DERIVED VARIABLES — Do not edit below this line
# =============================================================================

HOME_DIR="/root"
REPO_NAME=$(basename "$GITHUB_REPO" .git)
APP_DIR="$HOME_DIR/$REPO_NAME/$PROJECT_DIR"
VENV_DIR="$APP_DIR/venv"

# =============================================================================
# PREFLIGHT CHECKS
# =============================================================================

section "Preflight Checks"

if [[ "$GITHUB_REPO" == *"YOUR_USERNAME"* ]]; then
    error "Please edit the CONFIGURATION section at the top of this script before running."
fi
if [[ "$NGROK_AUTH_TOKEN" == "YOUR_NGROK_AUTH_TOKEN" ]]; then
    error "Please add your Ngrok auth token to the CONFIGURATION section before running."
fi

log "Running as: $(whoami)"
log "App directory: $APP_DIR"
log "Ngrok domain: $NGROK_DOMAIN"

# =============================================================================
# PHASE 1 — System Dependencies
# =============================================================================

section "Phase 1 — System Dependencies"

apt-get update -qq
apt-get install -y -qq \
    python3-pip \
    python3-venv \
    git \
    curl \
    wget \
    unzip \
    build-essential \
    lsof \
    screen

log "System packages installed."

# =============================================================================
# PHASE 2 — Clone GitHub Repo
# =============================================================================

section "Phase 2 — Clone GitHub Repo"

cd "$HOME_DIR"

if [ -d "$REPO_NAME" ]; then
    warn "Repo folder already exists. Pulling latest changes..."
    cd "$REPO_NAME"
    git pull
    cd "$HOME_DIR"
else
    git clone "$GITHUB_REPO"
fi

if [ ! -f "$APP_DIR/manage.py" ]; then
    error "Could not find manage.py in $APP_DIR — check that PROJECT_DIR is set correctly in the config."
fi

log "Repo ready at: $APP_DIR"

# =============================================================================
# PHASE 3 — Python Virtual Environment & Dependencies
# =============================================================================

section "Phase 3 — Python Dependencies"

cd "$APP_DIR"

python3 -m venv venv
source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q

pip install -q \
    django \
    djangorestframework \
    django-cors-headers \
    langchain \
    langchain-core \
    langchain-community \
    langchain-classic \
    langchain-huggingface \
    langchain-qdrant \
    langchain-ollama \
    sentence-transformers \
    qdrant-client \
    pymupdf \
    pypandoc \
    pandas \
    spacy

python -m spacy download en_core_web_sm -q

log "Python environment ready."

# =============================================================================
# PHASE 4 — Install Ollama & Pull Llama 3.2
# =============================================================================

section "Phase 4 — Ollama & Llama 3.2"

if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
    log "Ollama installed."
else
    log "Ollama already installed."
fi

# Start ollama in a background screen session
if ! pgrep -x "ollama" > /dev/null; then
    screen -dmS ollama bash -c "ollama serve >> /root/ollama.log 2>&1"
    sleep 5
    log "Ollama started in background screen session."
else
    log "Ollama already running."
fi

log "Pulling Llama 3.2 — this may take several minutes (~2GB)..."
ollama pull llama3.2
log "Llama 3.2 ready."

# =============================================================================
# PHASE 5 — Install Qdrant
# =============================================================================

section "Phase 5 — Qdrant"

mkdir -p /opt/qdrant

if [ ! -f "/opt/qdrant/qdrant" ]; then
    cd /opt/qdrant
    wget -q https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz
    tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
    rm qdrant-x86_64-unknown-linux-gnu.tar.gz
    chmod +x qdrant
    log "Qdrant downloaded."
else
    log "Qdrant already installed."
fi

mkdir -p /opt/qdrant/storage
mkdir -p /opt/qdrant/config

# Start Qdrant in a background screen session
if ! curl -s http://localhost:6333 > /dev/null 2>&1; then
    screen -dmS qdrant bash -c "cd /opt/qdrant && ./qdrant >> /root/qdrant.log 2>&1"
    sleep 5
    log "Qdrant started in background screen session."
else
    log "Qdrant already running."
fi

# Verify Qdrant is responding
if curl -s http://localhost:6333 > /dev/null 2>&1; then
    log "Qdrant is responding on port 6333."
else
    error "Qdrant failed to start. Check /root/qdrant.log for details."
fi

# =============================================================================
# PHASE 6 — Patch views.py (Lazy Loading + Qdrant backend)
# =============================================================================

section "Phase 6 — Patching views.py"

cd "$APP_DIR"

cat > api/views.py << 'VIEWSEOF'
import os
from rest_framework.views import APIView
from rest_framework.response import Response
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_ollama import ChatOllama
from langchain_classic.chains.retrieval import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

# Loaded lazily on first request so Django starts cleanly
_rag_chain = None
_embeddings = None

def get_rag_chain():
    global _rag_chain, _embeddings

    if _rag_chain is not None:
        return _rag_chain

    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    vector_db = QdrantVectorStore.from_existing_collection(
        embedding=_embeddings,
        url="http://localhost:6333",
        collection_name="sermon_brain"
    )
    retriever = vector_db.as_retriever(search_kwargs={"k": 3})

    llm = ChatOllama(model="llama3.2", temperature=0)

    system_prompt = (
        "You are a helpful pastor's assistant for the Nordin's church. "
        "Use ONLY the following sermon notes and Bible passages to answer. "
        "If the answer is not in the context, say you don't have that information. "
        "\n\nContext:\n{context}"
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}")
    ])

    qa_chain = create_stuff_documents_chain(llm, prompt)
    _rag_chain = create_retrieval_chain(retriever, qa_chain)
    return _rag_chain


class ChatAPI(APIView):
    def post(self, request):
        user_query = request.data.get("prompt") or request.data.get("query")
        if not user_query:
            return Response({"error": "No query provided"}, status=400)

        try:
            rag_chain = get_rag_chain()
        except Exception as e:
            return Response({
                "error": "AI system not ready. Sermon data may not be ingested yet.",
                "detail": str(e)
            }, status=503)

        result = rag_chain.invoke({"input": user_query})

        return Response({
            "answer": result["answer"],
            "sources": [
                os.path.basename(doc.metadata.get("source", "Unknown"))
                for doc in result["context"]
            ]
        })
VIEWSEOF

log "views.py patched."

# =============================================================================
# PHASE 7 — Update settings.py
# =============================================================================

section "Phase 7 — Django Settings"

cat > "$APP_DIR/pastor_project/settings.py" << SETTINGSEOF
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-wk3vp523=dp(u&*k7ghd6t-zkt^f5=odowt5whox)_zucw3cyn'

DEBUG = False

ALLOWED_HOSTS = [
    '$NGROK_DOMAIN',
    'localhost',
    '127.0.0.1',
]

CSRF_TRUSTED_ORIGINS = [
    'https://$NGROK_DOMAIN',
]

CORS_ALLOW_ALL_ORIGINS = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'pastor_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'static')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'pastor_project.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SETTINGSEOF

log "settings.py updated."

# =============================================================================
# PHASE 8 — Django Migrations & Static Files
# =============================================================================

section "Phase 8 — Django Setup"

cd "$APP_DIR"
source "$VENV_DIR/bin/activate"

python manage.py migrate
python manage.py collectstatic --noinput

log "Django migrations and static files done."

# =============================================================================
# PHASE 9 — Ingest Sermon Notes into Qdrant
# =============================================================================

section "Phase 9 — Sermon Ingestion"

cd "$APP_DIR"
source "$VENV_DIR/bin/activate"

if [ -d "$APP_DIR/converted_markdown" ]; then
    log "Found converted_markdown. Starting ingestion — this may take a while..."
    python ingest_qdrant.py
    log "Sermon ingestion complete."
else
    warn "converted_markdown not found! Skipping ingestion."
    warn "Run manually: source $VENV_DIR/bin/activate && cd $APP_DIR && python ingest_qdrant.py"
fi

# =============================================================================
# PHASE 10 — Install & Configure Ngrok
# =============================================================================

section "Phase 10 — Ngrok"

if ! command -v ngrok &> /dev/null; then
    cd "$HOME_DIR"
    wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
    tar -xzf ngrok-v3-stable-linux-amd64.tgz
    mv ngrok /usr/local/bin/ngrok
    rm -f ngrok-v3-stable-linux-amd64.tgz
    log "Ngrok installed."
else
    log "Ngrok already installed."
fi

ngrok config add-authtoken "$NGROK_AUTH_TOKEN"
log "Ngrok auth token saved."

# =============================================================================
# PHASE 11 — Start All Processes in Screen Sessions
# =============================================================================

section "Phase 11 — Starting All Processes"

cd "$APP_DIR"
source "$VENV_DIR/bin/activate"

# Start Django
screen -dmS django bash -c "cd $APP_DIR && source $VENV_DIR/bin/activate && python manage.py runserver 0.0.0.0:8000 >> /root/django.log 2>&1"
log "Django started in screen session 'django'."
sleep 5

# Start Ngrok
screen -dmS ngrok bash -c "ngrok http --url=$NGROK_DOMAIN 8000 >> /root/ngrok.log 2>&1"
log "Ngrok started in screen session 'ngrok'."
sleep 3

# =============================================================================
# PHASE 12 — Health Check
# =============================================================================

section "Phase 12 — Health Check"

echo ""
echo "Checking running screen sessions..."
screen -list

echo ""
echo "Checking Qdrant..."
if curl -s http://localhost:6333 > /dev/null 2>&1; then
    log "Qdrant is running ✔"
else
    warn "Qdrant not responding ✘ — check: cat /root/qdrant.log"
fi

echo ""
echo "Checking Qdrant sermon collection..."
sleep 2
COLLECTION=$(curl -s http://localhost:6333/collections/sermon_brain)
if echo "$COLLECTION" | grep -q "vectors_count"; then
    log "sermon_brain collection exists ✔"
else
    warn "sermon_brain collection not found — ingestion may have failed"
fi

echo ""
echo "Checking Django API..."
sleep 3
API_RESPONSE=$(curl -s -X POST http://localhost:8000/api/chat/ \
    -H "Content-Type: application/json" \
    -d '{"query": "What is faith?"}')

if echo "$API_RESPONSE" | grep -q "answer"; then
    log "Django API responding ✔"
else
    warn "Django API not responding — check: cat /root/django.log"
fi

# =============================================================================
# DONE
# =============================================================================

section "Setup Complete!"

echo -e "${GREEN}"
echo "  Pastor-AI is running!"
echo ""
echo "  Public URL:  https://$NGROK_DOMAIN"
echo "  Local URL:   http://localhost:8000"
echo ""
echo "  Useful commands:"
echo "    screen -list                    # See all running processes"
echo "    screen -r django                # View Django logs (Ctrl+A then D to exit)"
echo "    screen -r qdrant                # View Qdrant logs"
echo "    screen -r ollama                # View Ollama logs"
echo "    screen -r ngrok                 # View Ngrok logs"
echo "    cat /root/django.log            # Check Django log file"
echo "    cat /root/ngrok.log             # Check Ngrok log file"
echo "    cat /root/qdrant.log            # Check Qdrant log file"
echo ""
echo "  NOTE: RunPod containers do not use systemd."
echo "  If the pod restarts, run: bash $HOME_DIR/$REPO_NAME/setup.sh"
echo -e "${NC}"