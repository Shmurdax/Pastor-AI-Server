#!/usr/bin/env bash
# Blackwell / MIG GPU helper parsing (no nvidia-smi required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
log() { :; }
warn() { :; }
die() { echo "FAIL die: $*" >&2; exit 1; }
source "$ROOT/gpu_runtime.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

LISTING=$'GPU 0: NVIDIA RTX PRO 6000 Blackwell Server Edition (UUID: GPU-8621401c-ec1b-fc3c-5f9a-19f236ba0b1e)\n  MIG 1g.24gb     Device  0: (UUID: MIG-a43b6575-2af5-5a45-a867-fafcaa3ac002)'

uuid="$(gpu_parse_mig_uuid "$LISTING")"
[[ "$uuid" == "MIG-a43b6575-2af5-5a45-a867-fafcaa3ac002" ]] || fail "mig uuid: $uuid"

gb="$(gpu_parse_mig_slice_gb "$LISTING")"
[[ "$gb" == "24" ]] || fail "mig gb: $gb"

gpu_is_blackwell_name "$LISTING" || fail "name should be blackwell"
gpu_cap_is_blackwell "12.0" || fail "12.0 should be blackwell"
gpu_cap_is_blackwell "10.0" || fail "10.0 should be blackwell"
gpu_cap_is_blackwell "9.0" && fail "Hopper 9.0 is not blackwell" || true
gpu_cap_is_blackwell "8.9" && fail "Ada 8.9 is not blackwell" || true

[[ "$(gpu_parse_compute_cap "12.0")" == "12.0" ]] || fail "compute cap parse"

# 24GB MIG default util leaves Whisper headroom
GPU_IS_24GB_MIG=1
[[ "$(gpu_default_vllm_mem_util)" == "0.82" ]] || fail "24gb util"
GPU_IS_24GB_MIG=0
[[ "$(gpu_default_vllm_mem_util)" == "0.90" ]] || fail "full-gpu util"

echo "OK gpu_runtime blackwell/MIG helpers"
