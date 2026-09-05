#!/usr/bin/env bash
# Create the two RunPod Serverless GPU endpoints Pastor-AI expects:
#   1) vLLM chat  — Qwen2.5-14B-Instruct-AWQ + Christian LoRA (served as christianai)
#   2) Faster-Whisper — video ingest only (do not put Whisper on the 14B worker)
#
# Usage (from a machine with your RunPod API key — not required on the CPU web pod):
#   export RUNPOD_API_KEY=rpa_...
#   export HF_TOKEN=hf_...   # account that can read apophaticai/qwen2.5-14b-christianai-v1
#   bash serverless/create_runpod_endpoints.sh
#   bash serverless/create_runpod_endpoints.sh --write-tokens
#
# Preview the REST payloads without creating anything:
#   bash serverless/create_runpod_endpoints.sh --dry-run
#
# Console alternative: see RUNPOD.md ("Create the two serverless GPU endpoints").
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="${RUNPOD_REST_URL:-https://rest.runpod.io/v1}"

DRY_RUN=0
WRITE_TOKENS=0
LIST_ONLY=0
CREATE_VLLM=1
CREATE_WHISPER=1
PAYLOAD_DIR=""
TOKENS_FILE="${TOKENS_FILE:-$ROOT/tokens.env}"

VLLM_IMAGE="${VLLM_IMAGE:-runpod/worker-v1-vllm:v2.26.0}"
WHISPER_IMAGE="${WHISPER_IMAGE:-runpod/ai-api-faster-whisper:1.0.10}"
VLLM_TEMPLATE_NAME="${VLLM_TEMPLATE_NAME:-pastor-ai-vllm}"
WHISPER_TEMPLATE_NAME="${WHISPER_TEMPLATE_NAME:-pastor-ai-whisper}"
VLLM_ENDPOINT_NAME="${VLLM_ENDPOINT_NAME:-pastor-ai-chat-vllm}"
WHISPER_ENDPOINT_NAME="${WHISPER_ENDPOINT_NAME:-pastor-ai-whisper}"

VLLM_GPU_TYPE_IDS="${VLLM_GPU_TYPE_IDS:-NVIDIA RTX A5000,NVIDIA L4,NVIDIA GeForce RTX 4090,NVIDIA RTX A6000,NVIDIA L40,NVIDIA RTX 6000 Ada Generation}"
WHISPER_GPU_TYPE_IDS="${WHISPER_GPU_TYPE_IDS:-NVIDIA RTX A4000,NVIDIA L4,NVIDIA RTX A2000,NVIDIA GeForce RTX 3080,Tesla T4,NVIDIA GeForce RTX 3090}"

VLLM_WORKERS_MIN="${VLLM_WORKERS_MIN:-0}"
VLLM_WORKERS_MAX="${VLLM_WORKERS_MAX:-1}"
VLLM_IDLE_TIMEOUT="${VLLM_IDLE_TIMEOUT:-180}"
VLLM_EXECUTION_TIMEOUT_MS="${VLLM_EXECUTION_TIMEOUT_MS:-600000}"
VLLM_CONTAINER_DISK_GB="${VLLM_CONTAINER_DISK_GB:-80}"

WHISPER_WORKERS_MIN="${WHISPER_WORKERS_MIN:-0}"
WHISPER_WORKERS_MAX="${WHISPER_WORKERS_MAX:-1}"
WHISPER_IDLE_TIMEOUT="${WHISPER_IDLE_TIMEOUT:-90}"
WHISPER_EXECUTION_TIMEOUT_MS="${WHISPER_EXECUTION_TIMEOUT_MS:-600000}"
WHISPER_CONTAINER_DISK_GB="${WHISPER_CONTAINER_DISK_GB:-30}"

MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
LORA_NAME="${LORA_NAME:-christianai}"
LORA_PATH="${LORA_PATH:-apophaticai/qwen2.5-14b-christianai-v1}"
OPENAI_SERVED_MODEL_NAME_OVERRIDE="${OPENAI_SERVED_MODEL_NAME_OVERRIDE:-christianai}"
WHISPER_MODEL="${WHISPER_MODEL:-base}"

