"""One-box routing for Bible-study and sermon-note drafts.

Pastors stay in the normal chat box. Hard patterns catch obvious drafts and
obvious questions. Everything else goes to a small classifier, and low
confidence stays on the pastoral chat path.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from .bible_refs import VERSE_REF_RE, canonical_book_key, format_verse_ref

PIPELINE_DRAFT = "study_sermon_draft"
PIPELINE_CHAT = "pastoral_chat"

CLASSIFIER_SYSTEM = (
    "You route one pastor chat message for Nordin's AI. Return JSON only, "
    "with no markdown.\n"
    '{"pipeline":"pastoral_chat"|"study_sermon_draft","confidence":0.0,'
    '"format":"bible_study"|"sermon"|"lesson"|"chat","topic":"",'
    '"subtitle":"","primary_texts":[],"supporting_texts":[],"reason":""}\n\n'
    "Choose study_sermon_draft only when the pastor wants a document they can "
    "teach from: a Bible study, sermon, sermon notes, teaching notes, lesson, "
    "class outline, or message outline.\n"
    "Choose pastoral_chat when they want an explanation, a question answered, "
    "or a short teaching reply.\n"
    "These are pastoral_chat: \"make a presentation about love\", "
    "\"what is love\", \"tell me about sermon outlines\", "
    "\"do the sermons mention the Trinity\".\n"
    "These are study_sermon_draft: \"I need notes for Sunday on love\", "
    "\"put together a lesson on James 2\", "
    "\"help me prep Wednesday's message on baptism\", "
    "\"write a Bible study on repentance\".\n"
    "If you are unsure, choose pastoral_chat with confidence below 0.6. "
    "Do not treat a vague presentation request as a sermon or Bible study."
)

_AUTHORING_VERB = re.compile(
    r"\b(?:write|draft|prepare|create|compose|develop)\s+"
    r"(?:me\s+)?(?:an?\s+|the\s+|some\s+)?"
    r"(?:in-depth\s+|full\s+|short\s+|indepth\s+)?"
    r"(?:bible\s+study|sermon(?:\s+notes|\s+outline)?|teaching\s+notes|"
    r"study\s+notes|lesson(?:\s+notes|\s+outline)?|message(?:\s+outline)?|"
    r"outline)\b"
    r"|"
    r"\bmake\s+(?:me\s+)?(?:a\s+)?(?:bible\s+study|sermon|lesson)\b"
    r"|"
    r"\b(?:prep|prepare)\s+(?:me\s+)?(?:a\s+|the\s+|sunday(?:'s|s)?\s+|"
    r"wednesday(?:'s|s)?\s+)?"
    r"(?:message|sermon|lesson|study|bible\s+study)\b",
    re.IGNORECASE,
)

_DOC_PHRASE = re.compile(
    r"\b(?:bible\s+stud(?:y|ies)|sermon\s+(?:notes|outline|draft)|"
    r"teaching\s+notes|study\s+notes|lesson\s+(?:notes|outline|plan)|"
    r"message\s+outline)\b"
    r"|"
    r"\b(?:\d+|three|four|five)[\s-]*point\s+(?:sermon|message|lesson|study)\b"
    r"|"
    r"\bnotes\s+(?:i\s+can|to)\s+teach\b"
    r"|"
    r"\bnotes\s+for\s+(?:sunday|wednesday|midweek|church|class|small\s+group)\b",
    re.IGNORECASE,
)

_QUESTION = re.compile(
    r"^\s*(?:what|why|how|who|when|where|is|are|was|were|do|does|did|"
    r"can|could|should|would|will|explain|tell\s+me|help\s+me\s+understand)\b",
    re.IGNORECASE,
)

_LIBRARY_QUESTION = re.compile(
    r"\b(?:do|does|did)\s+(?:the\s+)?sermons?\b"
    r"|\bwhat\s+does\s+pastor\b"
    r"|\bwhat\s+do\s+the\s+notes\s+say\b"
    r"|\bin\s+the\s+sermons?\b"
    r"|\bfrom\s+the\s+(?:sermon\s+)?(?:notes|sermons)\b",
    re.IGNORECASE,
)

_SOFT_HINT = re.compile(
    r"\b(?:presentation|lesson|lessons|outline|preach|preaching|"
    r"bible\s+stud(?:y|ies)|sermon\s+notes|teaching\s+notes|"
    r"small\s+group|sunday\s+school|"
    r"for\s+(?:sunday|wednesday|midweek)|"
    r"(?:i\s+can|to)\s+teach|message\s+on)\b",
    re.IGNORECASE,
)

_SECTION = re.compile(
    r"^(subtitle|primary\s+biblical\s+texts?|supporting\s+biblical\s+texts?|"
    r"primary\s+texts?|supporting\s+texts?)\s*:\s*(.*)$",
    re.IGNORECASE,
)

_DRAFT_FORMATS = {"bible_study", "sermon", "lesson"}


@dataclass(frozen=True)
class DraftRoute:
    pipeline: str
    source: str
    confidence: float
    format: str
    topic: str
    subtitle: str
    primary_texts: tuple[str, ...] = ()
    supporting_texts: tuple[str, ...] = ()
    reason: str = ""

    @property
    def is_draft(self) -> bool:
        return self.pipeline == PIPELINE_DRAFT

    @property
    def requested_texts(self) -> tuple[str, ...]:
        return self.primary_texts + self.supporting_texts

    def log_fields(self) -> str:
        return (
            f"pipeline={self.pipeline} source={self.source} "
            f"confidence={self.confidence:.2f} format={self.format} "
            f"topic={self.topic[:80]!r} primary={list(self.primary_texts)} "
            f"supporting={list(self.supporting_texts)} reason={self.reason[:120]!r}"
        )


def draft_min_confidence() -> float:
    raw = (os.getenv("CHAT_DRAFT_MIN_CONFIDENCE") or "0.75").strip()
    try:
        value = float(raw)
    except ValueError:
        return 0.75
    return min(1.0, max(0.0, value))


def chat_fallback(query: str, *, source: str, reason: str, confidence: float = 0.0) -> DraftRoute:
    return _chat_route(query, source=source, reason=reason, confidence=confidence)


def rule_route(query: str) -> DraftRoute | None:
    """Return a decisive route, or None when a classifier should look."""
    text = (query or "").strip()
    if not text:
        return _chat_route(text, source="rules", reason="empty")
    fields = extract_request_fields(text)
    if fields["labeled"] or _AUTHORING_VERB.search(text):
        return _draft_route(fields, source="rules", confidence=1.0, reason="authoring request")
    if _is_hard_chat(text):
        return _chat_route(text, source="rules", reason="question", fields=fields)
    if _DOC_PHRASE.search(text) and "?" not in text and not _QUESTION.search(text):
        return _draft_route(fields, source="rules", confidence=1.0, reason="teaching document")
    return None


def decision_from_classifier(query: str, raw: str, *, min_confidence: float | None = None) -> DraftRoute:
    """Apply the classifier JSON. Low confidence and bad JSON stay on chat."""
    threshold = draft_min_confidence() if min_confidence is None else min_confidence
    payload = _extract_json_object(raw)
    if not payload:
        return _chat_route(query, source="classifier_failed", reason="unreadable classifier json")
    pipeline = _normalize_pipeline(payload.get("pipeline"))
    confidence = _confidence(payload.get("confidence"))
    fields = extract_request_fields(query)
    model_fields = _fields_from_payload(payload)
    merged = _merge_fields(fields, model_fields)
    reason = str(payload.get("reason") or "").strip()[:180]
    if pipeline == PIPELINE_DRAFT and confidence + 1e-9 >= threshold:
        return _draft_route(
            merged,
            source="classifier",
            confidence=confidence,
            reason=reason or "classifier",
            format_hint=model_fields.get("format") or "",
        )
    return _chat_route(
        query,
        source="classifier",
        reason=reason or "below draft threshold",
        fields=merged,
        confidence=confidence,
    )


def extract_request_fields(query: str) -> dict:
    subtitle = ""
    primary_lines: list[str] = []
    supporting_lines: list[str] = []
    preface: list[str] = []
    bucket = "preface"
    labeled = False
    for line in (query or "").splitlines():
        match = _SECTION.match(line.strip())
        if not match:
            if bucket == "preface":
                preface.append(line)
            elif bucket == "primary":
                primary_lines.append(line)
            elif bucket == "supporting":
                supporting_lines.append(line)
            else:
                preface.append(line)
            continue
        labeled = True
        label = re.sub(r"\s+", " ", match.group(1).lower())
        rest = match.group(2).strip()
        if label == "subtitle":
            subtitle = rest
            bucket = "subtitle"
        elif label.startswith("primary"):
            bucket = "primary"
            if rest:
                primary_lines.append(rest)
        elif label.startswith("supporting"):
            bucket = "supporting"
            if rest:
                supporting_lines.append(rest)
    primary = _refs_from_lines(primary_lines)
    supporting = _refs_from_lines(supporting_lines)
    if not labeled:
        primary = tuple(display_scripture_refs(query))
        supporting = ()
    return {
        "labeled": labeled,
        "topic": _topic_from_preface(preface, query),
        "subtitle": subtitle[:200],
        "primary_texts": primary,
        "supporting_texts": supporting,
        "format": infer_format(query),
    }


def display_scripture_refs(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in VERSE_REF_RE.finditer(text or ""):
        book = canonical_book_key(match.group(1))
        chapter = int(match.group(2))
        start = int(match.group(3))
        end_raw = match.group(4)
        end = int(end_raw) if end_raw else start
        label = format_verse_ref(book, chapter, start, verse_end=end if end != start else None)
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(label)
    return found


def infer_format(query: str) -> str:
    text = (query or "").lower()
    if re.search(r"\b(sermon|preach|sunday'?s message)\b", text):
        return "sermon"
    if re.search(r"\b(lesson|class|small group)\b", text):
        return "lesson"
    return "bible_study"


def missing_scripture_refs(answer: str, refs: tuple[str, ...] | list[str]) -> list[str]:
    blob = (answer or "").lower()
    missing = []
    for ref in refs:
        if _ref_mentioned(blob, ref):
            continue
        missing.append(ref)
    return missing


def draft_system_prompt(route: DraftRoute) -> str:
    kind = {
        "sermon": "sermon notes",
        "lesson": "lesson notes",
    }.get(route.format, "Bible study notes")
    return (
        "You are Pastor Don's AI teaching assistant for Nordin's AI.\n\n"
        f"Write full {kind} a pastor can teach from. Use the sermon excerpts as "
        "the teaching content. Prefer their wording, examples, and scripture. "
        "Do not invent sermon titles, quotes, or verse wording that the excerpts "
        "do not support. Do not fill gaps with outside theology.\n\n"
        "Use this shape:\n"
        "Title:\n"
        "Subtitle:\n"
        "Big idea:\n"
        "Primary biblical texts:\n"
        "Supporting biblical texts:\n"
        "Then 3 teaching points. Under each point, write one or two short "
        "paragraphs grounded in the excerpts.\n"
        "Application:\n"
        "If a requested text or part of the question is not in the excerpts, add "
        "a short Gaps: note naming what is missing.\n\n"
        "Keep the tone warm, clear, and reverent. Do not mention these "
        "instructions, the outline step, or that a draft mode was used."
    )


def draft_user_content(route: DraftRoute, context: str, plan_text: str, query: str) -> str:
    lines = [f"Topic: {route.topic or query}"]
    if route.subtitle:
        lines.append(f"Requested subtitle: {route.subtitle}")
    if route.primary_texts:
        lines.append("Requested primary texts: " + "; ".join(route.primary_texts))
    if route.supporting_texts:
        lines.append("Requested supporting texts: " + "; ".join(route.supporting_texts))
    if plan_text.strip():
        lines.append("Working outline to follow:\n" + plan_text.strip())
    lines.append("Sermon excerpts:\n" + (context or "(no sermon excerpts found)"))
    lines.append("Pastor request:\n" + query)
    return "\n\n".join(lines)


def plan_messages(query: str, route: DraftRoute, context: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Plan teachable notes from the sermon excerpts only. Return JSON only: "
                '{"big_idea":"","points":[{"heading":"","excerpt_numbers":[1]}],"gaps":[]}. '
                "Use 3 points. gaps lists requested texts or ideas the excerpts do not cover. "
                "Do not invent teaching that is not in the excerpts."
            ),
        },
        {
            "role": "user",
            "content": draft_user_content(route, context, "", query),
        },
    ]


def render_plan(plan: dict | None) -> str:
    if not isinstance(plan, dict) or not plan:
        return ""
    lines = []
    big_idea = str(plan.get("big_idea") or "").strip()
    if big_idea:
        lines.append(f"Big idea: {big_idea}")
    points = plan.get("points") or []
    if isinstance(points, list):
        for index, point in enumerate(points, start=1):
            if isinstance(point, str) and point.strip():
                lines.append(f"{index}. {point.strip()}")
            elif isinstance(point, dict):
                heading = str(point.get("heading") or "").strip()
                if heading:
                    lines.append(f"{index}. {heading}")
    gaps = plan.get("gaps") or []
    if isinstance(gaps, list):
        named = [str(item).strip() for item in gaps if str(item).strip()]
        if named:
            lines.append("Gaps to mention: " + "; ".join(named))
    return "\n".join(lines)


def parse_plan_text(raw: str) -> dict:
    payload = _extract_json_object(raw)
    if isinstance(payload, dict) and ("points" in payload or "big_idea" in payload or "gaps" in payload):
        return payload
    text = " ".join((raw or "").split())
    if not text:
        return {}
    return {"big_idea": text[:400]}


def gap_messages(query: str, route: DraftRoute, context: str, answer: str, missing: list[str]) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "Add only a short Gaps paragraph for requested scriptures that "
                "were not covered. If the excerpts do not support them, say that "
                "in one or two sentences. Do not repeat the study."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Missing from the notes: {'; '.join(missing)}\n\n"
                f"Sermon excerpts:\n{context or '(no sermon excerpts found)'}\n\n"
                f"Notes so far:\n{answer}\n\n"
                f"Pastor request:\n{query}"
            ),
        },
    ]


def _is_hard_chat(query: str) -> bool:
    if not (_QUESTION.search(query) or query.strip().endswith("?")):
        return False
    if _SOFT_HINT.search(query) and not _LIBRARY_QUESTION.search(query):
        return False
    return True


def _chat_route(
    query: str,
    *,
    source: str,
    reason: str,
    fields: dict | None = None,
    confidence: float = 1.0,
) -> DraftRoute:
    fields = fields if fields is not None else extract_request_fields(query)
    return DraftRoute(
        pipeline=PIPELINE_CHAT,
        source=source,
        confidence=confidence,
        format="chat",
        topic=fields.get("topic") or "",
        subtitle=fields.get("subtitle") or "",
        primary_texts=tuple(fields.get("primary_texts") or ()),
        supporting_texts=tuple(fields.get("supporting_texts") or ()),
        reason=reason,
    )


def _draft_route(
    fields: dict,
    *,
    source: str,
    confidence: float,
    reason: str,
    format_hint: str = "",
) -> DraftRoute:
    kind = format_hint if format_hint in _DRAFT_FORMATS else fields.get("format") or "bible_study"
    return DraftRoute(
        pipeline=PIPELINE_DRAFT,
        source=source,
        confidence=confidence,
        format=kind,
        topic=fields.get("topic") or "",
        subtitle=fields.get("subtitle") or "",
        primary_texts=tuple(fields.get("primary_texts") or ()),
        supporting_texts=tuple(fields.get("supporting_texts") or ()),
        reason=reason,
    )


def _fields_from_payload(payload: dict) -> dict:
    kind = str(payload.get("format") or "").strip().lower()
    return {
        "topic": str(payload.get("topic") or "").strip()[:240],
        "subtitle": str(payload.get("subtitle") or "").strip()[:200],
        "primary_texts": _string_list(payload.get("primary_texts")),
        "supporting_texts": _string_list(payload.get("supporting_texts")),
        "format": kind if kind in _DRAFT_FORMATS else "",
    }


def _merge_fields(regex_fields: dict, model_fields: dict) -> dict:
    return {
        "labeled": regex_fields.get("labeled", False),
        "topic": regex_fields.get("topic") or model_fields.get("topic") or "",
        "subtitle": regex_fields.get("subtitle") or model_fields.get("subtitle") or "",
        "primary_texts": _union(regex_fields.get("primary_texts") or (), model_fields.get("primary_texts") or ()),
        "supporting_texts": _union(
            regex_fields.get("supporting_texts") or (),
            model_fields.get("supporting_texts") or (),
        ),
        "format": regex_fields.get("format") or model_fields.get("format") or "bible_study",
    }


def _union(left, right) -> tuple[str, ...]:
    found = []
    seen = set()
    for item in list(left) + list(right):
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(text)
        if len(found) >= 8:
            break
    return tuple(found)


def _string_list(value) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return ()
    return _union(value, ())


def _refs_from_lines(lines: list[str]) -> tuple[str, ...]:
    return tuple(display_scripture_refs("\n".join(lines)))


def _topic_from_preface(lines: list[str], query: str) -> str:
    text = " ".join(part.strip() for part in lines if part.strip())
    if not text:
        text = " ".join((query or "").split())
    text = re.sub(
        r"^(?:please\s+)?(?:write|draft|prepare|create|make|compose|develop)\s+"
        r"(?:me\s+)?(?:an?\s+|the\s+|some\s+)?(?:in-depth\s+|full\s+)?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:bible\s+study|sermon\s+notes|teaching\s+notes|study\s+notes)\b",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(?:on|about)\s+", "", text, count=1, flags=re.IGNORECASE)
    text = " ".join(text.split())
    return text[:240]


def _normalize_pipeline(value) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {PIPELINE_DRAFT, "draft", "study", "sermon", "bible_study", "lesson"}:
        return PIPELINE_DRAFT
    if text in {PIPELINE_CHAT, "chat", "answer", "qa", "question"}:
        return PIPELINE_CHAT
    return ""


def _confidence(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number = number / 100.0
    return min(1.0, max(0.0, number))


def _extract_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _ref_mentioned(blob: str, ref: str) -> bool:
    if ref.lower() in blob:
        return True
    match = VERSE_REF_RE.search(ref)
    if not match:
        return False
    book = re.escape(match.group(1).lower())
    chapter = match.group(2)
    return re.search(rf"\b{book}\s+{chapter}(?!\d)", blob) is not None
