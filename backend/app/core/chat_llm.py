"""OpenAI-compatible chat client for local vLLM or RunPod Serverless."""

from __future__ import annotations

import os
import re
import time
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
    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()
    endpoint_id = _env_get(env, "RUNPOD_VLLM_ENDPOINT_ID")
    if endpoint_id:
        return f"https://api.runpod.ai/v2/{endpoint_id}/openai/v1"
    return normalize_vllm_base_url(_env_get(env, "VLLM_URL", default=_DEFAULT_LOCAL_URL))


def resolve_vllm_api_key(env: Optional[Mapping[str, str]] = None) -> str:
    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()
    for candidate in (
        _env_get(env, "VLLM_API_KEY"),
        _env_get(env, "RUNPOD_API_KEY"),
    ):
        if candidate and not _placeholder_key(candidate):
            return candidate
    # RunPod Serverless rejects the local-vLLM placeholder ("not-needed")
    # with 401 invalid api key.
    if vllm_is_remote(env):
        return ""
    return "not-needed"


def vllm_url_is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def vllm_is_remote(env: Optional[Mapping[str, str]] = None) -> bool:
    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()
    mode = _env_get(env, "VLLM_MODE").lower()
    if mode in {"serverless", "remote", "cpu"}:
        return True
    if _env_get(env, "CPU_ONLY").lower() in {"1", "true", "yes"}:
        return True
    if _env_get(env, "RUNPOD_VLLM_ENDPOINT_ID"):
        return True
    return not vllm_url_is_local(resolve_vllm_url(env))


def resolve_vllm_model(env: Optional[Mapping[str, str]] = None) -> str:
    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()
    return _env_get(env, "VLLM_MODEL", "CHRISTIANAI_SERVED_NAME", default=_DEFAULT_MODEL)


_CONTEXT_LEN_RE = re.compile(r"maximum context length is (\d+) tokens", re.IGNORECASE)
_DISCOVERED_WORKER_LEN: Optional[int] = None
_DISCOVERED_WORKER_AT = 0.0
_DISCOVERED_WORKER_TTL_S = 600.0


def parse_context_length_error(exc: BaseException | str) -> Optional[int]:
    """Read the live worker window from a vLLM 400 overflow error."""
    parts = [str(exc)]
    if isinstance(exc, BaseException):
        cause = exc.__cause__ or getattr(exc, "__context__", None)
        if cause is not None:
            parts.append(str(cause))
        parts.extend(str(arg) for arg in getattr(exc, "args", ()))
    match = _CONTEXT_LEN_RE.search(" ".join(parts))
    if not match:
        return None
    return max(512, int(match.group(1)))


def remember_worker_max_model_len(length: int) -> None:
    global _DISCOVERED_WORKER_LEN, _DISCOVERED_WORKER_AT
    _DISCOVERED_WORKER_LEN = max(512, int(length))
    _DISCOVERED_WORKER_AT = time.monotonic()


def discovered_worker_max_model_len(*, ttl_s: float = _DISCOVERED_WORKER_TTL_S) -> Optional[int]:
    if _DISCOVERED_WORKER_LEN is None:
        return None
    if time.monotonic() - _DISCOVERED_WORKER_AT > max(30.0, float(ttl_s)):
        return None
    return _DISCOVERED_WORKER_LEN


def reset_discovered_worker_max_model_len_for_tests() -> None:
    global _DISCOVERED_WORKER_LEN, _DISCOVERED_WORKER_AT
    _DISCOVERED_WORKER_LEN = None
    _DISCOVERED_WORKER_AT = 0.0


def resolve_chat_context_window(env: Optional[Mapping[str, str]] = None) -> int:
    """Prompt+completion budget. Never larger than the vLLM worker's max length."""
    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()
    window = int(_env_get(env, "CHAT_CONTEXT_WINDOW", default="32768") or "32768")
    vllm_len = _env_get(env, "VLLM_MAX_MODEL_LEN")
    if vllm_len.isdigit():
        window = min(window, int(vllm_len))
    discovered = discovered_worker_max_model_len()
    if discovered:
        window = min(window, discovered)
    return max(512, window)


