#!/usr/bin/env bash
# =============================================================================
# Pastor-AI Setup — RunPod Edition (Qwen2.5 fine-tuned + Qdrant RAG)
#
# First deploy on a new pod:
#   cd /workspace
#   git clone https://github.com/Shmurdax/Pastor-AI-Server.git
#   cd Pastor-AI-Server
#   cp config.env.example config.env   # add HF_TOKEN
#   bash setup.sh
#
# After pod restart (data on /workspace/pastor-ai persists):
#   cd /workspace/pastor-ai/Pastor-AI-Server && bash restart.sh
# =============================================================================
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=paths.sh
source "$ROOT/paths.sh"

if [[ -f "$ROOT/config.env" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/config.env"
fi

GITHUB_REPO="${GITHUB_REPO:-https://github.com/Shmurdax/Pastor-AI-Server.git}"
PROJECT_DIR="Pastor-AI-main"
CHRISTIANAI_HF_REPO="${CHRISTIANAI_HF_REPO:-apophaticai/qwen2.5-14b-christianai-v1}"
TUNNEL="${TUNNEL:-cloudflared}"
SKIP_INGEST="${SKIP_INGEST:-0}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
log() { echo -e "${GREEN}[✔]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die() { echo -e "${RED}[✘]${NC} $*" >&2; exit 1; }
section() {
  echo -e "\n${BLUE}═══════════════════════════════════════${NC}"
  echo -e "${BLUE}  $1${NC}"
  echo -e "${BLUE}═══════════════════════════════════════${NC}\n"
}

# Fast path: workspace already set up → just restart services
if [[ "${FORCE_SETUP:-0}" != "1" && -f "$MARKER_FILE" && -d "$LORA_DIR" && -x "$VENV_DIR/bin/python" ]]; then
  warn "Existing install found at $WORKSPACE_ROOT"
  warn "Running restart.sh (set FORCE_SETUP=1 to reinstall everything)"
  exec bash "$ROOT/restart.sh"
fi

section "Preflight"
[[ -n "${HF_TOKEN:-}" ]] || die "HF_TOKEN missing. Copy config.env.example to config.env and add your token."
command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1 || warn "No GPU detected — Qwen inference will fail"
log "Workspace: $WORKSPACE_ROOT"

section "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv git curl wget unzip build-essential screen

section "Clone / update repo"
mkdir -p "$WORKSPACE_ROOT"
if [[ -d "$REPO_DIR/.git" ]]; then
  log "Updating existing repo at $REPO_DIR"
  git -C "$REPO_DIR" pull --ff-only || warn "git pull failed — using existing copy"
else
  git clone "$GITHUB_REPO" "$REPO_DIR"
fi
[[ -f "$APP_DIR/manage.py" ]] || die "manage.py not found in $APP_DIR"

section "Python venv + dependencies"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q

# CUDA PyTorch first (required for Unsloth on RunPod NVIDIA GPUs)
pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -q \
  django djangorestframework django-cors-headers whitenoise \
  langchain langchain-core langchain-community langchain-classic \
  langchain-huggingface langchain-qdrant \
  sentence-transformers qdrant-client \
  pymupdf pypandoc pandas spacy \
  bitsandbytes accelerate peft transformers huggingface_hub

pip install -q "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" 2>/dev/null \
  || pip install -q unsloth

python -m spacy download en_core_web_sm -q
log "Python environment ready"

section "Download fine-tuned Qwen LoRA"
export HF_TOKEN
hf auth login --token "$HF_TOKEN" 2>/dev/null || true
if [[ ! -f "$LORA_DIR/adapter_model.safetensors" ]]; then
  log "Downloading $CHRISTIANAI_HF_REPO (~150 MB)..."
  hf download "$CHRISTIANAI_HF_REPO" --local-dir "$LORA_DIR"
else
  log "LoRA already at $LORA_DIR"
fi

section "Qdrant vector database"
if [[ ! -x "$QDRANT_DIR/qdrant" ]]; then
  mkdir -p "$QDRANT_DIR"
  cd "$QDRANT_DIR"
  wget -q https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz
  tar -xzf qdrant-x86_64-unknown-linux-gnu.tar.gz
  rm -f qdrant-x86_64-unknown-linux-gnu.tar.gz
  chmod +x qdrant
  log "Qdrant binary installed"
else
  log "Qdrant binary exists"
fi

section "Flutter static + API URL fix"
fix_api_url() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  sed -i 's|https://[^"]*ngrok-free\.dev/api/chat/|/api/chat/|g' "$f"
}
fix_api_url "$APP_DIR/static/main.dart.js"
fix_api_url "$APP_DIR/staticfiles/main.dart.js"

section "Django setup"
cd "$APP_DIR"
python manage.py migrate
python manage.py collectstatic --noinput
log "Django migrations + static files done"

section "Sermon ingestion (Qdrant)"
# Start Qdrant temporarily for ingestion check
if ! curl -sf http://localhost:6333 >/dev/null 2>&1; then
  screen -dmS qdrant bash -c "cd '$QDRANT_DIR' && ./qdrant >> '$LOG_DIR/qdrant.log' 2>&1"
  sleep 5
fi

COLLECTION_OK=0
if curl -sf "http://localhost:6333/collections/sermon_brain" | grep -q '"status":"green"'; then
  VECTORS="$(curl -sf "http://localhost:6333/collections/sermon_brain" | grep -o '"vectors_count":[0-9]*' | head -1 || true)"
  if [[ "$VECTORS" != '"vectors_count":0' && -n "$VECTORS" ]]; then
    COLLECTION_OK=1
    log "sermon_brain collection already populated — skipping ingestion"
  fi
fi

if [[ "$COLLECTION_OK" == "0" && "$SKIP_INGEST" != "1" && -d "$APP_DIR/converted_markdown" ]]; then
  warn "Ingesting sermon notes — this takes 10-20 minutes..."
  python ingest_qdrant.py
  log "Ingestion complete"
elif [[ "$COLLECTION_OK" == "0" ]]; then
  warn "No sermon_brain data. Run later: cd $APP_DIR && source $VENV_DIR/bin/activate && python ingest_qdrant.py"
fi

section "Optional: Ngrok"
if [[ "$TUNNEL" == "ngrok" || -n "${NGROK_AUTH_TOKEN:-}" ]]; then
  if ! command -v ngrok >/dev/null; then
    cd /tmp
    wget -q https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
    tar -xzf ngrok-v3-stable-linux-amd64.tgz
    mv ngrok /usr/local/bin/ngrok
    rm -f ngrok-v3-stable-linux-amd64.tgz
  fi
  [[ -n "${NGROK_AUTH_TOKEN:-}" ]] && ngrok config add-authtoken "$NGROK_AUTH_TOKEN"
  log "Ngrok installed (started by restart.sh if TUNNEL=ngrok)"
fi

date -Iseconds > "$MARKER_FILE"
log "Setup marker written: $MARKER_FILE"

section "Starting services"
bash "$ROOT/restart.sh"

section "Setup complete"
echo ""
echo "  Workspace (persists on RunPod volume): $WORKSPACE_ROOT"
echo "  LoRA model:                          $LORA_DIR"
echo "  After pod restart, run:"
echo "    cd $REPO_DIR && bash restart.sh"
echo ""
if [[ -f "$WORKSPACE_ROOT/public_url.txt" ]]; then
  echo "  Public URL: $(cat "$WORKSPACE_ROOT/public_url.txt")"
fi
echo ""
