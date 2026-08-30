"""Translate chat reply text into the user's selected display language."""

from __future__ import annotations

import logging
import re

from .chat_language import language_display_name, normalize_chat_language

logger = logging.getLogger(__name__)

_TRANSLATE_SYSTEM = (
    "You translate pastoral chatbot replies for Pastor Don Nordin's ministry site.\n"
    "Rules:\n"
    "- Translate the user's text into {language_name}.\n"
    "- Preserve markdown formatting (bold, italics, lists, blockquotes).\n"
    "- Keep Bible references and NKJV Scripture quotations in English (including text inside "
    "quotation marks that is clearly Scripture).\n"
    "- Do not add commentary, preface, or labels—return only the translated reply.\n"
    "- Do not echo or restate the user's question as a markdown blockquote or heading.\n"
    "- Keep the same pastoral tone and meaning.\n"
)


def _chat_llm():
    import os

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        base_url=os.getenv("VLLM_URL", "http://vllm:8000/v1"),
        api_key="not-needed",
        model=os.getenv("VLLM_MODEL", "christianai"),
        temperature=0.2,
        max_tokens=int(os.getenv("CHAT_MAX_TOKENS", "1200")),
        timeout=float(os.getenv("CHAT_TIMEOUT_S", "120")),
        default_headers={"ngrok-skip-browser-warning": "true"},
    )


def translate_texts(texts, language: str) -> list[str]:
    """Translate a list of reply strings into the target language."""
    from langchain_core.messages import HumanMessage, SystemMessage

    lang = normalize_chat_language(language)
    name = language_display_name(lang)
    cleaned = [(t if isinstance(t, str) else str(t or "")).strip() for t in texts]
    if not cleaned:
        return []
    if lang == "en":
        # Still run through the model only when source is clearly non-English? For simplicity,
        # translate into English when requested so switching back works.
        pass

    system = _TRANSLATE_SYSTEM.format(language_name=name)
    # Batch with numbered blocks so one call covers the visible chat thread.
    parts = []
    for i, text in enumerate(cleaned, start=1):
        parts.append(f"<<<ITEM {i}>>>\n{text}\n<<<END ITEM {i}>>>")
    human = (
        f"Translate each ITEM into {name}. Return every item with the same "
        f"<<<ITEM n>>> / <<<END ITEM n>>> markers and no extra text.\n\n"
        + "\n\n".join(parts)
    )

    try:
        llm = _chat_llm()
        response = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        content = (getattr(response, "content", None) or "").strip()
    except Exception:
        logger.exception("Batch translate failed; returning originals.")
        return cleaned

    parsed = _parse_numbered_items(content, len(cleaned))
    if parsed is None:
        logger.warning("Translate parse failed; returning originals.")
        return cleaned
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
