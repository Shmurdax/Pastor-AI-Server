"""Strip leaked Qwen self-critique (often Chinese) from pastoral replies."""

from __future__ import annotations

import re

from .chat_language import DEFAULT_CHAT_LANGUAGE, normalize_chat_language

# Han ideographs. Qwen often leaks rewrite notes in Chinese even on English chats.
_HAN_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]+")
_KANA_RE = re.compile(r"[\u3040-\u30ff]+")
_HR_RE = re.compile(r"\n\s*(?:[-*_]){3,}\s*\n")
_REWRITE_MARK_RE = re.compile(
    r"(?:"
    r"重塑回答.{0,240}?(?:调整后的回答|直接引文)|"
    r"以下是调整后的回答|"
    r"这段回答包含了[^。\n]{0,400}。?|"
    r"here is the (?:adjusted|revised|updated|rewritten) answer|"
    r"below is the (?:adjusted|revised) answer|"
    r"let me (?:revise|rewrite|adjust) (?:the )?(?:answer|response)|"
    r"reshape the answer to ensure.{0,240}"
    r")"
    r"[:：]?\s*",
    re.IGNORECASE | re.DOTALL,
)
_LATIN_RE = re.compile(r"[A-Za-z]")


def _strip_unexpected_scripts(text: str, language: str) -> str:
    cleaned = text or ""
    if language != "zh":
        cleaned = _HAN_RE.sub("", cleaned)
    if language != "ko":
        cleaned = _HANGUL_RE.sub("", cleaned)
    cleaned = _KANA_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _latin_ratio(text: str) -> float:
    letters = _LATIN_RE.findall(text or "")
    if not letters:
        return 0.0
    non_space = re.sub(r"\s+", "", text or "")
    if not non_space:
        return 0.0
    return len(letters) / max(1, len(non_space))


def sanitize_stream_delta(delta: str, *, language: str = DEFAULT_CHAT_LANGUAGE) -> str:
    """Drop leaked CJK from a live token when the UI language is not Chinese."""
    lang = normalize_chat_language(language)
    if not delta:
        return ""
    if lang == "zh":
        return delta
    return _HAN_RE.sub("", _HANGUL_RE.sub("", _KANA_RE.sub("", delta)))


def sanitize_chat_answer(text: str, *, language: str = DEFAULT_CHAT_LANGUAGE) -> str:
    """Remove leaked rewrite notes and keep one pastoral draft.

    Qwen often writes an English draft, then a Chinese instruction to reshape
    it, then a second English draft, then a Chinese summary. The user should
    only see the pastoral English (or the selected UI language).
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    lang = normalize_chat_language(language)
    if lang == "zh":
        return raw

    without_marks = _REWRITE_MARK_RE.sub("\n\n", raw)
    chunks = [part.strip() for part in _HR_RE.split(without_marks) if part.strip()]
    if not chunks:
        chunks = [without_marks]

    cleaned = []
    for chunk in chunks:
        piece = _strip_unexpected_scripts(chunk, lang)
        if not piece:
            continue
        if lang == "ko":
            cleaned.append(piece)
            continue
        if _latin_ratio(piece) < 0.35 and _HAN_RE.search(chunk):
            continue
        cleaned.append(piece)

    if not cleaned:
        return _strip_unexpected_scripts(raw, lang)

    if len(cleaned) == 1:
        return cleaned[0]

    # Prefer the draft that actually quoted the notes; otherwise the longest.
    best = max(cleaned, key=lambda part: (part.count('"'), len(part)))
    return best
