"""OpenAI-compatible chat client for local vLLM or RunPod Serverless."""

from __future__ import annotations

import os
import re
from typing import Mapping, Optional
from urllib.parse import urlparse

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "vllm"}
_RUNPOD_ENDPOINT_RE = re.compile(
    r"^https://api\.runpod\.ai/v2/([^/]+?)(?:/openai/v1)?/?$",
    re.IGNORECASE,
)
_DEFAULT_LOCAL_URL = "http://vllm:8000/v1"
_DEFAULT_MODEL = "christianai"


def _env_get(env: Mapping[str, str], *keys: str, default: str = "") -> str:
    for key in keys:
        raw = env.get(key)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return default


def _placeholder_key(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return True
    return lowered in {"not-needed", "empty", "paste_here"} or "paste_here" in lowered


def normalize_vllm_base_url(url: str) -> str:
    """Return an OpenAI SDK base_url that already includes /v1."""
    trimmed = (url or "").strip().rstrip("/")
    if not trimmed:
        return _DEFAULT_LOCAL_URL
    match = _RUNPOD_ENDPOINT_RE.match(trimmed)
    if match:
        return f"https://api.runpod.ai/v2/{match.group(1)}/openai/v1"
    if trimmed.endswith("/openai/v1") or trimmed.endswith("/v1"):
        return trimmed
    return f"{trimmed}/v1"


def resolve_vllm_url(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    endpoint_id = _env_get(env, "RUNPOD_VLLM_ENDPOINT_ID")
    if endpoint_id:
        return f"https://api.runpod.ai/v2/{endpoint_id}/openai/v1"
    return normalize_vllm_base_url(_env_get(env, "VLLM_URL", default=_DEFAULT_LOCAL_URL))


def resolve_vllm_api_key(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    key = _env_get(env, "VLLM_API_KEY", "RUNPOD_API_KEY")
    if _placeholder_key(key):
        return "not-needed"
    return key


def vllm_url_is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def vllm_is_remote(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    mode = _env_get(env, "VLLM_MODE").lower()
    if mode in {"serverless", "remote", "cpu"}:
        return True
    if _env_get(env, "CPU_ONLY").lower() in {"1", "true", "yes"}:
        return True
    if _env_get(env, "RUNPOD_VLLM_ENDPOINT_ID"):
        return True
    return not vllm_url_is_local(resolve_vllm_url(env))


def resolve_vllm_model(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    return _env_get(env, "VLLM_MODEL", "CHRISTIANAI_SERVED_NAME", default=_DEFAULT_MODEL)


def get_chat_llm(
    *,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    timeout: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
    **kwargs,
):
    """LangChain ChatOpenAI pointed at local vLLM or a RunPod Serverless worker."""
    from langchain_openai import ChatOpenAI

    env = os.environ if env is None else env
    remote = vllm_is_remote(env)
    if max_tokens is None:
        max_tokens = int(_env_get(env, "CHAT_MAX_TOKENS", default="2400"))
    if timeout is None:
        default_timeout = "600" if remote else "360"
        timeout = float(_env_get(env, "CHAT_TIMEOUT_S", default=default_timeout))
    default_retries = "6" if remote else "2"
    max_retries = int(_env_get(env, "VLLM_MAX_RETRIES", default=default_retries))
    headers = {"ngrok-skip-browser-warning": "true"}
    headers.update(kwargs.pop("default_headers", None) or {})
    return ChatOpenAI(
        base_url=resolve_vllm_url(env),
        api_key=resolve_vllm_api_key(env),
        model=resolve_vllm_model(env),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        default_headers=headers,
        **kwargs,
    )
