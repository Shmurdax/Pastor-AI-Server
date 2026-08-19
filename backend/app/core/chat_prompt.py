"""Helpers for chat retrieval and author-aware sermon notes."""
from __future__ import annotations

from typing import Callable, Iterable, List


def query_mentions_susan(query: str) -> bool:
    text = (query or "").lower()
    if "susan" in text:
        return True
    return "wife" in text and ("nordin" in text or "pastor" in text)


def document_mentions_susan(doc) -> bool:
    metadata = getattr(doc, "metadata", {}) or {}
    blob = " ".join(
        [
            getattr(doc, "page_content", "") or "",
            str(metadata.get("title") or ""),
            str(metadata.get("source") or ""),
            str(metadata.get("source_name") or ""),
        ]
    ).lower()
    return "susan" in blob


def prefer_susan_docs(docs: Iterable, query: str) -> List:
    """When the user asks about Susan Nordin, put her matching chunks first."""
    docs = list(docs)
    if not query_mentions_susan(query):
        return docs
    susan = [doc for doc in docs if document_mentions_susan(doc)]
    rest = [doc for doc in docs if not document_mentions_susan(doc)]
    return susan + rest


def retrieval_query_for(user_query: str) -> str:
    if query_mentions_susan(user_query):
        return f"{user_query}\nSusan Nordin sermon teaching notes"
    return user_query


def format_reference_notes(docs: Iterable, source_name_fn: Callable) -> str:
    parts: List[str] = []
    for doc in docs:
        text = (getattr(doc, "page_content", None) or "").strip()
        if not text:
            continue
        name = source_name_fn(doc) or "Untitled"
        parts.append(f"[{name}]\n{text}")
    return "\n\n".join(parts)
