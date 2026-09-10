"""Translate chat queries and replies across supported display languages."""

from __future__ import annotations

import logging
import re

from .chat_language import (
    DEFAULT_CHAT_LANGUAGE,
    language_display_name,
    normalize_chat_language,
)

logger = logging.getLogger(__name__)

_QUERY_TO_ENGLISH_SYSTEM = (
    "You translate a church chatbot user's question into English for search.\n"
    "Rules:\n"
    "- Translate into clear English while keeping the same meaning.\n"
    "- Keep Bible book names, references, and proper names recognizable.\n"
    "- Do not answer the question.\n"
    "- Do not add commentary, preface, or labels—return only the English question.\n"
)

_REPLY_SYSTEM = (
    "You translate pastoral chatbot replies for Pastor Don Nordin's ministry site.\n"
    "Rules:\n"
    "- Translate the user's text into {language_name}.\n"
    "- Preserve markdown formatting (bold, italics, lists, blockquotes).\n"
    "- Keep Bible references and NKJV Scripture quotations in English (including text inside "
    "quotation marks that is clearly Scripture).\n"
    "- Keep word-for-word quotations from Pastor Don Nordin or Susan Nordin in English.\n"
    "- Do not add commentary, preface, or labels—return only the translated reply.\n"
    "- Do not echo or restate the user's question as a markdown blockquote or heading.\n"
    "- Keep the same pastoral tone and meaning.\n"
)

_FENCE_RE = re.compile(r"^```(?:\w+)?\s*|\s*```$", re.MULTILINE)


def _chat_llm():
    from .chat_llm import get_chat_llm

    return get_chat_llm(temperature=0.2)


def _clean_translation(content: str) -> str:
    text = (content or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    return text


def _invoke_translate(system: str, human: str) -> str | None:
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        llm = _chat_llm()
        response = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        content = _clean_translation(getattr(response, "content", None) or "")
        return content or None
    except Exception:
        logger.exception("Translate invocation failed.")
        return None


def translate_to_english(text: str) -> str:
    """Translate a user question into English for retrieval and generation."""
    cleaned = (text if isinstance(text, str) else str(text or "")).strip()
    if not cleaned:
        return ""
    human = (
        "Translate this user question into English. Return only the English question.\n\n"
        f"{cleaned}"
    )
    translated = _invoke_translate(_QUERY_TO_ENGLISH_SYSTEM, human)
    return translated or cleaned


def translate_reply(text: str, language: str) -> str:
    """Translate one pastoral reply into a supported display language."""
    cleaned = (text if isinstance(text, str) else str(text or "")).strip()
    if not cleaned:
        return ""
    lang = normalize_chat_language(language)
    name = language_display_name(lang)
    human = (
        f"Translate the following pastoral reply into {name}. "
        "Return only the translated reply.\n\n"
        f"{cleaned}"
    )
    translated = _invoke_translate(_REPLY_SYSTEM.format(language_name=name), human)
    return translated or cleaned


def english_search_query(user_text: str, language: str) -> str:
    """Inbound: display-language question → English for Qdrant + the chat model."""
    cleaned = (user_text if isinstance(user_text, str) else str(user_text or "")).strip()
    if not cleaned:
        return ""
    if normalize_chat_language(language) == DEFAULT_CHAT_LANGUAGE:
        return cleaned
    return translate_to_english(cleaned)


def display_reply(english_reply: str, language: str) -> str:
    """Outbound: English answer → selected display language (es/fr/pt/de/ko/zh/en)."""
    cleaned = (
        english_reply if isinstance(english_reply, str) else str(english_reply or "")
    ).strip()
    if not cleaned:
        return ""
    if normalize_chat_language(language) == DEFAULT_CHAT_LANGUAGE:
        return cleaned
    return translate_reply(cleaned, language)


def translate_texts(texts, language: str) -> list[str]:
    """Translate a list of reply strings into the target language."""
    lang = normalize_chat_language(language)
    name = language_display_name(lang)
    cleaned = [(t if isinstance(t, str) else str(t or "")).strip() for t in texts]
    if not cleaned:
        return []

    system = _REPLY_SYSTEM.format(language_name=name)
    parts = []
    for i, text in enumerate(cleaned, start=1):
        parts.append(f"<<<ITEM {i}>>>\n{text}\n<<<END ITEM {i}>>>")
    human = (
        f"Translate each ITEM into {name}. Return every item with the same "
        f"<<<ITEM n>>> / <<<END ITEM n>>> markers and no extra text.\n\n"
        + "\n\n".join(parts)
    )

    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        llm = _chat_llm()
        response = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        content = (getattr(response, "content", None) or "").strip()
    except Exception:
        logger.exception("Batch translate failed; translating items individually.")
        return [translate_reply(text, lang) for text in cleaned]

    parsed = _parse_numbered_items(content, len(cleaned))
    if parsed is None:
        logger.warning("Translate parse failed; translating items individually.")
        return [translate_reply(text, lang) for text in cleaned]
    return parsed


def _parse_numbered_items(content: str, expected: int):
    pattern = re.compile(
        r"<<<ITEM\s+(\d+)>>>\s*(.*?)\s*<<<END ITEM\s+\1>>>",
        re.IGNORECASE | re.DOTALL,
    )
    found = {int(m.group(1)): m.group(2).strip() for m in pattern.finditer(content)}
    if len(found) < expected:
        return None
    out = []
    for i in range(1, expected + 1):
        if i not in found or not found[i]:
            return None
        out.append(found[i])
    return out
