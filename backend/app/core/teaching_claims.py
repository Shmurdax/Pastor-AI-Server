"""Retrieve Don/Susan theses, bind them as required content, and check coverage.

Tone stays generic pastoral English. The claims are the doctrine and outline.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .chat_retrieval import (
    SENSE_ALCOHOL,
    SENSE_NONE,
    SENSE_SEXUALITY,
    chunk_text,
    is_bible_source,
    looks_like_library_pull,
    metadata_source_hint,
    query_topic_sense,
    text_has_alcohol_application,
    text_has_alcohol_teaching,
    text_has_sexuality_application,
    text_has_sexuality_teaching,
    text_looks_like_communion_only,
)
from .grounding import (
    looks_like_scripture_blob,
    normalize_grounding_text,
    quote_attributed_to_pastor,
)
from .note_priority import (
    looks_like_deck_junk,
    looks_like_kjv_diction,
    looks_like_stat_slide,
    looks_like_vice_catalog,
    thesis_sentence_score,
)
from .quote_chunking import extract_quote_spans, spoken_text_without_timestamps, split_sentences

_MARKUP_RE = re.compile(r"[*_`>#]+")
_SPACE_RE = re.compile(r"\s+")
_CLAIM_MAX_CHARS = 280
_CLAIM_MIN_CHARS = 24
_DEFAULT_LIMIT = 8
_CONTRAST_RE = re.compile(
    r"\b("
    r"not just|rather than|only if|only indicative|same power|"
    r"fool'?s paradise|come let us|instead of|but the|"
    r"do not|don't|cannot|can't|does not mean|"
    r"stand firmly|not an acceptable|judgment is not ours"
    r")\b",
    re.IGNORECASE,
)
_BULLET_SPLIT_RE = re.compile(r"[•●▪]\s*")
_ELLIPSIS_SPLIT_RE = re.compile(r"\s*(?:\u2026|\.{3})\s+")
_APPLICATION_CLIP_RE = re.compile(
    r"(?i)("
    r"not an acceptable lifestyle|love the homosexual|stand firmly|"
    r"those who approve|stone the homosexual|judgment is not ours|"
    r"natural law|"
    r"total abstinence|only acceptable way|alcoholism is a sin|"
    r"not a sickness|not a disease|abstain from alcoholic"
    r")"
)
_PACKED_VERSE_RE = re.compile(r"\d+[A-Z][a-z]")
_ROMANS_LIBERTY_BLOB_RE = re.compile(
    r"(?i)("
    r"whatever is not from faith is sin|"
    r"does not condemn himself in what he approves|"
    r"he who doubts is condemned if he eats"
    r")"
)

# Topic words we still want when matching a user question, even though they are
# too generic to identify a distinctive Don thesis on their own.
_QUERY_TOPIC_WORDS = frozenset(
    {
        "faith",
        "hope",
        "love",
        "loving",
        "patience",
        "prayer",
        "barriers",
        "alcohol",
        "gay",
        "church",
        "lord",
        "god",
        "jesus",
        "christ",
        "holy",
        "spirit",
        "bible",
        "scripture",
        "gospel",
        "grace",
        "worship",
        "gift",
        "gifts",
        "altar",
        "anointing",
        "tithe",
        "tithing",
        "marriage",
        "covenant",
        "tongues",
        "baptism",
        "giving",
        "gratitude",
        "grateful",
        "thanksgiving",
        "thankfulness",
    }
)
# Words almost every sermon uses. Overlap on these alone must not make a
# Community / harvest sentence a required point for "why this church…".
_WEAK_QUERY_WORDS = frozenset(
    {
        "faith",
        "hope",
        "love",
        "loving",
        "prayer",
        "church",
        "churches",
        "lord",
        "god",
        "jesus",
        "christ",
        "holy",
        "spirit",
        "bible",
        "scripture",
        "gospel",
        "grace",
        "worship",
        "gift",
        "gifts",
        "christian",
        "christians",
        "life",
        "lives",
        "people",
    }
)
_MEMOIR_RE = re.compile(
    r"(?i)\b("
    r"i grew up|when i was \d+|i accepted christ|"
    r"my parents(?:,| were)|i began preaching|"
    r"working on a sermon that late"
    r")\b"
)
_TESTIMONY_QUERY_RE = re.compile(
    r"(?i)\b(testimony|biography|childhood|grew up|your story|"
    r"pastor don'?s (?:life|story)|parents)\b"
)

# Common English + generic Christian words. Distinctive Don content must survive this list.
_STOP = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "than", "that", "this",
        "these", "those", "to", "of", "in", "on", "for", "from", "with", "without",
        "as", "at", "by", "into", "onto", "over", "under", "about", "above", "after",
        "before", "between", "through", "during", "because", "while", "when", "where",
        "which", "who", "whom", "whose", "what", "why", "how", "not", "no", "nor",
        "so", "too", "very", "just", "also", "even", "still", "only", "own", "same",
        "other", "another", "each", "every", "all", "any", "both", "few", "more",
        "most", "some", "such", "is", "are", "was", "were", "be", "been", "being",
        "am", "do", "does", "did", "done", "doing", "have", "has", "had", "having",
        "will", "would", "shall", "should", "can", "could", "may", "might", "must",
        "i", "we", "you", "he", "she", "it", "they", "me", "us", "him", "her", "them",
        "my", "our", "your", "his", "its", "their", "mine", "ours", "yours", "theirs",
        "pastor", "don", "susan", "nordin", "nordins", "said", "says", "teach",
        "teaches", "taught", "teaching", "preach", "preaches", "preached",
        "god", "lord", "jesus", "christ", "holy", "spirit", "bible", "scripture",
        "scriptures", "church", "churches", "christian", "christians", "faith",
        "people", "person", "life", "lives", "way", "ways", "thing", "things",
        "time", "times", "today", "now", "let", "lets", "need", "needs", "needed",
        "want", "wants", "like", "make", "makes", "come", "comes", "go", "goes",
        "know", "knows", "see", "sees", "say", "says", "get", "gets", "give",
        "gives", "take", "takes", "one", "two", "first", "second", "third",
        "point", "points", "week", "topic", "topics", "note", "notes",
        "verse", "verses", "word", "words", "amen", "hallelujah",
    }
)


def _metadata(doc: Any) -> dict:
    return dict(getattr(doc, "metadata", None) or {})


def _is_bible_doc(doc: Any) -> bool:
    meta = _metadata(doc)
    kind = str(meta.get("chunk_kind") or "").lower()
    if kind.startswith("bible"):
        return True
    return is_bible_source(metadata_source_hint(doc) or str(meta.get("source") or ""))


def _clip_claim(text: str) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = _MARKUP_RE.sub(" ", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip(" \"“”'")
    if len(cleaned) <= _CLAIM_MAX_CHARS:
        return cleaned
    match = _APPLICATION_CLIP_RE.search(cleaned)
    if match:
        start = max(0, match.start() - 48)
        if start:
            snapped = cleaned.rfind(" ", 0, start)
            if snapped >= 0:
                start = snapped + 1
        window = cleaned[start : start + _CLAIM_MAX_CHARS]
        if " " in window:
            window = window.rsplit(" ", 1)[0]
        window = window.strip(" \"“”'")
        if len(window) >= _CLAIM_MIN_CHARS:
            return window
    return cleaned[: _CLAIM_MAX_CHARS - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


def _merge_short_units(parts: list[str]) -> list[str]:
    merged: list[str] = []
    for part in parts:
        piece = " ".join((part or "").split()).strip(" •●▪-\t")
        if not piece:
            continue
        if merged and len(piece) < 40:
            merged[-1] = merged[-1].rstrip(";,. ") + "; " + piece
        else:
            merged.append(piece)
    return merged


def _looks_like_parallel_list(part: str) -> bool:
    clauses = [item.strip() for item in (part or "").split("; ") if item.strip()]
    if len(clauses) < 3:
        return False
    headed = sum(
        1
        for item in clauses
        if item.lower().startswith("those who") or item.lower().startswith("the ")
    )
    return headed >= max(2, len(clauses) - 1)


def _split_long_part(part: str) -> list[str]:
    cleaned = " ".join((part or "").split()).strip()
    if not cleaned:
        return []
    if len(cleaned) <= _CLAIM_MAX_CHARS:
        return [cleaned]
    ellipsis_bits = [item.strip() for item in _ELLIPSIS_SPLIT_RE.split(cleaned) if item.strip()]
    if len(ellipsis_bits) > 1:
        split_bits = _merge_short_units(ellipsis_bits)
        if len(split_bits) > 1:
            units: list[str] = []
            for bit in split_bits:
                units.extend(_split_long_part(bit) if len(bit) > _CLAIM_MAX_CHARS else [bit])
            return units
    if not _looks_like_parallel_list(cleaned):
        clauses = [item.strip() for item in cleaned.split("; ") if item.strip()]
        if len(clauses) > 1:
            split_bits = _merge_short_units(clauses)
            if len(split_bits) > 1:
                units = []
                for bit in split_bits:
                    units.extend(_split_long_part(bit) if len(bit) > _CLAIM_MAX_CHARS else [bit])
                return units
    return [_clip_claim(cleaned)]


def _split_claim_units(raw: str) -> list[str]:
    """Break long sermon bullets so application theses survive clipping."""
    units: list[str] = []
    for sentence in split_sentences(raw) or [raw or ""]:
        bullets = [item.strip() for item in _BULLET_SPLIT_RE.split(sentence) if item.strip()]
        parts = bullets or [sentence]
        for part in parts:
            units.extend(_split_long_part(part))
    return units


def claim_content_tokens(text: str) -> list[str]:
    words = normalize_grounding_text(text).split()
    return [word for word in words if word not in _STOP and len(word) >= 4]


def query_topic_tokens(query: str) -> set[str]:
    """Content tokens from the user question, keeping faith/love/Lord and similar."""
    words = normalize_grounding_text(query).split()
    kept: set[str] = set()
    for word in words:
        if len(word) < 4 and word not in _QUERY_TOPIC_WORDS:
            continue
        if word in _STOP and word not in _QUERY_TOPIC_WORDS:
            continue
        kept.add(word)
    if query_topic_sense(query) == SENSE_ALCOHOL:
        kept.add("alcohol")
    if query_topic_sense(query) == SENSE_SEXUALITY:
        kept.add("gay")
        kept.add("homosexuality")
    return kept


# Outline leftovers from "3 point sermon on faith" must not outrank the topic.
_OUTLINE_DISTINCTIVE_STOP = frozenset(
    {
        "sermon",
        "sermons",
        "point",
        "points",
        "outline",
        "topic",
        "topics",
        "week",
        "notes",
        "note",
    }
)
_SERMON_OUTLINE_REQUEST_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:\d+|one|two|three|four|five)\s*[- ]?\s*points?"
    r"|sermon\s+outline"
    r"|outline\s+(?:of|on|for)"
    r"|bullet\s+points?"
    r")\b"
)


def looks_like_sermon_outline_request(query: str) -> bool:
    """True when the user asked for an outline or N-point sermon layout."""
    return bool(_SERMON_OUTLINE_REQUEST_RE.search(query or ""))


def distinctive_query_tokens(query_tokens: Iterable[str]) -> set[str]:
    """Query words that identify the topic.

    Outline words (sermon / point) are never distinctive. Weak Christian words
    (faith, gratitude, church) become distinctive when they are the only topic
    left, so a one-word faith question keeps faith theses instead of
    discussion-guide sentences that only say "sermon".
    """
    tokens = {
        str(token).lower()
        for token in query_tokens
        if str(token).strip() and str(token).lower() not in _OUTLINE_DISTINCTIVE_STOP
    }
    distinctive = {token for token in tokens if token not in _WEAK_QUERY_WORDS}
    if distinctive:
        return distinctive
    return {token for token in tokens if token in _QUERY_TOPIC_WORDS or token in _WEAK_QUERY_WORDS}


def claim_matches_query(claim: str, query_tokens: set[str], *, query: str = "") -> bool:
    """True when a retrieved thesis still belongs to the user's question.

    Alcohol/drink questions must keep alcohol teaching, not Lord's Table
    sentences that only share the word drink.
    Homosexuality questions must keep sexuality teaching, not Happiness notes
    that only share people/Christians.
    """
    sense = query_topic_sense(query) if query else SENSE_NONE
    if sense == SENSE_ALCOHOL:
        if text_looks_like_communion_only(claim):
            return False
        return text_has_alcohol_teaching(claim)
    if sense == SENSE_SEXUALITY:
        return text_has_sexuality_teaching(claim)
    if not query_tokens:
        return True
    claim_words = set(normalize_grounding_text(claim).split())
    distinctive = distinctive_query_tokens(query_tokens)
    if distinctive:
        return bool(distinctive & claim_words)
    return bool(query_tokens & claim_words)


def _looks_like_memoir(claim: str) -> bool:
    return bool(_MEMOIR_RE.search(claim or ""))


def _score_claim(claim: str, query_tokens: set[str], *, query: str = "") -> int:
    tokens = claim_content_tokens(claim)
    if not tokens:
        return -1
    claim_words = set(normalize_grounding_text(claim).split())
    distinctive = distinctive_query_tokens(query_tokens)
    dist_overlap = sum(1 for token in distinctive if token in claim_words)
    overlap = sum(1 for token in query_tokens if token in claim_words)
    contrast = 6 if _CONTRAST_RE.search(claim) else 0
    application = 0
    sense = query_topic_sense(query)
    lowered = claim.lower()
    if sense == SENSE_SEXUALITY and text_has_sexuality_application(claim):
        application = 16
        if "not an acceptable lifestyle" in lowered or "love the homosexual" in lowered:
            application += 8
        if "stone the homosexual" in lowered or "those who approve" in lowered:
            application += 4
    if sense == SENSE_ALCOHOL and text_has_alcohol_application(claim):
        application = 16
        if "only acceptable way" in lowered or "alcoholism is a sin" in lowered:
            application += 8
    return dist_overlap * 6 + overlap * 3 + min(len(tokens), 8) + contrast + application


def extract_teaching_claims(
    docs: Iterable[Any] | None,
    *,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[str]:
    """Sentence-sized Don/Susan theses from retrieved sermon notes, not Bible."""
    query_tokens = query_topic_tokens(query)
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    allow_memoir = bool(_TESTIMONY_QUERY_RE.search(query or ""))

    def add(raw: str, *, bonus: int = 0) -> None:
        for unit in _split_claim_units(raw) or [raw]:
            claim = _clip_claim(unit)
            if looks_like_deck_junk(claim) or looks_like_kjv_diction(claim):
                continue
            if looks_like_scripture_blob(claim) or looks_like_vice_catalog(claim):
                continue
            if _PACKED_VERSE_RE.search(claim) or _ROMANS_LIBERTY_BLOB_RE.search(claim):
                continue
            if looks_like_stat_slide(claim):
                continue
            if thesis_sentence_score(claim) < 0:
                continue
            if len(claim) < _CLAIM_MIN_CHARS:
                continue
            if len(claim_content_tokens(claim)) < 2 and bonus <= 0:
                continue
            if _looks_like_memoir(claim) and not allow_memoir:
                continue
            key = normalize_grounding_text(claim)
            if len(key) < 16 or key in seen:
                continue
            seen.add(key)
            scored.append(
                (
                    _score_claim(claim, query_tokens, query=query)
                    + bonus
                    + int(thesis_sentence_score(claim) * 4),
                    claim,
                )
            )

    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        kind = str(meta.get("chunk_kind") or "").lower()
        if "overview" in kind:
            continue
        stored = str(meta.get("quote_text") or "").strip()
        if stored:
            for part in stored.split(" | "):
                add(part, bonus=4)
        body = spoken_text_without_timestamps(chunk_text(doc))
        if not body:
            continue
        for span in extract_quote_spans(body):
            add(span, bonus=2)
        for sentence in split_sentences(body):
            add(sentence)

    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        kind = str(meta.get("chunk_kind") or "").lower()
        if "overview" in kind:
            continue
        stored = str(meta.get("quote_text") or "").strip()
        if stored:
            for part in stored.split(" | "):
                add(part, bonus=4)
        body = spoken_text_without_timestamps(chunk_text(doc))
        if not body:
            continue
        for span in extract_quote_spans(body):
            add(span, bonus=2)
        for sentence in split_sentences(body):
            add(sentence)

    scored.sort(key=lambda item: (-item[0], len(item[1])))
    ranked = [claim for score, claim in scored if score >= 0]
    if query_tokens and ranked and not looks_like_library_pull(query):
        topical = [
            claim
            for claim in ranked
            if claim_matches_query(claim, query_tokens, query=query)
        ]
        if topical:
            ranked = topical
        elif query_topic_sense(query) in {SENSE_ALCOHOL, SENSE_SEXUALITY}:
            ranked = []
    sense = query_topic_sense(query)
    if sense == SENSE_ALCOHOL:
        applied = [claim for claim in ranked if text_has_alcohol_application(claim)]
        if applied:
            rest = [claim for claim in ranked if claim not in applied]
            ranked = applied + rest
    elif sense == SENSE_SEXUALITY:
        applied = [claim for claim in ranked if text_has_sexuality_application(claim)]
        if applied:
            rest = [claim for claim in ranked if claim not in applied]
            ranked = applied + rest
    return ranked[: max(1, limit)]


def format_teaching_claims_block(claims: Iterable[str]) -> str:
    points = [item.strip() for item in claims if item and item.strip()]
    if not points:
        return ""
    lines = [
        "<required_teaching_points>",
        "Use a clear, generic Christian pastoral tone. Do not imitate Pastor Don's or Susan's speaking style.",
        "The numbered points are the only ideas you may teach. Paraphrase them in your own words. "
        "Do not add theology, caveats, verses, or advice that is not in these points. "
        "REFERENCE NOTES are the source of these points, not a license to invent a new outline. "
        "You may use paragraphs, bullets, or headings for layout. Do not invent extra points.",
        "In your own words means the same thesis with different wording. Keep the contrast "
        "(the not / only if / same power / rather than). Do not keep a story or illustration "
        "and teach a different point with it.",
        "They are the outline and the doctrine. Do not replace them with generic Christian topics "
        "(for example a communication or conflict-resolution seminar) unless those topics appear below.",
        "Cover every numbered point. If the user asked for an outline or N sermon points, "
        "present that many of these theses as labeled Markdown points, then continue with "
        "any remaining theses. Otherwise mix paragraphs and bullets as the question needs. "
        "Do not invent a yes/no that is not in the points. "
        "Do not substitute an LGBTQ inclusion frame, sexual-orientation "
        "acceptance, or a greatest-commandment / Mark 12 answer unless that idea appears in the points.",
        "Do not teach that alcoholic drink is a personal decision, a Romans 14 liberty issue, "
        "or that many Christians may drink in moderation unless that idea appears in the points.",
        "If part of the user's question is not covered by these points, say the retrieved teaching does not address that part. "
        "Do not fill the gap from general Christian knowledge.",
    ]
    for index, claim in enumerate(points, start=1):
        lines.append(f"{index}. {claim}")
    lines.append("</required_teaching_points>")
    return "\n".join(lines) + "\n"


def format_generation_user_prompt(query: str, claims: Iterable[str] | None) -> str:
    """Last-turn lock so the first generate paraphrases retrieved theses."""
    question = " ".join((query or "").split()).strip()
    points = [item.strip() for item in (claims or []) if item and str(item).strip()]
    sense = query_topic_sense(question)
    lines: list[str] = []
    if points:
        lines.append(
            "Paraphrase every numbered sermon point below. "
            "They are the doctrine. Do not add theology or a yes/no that is not in them. "
            "Do not invent extra outline points."
        )
        for index, claim in enumerate(points, start=1):
            lines.append(f"{index}. {claim}")
        if sense == SENSE_ALCOHOL:
            lines.append(
                "Do not say drinking is a personal decision, a Romans 14 liberty issue, "
                "or that many Christians may drink in moderation unless a numbered point says that."
            )
        if sense == SENSE_SEXUALITY:
            lines.append(
                "Do not begin by saying gay people can be Christians unless a numbered point says that. "
                "Do not write Certainly. Do not give an LGBTQ inclusion, sexual-orientation acceptance, "
                "or Mark 12 greatest-commandment answer unless a numbered point says that."
            )
        lines.append("")
        lines.append("User question:")
        lines.append(question or "(empty)")
        if looks_like_sermon_outline_request(question):
            lines.append(
                "Write the answer now. The user asked for an outline. Present the retrieved "
                "theses as a Markdown outline (numbered or bulleted points, with a short "
                "paragraph under a point when it helps). If they asked for N points, use N "
                "of these theses as the labeled points, then cover any remaining theses. "
                "Do not invent extra points. Cover every numbered point."
            )
        else:
            lines.append(
                "Write the answer now. Mix short paragraphs and bullets as the question needs. "
                "Cover every numbered point. Do not invent extra outline points. "
                "Do not stop after the first sentence."
            )
    elif sense in {SENSE_ALCOHOL, SENSE_SEXUALITY}:
        lines.append("User question:")
        lines.append(question or "(empty)")
        lines.append("")
        lines.append(
            "Retrieved sermon notes did not yield teaching points for this question. "
            "Say that plainly. Do not answer from general Christian knowledge."
        )
    else:
        lines.append("User question:")
        lines.append(question or "(empty)")
    return "\n".join(lines)


def claim_is_covered(claim: str, answer: str) -> bool:
    tokens = claim_content_tokens(claim)
    if len(tokens) < 2:
        return True
    answer_norm = normalize_grounding_text(answer)
    if not answer_norm:
        return False
    answer_words = set(answer_norm.split())
    hits = sum(1 for token in tokens if token in answer_words)
    if len(tokens) >= 4:
        for index in range(len(tokens) - 2):
            if all(token in answer_words for token in tokens[index : index + 3]):
                return True
        later = tokens[len(tokens) // 2 :]
        later_hits = sum(1 for token in later if token in answer_words)
        if later_hits >= 2 and hits >= max(3, (len(tokens) + 1) // 2):
            return True
        return False
    phrases = [" ".join(tokens[index : index + 2]) for index in range(len(tokens) - 1)]
    if any(phrase in answer_norm for phrase in phrases):
        return True
    return hits >= min(2, len(tokens))


def uncovered_claims(answer: str, claims: Iterable[str]) -> list[str]:
    return [claim for claim in claims if claim and not claim_is_covered(claim, answer)]


def repairable_claims(answer: str, claims: Iterable[str], *, query: str = "") -> list[str]:
    """Missed claims that still belong to the user's question (skip memoir / off-topic)."""
    missing = uncovered_claims(answer, claims)
    query_tokens = query_topic_tokens(query)
    if not query_tokens:
        return missing
    return [
        claim
        for claim in missing
        if claim_matches_query(claim, query_tokens, query=query)
    ]