usage() {
  cat <<'EOF'
Create Pastor-AI RunPod Serverless GPU endpoints (vLLM chat + Faster-Whisper).

Usage:
  bash serverless/create_runpod_endpoints.sh [options]

Options:
  --dry-run           Print REST payloads; do not call RunPod
  --write-tokens      After create, upsert IDs into tokens.env
  --list              List existing templates and endpoints, then exit
  --vllm-only         Create only the chat vLLM endpoint
  --whisper-only      Create only the Faster-Whisper endpoint
  --payload-dir DIR   Write JSON payloads (and result snippet) to DIR
  -h, --help          Show this help

Required for a real create:
  RUNPOD_API_KEY      https://www.runpod.io/console/user/settings
  HF_TOKEN            Hugging Face token with access to the private Christian LoRA
                      (vLLM worker only; not needed for Whisper)

Optional:
  RUNPOD_NETWORK_VOLUME_ID   Attach a network volume at /runpod-volume (recommended
                             for vLLM so 14B weights survive scale-to-zero)
  VLLM_IMAGE / WHISPER_IMAGE
  VLLM_GPU_TYPE_IDS / WHISPER_GPU_TYPE_IDS   comma-separated RunPod GPU names

Do not put Whisper on the 14B vLLM worker. This script always creates two
separate templates/endpoints unless you pass --vllm-only or --whisper-only.
EOF
}

log()  { printf '[*] %s\n' "$*"; }
warn() { printf '[!] %s\n' "$*" >&2; }
die()  { printf '[✘] %s\n' "$*" >&2; exit 1; }

is_placeholder() {
  local value="${1:-}"
  local lowered
  lowered="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  [[ -z "$value" ]] && return 0
  [[ "$lowered" == *paste_here* ]] && return 0
  [[ "$lowered" == "not-needed" || "$lowered" == "empty" ]] && return 0
  return 1
}

redact_json() {
  python3 -c '
import json, sys
data = json.load(sys.stdin)

def walk(obj):
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            upper = str(key).upper()
            if any(token in upper for token in ("TOKEN", "KEY", "SECRET", "PASSWORD", "AUTH")):
                if isinstance(value, str) and value:
                    out[key] = value[:4] + "***redacted***"
                else:
                    out[key] = value
            else:
                out[key] = walk(value)
        return out
    if isinstance(obj, list):
        return [walk(item) for item in obj]
    return obj

print(json.dumps(walk(data), indent=2))
'
}

require_jq_python() {
  command -v python3 >/dev/null 2>&1 || die "python3 is required"
  command -v curl >/dev/null 2>&1 || die "curl is required"
}

unique_name() {
  local base="$1"
  printf '%s-%s-%s' "$base" "$(date +%Y%m%d%H%M%S)" "${RANDOM:-$$}"
}

rp_request() {
  local method="$1" path="$2" body="${3:-}"
  local url="${API}${path}"
  local tmp http
  tmp="$(mktemp)"
  local args=(-sS -X "$method"
    -H "Authorization: Bearer ${RUNPOD_API_KEY}"
    -H "Content-Type: application/json"
    -o "$tmp" -w '%{http_code}')
  if [[ -n "$body" ]]; then
    args+=(--data "$body")
  fi
  http="$(curl "${args[@]}" "$url" || true)"
  if [[ ! "$http" =~ ^2 ]]; then
    warn "RunPod ${method} ${path} → HTTP ${http}"
    python3 -m json.tool <"$tmp" 2>/dev/null || cat "$tmp"
    echo
    rm -f "$tmp"
    die "RunPod API request failed"
  fi
  cat "$tmp"
  rm -f "$tmp"
}

json_id() {
  python3 -c 'import json,sys
obj=json.load(sys.stdin)
if isinstance(obj, dict):
    ident=obj.get("id") or (obj.get("data") or {}).get("id") or ""
    print(ident)
'
}

