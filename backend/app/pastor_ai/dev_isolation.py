"""Refuse to boot a development pod that can still reach production users."""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

PRODUCTION_HOST = "christianaiapophatictestdomain.com"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _denylist(path: str) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {
        "endpoint": set(),
        "mailchimp_audience": set(),
        "vimeo_folder": set(),
    }
    if not path:
        return groups
    file = Path(path)
    if not file.is_file():
        return groups
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or " " not in line:
            continue
        kind, value = line.split(None, 1)
        kind = kind.strip().lower()
        value = value.strip()
        if kind in groups and value:
            groups[kind].add(value)
    return groups


def _host_of(url: str) -> str:
    text = (url or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.split("/", 1)[0]
    if text.startswith("["):
        return text.split("]", 1)[0].strip("[]")
    return text.split(":", 1)[0]


def _is_loopback(url_or_host: str) -> bool:
    host = _host_of(url_or_host)
    return host in LOOPBACK_HOSTS


def _is_local_vllm(url: str) -> bool:
    host = _host_of(url)
    return host in LOOPBACK_HOSTS or host == "vllm"


def development_isolation_problems(env: Mapping[str, str]) -> list[str]:
    """Return reasons a development environment must not boot. Empty if safe."""
    if (env.get("PASTOR_ENV") or "").strip().lower() != "development":
        return []

    problems: list[str] = []
    stripe = (env.get("STRIPE_SECRET_KEY") or "").strip()
    publishable = (env.get("STRIPE_PUBLISHABLE_KEY") or "").strip()
    if stripe.startswith("sk_live_"):
        problems.append("STRIPE_SECRET_KEY is a live key")
    if publishable.startswith("pk_live_"):
        problems.append("STRIPE_PUBLISHABLE_KEY is a live key")

    public = (env.get("PUBLIC_APP_URL") or "") + " " + (env.get("DJANGO_ALLOWED_HOSTS") or "")
    if PRODUCTION_HOST in public:
        problems.append(f"public host contains {PRODUCTION_HOST}")

    if (env.get("CLOUDFLARE_TUNNEL_TOKEN") or "").strip():
        problems.append("CLOUDFLARE_TUNNEL_TOKEN is set")

    postgres_host = (env.get("POSTGRES_HOST") or "127.0.0.1").strip()
    if not _is_loopback(postgres_host):
        problems.append("POSTGRES_HOST is not loopback")

    qdrant = (env.get("QDRANT_URL") or "http://127.0.0.1:6333").strip()
    if not _is_loopback(qdrant):
        problems.append("QDRANT_URL is not loopback")

    vllm = (env.get("VLLM_URL") or "").strip()
    if vllm and _is_local_vllm(vllm):
        problems.append("VLLM_URL is local; development must use its serverless endpoint")

    denied = _denylist((env.get("PASTOR_ISOLATION_DENYLIST") or "").strip())
    endpoint = (env.get("RUNPOD_VLLM_ENDPOINT_ID") or "").strip()
    whisper = (env.get("RUNPOD_WHISPER_ENDPOINT_ID") or "").strip()
    for item in (endpoint, whisper, vllm):
        if item and any(blocked and blocked in item for blocked in denied["endpoint"]):
            problems.append("RunPod endpoint is on the production denylist")
            break

    sandbox = {
        part.strip().lower()
        for part in (env.get("GMAIL_SANDBOX_SENDERS") or "").split(",")
        if part.strip()
    }
    sender = (env.get("GMAIL_SENDER") or "").strip()
    smtp_user = (env.get("EMAIL_HOST_USER") or "").strip()
    gmail_on = any(
        (env.get(key) or "").strip()
        for key in (
            "GMAIL_SERVICE_ACCOUNT_JSON",
            "GMAIL_SERVICE_ACCOUNT_FILE",
            "GOOGLE_REFRESH_TOKEN",
            "EMAIL_HOST_PASSWORD",
        )
    )
    if gmail_on and sender.lower() not in sandbox and smtp_user.lower() not in sandbox:
        problems.append("outbound mail is configured for a sender outside the sandbox list")

    audience = (env.get("MAILCHIMP_AUDIENCE_ID") or "").strip()
    if audience and audience in denied["mailchimp_audience"]:
        problems.append("MAILCHIMP_AUDIENCE_ID is the production audience")

    return problems


def assert_development_isolated(env: Mapping[str, str] | None = None) -> None:
    problems = development_isolation_problems(env if env is not None else os.environ)
    if problems:
        raise RuntimeError(
            "Development pod is not isolated from production: " + "; ".join(problems)
        )
