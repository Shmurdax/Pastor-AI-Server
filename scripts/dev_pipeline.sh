#!/usr/bin/env bash
# Development CPU pod: pull development, isolate, migrate, health-check, write a marker.
# Does not push and does not arm production.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT/scripts/git_channel.sh"
# shellcheck source=/dev/null
source "$ROOT/scripts/pod_profile.sh"

WS="${WORKSPACE_ROOT:-$ROOT}"
CHANNEL="$(pastor_git_channel "$WS")"
[[ "$CHANNEL" == "development" ]] || {
  echo "dev-pipeline: refusing because channel is $CHANNEL" >&2
  exit 1
}

if [[ "${DEV_PIPELINE_SKIP_ISOLATE:-0}" != "1" ]]; then
  bash "$ROOT/scripts/isolate_dev_env.sh"
fi

if [[ -d "$WS/.git" && "${DEV_PIPELINE_SKIP_PULL:-0}" != "1" ]]; then
  git -C "$WS" fetch origin development
  git -C "$WS" checkout -B development FETCH_HEAD
fi

MODE="$(pastor_vllm_mode_name)"
[[ "$MODE" == "serverless" ]] || {
  echo "dev-pipeline: refusing local vLLM on the development pod" >&2
  exit 1
}

# shellcheck disable=SC1091
[[ -f "$WS/config.env" ]] && set -a && source "$WS/config.env" && set +a
VIMEO_TEST=""
if [[ -f "$WS/tokens.test.env" ]]; then
  VIMEO_TEST="$(grep -E '^VIMEO_FOLDER_ID=' "$WS/tokens.test.env" | tail -1 | cut -d= -f2- || true)"
fi
if [[ -z "${VIMEO_TEST:-}" ]]; then
  echo "dev-pipeline: skipping Vimeo sync (no test folder)"
fi

APP="$WS/backend/app"
if [[ "${DEV_PIPELINE_SKIP_MIGRATE:-0}" != "1" && -x "$WS/venv/bin/python" ]]; then
  (cd "$APP" && "$WS/venv/bin/python" manage.py migrate --noinput)
fi

PORT="${DJANGO_PORT:-8000}"
if [[ "${DEV_PIPELINE_SKIP_HEALTH:-0}" != "1" ]]; then
  # auth/config is public. Media and church events are premium routes:
  # 401 means Django is up and the gate is closed.
  declare -A expect_ok=(
    [/api/auth/config/]=200
    [/api/media/]="200 401"
    [/api/church-events/]="200 401"
  )
  for path in /api/auth/config/ /api/media/ /api/church-events/; do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}${path}" || true)"
    ok=0
    for allowed in ${expect_ok[$path]}; do
      [[ "$code" == "$allowed" ]] && ok=1
    done
    [[ "$ok" == "1" ]] || {
      echo "dev-pipeline: GET $path returned ${code:-000}" >&2
      exit 1
    }
  done
fi

SHA="$(git -C "$WS" rev-parse HEAD 2>/dev/null || echo unknown)"
PASTOR_GPU_SMOKE=0
if [[ "${DEV_PIPELINE_SKIP_GPU_SMOKE:-0}" != "1" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/scripts/gpu_smoke.sh"
  pastor_serverless_gpu_smoke || true
fi
GPU_SMOKE="${PASTOR_GPU_SMOKE:-0}"
mkdir -p "$WS/release"
cat > "$WS/.dev_pipeline_success" <<EOF
SHA=${SHA}
HEALTH=ok
ISOLATION=ok
GPU_SMOKE=${GPU_SMOKE}
EOF
chmod 600 "$WS/.dev_pipeline_success"
echo "dev-pipeline: success marker $SHA"