load_local_secrets() {
  local file
  for file in "$TOKENS_FILE" "$ROOT/config.env"; do
    if [[ -f "$file" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$file"
      set +a
    fi
  done
}

vllm_env_json() {
  local hf_token="$1"
  python3 - "$hf_token" <<'PY'
import json, os, sys
hf_token = sys.argv[1]
lora = [{"name": os.environ.get("LORA_NAME", "christianai"),
         "path": os.environ.get("LORA_PATH", "apophaticai/qwen2.5-14b-christianai-v1")}]
env = {
    "MODEL_NAME": os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-14B-Instruct-AWQ"),
    "MAX_MODEL_LEN": os.environ.get("MAX_MODEL_LEN", "8192"),
    "GPU_MEMORY_UTILIZATION": os.environ.get("GPU_MEMORY_UTILIZATION", "0.90"),
    "TRUST_REMOTE_CODE": "1",
    "QUANTIZATION": "awq",
    "ENABLE_LORA": "true",
    "MAX_LORAS": "1",
    "MAX_LORA_RANK": "16",
    "LORA_MODULES": json.dumps(lora, separators=(",", ":")),
    "OPENAI_SERVED_MODEL_NAME_OVERRIDE": os.environ.get(
        "OPENAI_SERVED_MODEL_NAME_OVERRIDE", "christianai"
    ),
    "RAW_OPENAI_OUTPUT": "1",
    "HF_TOKEN": hf_token,
    "DOWNLOAD_DIR": "/runpod-volume/huggingface-cache",
    "HF_HOME": "/runpod-volume/huggingface-cache",
}
print(json.dumps(env))
PY
}

whisper_env_json() {
  python3 - <<'PY'
import json, os
print(json.dumps({"MODEL_NAME": os.environ.get("WHISPER_MODEL", "base")}))
PY
}

template_payload() {
  local name="$1" image="$2" env_json="$3" disk_gb="$4"
  python3 - "$name" "$image" "$env_json" "$disk_gb" <<'PY'
import json, sys
name, image, env_json, disk_gb = sys.argv[1:5]
print(json.dumps({
    "name": name,
    "imageName": image,
    "isServerless": True,
    "containerDiskInGb": int(disk_gb),
    "volumeInGb": 0,
    "volumeMountPath": "/runpod-volume",
    "env": json.loads(env_json),
}))
PY
}

endpoint_payload() {
  local name="$1" template_id="$2" gpu_csv="$3" workers_min="$4" workers_max="$5"
  local idle="$6" exec_ms="$7"
  python3 - "$name" "$template_id" "$gpu_csv" "$workers_min" "$workers_max" "$idle" "$exec_ms" \
    "${RUNPOD_NETWORK_VOLUME_ID:-}" <<'PY'
import json, os, sys
name, template_id, gpu_csv, workers_min, workers_max, idle, exec_ms, volume_id = sys.argv[1:9]
gpus = [part.strip() for part in gpu_csv.split(",") if part.strip()]
body = {
    "name": name,
    "templateId": template_id,
    "computeType": "GPU",
    "gpuCount": 1,
    "gpuTypeIds": gpus,
    "workersMin": int(workers_min),
    "workersMax": int(workers_max),
    "idleTimeout": int(idle),
    "executionTimeoutMs": int(exec_ms),
    "flashboot": True,
    "scalerType": "QUEUE_DELAY",
    "scalerValue": 4,
}
if volume_id.strip():
    body["networkVolumeId"] = volume_id.strip()
print(json.dumps(body))
PY
}

write_payload() {
  local name="$1" json="$2"
  [[ -z "$PAYLOAD_DIR" ]] && return 0
  mkdir -p "$PAYLOAD_DIR"
  printf '%s\n' "$json" > "$PAYLOAD_DIR/${name}.json"
}

print_payload() {
  local title="$1" json="$2"
  echo
  echo "=== ${title} ==="
  printf '%s\n' "$json" | redact_json
}

upsert_tokens_key() {
  local file="$1" key="$2" val="$3"
  [[ -z "$val" ]] && return 0
  python3 - "$file" "$key" "$val" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
key, val = sys.argv[2], sys.argv[3]
text = path.read_text() if path.exists() else ""
lines = text.splitlines()
prefix = f"{key}="
commented = f"# {key}="
replaced = False
out = []
for line in lines:
    stripped = line.lstrip()
    if stripped.startswith(prefix) or stripped.startswith(commented):
        out.append(f"{key}={val}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    if out and out[-1] != "":
        out.append("")
    out.append(f"{key}={val}")
path.write_text("\n".join(out) + "\n")
PY
}

tokens_snippet() {
  local vllm_id="${1:-}" whisper_id="${2:-}"
  cat <<EOF
CPU_ONLY=1
VLLM_MODE=serverless
RUNPOD_VLLM_ENDPOINT_ID=${vllm_id:-your_vllm_endpoint_id}
WHISPER_MODE=serverless
RUNPOD_WHISPER_ENDPOINT_ID=${whisper_id:-your_whisper_endpoint_id}
RUNPOD_API_KEY=${RUNPOD_API_KEY:-rpa_your_runpod_api_key}
EOF
}

list_resources() {
  [[ -n "${RUNPOD_API_KEY:-}" ]] && ! is_placeholder "$RUNPOD_API_KEY" \
    || die "RUNPOD_API_KEY is required for --list"
  echo "=== Templates ==="
  rp_request GET /templates | python3 -m json.tool
  echo
  echo "=== Endpoints ==="
  rp_request GET /endpoints | python3 -m json.tool
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --write-tokens) WRITE_TOKENS=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    --vllm-only) CREATE_WHISPER=0; shift ;;
    --whisper-only) CREATE_VLLM=0; shift ;;
    --payload-dir)
      PAYLOAD_DIR="${2:-}"
      [[ -n "$PAYLOAD_DIR" ]] || die "--payload-dir needs a directory"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