def claim_repair_steer(missing: Iterable[str]) -> str:
    points = [item.strip() for item in missing if item and item.strip()]
    lines = [
        "The draft on screen already answers the user. Do not restart it.",
        "Do not say Certainly, Let's continue, or Teaching Points.",
        "Add only missed theses. You may use a short paragraph or a bullet. "
        "Do not invent extra outline points. Stop on a complete sentence.",
        "Keep a generic Christian pastoral tone. Do not imitate Pastor Don's speaking style.",
        "Only add a missed point if it actually answers the user's question. Skip autobiography, jokes, and unrelated notes.",
        "If none of the points below answer the user's question, reply with nothing.",
        "Keep the same thesis, including the contrast. Do not keep the illustration and change what it teaches.",
    ]
    for index, claim in enumerate(points[:_DEFAULT_LIMIT], start=1):
        lines.append(f"{index}. {claim}")
    return "\n".join(lines)


def claim_repair_token_budget(*, completion_tokens: int, limit: int = 384) -> int:
    completion = int(completion_tokens or 0)
    if completion <= 0:
        return 0
    return min(completion, max(128, int(limit)))


def _content_ngrams(text: str, size: int) -> list[str]:
    tokens = claim_content_tokens(text)
    return [" ".join(tokens[index : index + size]) for index in range(0, max(0, len(tokens) - size + 1))]


