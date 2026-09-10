"""Topic metadata for video/audio transcripts.

Embeddings only see chunk *text*, so we:

1. Derive a topic title, topics, keywords, summary, and Scripture refs.
2. Prepend a searchable header into every embedded chunk (and one overview chunk).
3. Persist the same fields on ``IngestedDocument.topic_metadata`` and Qdrant payloads.

LLM enrichment (vLLM) is preferred when enabled; a heuristic fallback keeps ingest
online and makes unit tests deterministic.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional, Sequence

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "for",
        "from",
        "god",
        "have",
        "he",
        "her",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "just",
        "know",
        "let",
        "like",
        "lord",
        "me",
        "my",
        "not",
        "of",
        "on",
        "one",
        "or",
        "our",
        "out",
        "said",
        "say",
        "says",
        "she",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "this",
        "to",
        "up",
        "us",
        "was",
        "we",
        "what",
        "when",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
        "amen",
        "gonna",
        "wanna",
        "yeah",
        "okay",
        "ok",
        "uh",
        "um",
        "pastor",
        "church",
        "today",
        "people",
        "thing",
        "things",
        "going",
        "come",
        "comes",
        "want",
        "wanting",
        "really",
        "very",
        "also",
        "even",
        "because",
        "about",
        "through",
        "over",
        "into",
    }
)

_SCRIPTURE_RE = re.compile(
    r"\b(?:"
    r"Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|"
    r"(?:1|2|I|II)\s*Samuel|(?:1|2|I|II)\s*Kings|(?:1|2|I|II)\s*Chronicles|"
    r"Ezra|Nehemiah|Esther|Job|Psalm(?:s)?|Proverbs|Ecclesiastes|Song(?:\s+of\s+Solomon)?|"
    r"Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|"
    r"Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|"
    r"Matthew|Mark|Luke|John|Acts|Romans|(?:1|2|I|II)\s*Corinthians|"
    r"Galatians|Ephesians|Philippians|Colossians|(?:1|2|I|II)\s*Thessalonians|"
    r"(?:1|2|I|II)\s*Timothy|Titus|Philemon|Hebrews|James|(?:1|2|I|II)\s*Peter|"
    r"(?:1|2|3|I|II|III)\s*John|Jude|Revelation"
    r")\s+\d{1,3}(?::\d{1,3}(?:\s*[-–]\s*\d{1,3})?)?",
    re.IGNORECASE,
)

_DATE_ONLY_TITLE_RE = re.compile(
    r"""(?ix)
        ^\s*
        (?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|
           jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|
           nov(?:ember)?|dec(?:ember)?)
        \s+\d{1,2}
        (?:[\s,\-]+\d{2,4})?
        \s*$
    """
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']{2,}")


@dataclass
class VideoTopicMetadata:
    topic_title: str = ""
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    summary: str = ""
    scripture_refs: list[str] = field(default_factory=list)
    speakers: list[str] = field(default_factory=list)
    original_title: str = ""
    source: str = "heuristic"  # heuristic | llm | merged

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep JSON compact / stable for DB + Qdrant payloads.
        data["topics"] = [str(x).strip() for x in self.topics if str(x).strip()][:12]
        data["keywords"] = [str(x).strip() for x in self.keywords if str(x).strip()][:24]
        data["scripture_refs"] = [str(x).strip() for x in self.scripture_refs if str(x).strip()][:16]
        data["speakers"] = [str(x).strip() for x in self.speakers if str(x).strip()][:6]
        data["topic_title"] = (self.topic_title or "").strip()[:180]
        data["summary"] = (self.summary or "").strip()[:600]
        data["original_title"] = (self.original_title or "").strip()[:180]
        data["source"] = (self.source or "heuristic").strip()[:32]
        return data

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "VideoTopicMetadata":
        data = dict(raw or {})
        return cls(
            topic_title=str(data.get("topic_title") or "").strip(),
            topics=[str(x).strip() for x in (data.get("topics") or []) if str(x).strip()],
            keywords=[str(x).strip() for x in (data.get("keywords") or []) if str(x).strip()],
            summary=str(data.get("summary") or "").strip(),
            scripture_refs=[
                str(x).strip() for x in (data.get("scripture_refs") or []) if str(x).strip()
            ],
            speakers=[str(x).strip() for x in (data.get("speakers") or []) if str(x).strip()],
            original_title=str(data.get("original_title") or "").strip(),
            source=str(data.get("source") or "heuristic").strip() or "heuristic",
        )


def title_looks_like_date_only(title: str) -> bool:
    return bool(_DATE_ONLY_TITLE_RE.match((title or "").strip()))


def _unique_keep_order(items: Sequence[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = " ".join(str(item).split()).strip(" .,;:")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def extract_scripture_refs(text: str, *, limit: int = 12) -> list[str]:
    matches = [m.group(0) for m in _SCRIPTURE_RE.finditer(text or "")]
    return _unique_keep_order(matches, limit=limit)


def _top_keywords(text: str, *, limit: int = 16) -> list[str]:
    counts: dict[str, int] = {}
    for match in _WORD_RE.finditer(text or ""):
        word = match.group(0).lower()
        if word in _STOPWORDS or len(word) < 4:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [word for word, _count in ranked[:limit]]


def _first_summary_sentence(text: str, *, max_chars: int = 280) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    for sep in (". ", "? ", "! "):
        if sep in cleaned:
            sentence = cleaned.split(sep, 1)[0].strip() + sep.strip()
            if len(sentence) >= 40:
                cleaned = sentence
                break
    if len(cleaned) > max_chars:
        clipped = cleaned[: max_chars - 1]
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        return clipped.rstrip(".,;:") + "…"
    return cleaned


def _title_from_keywords(keywords: Sequence[str], fallback: str) -> str:
    if not keywords:
        return fallback
    words = [w.capitalize() for w in list(keywords)[:4]]
    if len(words) == 1:
        return words[0]
    if len(words) == 2:
        return f"{words[0]} and {words[1]}"
    return f"{', '.join(words[:-1])}, and {words[-1]}"


def extract_heuristic_metadata(
    transcript: str,
    *,
    original_title: str,
) -> VideoTopicMetadata:
    keywords = _top_keywords(transcript, limit=16)
    topics = keywords[:6]
    refs = extract_scripture_refs(transcript)
    summary = _first_summary_sentence(transcript)
    base = (original_title or "").strip() or "Sermon"
    if title_looks_like_date_only(base) or not base:
        topic_title = _title_from_keywords(keywords, base or "Sermon teaching")
    else:
        topic_title = base
    speakers: list[str] = []
    lowered = (transcript or "").lower()
    if "don nordin" in lowered or "pastor don" in lowered:
        speakers.append("Pastor Don Nordin")
    if "susan nordin" in lowered:
        speakers.append("Susan Nordin")
    return VideoTopicMetadata(
        topic_title=topic_title,
        topics=topics,
        keywords=keywords,
        summary=summary,
        scripture_refs=refs,
        speakers=speakers,
        original_title=base,
        source="heuristic",
    )


def _llm_enabled() -> bool:
    raw = (os.getenv("VIDEO_TOPIC_METADATA_LLM") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _parse_llm_json(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    if "```" in text:
        # Strip optional ```json fences.
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_llm_metadata(
    transcript: str,
    *,
    original_title: str,
    llm: Any = None,
    invoke_fn: Optional[Callable[[Any, str], str]] = None,
) -> Optional[VideoTopicMetadata]:
    if not _llm_enabled():
        return None
    sample = " ".join((transcript or "").split())
    if len(sample) < 80:
        return None
    if len(sample) > 6000:
        sample = sample[:6000]

    prompt = (
        "You extract searchable sermon metadata for a church RAG database.\n"
        "Return ONLY compact JSON with keys: topic_title (string), topics (string array), "
        "keywords (string array), summary (1-2 sentences), scripture_refs (string array), "
        "speakers (string array).\n"
        "topic_title must be a clear topical sermon title (not only a date). "
        "topics/keywords should help someone find this video by subject "
        "(e.g. women pastors, marriage, faith, prayer).\n"
        f"Filename/date title: {original_title!r}\n"
        f"Transcript excerpt:\n{sample}\n"
    )

    def _default_invoke(client: Any, text: str) -> str:
        from langchain_core.messages import HumanMessage, SystemMessage

        response = client.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a careful metadata extractor. Output valid JSON only. "
                        "Do not invent Scripture references that are not in the transcript."
                    )
                ),
                HumanMessage(content=text),
            ]
        )
        content = getattr(response, "content", response)
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content or "")

    try:
        client = llm
        if client is None and invoke_fn is None:
            from .chat_llm import get_chat_llm

            client = get_chat_llm(temperature=0.1, max_tokens=512, timeout=90)
        runner = invoke_fn or (lambda c, t: _default_invoke(c, t))
        raw = runner(client, prompt)
        parsed = _parse_llm_json(raw)
        if not parsed:
            return None
        meta = VideoTopicMetadata.from_dict(parsed)
        meta.original_title = (original_title or "").strip()
        meta.source = "llm"
        if not meta.topic_title:
            return None
        if not meta.keywords and not meta.topics:
            return None
        return meta
    except Exception:
        logger.exception("LLM video topic metadata failed for %s", original_title)
        return None


def build_video_topic_metadata(
    transcript: str,
    *,
    original_title: str,
    llm: Any = None,
    invoke_fn: Optional[Callable[[Any, str], str]] = None,
) -> VideoTopicMetadata:
    heuristic = extract_heuristic_metadata(transcript, original_title=original_title)
    llm_meta = extract_llm_metadata(
        transcript,
        original_title=original_title,
        llm=llm,
        invoke_fn=invoke_fn,
    )
    if llm_meta is None:
        return heuristic

    # Merge: prefer LLM title/summary/topics; fill gaps from heuristic.
    topics = _unique_keep_order([*llm_meta.topics, *heuristic.topics], limit=12)
    keywords = _unique_keep_order([*llm_meta.keywords, *heuristic.keywords], limit=24)
    refs = _unique_keep_order([*llm_meta.scripture_refs, *heuristic.scripture_refs], limit=16)
    speakers = _unique_keep_order([*llm_meta.speakers, *heuristic.speakers], limit=6)
    topic_title = llm_meta.topic_title or heuristic.topic_title
    if title_looks_like_date_only(topic_title):
        topic_title = heuristic.topic_title
    return VideoTopicMetadata(
        topic_title=topic_title,
        topics=topics,
        keywords=keywords,
        summary=llm_meta.summary or heuristic.summary,
        scripture_refs=refs,
        speakers=speakers,
        original_title=(original_title or "").strip(),
        source="merged",
    )


def format_searchable_header(
    meta: VideoTopicMetadata,
    *,
    display_title: Optional[str] = None,
) -> str:
    title = (display_title or meta.topic_title or meta.original_title or "Sermon").strip()
    lines = [f"# {title}"]
    if meta.original_title and meta.original_title.lower() != title.lower():
        lines.append(f"Date/source label: {meta.original_title}")
    if meta.topics:
        lines.append("Topics: " + ", ".join(meta.topics))
    if meta.keywords:
        lines.append("Keywords: " + ", ".join(meta.keywords))
    if meta.scripture_refs:
        lines.append("Scripture: " + "; ".join(meta.scripture_refs))
    if meta.speakers:
        lines.append("Speakers: " + ", ".join(meta.speakers))
    if meta.summary:
        lines.append(f"Summary: {meta.summary}")
    lines.append(
        "Search phrases: "
        + ", ".join(
            _unique_keep_order(
                [
                    title,
                    meta.original_title,
                    *meta.topics,
                    *meta.keywords[:8],
                    *meta.scripture_refs[:4],
                ],
                limit=20,
            )
        )
    )
    return "\n".join(lines).strip() + "\n"


def prepend_searchable_header(chunk_text: str, header: str) -> str:
    body = (chunk_text or "").strip()
    head = (header or "").strip()
    if not head:
        return body
    if not body:
        return head
    # Avoid double-prefixing on re-ingest.
    first_line = body.split("\n", 1)[0].strip().lstrip("# ").strip().lower()
    topic_line = head.split("\n", 1)[0].strip().lstrip("# ").strip().lower()
    if "topics:" in body.lower()[:400] and first_line == topic_line:
        return body
    if body.startswith("# ") and "\n\n" in body:
        # Replace the simple markdown title wrapper with the richer header + body.
        _title, rest = body.split("\n\n", 1)
        return f"{head}\n{rest.strip()}".strip()
    return f"{head}\n{body}".strip()


def build_topic_overview_chunk(meta: VideoTopicMetadata) -> str:
    header = format_searchable_header(meta)
    return (
        f"{header}\n"
        "This overview chunk indexes the full video by topic so retrieval can find "
        "the message when users ask about these subjects."
    ).strip()


def qdrant_metadata_from_topic(meta: VideoTopicMetadata) -> dict[str, Any]:
    data = meta.as_dict()
    return {
        "topic_title": data["topic_title"],
        "topics": data["topics"],
        "keywords": data["keywords"],
        "summary": data["summary"],
        "scripture_refs": data["scripture_refs"],
        "speakers": data["speakers"],
        "original_title": data["original_title"],
        "topic_metadata_source": data["source"],
    }


def display_title_for_document(meta: VideoTopicMetadata, fallback_title: str) -> str:
    """Prefer a topical title for library/chat labels; keep dates as secondary."""
    topic = (meta.topic_title or "").strip()
    fallback = (fallback_title or meta.original_title or "").strip()
    if topic and not title_looks_like_date_only(topic):
        if fallback and title_looks_like_date_only(fallback) and fallback.lower() not in topic.lower():
            return f"{topic} ({fallback})"
        return topic
    return fallback or topic or "Sermon"