require_jq_python
load_local_secrets
export MODEL_NAME MAX_MODEL_LEN GPU_MEMORY_UTILIZATION LORA_NAME LORA_PATH \
  OPENAI_SERVED_MODEL_NAME_OVERRIDE WHISPER_MODEL

if [[ "$LIST_ONLY" == 1 ]]; then
  list_resources
  exit 0
fi

if [[ "$CREATE_VLLM" == 0 && "$CREATE_WHISPER" == 0 ]]; then
  die "Nothing to create (both --vllm-only and --whisper-only?)"
fi

HF_VALUE="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"
if [[ "$CREATE_VLLM" == 1 ]]; then
  if is_placeholder "$HF_VALUE"; then
    if [[ "$DRY_RUN" == 1 ]]; then
      HF_VALUE="hf_paste_here"
      warn "HF_TOKEN is missing; dry-run payload uses hf_paste_here. The real vLLM worker needs a token that can read ${LORA_PATH}."
    else
      die "HF_TOKEN is required to create the vLLM worker (private LoRA ${LORA_PATH})."
    fi
  fi
fi

if [[ "$DRY_RUN" != 1 ]]; then
  [[ -n "${RUNPOD_API_KEY:-}" ]] && ! is_placeholder "$RUNPOD_API_KEY" \
    || die "RUNPOD_API_KEY is required (https://www.runpod.io/console/user/settings)"
fi

if [[ -n "${RUNPOD_NETWORK_VOLUME_ID:-}" ]]; then
  log "Will attach network volume ${RUNPOD_NETWORK_VOLUME_ID} at /runpod-volume"
else
  warn "No RUNPOD_NETWORK_VOLUME_ID — vLLM will re-download ~14B weights on every cold start. Attach a volume if you already have one."
fi

VLLM_TEMPLATE_JSON=""
WHISPER_TEMPLATE_JSON=""
VLLM_ENDPOINT_JSON=""
WHISPER_ENDPOINT_JSON=""
VLLM_TEMPLATE_ID="tmpl_vllm_dry_run"
WHISPER_TEMPLATE_ID="tmpl_whisper_dry_run"
VLLM_ENDPOINT_ID=""
WHISPER_ENDPOINT_ID=""

if [[ "$CREATE_VLLM" == 1 ]]; then
  VLLM_TEMPLATE_JSON="$(template_payload \
    "$(unique_name "$VLLM_TEMPLATE_NAME")" \
    "$VLLM_IMAGE" \
    "$(vllm_env_json "$HF_VALUE")" \
    "$VLLM_CONTAINER_DISK_GB")"
  write_payload vllm_template "$VLLM_TEMPLATE_JSON"
  print_payload "vLLM template" "$VLLM_TEMPLATE_JSON"
fi

