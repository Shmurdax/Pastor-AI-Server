"""
Best-effort PII redaction for user chat queries before persistence and model calls.

Applies high-precision patterns only: emails, phone-like numbers, and US-style
street addresses. First and last names are not redacted (they caused false
positives on theological English and blocked in-scope chat retrieval).

Use `redact_user_query` for persistence; use `query_text_for_llm` when feeding the
model or retriever so `[REDACTED]` markers do not confuse generation.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Plain-language substitute for retrieval + LLM only. Storage keeps `REDACTED`.
LLM_PII_PLACEHOLDER = "someone"

_MULTI_PLACEHOLDER_RE = re.compile(
    rf"(?:\b{re.escape(LLM_PII_PLACEHOLDER)}\b\s*){{2,}}",
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# US-centric phones; extension formats and spaced digits.
_PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?)?"
    r"(?:\(\s*\d{3}\s*\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
    r"|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
    r"|\b\d{10}\b"
)

_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[NWES]?\s*[A-Za-z0-9.'\u2019]+\s+"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|"
    r"Boulevard|Blvd\.?|Court|Ct\.?|Way|Circle|Cir\.?|Place|Pl\.?|"
    r"Highway|Hwy\.?|Route|Rt\.?)\b",
    re.IGNORECASE,
)


def _redact_pattern(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(REDACTED, text)


def redact_user_query(text: str | None) -> str:
    """
    Return text with likely PII replaced by REDACTED. Empty input becomes empty string.

    Does not redact personal names.
    """
    if text is None:
        return ""
    s = str(text).strip()
    if not s:
        return ""

    s = _redact_pattern(s, _EMAIL_RE)
    s = _redact_pattern(s, _PHONE_RE)
    s = _redact_pattern(s, _STREET_RE)
    return s


def query_text_for_llm(stored_redacted: str | None) -> str:
    """
    Convert DB-safe redacted strings into natural wording for embeddings and the model.

    Literal `[REDACTED]` tokens can skew refusal behavior and retrieval; persistence
    still uses `redact_user_query` output unchanged.
    """
    if stored_redacted is None:
        return ""
    s = str(stored_redacted).strip()
    if not s:
        return ""
    s = s.replace(REDACTED, LLM_PII_PLACEHOLDER)
    s = _MULTI_PLACEHOLDER_RE.sub(f"{LLM_PII_PLACEHOLDER} ", s)
    return re.sub(r"\s+", " ", s).strip()
