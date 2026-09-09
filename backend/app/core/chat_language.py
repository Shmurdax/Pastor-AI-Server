"""Normalize chat UI language codes and build LLM language instructions."""

from __future__ import annotations

SUPPORTED_CHAT_LANGUAGES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "pt": "Portuguese",
    "de": "German",
    "ko": "Korean",
    "zh": "Simplified Chinese",
}

DEFAULT_CHAT_LANGUAGE = "en"


def normalize_chat_language(raw) -> str:
    """Return a supported language code; default to English."""
    if raw is None:
        return DEFAULT_CHAT_LANGUAGE
    text = str(raw).strip().lower().replace("_", "-")
    if not text:
        return DEFAULT_CHAT_LANGUAGE
    if text in SUPPORTED_CHAT_LANGUAGES:
        return text
    short = text.split("-", 1)[0]
    if short in SUPPORTED_CHAT_LANGUAGES:
        return short
    # Common aliases
    aliases = {
        "spa": "es",
        "esp": "es",
        "fra": "fr",
        "fre": "fr",
        "por": "pt",
        "deu": "de",
        "ger": "de",
        "kor": "ko",
        "chi": "zh",
        "zho": "zh",
        "cn": "zh",
        "zh-cn": "zh",
        "zh-hans": "zh",
        "zh-hant": "zh",
    }
    if text in aliases:
        return aliases[text]
    if short in aliases:
        return aliases[short]
    return DEFAULT_CHAT_LANGUAGE


def language_display_name(code: str) -> str:
    return SUPPORTED_CHAT_LANGUAGES.get(
        normalize_chat_language(code),
        SUPPORTED_CHAT_LANGUAGES[DEFAULT_CHAT_LANGUAGE],
    )


def language_reply_instruction(code: str) -> str:
    """System-prompt block so the model answers in the user's UI language."""
    normalized = normalize_chat_language(code)
    name = language_display_name(normalized)
    if normalized == DEFAULT_CHAT_LANGUAGE:
        return (
            "<language>\n"
            "Write your entire reply in English.\n"
            "Do not switch into another language mid-response.\n"
            "Never write Chinese, Japanese, or Korean.\n"
            "Never write hidden notes, self-critique, or instructions to reshape, "
            "adjust, or evaluate the answer. Output only the pastoral reply the user should read.\n"
            "Scripture quotations remain NKJV English as required elsewhere.\n"
            "</language>\n"
        )
    return (
        "<language>\n"
        f"Write your entire reply in {name}.\n"
        "Translate pastoral explanations, invitations, and declines into that language.\n"
        "Do not switch into another language mid-response.\n"
        "When quoting Scripture, still use NKJV English wording inside quotation marks, "
        f"then briefly explain the meaning in {name}.\n"
        "Do not mention this language instruction.\n"
        "Never write hidden notes, self-critique, or instructions to reshape or adjust the answer.\n"
        "</language>\n"
    )