if [[ "$CREATE_WHISPER" == 1 ]]; then
  WHISPER_TEMPLATE_JSON="$(template_payload \
    "$(unique_name "$WHISPER_TEMPLATE_NAME")" \
    "$WHISPER_IMAGE" \
    "$(whisper_env_json)" \
    "$WHISPER_CONTAINER_DISK_GB")"
  write_payload whisper_template "$WHISPER_TEMPLATE_JSON"
  print_payload "Whisper template" "$WHISPER_TEMPLATE_JSON"
fi

if [[ "$DRY_RUN" == 1 ]]; then
  if [[ "$CREATE_VLLM" == 1 ]]; then
    VLLM_ENDPOINT_JSON="$(endpoint_payload \
      "$VLLM_ENDPOINT_NAME" "$VLLM_TEMPLATE_ID" "$VLLM_GPU_TYPE_IDS" \
      "$VLLM_WORKERS_MIN" "$VLLM_WORKERS_MAX" \
      "$VLLM_IDLE_TIMEOUT" "$VLLM_EXECUTION_TIMEOUT_MS")"
    write_payload vllm_endpoint "$VLLM_ENDPOINT_JSON"
    print_payload "vLLM endpoint" "$VLLM_ENDPOINT_JSON"
  fi
  if [[ "$CREATE_WHISPER" == 1 ]]; then
    WHISPER_ENDPOINT_JSON="$(endpoint_payload \
      "$WHISPER_ENDPOINT_NAME" "$WHISPER_TEMPLATE_ID" "$WHISPER_GPU_TYPE_IDS" \
      "$WHISPER_WORKERS_MIN" "$WHISPER_WORKERS_MAX" \
      "$WHISPER_IDLE_TIMEOUT" "$WHISPER_EXECUTION_TIMEOUT_MS")"
    write_payload whisper_endpoint "$WHISPER_ENDPOINT_JSON"
    print_payload "Whisper endpoint" "$WHISPER_ENDPOINT_JSON"
  fi
  echo
  echo "=== tokens.env snippet (IDs filled after a real create) ==="
  tokens_snippet
  if [[ -n "$PAYLOAD_DIR" ]]; then
    tokens_snippet > "$PAYLOAD_DIR/tokens.env.snippet"
    log "Wrote payloads to $PAYLOAD_DIR"
  fi
  log "Dry run only — no endpoints were created."
  log "Console Hub (if you prefer clicks):"
  log "  vLLM:    https://console.runpod.io/hub/runpod-workers/worker-vllm"
  log "  Whisper: https://console.runpod.io/hub/runpod-workers/worker-faster_whisper"
  exit 0
fi

if [[ "$CREATE_VLLM" == 1 ]]; then
  log "Creating vLLM serverless template (${VLLM_IMAGE})"
  VLLM_TEMPLATE_ID="$(rp_request POST /templates "$VLLM_TEMPLATE_JSON" | json_id)"
  [[ -n "$VLLM_TEMPLATE_ID" ]] || die "vLLM template create returned no id"
  log "vLLM template id: $VLLM_TEMPLATE_ID"
  VLLM_ENDPOINT_JSON="$(endpoint_payload \
    "$VLLM_ENDPOINT_NAME" "$VLLM_TEMPLATE_ID" "$VLLM_GPU_TYPE_IDS" \
    "$VLLM_WORKERS_MIN" "$VLLM_WORKERS_MAX" \
    "$VLLM_IDLE_TIMEOUT" "$VLLM_EXECUTION_TIMEOUT_MS")"
  write_payload vllm_endpoint "$VLLM_ENDPOINT_JSON"
  print_payload "vLLM endpoint request" "$VLLM_ENDPOINT_JSON"
  log "Creating vLLM serverless endpoint"
  VLLM_ENDPOINT_ID="$(rp_request POST /endpoints "$VLLM_ENDPOINT_JSON" | json_id)"
  [[ -n "$VLLM_ENDPOINT_ID" ]] || die "vLLM endpoint create returned no id"
  log "vLLM endpoint id: $VLLM_ENDPOINT_ID"
  log "OpenAI base: https://api.runpod.ai/v2/${VLLM_ENDPOINT_ID}/openai/v1"
fi

