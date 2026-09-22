"""Read the live git checkout and DEPLOYED_* stamp files.

Used by GET /api/health/ so a RunPod volume cannot look like the latest
master while HEAD, origin, or a dirty overlay disagree.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def workspace_root() -> Path:
    env = (os.environ.get("WORKSPACE_ROOT") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _git(ws: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(ws), *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").strip()


def _tracked_dirty(ws: Path) -> bool:
    porcelain = _git(ws, "status", "--porcelain", "--untracked-files=no")
    for line in porcelain.splitlines():
        if "frontend/build/" in line:
            continue
        if line.strip():
            return True
    return False


def read_deploy_status(ws: Path | None = None) -> dict[str, object]:
    root = ws if ws is not None else workspace_root()
    git_dir = root / ".git"
    channel = _read_text(root / ".git_channel") or _read_text(root / "DEPLOYED_CHANNEL") or "master"
    sha = _git(root, "rev-parse", "HEAD") if git_dir.is_dir() else ""
    oneline = _git(root, "log", "-1", "--oneline") if git_dir.is_dir() else ""
    origin_sha = ""
    if git_dir.is_dir() and channel:
        origin_sha = _git(root, "rev-parse", f"refs/remotes/origin/{channel}")
    if not origin_sha:
        origin_sha = _read_text(root / "DEPLOYED_ORIGIN_SHA")
    dirty = _tracked_dirty(root) if git_dir.is_dir() else False
    stamp_sha = _read_text(root / "DEPLOYED_SHA") or _read_text(root / "DEPLOYED_MASTER_SHA")
    deployed_at = _read_text(root / "DEPLOYED_AT")
    sync_error = _read_text(root / "DEPLOYED_SYNC_ERROR")
    in_sync = bool(sha) and bool(origin_sha) and sha == origin_sha and not dirty
    return {
        "ok": True,
        "git_channel": channel,
        "git_sha": sha,
        "git_oneline": oneline,
        "origin_sha": origin_sha,
        "deployed_sha": stamp_sha,
        "deployed_at": deployed_at,
        "dirty": dirty,
        "in_sync": in_sync,
        "sync_error": sync_error,
    }