def estimate_chat_tokens(text: str) -> int:
    """Pessimistic token estimate for English plus XML-style prompt markup.

    chars/3 under-counted Qwen prompts and overflowed short serverless windows.
    """
    return max(1, (len(text or "") * 2 + 4) // 5)


NOTES_MARKER = "REFERENCE NOTES:\n"
REFUSAL_NOTES_SENTINEL = "No relevant sermon notes found."
EMPTY_REFERENCE_NOTES = (
    "No sermon excerpts were attached for this turn. "
    "Answer from Scripture (NKJV) and Pastor Don and Susan Nordin's teaching "
    "in several long paragraphs. Do not claim that sermon notes were missing or irrelevant."
)

# Prefer keeping retrieved notes over a long completion on short-context workers.
# 400 was enough to emit EOS after one short paragraph; keep room for 4+ long ones.
_MIN_COMPLETION_TOKENS = 2048
_MIN_NOTES_CHARS = 1600
_OPTIONAL_PROMPT_BLOCKS = (
    re.compile(r"<scope_policy>.*?</scope_policy>\n*", re.DOTALL | re.IGNORECASE),
    re.compile(r"<biblical_characters>.*?</biblical_characters>\n*", re.DOTALL | re.IGNORECASE),
    re.compile(r"<safety_protocol>.*?</safety_protocol>\n*", re.DOTALL | re.IGNORECASE),
)


def split_reference_notes(system_filled: str) -> tuple[str, str | None]:
    idx = (system_filled or "").find(NOTES_MARKER)
    if idx < 0:
        return system_filled, None
    return system_filled[: idx + len(NOTES_MARKER)], system_filled[idx + len(NOTES_MARKER) :]


def notes_are_usable(notes: str | None) -> bool:
    text = (notes or "").strip()
    return bool(text) and text != REFUSAL_NOTES_SENTINEL


def _clip_prefix(prefix: str, keep: int) -> str:
    """Shorten instruction text from the end, but keep the notes marker."""
    keep = max(1, int(keep))
    if len(prefix) <= keep:
        return prefix
    if prefix.endswith(NOTES_MARKER):
        body = prefix[: -len(NOTES_MARKER)]
        keep_body = max(200, keep - len(NOTES_MARKER))
        return body[:keep_body] + NOTES_MARKER
    return prefix[:keep]


def _clip_notes(notes: str, keep: int) -> str:
    keep = max(1, int(keep))
    if len(notes) <= keep:
        return notes
    clipped = notes[:keep]
    if "\n" in clipped:
        return clipped.rsplit("\n", 1)[0] or clipped
    if " " in clipped:
        return clipped.rsplit(" ", 1)[0] or clipped
    return clipped


def fit_chat_budget(
    system_filled: str,
    history_messages,
    question: str,
    max_completion: int,
    *,
    window: Optional[int] = None,
    safety: Optional[int] = None,
    env: Optional[Mapping[str, str]] = None,
):
    """Trim history/system so prompt + completion stays inside the model window.

    Retrieved REFERENCE NOTES are kept whenever they exist. Completion shrinks
    first; optional prompt sections shrink next. Notes are never replaced with
    the old "No relevant sermon notes found." refusal.
    """
    if window is None:
        window = resolve_chat_context_window(env)
    window = max(512, int(window))
    if safety is None:
        safety = int(_env_get(env or {}, "CHAT_TOKEN_SAFETY", default="192") or "192")
    safety = max(16, int(safety))
    hard_cap = max(128, window - 256)
    min_completion = min(_MIN_COMPLETION_TOKENS, max(768, window // 2), hard_cap)
    if window <= 8192:
        min_completion = min(min_completion, max(768, window - 2000), hard_cap)
    completion = max(min_completion, min(int(max_completion), hard_cap))

    def prompt_tokens(sys_text, history, q):
        hist_text = "\n".join(getattr(m, "content", "") or "" for m in history)
        return (
            estimate_chat_tokens(sys_text)
            + estimate_chat_tokens(hist_text)
            + estimate_chat_tokens(q)
            + 24  # role/format overhead
        )

    def over_budget(sys_text, history=None, comp=None) -> bool:
        return (
            prompt_tokens(sys_text, history if history is not None else history_msgs, question)
            + (completion if comp is None else comp)
            + safety
            > window
        )

    history_msgs = list(history_messages)
    # Follow-up answers blow a 4096 worker. Drop history so completion stays usable.
    if window <= 8192:
        history_msgs = []
    prefix, notes = split_reference_notes(system_filled)
    if notes is None:
        sys_text = system_filled
    elif notes_are_usable(notes):
        sys_text = prefix + notes
    else:
        notes = EMPTY_REFERENCE_NOTES
        sys_text = prefix + notes

    while history_msgs and over_budget(sys_text):
        if len(history_msgs) >= 2:
            history_msgs = history_msgs[2:]
        else:
            history_msgs = history_msgs[1:]

    if notes_are_usable(notes):
        target_notes = min(len(notes), _MIN_NOTES_CHARS)
        target_sys = prefix + notes[:target_notes]
        while over_budget(target_sys) and completion > _MIN_COMPLETION_TOKENS:
            completion = max(_MIN_COMPLETION_TOKENS, completion - 128)
        while over_budget(sys_text) and completion > _MIN_COMPLETION_TOKENS:
            completion = max(_MIN_COMPLETION_TOKENS, completion - 128)
        for block_re in _OPTIONAL_PROMPT_BLOCKS:
            if not over_budget(sys_text):
                break
            trimmed_prefix = block_re.sub("", prefix, count=1)
            if trimmed_prefix != prefix:
                prefix = trimmed_prefix
                sys_text = prefix + notes
        while over_budget(sys_text) and len(notes) > 400:
            overflow = (
                prompt_tokens(sys_text, history_msgs, question) + completion + safety - window
            )
            cut_chars = max(200, overflow * 3)
            notes = _clip_notes(notes, max(400, len(notes) - cut_chars))
            sys_text = prefix + notes
        while over_budget(sys_text) and len(prefix) > 900:
            overflow = (
                prompt_tokens(sys_text, history_msgs, question) + completion + safety - window
            )
            cut_chars = max(300, overflow * 3)
            prefix = _clip_prefix(prefix, max(900, len(prefix) - cut_chars))
            sys_text = prefix + notes
    else:
        while over_budget(sys_text) and completion > 128:
            completion = max(128, completion - 128)
        for block_re in _OPTIONAL_PROMPT_BLOCKS:
            if not over_budget(sys_text):
                break
            trimmed = block_re.sub("", sys_text, count=1)
            if trimmed != sys_text:
                sys_text = trimmed
        while over_budget(sys_text) and completion > 128:
            completion = max(128, completion - 128)
        while over_budget(sys_text) and len(sys_text) > 800:
            overflow = (
                prompt_tokens(sys_text, history_msgs, question) + completion + safety - window
            )
            cut_chars = max(400, overflow * 3)
            sys_text = sys_text[: max(800, len(sys_text) - cut_chars)]

    while over_budget(sys_text) and completion > 128:
        completion = max(128, completion - 64)
    if over_budget(sys_text):
        prefix, notes = split_reference_notes(sys_text)
        if notes_are_usable(notes):
            while over_budget(sys_text) and len(notes) > 240:
                notes = _clip_notes(notes, max(240, int(len(notes) * 0.7)))
                sys_text = prefix + notes
            while over_budget(sys_text) and len(prefix) > 600:
                prefix = _clip_prefix(prefix, max(600, int(len(prefix) * 0.85)))
                sys_text = prefix + notes
        else:
            while over_budget(sys_text) and len(sys_text) > 600:
                sys_text = sys_text[: max(600, int(len(sys_text) * 0.85))]

    used = prompt_tokens(sys_text, history_msgs, question)
    return sys_text, history_msgs, completion, used


def _live_vllm_api_key(fallback: str):
    """Re-read config.env at request time.

    RunPod CPU images can zero libc environ after ChatOpenAI is constructed.
    The OpenAI SDK refreshes callable keys on each request; a captured string
    can become useless if a later getenv() sees an empty environ.
    """

    def _read() -> str:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        try:
            load_workspace_env()
            live = resolve_vllm_api_key(env_with_workspace())
        except Exception:
            return fallback
        if live and not _placeholder_key(live):
            return live
        return fallback

    return _read


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

    if env is None:
        from pastor_ai.workspace_env import env_with_workspace, load_workspace_env

        load_workspace_env()
        env = env_with_workspace()
    remote = vllm_is_remote(env)
    if max_tokens is None:
        max_tokens = int(_env_get(env, "CHAT_MAX_TOKENS", default="6144"))
    if timeout is None:
        default_timeout = "600" if remote else "360"
        timeout = float(_env_get(env, "CHAT_TIMEOUT_S", default=default_timeout))
    default_retries = "6" if remote else "2"
    max_retries = int(_env_get(env, "VLLM_MAX_RETRIES", default=default_retries))
    api_key = resolve_vllm_api_key(env)
    headers = {"ngrok-skip-browser-warning": "true"}
    if api_key and not _placeholder_key(api_key):
        headers["Authorization"] = f"Bearer {api_key}"
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["RUNPOD_API_KEY"] = api_key
        os.environ["VLLM_API_KEY"] = api_key
    headers.update(kwargs.pop("default_headers", None) or {})
    client_api_key: object = api_key
    if remote and api_key:
        client_api_key = _live_vllm_api_key(api_key)
    return ChatOpenAI(
        base_url=resolve_vllm_url(env),
        api_key=client_api_key,
        model=resolve_vllm_model(env),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        default_headers=headers,
        **kwargs,
    )