if [[ "$CREATE_WHISPER" == 1 ]]; then
  log "Creating Faster-Whisper serverless template (${WHISPER_IMAGE})"
  WHISPER_TEMPLATE_ID="$(rp_request POST /templates "$WHISPER_TEMPLATE_JSON" | json_id)"
  [[ -n "$WHISPER_TEMPLATE_ID" ]] || die "Whisper template create returned no id"
  log "Whisper template id: $WHISPER_TEMPLATE_ID"
  WHISPER_ENDPOINT_JSON="$(endpoint_payload \
    "$WHISPER_ENDPOINT_NAME" "$WHISPER_TEMPLATE_ID" "$WHISPER_GPU_TYPE_IDS" \
    "$WHISPER_WORKERS_MIN" "$WHISPER_WORKERS_MAX" \
    "$WHISPER_IDLE_TIMEOUT" "$WHISPER_EXECUTION_TIMEOUT_MS")"
  write_payload whisper_endpoint "$WHISPER_ENDPOINT_JSON"
  print_payload "Whisper endpoint request" "$WHISPER_ENDPOINT_JSON"
  log "Creating Faster-Whisper serverless endpoint"
  WHISPER_ENDPOINT_ID="$(rp_request POST /endpoints "$WHISPER_ENDPOINT_JSON" | json_id)"
  [[ -n "$WHISPER_ENDPOINT_ID" ]] || die "Whisper endpoint create returned no id"
  log "Whisper endpoint id: $WHISPER_ENDPOINT_ID"
  log "runsync URL: https://api.runpod.ai/v2/${WHISPER_ENDPOINT_ID}/runsync"
fi

echo
echo "=== Paste into tokens.env on the CPU web pod ==="
tokens_snippet "$VLLM_ENDPOINT_ID" "$WHISPER_ENDPOINT_ID"
if [[ -n "$PAYLOAD_DIR" ]]; then
  tokens_snippet "$VLLM_ENDPOINT_ID" "$WHISPER_ENDPOINT_ID" > "$PAYLOAD_DIR/tokens.env.snippet"
  printf '%s\n' "$VLLM_ENDPOINT_ID" > "$PAYLOAD_DIR/vllm_endpoint_id.txt"
  printf '%s\n' "$WHISPER_ENDPOINT_ID" > "$PAYLOAD_DIR/whisper_endpoint_id.txt"
fi

if [[ "$WRITE_TOKENS" == 1 ]]; then
  if [[ ! -f "$TOKENS_FILE" && -f "$ROOT/tokens.env.example" ]]; then
    cp "$ROOT/tokens.env.example" "$TOKENS_FILE"
    log "Created $TOKENS_FILE from example"
  fi
  [[ -f "$TOKENS_FILE" ]] || die "No $TOKENS_FILE to write (copy tokens.env.example first)"
  upsert_tokens_key "$TOKENS_FILE" CPU_ONLY 1
  upsert_tokens_key "$TOKENS_FILE" VLLM_MODE serverless
  upsert_tokens_key "$TOKENS_FILE" RUNPOD_API_KEY "${RUNPOD_API_KEY:-}"
  [[ -n "$VLLM_ENDPOINT_ID" ]] && upsert_tokens_key "$TOKENS_FILE" RUNPOD_VLLM_ENDPOINT_ID "$VLLM_ENDPOINT_ID"
  upsert_tokens_key "$TOKENS_FILE" WHISPER_MODE serverless
  [[ -n "$WHISPER_ENDPOINT_ID" ]] && upsert_tokens_key "$TOKENS_FILE" RUNPOD_WHISPER_ENDPOINT_ID "$WHISPER_ENDPOINT_ID"
  log "Updated $TOKENS_FILE — on the CPU pod run: bash apply-tokens.sh --restart"
fi

echo
log "Smoke tests (first call may take 1–3 minutes while the worker cold-starts):"
if [[ -n "$VLLM_ENDPOINT_ID" ]]; then
  log "  bash scripts/check_vllm.sh"
fi
if [[ -n "$WHISPER_ENDPOINT_ID" ]]; then
  log "  bash scripts/check_whisper.sh"
fi
log "Console:"
log "  https://console.runpod.io/serverless"
