"""Strip leaked Qwen self-critique (often Chinese) from pastoral replies."""

from __future__ import annotations

import re

from .chat_language import DEFAULT_CHAT_LANGUAGE, normalize_chat_language

# Han ideographs. Qwen often leaks rewrite notes in Chinese even on English chats.
_HAN_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]+")
_HAN_BLOCK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]{2,}")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]+")
_KANA_RE = re.compile(r"[\u3040-\u30ff]+")
_CJK_PUNCT_RE = re.compile(r"[\u3000-\u303f\uff00-\uffef]+")
_HR_RE = re.compile(r"\n\s*(?:[-*_]){3,}\s*\n")
_SPLIT = "\n<<<DRAFT>>>\n"
_REWRITE_MARK_RE = re.compile(
    r"(?:"
    r"重塑回答.{0,240}?(?:调整后的回答|直接引文)|"
    r"以下是(?:调整后的|改写后的|修改后的)?回答|"
    r"这段回答包含了[^。\n]{0,400}。?|"
    r"(?:让我|我来)?(?:重新|再次)?(?:调整|改写|重塑|修改)(?:一下)?(?:这个|该)?回答|"
    r"here is the (?:adjusted|revised|updated|rewritten|corrected) (?:answer|response)|"
    r"below is the (?:adjusted|revised|updated|rewritten) (?:answer|response)|"
    r"let me (?:revise|rewrite|adjust|reshape) (?:the )?(?:answer|response)|"
    r"i(?:'ll| will) now (?:revise|rewrite|adjust) (?:the )?(?:answer|response)|"
    r"reshape the answer to ensure.{0,240}|"
    r"the (?:adjusted|revised|rewritten) (?:answer|response)\s*(?:is|:)"
    r")"
    r"[:：]?\s*",
    re.IGNORECASE | re.DOTALL,
)
_REMINDER_ECHO_RE = re.compile(
    r"\n?\s*\[Write the reply only in [^\]]{0,240}\]\s*$",
    re.IGNORECASE,
)
_LATIN_RE = re.compile(r"[A-Za-z]")
_DRAFT_HEADING_RE = re.compile(
    r"^(?:here is|below is|adjusted|revised|rewritten|updated)\b.{0,80}$",
    re.IGNORECASE,
)


def _strip_unexpected_scripts(text: str, language: str) -> str:
    cleaned = text or ""
    if language != "zh":
        cleaned = _HAN_RE.sub("", cleaned)
        cleaned = _CJK_PUNCT_RE.sub("", cleaned)
    if language != "ko":
        cleaned = _HANGUL_RE.sub("", cleaned)
    cleaned = _KANA_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def _latin_ratio(text: str) -> float:
    letters = _LATIN_RE.findall(text or "")
    if not letters:
        return 0.0
    non_space = re.sub(r"\s+", "", text or "")
    if not non_space:
        return 0.0
    return len(letters) / max(1, len(non_space))


def looks_like_rewrite_leak(text: str, *, language: str = DEFAULT_CHAT_LANGUAGE) -> bool:
    """True when Qwen started a rewrite plan or switched into unexpected CJK."""
    raw = text or ""
    if not raw:
        return False
    lang = normalize_chat_language(language)
    if _REWRITE_MARK_RE.search(raw):
        return True
    if lang != "zh" and _HAN_BLOCK_RE.search(raw):
        return True
    if lang != "ko" and _HANGUL_RE.search(raw):
        return True
    if _KANA_RE.search(raw):
        return True
    return False


def sanitize_stream_delta(delta: str, *, language: str = DEFAULT_CHAT_LANGUAGE) -> str:
    """Drop leaked CJK from a live token when the UI language is not Chinese."""
    lang = normalize_chat_language(language)
    if not delta:
        return ""
    if lang == "zh":
        return delta
    cleaned = delta
    cleaned = _HAN_RE.sub("", cleaned)
    cleaned = _CJK_PUNCT_RE.sub("", cleaned)
    if lang != "ko":
        cleaned = _HANGUL_RE.sub("", cleaned)
    cleaned = _KANA_RE.sub("", cleaned)
    return cleaned


def _split_into_drafts(text: str) -> list[str]:
    marked = _REWRITE_MARK_RE.sub(_SPLIT, text or "")
    marked = _HAN_BLOCK_RE.sub(_SPLIT, marked)
    parts: list[str] = []
    for piece in marked.split("<<<DRAFT>>>"):
        for sub in _HR_RE.split(piece):
            chunk = sub.strip()
            if chunk:
                parts.append(chunk)
    return parts or [text or ""]


def _extract_latin_spans(text: str, language: str) -> list[str]:
    spans = []
    for piece in _HAN_BLOCK_RE.split(text or ""):
        cleaned = _strip_unexpected_scripts(piece, language)
        cleaned = _REWRITE_MARK_RE.sub("", cleaned).strip()
        if len(cleaned) >= 40 and (language == "ko" or _latin_ratio(cleaned) >= 0.45):
            spans.append(cleaned)
    return spans


def sanitize_chat_answer(text: str, *, language: str = DEFAULT_CHAT_LANGUAGE) -> str:
    """Remove leaked rewrite notes and keep one pastoral draft.

    Qwen often writes an English draft, then a Chinese instruction to reshape
    it, then a second English draft, then a Chinese summary. The user should
    only see the pastoral English (or the selected UI language). After a long
    session the same leak also shows up as mixed Chinese in a single reply.
    """
    raw = _REMINDER_ECHO_RE.sub("", (text or "").strip()).strip()
    if not raw:
        return ""
    lang = normalize_chat_language(language)
    if lang == "zh":
        return raw

    cleaned = []
    for chunk in _split_into_drafts(raw):
        piece = _strip_unexpected_scripts(chunk, lang)
        piece = _REWRITE_MARK_RE.sub("", piece).strip()
        piece = _REMINDER_ECHO_RE.sub("", piece).strip()
        if not piece:
            continue
        if _DRAFT_HEADING_RE.match(piece) and len(piece) < 80:
            continue
        if lang == "ko":
            cleaned.append(piece)
            continue
        if _latin_ratio(piece) < 0.35:
            continue
        cleaned.append(piece)

    if not cleaned:
        salvaged = _extract_latin_spans(raw, lang)
        if salvaged:
            if _REWRITE_MARK_RE.search(raw):
                return max(salvaged, key=len)
            return "\n\n".join(salvaged)
        return _strip_unexpected_scripts(raw, lang)

    if len(cleaned) == 1:
        return cleaned[0]

    # Competing drafts (rewrite plan or ---): keep the quoted/longest one.
    # Mixed Chinese in one reply: stitch the English pieces back together.
    if _REWRITE_MARK_RE.search(raw) or _HR_RE.search("\n" + raw + "\n"):
        return max(cleaned, key=lambda part: (part.count('"'), len(part)))
    return "\n\n".join(cleaned)


def sanitize_history_text(
    text: str,
    *,
    language: str = DEFAULT_CHAT_LANGUAGE,
    is_user: bool = False,
) -> str:
    """Keep prior turns from re-seeding Chinese into the next prompt."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if is_user:
        return _strip_unexpected_scripts(raw, normalize_chat_language(language))
    return sanitize_chat_answer(raw, language=language)
