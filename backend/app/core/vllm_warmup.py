"""Kick the serverless vLLM worker so it starts while the user is still browsing."""

from __future__ import annotations

import logging
import threading
import time
import urllib.request
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_last_started = 0.0
DEFAULT_COOLDOWN_S = 45.0


def _cooldown_s(env: Optional[Mapping[str, str]] = None) -> float:
    from .chat_llm import _env_get

    raw = _env_get(env or {}, "CHAT_WARMUP_COOLDOWN_S", default=str(int(DEFAULT_COOLDOWN_S)))
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_COOLDOWN_S


def warmup_vllm_worker(
    *,
    cooldown_s: Optional[float] = None,
    timeout_s: float = 8.0,
    env: Optional[Mapping[str, str]] = None,
    wait: bool = False,
) -> dict:
    """Start (or no-op) a background GET to the OpenAI /models route.

    RunPod scales a worker when the first request arrives. A short client
    timeout still queues that request, so the GPU can boot while the user types.
    """
    global _last_started
    from .chat_llm import resolve_vllm_api_key, resolve_vllm_url

    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()

    gap = _cooldown_s(env) if cooldown_s is None else max(5.0, float(cooldown_s))
    now = time.monotonic()
    with _lock:
        remaining = gap - (now - _last_started)
        if remaining > 0 and _last_started > 0:
            return {"ok": True, "warming": False, "skipped": True, "retry_after_s": int(remaining)}
        _last_started = now

    url = resolve_vllm_url(env).rstrip("/") + "/models"
    api_key = resolve_vllm_api_key(env)

    def _ping():
        req = urllib.request.Request(url, method="GET")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=max(2.0, float(timeout_s))) as resp:
                logger.info("vLLM warmup ping status=%s", getattr(resp, "status", "?"))
        except Exception:
            logger.info("vLLM warmup ping dispatched (worker may still be starting)")

    thread = threading.Thread(target=_ping, name="vllm-warmup", daemon=True)
    thread.start()
    if wait:
        thread.join(timeout=max(2.0, float(timeout_s)) + 1)
    return {"ok": True, "warming": True, "skipped": False}


def reset_warmup_state_for_tests():
    global _last_started
    with _lock:
        _last_started = 0.0
