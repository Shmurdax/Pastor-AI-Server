#!/usr/bin/env bash
# GPU / vLLM helpers for RunPod. Sourced by install.sh and start.sh.
# Detects NVIDIA Blackwell (sm_120, including RTX PRO 6000 MIG slices) and
# installs a CUDA 12.9+ PyTorch + vLLM stack that actually has those kernels.
#
# Expects: log, warn, die, VENV_DIR (optional until venv exists).

gpu_nvidia_smi() {
  nvidia-smi "$@"
}

gpu_smi_list() {
  gpu_nvidia_smi -L 2>/dev/null || true
}

gpu_parse_mig_uuid() {
  # Prefer the MIG instance UUID over the parent GPU UUID.
  printf '%s\n' "${1:-}" | grep -oE 'MIG-[0-9a-fA-F-]+' | head -1 || true
}

gpu_parse_mig_slice_gb() {
  # "MIG 1g.24gb" → 24
  printf '%s\n' "${1:-}" | grep -oiE '[0-9]+g\.[0-9]+gb' | head -1 | grep -oE '[0-9]+gb' | tr -d 'GBgb' || true
}

gpu_parse_compute_cap() {
  # "12.0" from nvidia-smi --query-gpu=compute_cap
  printf '%s\n' "${1:-}" | grep -oE '^[0-9]+\.[0-9]+' | head -1 || true
}

gpu_is_blackwell_name() {
  printf '%s\n' "${1:-}" | grep -qiE 'Blackwell|RTX PRO 6000|GB200|B200|RTX 50[0-9]{2}'
}

gpu_cap_is_blackwell() {
  local cap="${1:-}"
  local major="${cap%%.*}"
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  # Hopper is 9.x. Blackwell datacenter is 10.x; consumer/PRO is 12.x.
  (( major >= 10 ))
}

gpu_detect() {
  GPU_NAME=""
  GPU_MIG_UUID=""
  GPU_MIG_GB=""
  GPU_COMPUTE_CAP=""
  GPU_CUDA_VISIBLE=""
  GPU_IS_BLACKWELL=0
  GPU_IS_24GB_MIG=0
  local listing cap_raw
  listing="$(gpu_smi_list)"
  GPU_NAME="$(printf '%s\n' "$listing" | head -1 | sed 's/^GPU [0-9]*: //; s/ (UUID:.*//' || true)"
  GPU_MIG_UUID="$(gpu_parse_mig_uuid "$listing")"
  GPU_MIG_GB="$(gpu_parse_mig_slice_gb "$listing")"
  cap_raw="$(gpu_nvidia_smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ' || true)"
  GPU_COMPUTE_CAP="$(gpu_parse_compute_cap "$cap_raw")"
  if [[ -n "$GPU_MIG_UUID" ]]; then
    GPU_CUDA_VISIBLE="$GPU_MIG_UUID"
  elif command -v nvidia-smi >/dev/null 2>&1; then
    GPU_CUDA_VISIBLE="0"
  fi
  if gpu_is_blackwell_name "$listing" || gpu_cap_is_blackwell "$GPU_COMPUTE_CAP"; then
    GPU_IS_BLACKWELL=1
  fi
  if [[ "$GPU_MIG_GB" == "24" ]]; then
    GPU_IS_24GB_MIG=1
  fi
}

gpu_default_vllm_mem_util() {
  # 24GB MIG must leave a few GB for Whisper; 48GB+ can keep 0.90.
  if [[ "${GPU_IS_24GB_MIG:-0}" == "1" ]]; then
    echo "0.82"
  else
    echo "0.90"
  fi
}

gpu_free_mib() {
  # MIG-enabled cards often return "[Insufficient Permissions]" for memory.free.
  local raw
  raw="$(gpu_nvidia_smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ' || true)"
  [[ "$raw" =~ ^[0-9]+$ ]] || return 0
  echo "$raw"
}

gpu_torch_index_url() {
  if [[ "${GPU_IS_BLACKWELL:-0}" == "1" ]]; then
    echo "https://download.pytorch.org/whl/cu129"
  else
    echo "https://download.pytorch.org/whl/cu128"
  fi
}

gpu_venv_python() {
  if [[ -n "${VENV_DIR:-}" && -x "${VENV_DIR}/bin/python" ]]; then
    echo "${VENV_DIR}/bin/python"
  else
    command -v python3
  fi
}

gpu_cuda13_lib_dir() {
  local py
  py="$(gpu_venv_python)" || return 0
  "$py" - <<'PY'
import pathlib
try:
    import nvidia
except Exception:
    raise SystemExit(0)
root = pathlib.Path(nvidia.__file__).resolve().parent
for path in root.rglob("libcudart.so.13"):
    print(path.parent)
    break
PY
}

