"""Guardrails so bilingual base models (e.g. Qwen) stay in English for chat replies."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# CJK Unified Ideographs + common extension / compatibility blocks Qwen often leaks.
_CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    r"\U0002b740-\U0002b81f\U0002b820-\U0002ceaf]"
)

ENGLISH_LANGUAGE_FALLBACK = (
    "I don't have enough support in Pastor Don's notes for a complete answer on that. "
    "Ask another faith or Bible question and I'll help from there."
)

_MIN_KEEP_ENGLISH_CHARS = 80
_COMPLETE_LINE_RE = re.compile(r'[.!?]"?\s*$')


def contains_cjk(text: str | None) -> bool:
    if not text:
        return False
    return _CJK_RE.search(text) is not None


def _drop_incomplete_trailing_lines(text: str) -> str:
    """Remove lines cut off mid-sentence by a language switch (e.g. '5. Romans 12:1 — Therefore...')."""
    lines = text.splitlines()
    while lines and not _COMPLETE_LINE_RE.search(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).strip()


def sanitize_english_response(text: str | None) -> str:
    """
    Keep English-only assistant output.

    If a bilingual model drifts into Chinese mid-reply (common RAG-refusal templates),
    keep a usable English prefix when possible; otherwise use a short English fallback.
    """
    if text is None:
        return ENGLISH_LANGUAGE_FALLBACK

    cleaned = str(text).strip()
    if not cleaned:
        return ENGLISH_LANGUAGE_FALLBACK

    if not contains_cjk(cleaned):
        return cleaned

    match = _CJK_RE.search(cleaned)
    prefix = cleaned[: match.start()].rstrip(" \t\r\n,;:-") if match else ""
    prefix = _drop_incomplete_trailing_lines(prefix)

    if len(prefix) >= _MIN_KEEP_ENGLISH_CHARS:
        logger.warning("Stripped non-English characters from chat response.")
        return prefix

    logger.warning("Replaced mostly non-English chat response with English fallback.")
    return ENGLISH_LANGUAGE_FALLBACK