_THESIS_ALLOWED_MIN = 1.5


def thesis_sentences_from_docs(
    docs: Iterable[Any] | None,
    *,
    limit: int = 12,
) -> list[str]:
    """Teaching sentences from retrieved sermon notes, excluding stats and KJV."""
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        body = spoken_text_without_timestamps(chunk_text(doc))
        for sentence in _split_claim_units(body) or split_sentences(body) or []:
            if looks_like_vice_catalog(sentence):
                continue
            score = thesis_sentence_score(sentence)
            if text_has_sexuality_application(sentence):
                score += 0.8
            if score < _THESIS_ALLOWED_MIN:
                continue
            claim = _clip_claim(sentence)
            key = normalize_grounding_text(claim)
            if len(key) < 16 or key in seen:
                continue
            seen.add(key)
            scored.append((score, claim))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return [claim for _score, claim in scored[: max(1, limit)]]


def resolve_teaching_claims(
    docs: Iterable[Any] | None,
    *,
    query: str = "",
    claims: Iterable[str] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> list[str]:
    """Use extracted claims when present; otherwise topical theses from the notes."""
    points = [item.strip() for item in (claims or []) if item and str(item).strip()]
    if points:
        return points[: max(1, limit)]
    fallback = thesis_sentences_from_docs(docs, limit=max(limit, 12))
    if not query:
        return fallback[: max(1, limit)]
    query_tokens = query_topic_tokens(query)
    topical = [
        claim
        for claim in fallback
        if claim_matches_query(claim, query_tokens, query=query)
    ]
    if topical:
        return topical[: max(1, limit)]
    if query_topic_sense(query) in {SENSE_ALCOHOL, SENSE_SEXUALITY}:
        return []
    return fallback[: max(1, limit)]


def allowed_idea_texts(
    docs: Iterable[Any] | None,
    claims: Iterable[str] | None,
    *,
    query: str = "",
) -> list[str]:
    """The only ideas generation may teach: retrieved theses, not side slides."""
    points = [item.strip() for item in (claims or []) if item and str(item).strip()]
    seen = {normalize_grounding_text(item) for item in points}
    query_tokens = query_topic_tokens(query) if query else set()
    for sentence in thesis_sentences_from_docs(docs):
        key = normalize_grounding_text(sentence)
        if key in seen:
            continue
        if query and not claim_matches_query(sentence, query_tokens, query=query):
            continue
        seen.add(key)
        points.append(sentence)
    return points


def allowed_idea_hay(
    docs: Iterable[Any] | None,
    claims: Iterable[str] | None,
    *,
    query: str = "",
) -> str:
    return normalize_grounding_text(
        " ".join(allowed_idea_texts(docs, claims, query=query))
    )


def _scripture_attributed_to_pastor(answer: str, sentence: str) -> bool:
    """True when this sentence puts Bible wording in Pastor Don's or Susan's mouth."""
    cleaned = (sentence or "").strip()
    if not cleaned:
        return False
    spans = extract_quote_spans(cleaned) or [cleaned]
    if looks_like_kjv_diction(cleaned) or looks_like_scripture_blob(cleaned):
        spans = [cleaned] + [span for span in spans if span != cleaned]
    for span in spans:
        if not (looks_like_kjv_diction(span) or looks_like_scripture_blob(span)):
            continue
        if quote_attributed_to_pastor(answer, span):
            return True
        prefix = normalize_grounding_text(cleaned[:160])
        if re.search(
            r"\b(?:pastor )?(?:don(?: and susan)?|susan)(?: nordin)?s? "
            r"(?:also )?(?:teaches|taught|said|says|preach|preaches|preached|writes|wrote)\b",
            prefix,
        ):
            return True
    return False


def _hay_content_text(hay: str, claims: Iterable[str]) -> str:
    parts = [hay or ""]
    for claim in claims or []:
        parts.append(str(claim or ""))
    return " ".join(claim_content_tokens(" ".join(parts)))


def sentence_idea_is_in_notes(sentence: str, hay: str, claims: Iterable[str]) -> bool:
    """True when this sentence is mostly made of retrieved thesis words.

    Sharing two thesis words is not enough: a seminar heading can mention
    "total abstinence" and then teach drunk-driving statistics that are not
    in the notes.
    """
    cleaned = (sentence or "").strip()
    if not cleaned:
        return False
    tokens = claim_content_tokens(cleaned)
    if len(tokens) < 2:
        return False
    hay_content = _hay_content_text(hay, claims)
    if not hay_content:
        return False
    hay_set = set(hay_content.split())
    hits = [token for token in tokens if token in hay_set]
    needed = max(2, (len(tokens) * 3 + 4) // 5)
    if len(hits) < needed:
        return False
    grams = _content_ngrams(cleaned, 2)
    if any(gram and gram in hay_content for gram in grams):
        return True
    return len(hits) == len(tokens)


def keep_note_paraphrase_sentences(
    answer: str,
    *,
    sermon_docs: Iterable[Any] | None = None,
    nkjv_docs: Iterable[Any] | None = None,
    claims: Iterable[str] | None = None,
    query: str = "",
) -> str:
    """Drop sentences whose ideas are not in retrieved teaching theses."""
    _ = nkjv_docs
    point_list = resolve_teaching_claims(sermon_docs, query=query, claims=claims)
    hay = allowed_idea_hay(sermon_docs, point_list, query=query)
    kept: list[str] = []
    for sentence in split_sentences(answer) or [answer or ""]:
        cleaned = (sentence or "").strip()
        if not cleaned:
            continue
        if _scripture_attributed_to_pastor(answer, cleaned):
            continue
        if looks_like_kjv_diction(cleaned) or looks_like_scripture_blob(cleaned):
            continue
        if sentence_idea_is_in_notes(cleaned, hay, point_list):
            kept.append(cleaned)
    return " ".join(kept).strip()


def notes_only_from_claims(claims: Iterable[str] | None) -> str:
    """Fallback reply built only from retrieved teaching sentences."""
    points = [item.strip() for item in (claims or []) if item and str(item).strip()]
    return " ".join(points[:4]).strip()


def paraphrase_too_thin(answer: str, claims: Iterable[str] | None) -> bool:
    text = (answer or "").strip()
    if len(text) < 80:
        return True
    point_list = [item.strip() for item in (claims or []) if item and str(item).strip()]
    if point_list and not any(claim_is_covered(claim, text) for claim in point_list[:2]):
        return True
    return False


def ground_to_note_paraphrase(
    answer: str,
    *,
    sermon_docs: Iterable[Any] | None = None,
    nkjv_docs: Iterable[Any] | None = None,
    claims: Iterable[str] | None = None,
    query: str = "",
) -> str:
    """Single paraphrase layer: keep note-backed sentences or emit the theses."""
    point_list = resolve_teaching_claims(sermon_docs, query=query, claims=claims)
    kept = keep_note_paraphrase_sentences(
        answer,
        sermon_docs=sermon_docs,
        nkjv_docs=nkjv_docs,
        claims=point_list,
        query=query,
    )
    if paraphrase_too_thin(kept, point_list):
        return notes_only_from_claims(point_list) or kept
    return kept
