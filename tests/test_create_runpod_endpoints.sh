#!/usr/bin/env bash
# Dry-run payload checks for serverless/create_runpod_endpoints.sh (no RunPod key).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT/serverless/create_runpod_endpoints.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -x "$SCRIPT" || -f "$SCRIPT" ]] || fail "missing $SCRIPT"
chmod +x "$SCRIPT" "$ROOT/scripts/check_whisper.sh" 2>/dev/null || true

DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT

# Dry-run must work without RUNPOD_API_KEY / HF_TOKEN.
unset RUNPOD_API_KEY HF_TOKEN HUGGING_FACE_HUB_TOKEN RUNPOD_NETWORK_VOLUME_ID || true
bash "$SCRIPT" --dry-run --payload-dir "$DIR" >/dev/null

for name in vllm_template vllm_endpoint whisper_template whisper_endpoint tokens.env.snippet; do
  [[ -s "$DIR/$name.json" || -s "$DIR/$name" ]] || fail "expected payload $name"
done

python3 - "$DIR" <<'PY' || fail "payload assertions"
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])

def load(name):
    return json.loads((d / name).read_text())

vllm_t = load("vllm_template.json")
vllm_e = load("vllm_endpoint.json")
wh_t = load("whisper_template.json")
wh_e = load("whisper_endpoint.json")

assert vllm_t["isServerless"] is True
assert vllm_t["imageName"].startswith("runpod/worker-v1-vllm:")
assert vllm_t["volumeMountPath"] == "/runpod-volume"
env = vllm_t["env"]
assert env["MODEL_NAME"] == "Qwen/Qwen2.5-14B-Instruct-AWQ"
assert env["QUANTIZATION"] == "awq"
assert env["ENABLE_LORA"] == "true"
assert env["OPENAI_SERVED_MODEL_NAME_OVERRIDE"] == "christianai"
assert "christianai" in env["LORA_MODULES"]
assert "apophaticai/qwen2.5-14b-christianai-v1" in env["LORA_MODULES"]
assert env["RAW_OPENAI_OUTPUT"] == "1"
assert "HF_TOKEN" in env
assert "faster-whisper" not in vllm_t["imageName"]

assert vllm_e["computeType"] == "GPU"
assert vllm_e["workersMin"] == 0
assert vllm_e["workersMax"] == 1
assert vllm_e["idleTimeout"] >= 120
assert vllm_e["executionTimeoutMs"] >= 600000
assert vllm_e["flashboot"] is True
gpus = vllm_e["gpuTypeIds"]
assert "NVIDIA RTX A5000" in gpus or "NVIDIA L4" in gpus
assert "Tesla T4" not in gpus  # 16GB T4 is for Whisper, not 14B chat

assert wh_t["isServerless"] is True
assert "faster-whisper" in wh_t["imageName"]
assert "LORA_MODULES" not in wh_t["env"]
assert "Qwen" not in json.dumps(wh_t)
assert wh_t["env"]["MODEL_NAME"] == "base"

assert wh_e["workersMin"] == 0
assert wh_e["workersMax"] == 1
assert "Tesla T4" in wh_e["gpuTypeIds"] or "NVIDIA RTX A4000" in wh_e["gpuTypeIds"]
assert "NVIDIA H100 80GB HBM3" not in wh_e["gpuTypeIds"]

snippet = (d / "tokens.env.snippet").read_text()
assert "CPU_ONLY=1" in snippet
assert "VLLM_MODE=serverless" in snippet
assert "WHISPER_MODE=serverless" in snippet
assert "RUNPOD_VLLM_ENDPOINT_ID=" in snippet
assert "RUNPOD_WHISPER_ENDPOINT_ID=" in snippet
print("payload assertions ok")
PY

# --vllm-only must not emit a Whisper template.
DIR2="$(mktemp -d)"
bash "$SCRIPT" --dry-run --vllm-only --payload-dir "$DIR2" >/dev/null
[[ -f "$DIR2/vllm_template.json" ]] || fail "vllm-only missing vllm template"
[[ ! -f "$DIR2/whisper_template.json" ]] || fail "vllm-only must not write whisper template"

DIR3="$(mktemp -d)"
bash "$SCRIPT" --dry-run --whisper-only --payload-dir "$DIR3" >/dev/null
[[ -f "$DIR3/whisper_template.json" ]] || fail "whisper-only missing whisper template"
[[ ! -f "$DIR3/vllm_template.json" ]] || fail "whisper-only must not write vllm template"

# Network volume is attached when requested.
DIR4="$(mktemp -d)"
RUNPOD_NETWORK_VOLUME_ID=volabc bash "$SCRIPT" --dry-run --payload-dir "$DIR4" >/dev/null
python3 - "$DIR4" <<'PY' || fail "network volume not attached"
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
for name in ("vllm_endpoint.json", "whisper_endpoint.json"):
    body = json.loads((d / name).read_text())
    assert body.get("networkVolumeId") == "volabc", name
print("volume attach ok")
PY

# Real create without a key must fail.
if HF_TOKEN=hf_test_token bash "$SCRIPT" --vllm-only >/dev/null 2>"$DIR/err"; then
  fail "create without RUNPOD_API_KEY should fail"
fi
grep -q "RUNPOD_API_KEY" "$DIR/err" || fail "missing API key error"

# Help / scripts exist and are wired.
grep -q 'create_runpod_endpoints.sh' "$ROOT/install.sh" || fail "install.sh must copy create script"
grep -q 'check_whisper.sh' "$ROOT/install.sh" || fail "install.sh must copy check_whisper.sh"
grep -q 'check_whisper.sh' "$ROOT/RUNPOD.md" || fail "RUNPOD.md must mention whisper smoke test"
grep -q 'create_runpod_endpoints.sh' "$ROOT/RUNPOD.md" || fail "RUNPOD.md must mention create script"
[[ -f "$ROOT/scripts/check_whisper.sh" ]] || fail "missing check_whisper.sh"

echo "OK create_runpod_endpoints dry-run payloads"
