#!/usr/bin/env bash
# Push development to GitHub master from the dev pod after a rehearsal marker.
# Does not SSH to the production pod and does not arm the 1:00am deploy.
#
#   bash scripts/promote_to_master.sh --yes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# same   — master already is the rehearsed SHA
# ff     — master is an ancestor; a normal push fast-forwards
# lease  — master has extra commits whose file changes are already in development
# refuse — master has changes development does not have
promote_push_plan() {
  local dev_sha="$1" master_sha="$2" merge_tree dev_tree
  if [[ "$dev_sha" == "$master_sha" ]]; then
    printf 'same\n'
    return 0
  fi
  if git merge-base --is-ancestor "$master_sha" "$dev_sha"; then
    printf 'ff\n'
    return 0
  fi
  if merge_tree="$(git merge-tree --write-tree "$dev_sha" "$master_sha" 2>/dev/null)"; then
    merge_tree="${merge_tree%%$'\n'*}"
    dev_tree="$(git rev-parse "${dev_sha}^{tree}")"
    if [[ -n "$merge_tree" && "$merge_tree" == "$dev_tree" ]]; then
      printf 'lease\n'
      return 0
    fi
  fi
  printf 'refuse\n'
}

promote_main() {
  local YES REMOTE dev_sha master_sha MARKER MANIFEST ASKPASS plan migration blob tree commit
  YES=0
  [[ "${1:-}" == "--yes" ]] && YES=1
  REMOTE="${REMOTE:-origin}"

  if [[ "$YES" != "1" ]]; then
    echo "promote: refusing without --yes. The live site is unchanged." >&2
    exit 1
  fi

  if [[ -f "$ROOT/tokens.promote.env" ]]; then
    # shellcheck disable=SC1091
    set -a
    source "$ROOT/tokens.promote.env"
    set +a
  fi

  cd "$ROOT"
  git fetch "$REMOTE" development master

  dev_sha="$(git rev-parse "$REMOTE/development")"
  master_sha="$(git rev-parse "$REMOTE/master")"
  echo "development: $dev_sha"
  echo "master:      $master_sha"

  MARKER="${PROMOTE_MARKER:-$ROOT/.dev_pipeline_success}"
  [[ -f "$MARKER" ]] || { echo "promote: missing rehearsal marker $MARKER" >&2; exit 1; }
  # shellcheck disable=SC1090
  source "$MARKER"
  [[ "${SHA:-}" == "$dev_sha" ]] || { echo "promote: marker SHA ${SHA:-empty} != $dev_sha" >&2; exit 1; }
  [[ "${HEALTH:-}" == "ok" && "${ISOLATION:-}" == "ok" ]] || {
    echo "promote: rehearsal marker is not healthy" >&2
    exit 1
  }

  if [[ "${ALLOW_DESTRUCTIVE_MIGRATIONS:-0}" != "1" ]]; then
    while IFS= read -r migration; do
      [[ -n "$migration" && -f "$migration" ]] || continue
      if grep -q -E 'migrations\.(RemoveField|DeleteModel)' "$migration"; then
        echo "promote: $migration drops schema; ship that in a later night" >&2
        exit 1
      fi
    done < <(git diff --name-only "$master_sha" "$dev_sha" -- 'backend/app/**/migrations/*.py' || true)
  fi

  plan="$(promote_push_plan "$dev_sha" "$master_sha")"
  if [[ "$plan" == "refuse" ]]; then
    echo "promote: origin/master is not contained in origin/development." >&2
    echo "promote: these master commits were not rehearsed:" >&2
    git log --oneline "${dev_sha}..${master_sha}" >&2 || true
    echo "promote: merge them into development, rerun dev_pipeline.sh, then promote again." >&2
    echo "promote: arm_prod_deploy.sh cannot arm a master SHA that has no release manifest." >&2
    exit 1
  fi

  mkdir -p "$ROOT/release"
  MANIFEST="$ROOT/release/${dev_sha}.manifest"
  {
    echo "SHA=${dev_sha}"
    echo "HEALTH=${HEALTH}"
    echo "ISOLATION=${ISOLATION}"
    echo "GPU_SMOKE=${GPU_SMOKE:-0}"
    echo "MIGRATIONS=$(git diff --name-only "$master_sha" "$dev_sha" -- 'backend/app/**/migrations/*.py' | tr '\n' ' ')"
    if [[ -f "$ROOT/release/required-keys.txt" ]]; then
      while read -r key; do
        [[ -n "$key" && "$key" != \#* ]] && echo "REQUIRED ${key}"
      done < "$ROOT/release/required-keys.txt"
    fi
  } > "$MANIFEST"
  chmod 600 "$MANIFEST"

  ASKPASS=""
  cleanup_askpass() { [[ -n "${ASKPASS}" ]] && rm -f "$ASKPASS"; }
  trap cleanup_askpass EXIT

  if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    ASKPASS="$(mktemp)"
    printf '#!/bin/sh\necho "$GITHUB_TOKEN"\n' > "$ASKPASS"
    chmod 700 "$ASKPASS"
    export GIT_ASKPASS="$ASKPASS" GITHUB_TOKEN
  fi

  case "$plan" in
    same)
      echo "master already matches development — skipping branch push"
      ;;
    ff)
      echo "Promoting development → master"
      git push "$REMOTE" "$REMOTE/development:master"
      ;;
    lease)
      echo "promote: origin/master has extra commits already contained in the development tree:"
      git log --oneline "${dev_sha}..${master_sha}" || true
      echo "promote: moving master to the rehearsed SHA with --force-with-lease"
      git push --force-with-lease="refs/heads/master:${master_sha}" "$REMOTE" "${dev_sha}:master"
      ;;
    *)
      echo "promote: unexpected push plan ${plan}" >&2
      exit 1
      ;;
  esac

  # Publish the manifest without changing the master SHA.
  # The login stays active for this push. commit-tree refuses when the pod has no user.email.
  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-pastor-promote}"
  export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-promote@dev.invalid}"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-pastor-promote}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-promote@dev.invalid}"
  if git check-ref-format "refs/pastor/manifests/${dev_sha}" 2>/dev/null; then
    blob="$(git hash-object -w "$MANIFEST")"
    tree="$(printf '100644 blob %s\tmanifest\n' "$blob" | git mktree)"
    commit="$(git commit-tree "$tree" -m "release ${dev_sha}")"
    git update-ref "refs/pastor/manifests/${dev_sha}" "$commit"
    git push "$REMOTE" "refs/pastor/manifests/${dev_sha}"
  else
    echo "promote: bad manifest ref for ${dev_sha}" >&2
    exit 1
  fi

  echo "Done. The production pod is unchanged."
  echo "On the GPU pod, when you want the 1:00am Central window:"
  echo "  bash scripts/arm_prod_deploy.sh"
  cleanup_askpass
  trap - EXIT
}

if [[ "${PROMOTE_SOURCE_ONLY:-0}" != "1" && "${BASH_SOURCE[0]}" == "$0" ]]; then
  promote_main "$@"
fi