gpu_export_cuda_libs() {
  local dir
  dir="$(gpu_cuda13_lib_dir || true)"
  if [[ -n "${dir:-}" && -d "$dir" ]]; then
    export LD_LIBRARY_PATH="${dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  fi
}

gpu_torch_supports_device() {
  local py
  py="$(gpu_venv_python)" || return 1
  "$py" - <<'PY'
import sys
try:
    import torch
except Exception:
    sys.exit(1)
archs = []
if hasattr(torch.cuda, "get_arch_list"):
    try:
        archs = list(torch.cuda.get_arch_list() or [])
    except Exception:
        archs = []
cuda = str(getattr(torch.version, "cuda", "") or "")
need = None
if torch.cuda.is_available():
    try:
        major, minor = torch.cuda.get_device_capability(0)
        need = f"sm_{major}{minor}"
    except Exception:
        need = None
ok = True
if need:
    ok = need in archs or need.replace("sm_", "compute_") in archs
# Blackwell (12.x) also needs a CUDA 12.8+ runtime even if arch list is empty.
try:
    cuda_maj = float(cuda.split(".")[0] + "." + (cuda.split(".")[1] if "." in cuda else "0"))
except Exception:
    cuda_maj = 0.0
if need and need.startswith("sm_12") and cuda_maj < 12.8:
    ok = False
if need and need.startswith("sm_10") and cuda_maj < 12.8:
    ok = False
sys.exit(0 if ok else 1)
PY
}

gpu_install_vllm_stack() {
  local py pip_bin index extra
  [[ -n "${VENV_DIR:-}" && -x "${VENV_DIR}/bin/pip" ]] || die "venv missing at ${VENV_DIR:-unset}"
  pip_bin="${VENV_DIR}/bin/pip"
  py="${VENV_DIR}/bin/python"
  index="$(gpu_torch_index_url)"
  extra=("--extra-index-url" "$index")
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.cache/pip}"
  export TMPDIR="${TMPDIR:-/workspace/tmp}"
  mkdir -p "$PIP_CACHE_DIR" "$TMPDIR"
gpu_install_vllm_stack() {
  local py pip_bin index extra
  [[ -n "${VENV_DIR:-}" && -x "${VENV_DIR}/bin/pip" ]] || die "venv missing at ${VENV_DIR:-unset}"
  pip_bin="${VENV_DIR}/bin/pip"
  py="${VENV_DIR}/bin/python"
  index="$(gpu_torch_index_url)"
  extra=("--extra-index-url" "$index")
  export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.cache/pip}"
  export TMPDIR="${TMPDIR:-/workspace/tmp}"
  mkdir -p "$PIP_CACHE_DIR" "$TMPDIR"
  if [[ "${GPU_IS_BLACKWELL:-0}" == "1" ]]; then
    log "Installing vLLM + PyTorch CUDA 12.9+ for Blackwell (sm_120)"
    "$pip_bin" uninstall -y torch torchvision torchaudio torchcodec vllm 2>/dev/null || true
    # Official vLLM wheels ship CUDA 12.9 kernels; they pull a matching torch.
    "$pip_bin" install --upgrade --cache-dir "$PIP_CACHE_DIR" "vllm>=0.11" "${extra[@]}" \
      || "$pip_bin" install --upgrade --cache-dir "$PIP_CACHE_DIR" vllm --extra-index-url https://download.pytorch.org/whl/cu128 \
      || die "vLLM install failed for Blackwell"
    gpu_export_cuda_libs
  else
    log "Installing PyTorch CUDA 12.8 + vLLM 0.8.5"
    "$pip_bin" install --upgrade --cache-dir "$PIP_CACHE_DIR" torch torchvision torchaudio --index-url "$index"
    "$pip_bin" install --cache-dir "$PIP_CACHE_DIR" "vllm==0.8.5" \
      || "$pip_bin" install --cache-dir "$PIP_CACHE_DIR" "vllm==0.7.3" \
      || die "vLLM install failed"
    "$pip_bin" install --cache-dir "$PIP_CACHE_DIR" "transformers==4.51.3" "tokenizers==0.21.1" || true
  fi
  "$pip_bin" uninstall -y torchcodec torch_c_dlpack_ext 2>/dev/null || true
  log "Python GPU stack: torch $($py -c 'import torch; print(torch.__version__)') vllm $($py -c 'import vllm; print(vllm.__version__)')"
}

gpu_ensure_vllm_stack() {
  gpu_detect
  if gpu_torch_supports_device; then
    return 0
  fi
  warn "PyTorch/vLLM in $VENV_DIR cannot run this GPU (need CUDA 12.9+ kernels for Blackwell sm_120)"
  gpu_install_vllm_stack
  gpu_torch_supports_device || warn "GPU stack installed but torch still reports missing kernels — check ${LOG_DIR:-/tmp}/vllm.log"
}
