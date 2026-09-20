"""Extractive grounding: allowed sermon quotes, NKJV lookup, and answer verification."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

from .bible_refs import canonical_book_key, format_verse_ref, parse_verse_refs
from .chat_retrieval import (
    chunk_text,
    extract_used_verse_refs,
    is_bible_source,
    metadata_source_hint,
    query_focus_tokens,
    required_topic_synonyms,
)
from .quote_chunking import extract_quote_spans, spoken_text_without_timestamps, split_sentences
from .speaker_attribution import (
    is_pastor_own_voice,
    known_verse_ref,
    looks_like_divine_speech,
    looks_like_nonteaching_excerpt,
    looks_like_scripture_wording,
    quoted_spans_with_voice,
    rewrite_misattributed_quotes,
    normalize_mixed_inner_quotes,
)

logger = logging.getLogger(__name__)

_QUOTE_RE = re.compile(r"[\"“](.{12,400}?)[\"”]")
_MARKUP_RE = re.compile(r"[*_`>#]+")
_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)


def normalize_grounding_text(text: str) -> str:
    folded = (text or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    folded = _MARKUP_RE.sub(" ", folded)
    folded = _PUNCT_RE.sub(" ", folded.lower())
    return _SPACE_RE.sub(" ", folded).strip()


def _metadata(doc: Any) -> dict:
    return dict(getattr(doc, "metadata", None) or {})


def _is_bible_doc(doc: Any) -> bool:
    meta = _metadata(doc)
    kind = str(meta.get("chunk_kind") or "").lower()
    if kind.startswith("bible"):
        return True
    return is_bible_source(metadata_source_hint(doc) or str(meta.get("source") or ""))


_SCRIPTURE_HINT_RE = re.compile(
    r"\b(?:nkjv|kjv)\b|\b(?:psalm|proverbs|matthew|john|james|timothy|corinthians)\b\s+\d+",
    re.IGNORECASE,
)
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "does",
        "don",
        "for",
        "how",
        "nordin",
        "of",
        "pastor",
        "someone",
        "susan",
        "the",
        "to",
        "what",
        "when",
        "whose",
        "create",
        "sermon",
        "notes",
        "about",
        "based",
        "outline",
        "teach",
        "teaches",
        "says",
        "say",
    }
)


def looks_like_scripture_blob(text: str) -> bool:
    blob = text or ""
    if _SCRIPTURE_HINT_RE.search(blob) and parse_verse_refs(blob[:1200]):
        return True
    return bool(parse_verse_refs(blob[:400]) and len(parse_verse_refs(blob[:800])) >= 2)


_HEADING_QUOTE_RE = re.compile(r"^\s*#{1,6}\s+\S")


def looks_like_heading_quote(text: str) -> bool:
    """True for sermon titles / markdown headings, not spoken teaching."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return True
    if cleaned.startswith("#") or _HEADING_QUOTE_RE.match(cleaned):
        return True
    return looks_like_nonteaching_excerpt(cleaned)


def snippet_query_score(text: str, query: str) -> float:
    q_words = {
        word
        for word in normalize_grounding_text(query).split()
        if word not in _QUERY_STOPWORDS and len(word) > 2
    }
    q_words.update(str(token).lower() for token in query_focus_tokens(query) if len(str(token)) > 2)
    q_words.update(str(token).lower() for token in required_topic_synonyms(query) if len(str(token)) > 2)
    q_words = {word for word in q_words if word not in _QUERY_STOPWORDS}
    t_words = set(normalize_grounding_text(text).split())
    if not q_words or not t_words:
        return 0.0
    return len(q_words & t_words) / len(q_words)


def select_query_grounded_quotes(
    quotes: Iterable[str], query: str, *, limit: int = 2, min_score: float = 0.12
) -> list[str]:
    ranked = sorted(
        (
            item.strip()
            for item in quotes
            if item and str(item).strip() and not looks_like_heading_quote(item)
        ),
        key=lambda item: snippet_query_score(item, query),
        reverse=True,
    )
    picked = [item for item in ranked if snippet_query_score(item, query) >= min_score]
    if not picked:
        positive = [item for item in ranked if snippet_query_score(item, query) > 0]
        picked = positive or ranked
    return picked[:limit]


def select_query_grounded_nkjv(
    pairs: Iterable[tuple[str, str]],
    query: str,
    *,
    limit: int = 1,
    min_score: float = 0.12,
) -> list[tuple[str, str]]:
    ranked = sorted(
        [(str(ref), str(text).strip()) for ref, text in pairs if text and str(text).strip()],
        key=lambda item: snippet_query_score(f"{item[0]} {item[1]}", query),
        reverse=True,
    )
    picked = [
        item
        for item in ranked
        if snippet_query_score(f"{item[0]} {item[1]}", query) >= min_score
    ]
    if not picked:
        positive = [
            item
            for item in ranked
            if snippet_query_score(f"{item[0]} {item[1]}", query) > 0
        ]
        picked = positive or ranked
    return picked[:limit]


_MIXED_PASTOR_MIN_CHARS = 100


def _pastor_sentences_from_mixed_notes(body: str, *, bible_corpus: str = "") -> list[str]:
    """Keep spoken teaching from a chunk that also cites verses."""
    sentences = split_sentences(body) or [body]
    pastor: list[str] = []
    verse_sentences = 0
    for sentence in sentences:
        cleaned = " ".join(sentence.split()).strip()
        if len(cleaned) < 40:
            continue
        if (
            looks_like_scripture_blob(cleaned)
            or parse_verse_refs(cleaned[:400])
            or looks_like_scripture_wording(cleaned, bible_corpus)
            or looks_like_heading_quote(cleaned)
        ):
            verse_sentences += 1
            continue
        if is_pastor_own_voice(cleaned, bible_corpus=bible_corpus):
            pastor.append(cleaned)
    pastor_chars = sum(len(item) for item in pastor)
    if pastor_chars < _MIXED_PASTOR_MIN_CHARS:
        return []
    if verse_sentences and pastor_chars < 160 and verse_sentences >= len(pastor):
        return []
    return pastor


def collect_allowed_sermon_quotes(
    docs: Iterable[Any],
    *,
    limit: int = 12,
    bible_corpus: str = "",
) -> list[str]:
    """Exact lines the model may quote as Pastor Don / Susan."""
    quotes: list[str] = []
    seen: set[str] = set()
    bible = bible_corpus or ""
    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        kind = str(meta.get("chunk_kind") or "").lower()
        if "overview" in kind:
            continue
        stored = str(meta.get("quote_text") or "").strip()
        body = spoken_text_without_timestamps(chunk_text(doc))
        candidates: list[str] = []
        if stored:
            for part in stored.split(" | "):
                piece = " ".join(part.split()).strip()
                if (
                    piece
                    and not looks_like_scripture_blob(piece)
                    and is_pastor_own_voice(piece, bible_corpus=bible)
                ):
                    candidates.append(piece)
        candidates.extend(extract_quote_spans(body))
        candidates.extend(_pastor_sentences_from_mixed_notes(body, bible_corpus=bible))
        if body and len(body) >= 40 and not looks_like_scripture_blob(body):
            candidates.append(body)
        for item in candidates:
            cleaned = " ".join(item.split())
            key = normalize_grounding_text(cleaned)
            if len(cleaned) < 12 or key in seen:
                continue
            if looks_like_heading_quote(cleaned):
                continue
            if looks_like_scripture_blob(cleaned):
                continue
            if not is_pastor_own_voice(cleaned, bible_corpus=bible):
                continue
            seen.add(key)
            quotes.append(cleaned)
            if len(quotes) >= limit:
                return quotes
    return quotes


def collect_allowed_nkjv(docs: Iterable[Any], *, limit: int = 12) -> list[tuple[str, str]]:
    """(ref, exact NKJV wording) pairs from retrieved or looked-up Bible chunks."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for doc in docs or []:
        if not _is_bible_doc(doc):
            continue
        meta = _metadata(doc)
        ref = str(meta.get("verse_ref") or "").strip()
        if not ref:
            book = meta.get("book")
            chapter = meta.get("chapter")
            start = meta.get("verse_start")
            if book and chapter and start:
                ref = format_verse_ref(book, int(chapter), int(start), verse_end=meta.get("verse_end"))
        wording = str(meta.get("quote_text") or "").strip() or spoken_text_without_timestamps(chunk_text(doc))
        wording = " ".join(wording.split())
        if len(wording) < 8:
            continue
        key = normalize_grounding_text(f"{ref}|{wording}")
        if key in seen:
            continue
        seen.add(key)
        pairs.append((ref or "NKJV", wording))
        if len(pairs) >= limit:
            break
    return pairs


def sermon_note_corpus(docs: Iterable[Any]) -> str:
    parts = []
    for doc in docs or []:
        if _is_bible_doc(doc):
            continue
        parts.append(spoken_text_without_timestamps(chunk_text(doc)))
        quote_text = str(_metadata(doc).get("quote_text") or "")
        if quote_text:
            parts.append(quote_text.replace(" | ", " "))
    return " ".join(parts)


def nkjv_corpus(docs: Iterable[Any]) -> str:
    parts = []
    for doc in docs or []:
        if not _is_bible_doc(doc):
            continue
        parts.append(str(_metadata(doc).get("quote_text") or ""))
        parts.append(chunk_text(doc))
    return " ".join(parts)


def text_is_grounded(span: str, corpus: str, *, min_ratio: float = 0.92) -> bool:
    needle = normalize_grounding_text(span)
    hay = normalize_grounding_text(corpus)
    if not needle or len(needle) < 12:
        return True
    if needle in hay:
        return True
    words = needle.split()
    if len(words) < 6:
        return False
    # Allow a short prefix/suffix mismatch from punctuation or NKJV italics.
    probe = " ".join(words[1:-1] if len(words) > 8 else words)
    if len(probe) >= 20 and probe in hay:
        return True
    from difflib import SequenceMatcher

    window = max(len(needle) - 8, 24)
    if len(hay) < 12:
        return False
    best = 0.0
    step = max(12, window // 4)
    for start in range(0, max(1, len(hay) - window + 1), step):
        chunk = hay[start : start + window + 16]
        best = max(best, SequenceMatcher(None, needle, chunk).ratio())
        if best >= min_ratio:
            return True
    return False


@dataclass
class GroundingReport:
    ok: bool
    invented_quotes: list[str] = field(default_factory=list)
    invented_scripture: list[str] = field(default_factory=list)
    missing_nkjv_refs: list[str] = field(default_factory=list)
    misattributed_quotes: list[str] = field(default_factory=list)


def verify_answer_grounding(
    answer: str,
    *,
    sermon_docs: Iterable[Any],
    nkjv_docs: Iterable[Any],
) -> GroundingReport:
    notes = sermon_note_corpus(sermon_docs)
    bible = nkjv_corpus(nkjv_docs)
    allowed_refs = {
        canonical_book_key(book) + f"|{chapter}|{verse}"
        for book, chapter, verse in parse_verse_refs(
            " ".join(str(_metadata(doc).get("verse_ref") or "") + " " + chunk_text(doc) for doc in (nkjv_docs or []))
        )
    }
    for doc in nkjv_docs or []:
        meta = _metadata(doc)
        book = canonical_book_key(str(meta.get("book") or ""))
        chapter = meta.get("chapter")
        start = int(meta.get("verse_start") or 0)
        end = int(meta.get("verse_end") or start)
        if book and chapter and start:
            for verse in range(start, max(start, end) + 1):
                allowed_refs.add(f"{book}|{int(chapter)}|{verse}")

    invented_quotes: list[str] = []
    invented_scripture: list[str] = []
    misattributed_quotes: list[str] = []
    voiced = quoted_spans_with_voice(answer)
    for span, voice in voiced:
        in_notes = text_is_grounded(span, notes)
        in_bible = text_is_grounded(span, bible)
        scripture_like = looks_like_scripture_wording(span, bible) or in_bible
        if voice == "pastor" and scripture_like:
            misattributed_quotes.append(span)
            continue
        if in_notes or in_bible:
            continue
        if voice == "scripture" and (
            known_verse_ref(span) or looks_like_divine_speech(span)
        ):
            continue
        lowered = (span or "").lower()
        if "nkjv" in lowered or parse_verse_refs(span) or voice == "scripture":
            invented_scripture.append(span)
        else:
            invented_quotes.append(span)

    missing_refs: list[str] = []
    for ref in extract_used_verse_refs([answer]):
        parsed = parse_verse_refs(ref)
        if not parsed:
            continue
        book, chapter, verse = parsed[0]
        key = f"{canonical_book_key(book)}|{chapter}|{verse}"
        if allowed_refs and key not in allowed_refs:
            missing_refs.append(ref)
        elif not bible.strip():
            missing_refs.append(ref)

    ok = (
        not invented_quotes
        and not invented_scripture
        and not missing_refs
        and not misattributed_quotes
    )
    return GroundingReport(
        ok=ok,
        invented_quotes=invented_quotes,
        invented_scripture=invented_scripture,
        missing_nkjv_refs=missing_refs,
        misattributed_quotes=misattributed_quotes,
    )


def strip_ungrounded_spans(answer: str, report: GroundingReport | None) -> str:
    """Drop invented quotation/verse wording so a repair pass is not a second sermon."""
    text = answer or ""
    if report is None:
        return text
    for span in list(report.invented_quotes) + list(report.invented_scripture):
        snippet = (span or "").strip()
        if len(snippet) < 20:
            continue
        text = text.replace(snippet, "")
    text = re.sub(r'"\s*"', "", text)
    text = re.sub(r"[“”]\s*[“”]", "", text)
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    return text.strip()


_RETRIEVAL_DUMP_RE = re.compile(
    r"(?im)^\s*from the retrieved notes:\s*$"
)
_RETRIEVAL_HEADER_RE = re.compile(
    r"(?im)^\s*(?:"
    r"from the retrieved notes:|"
    r"pastor don and susan nordin teach from the retrieved sermons:|"
    r"the retrieved sermon notes do not include a usable pastor don or susan quotation.*|"
    r"no nkjv verse from the retrieved bible document applies.*|"
    r"scripture \(nkjv\):"
    r")\s*$"
)
_RETRIEVAL_DISCLAIMER_RE = re.compile(
    r"(?is)\n*\s*I can only teach from these retrieved lines\.[^\n]*"
)
_TITLE_WEAVE_RE = re.compile(
    r'(?is)\s*Pastor Don(?: and Susan)? Nordin(?: also)? teach(?:es)?,?\s*"[#][^"]*"'
)
_META_OPENER_RE = re.compile(
    r"(?is)^\s*(?:certainly|sure)[!.,]?\s+"
    r"here(?:'s| is)\s+.{0,160}?based on the provided (?:scripture and )?notes[:.]?\s*"
)
_SLIDE_NOTE_RE = re.compile(
    r"(?is)\s*(?:\((?:LEAVE ON SCREEN|UNTIL END OF SERVICE)[^)]*\)|"
    r"LEAVE ON SCREEN UNTIL END OF SERVICE)"
)
_HEADING_BLOCK_RE = re.compile(r"^(?:#{1,3}\s+|\*\*).{2,80}\*?\*?$")
_GLUED_BOOK_RE = re.compile(
    r"\bT(Jeremiah|Hebrews|Psalms?|Isaiah|Matthew|John|Luke|Romans|Corinthians)\b"
)
_SOURCE_BULLET_RE = re.compile(
    r"(?im)^\s*[•\-\*]\s*(?:Pastor Don(?: and Susan)?(?: Nordin)?|NKJV|Scripture)\s*$"
)
_EMPTY_EXPLAIN_RE = re.compile(
    r'(?im)^\s*(?:He|She|They|Pastor Don(?: and Susan)?(?: Nordin)?)\s+'
    r'(?:explains?|teaches?|says|said|emphasizes?),?\s*["“]\s*$'
)
_EMPTY_ADVISES_RE = re.compile(r"(?i)\b(?:specifically,\s*)?he advises:\.\s*")
_EMPTY_STATES_RE = re.compile(
    r"(?i)(?:in\s+)?((?:[1-3]\s+)?[A-Za-z]+(?:\s+[A-Za-z]+)?\s+\d+:\d+(?:-\d+)?)"
    r"\s*\(\s*NKJV\s*\)\s*,?\s*it states,\s*(?=[A-Z])"
)
_EMPTY_NKJV_CITE_RE = re.compile(
    r"(?i)(?:in\s+)?"
    r"((?:[1-3]\s+)?[A-Za-z][A-Za-z]+(?:\s+[A-Za-z][A-Za-z]+)?\s+\d+:\d+(?:-\d+)?)"
    r"\s*\(\s*NKJV\s*\)\s*,?\s*"
    r"(?:it\s+)?"
    r"(?:states|says|reminds(?:\s+\w+)?|promises|instructs|encourages(?:\s+\w+)?|"
    r"assures(?:\s+\w+)?|reassures(?:\s+\w+)?|outlines|warns(?:\s+against)?|"
    r"teaches\s+that|highlights(?:\s+\w+(?:\s+\w+)?)?|"
    r"emphasizes(?:\s+\w+(?:\s+\w+)?)?|we see)"
    r'(?!\s*,?\s*[\"“])'
    r",?\s*"
)
_THIS_VERSE_PREFIX_RE = re.compile(
    r"(?i)^(?:This means\s+|"
    r"This (?:verse|passage) (?:highlights that|emphasizes that|"
    r"encourages us to|assures us that|instructs(?:\s+us)?(?:\s+that)?|"
    r"promises that|teaches that|says that|reminds us that|highlights|"
    r"emphasizes|encourages us|assures us|promises|teaches|says|reminds us)\s+)"
)
_EMPTY_TEACHES_MEANS_RE = re.compile(
    r"(?i)Pastor Don(?: and Susan)?(?: Nordin)?(?: also)? teach(?:es)?,\s*This means\s+"
)
_EMPTY_SAYS_THIS_RE = re.compile(
    r"(?i)\(\s*NKJV\s*\)\s+says,\s+This (?:verse|passage)\s+"
)
_TEACHINGS_PROVIDED_RE = re.compile(
    r"(?i)(?:here are some key points )?based on the teachings provided:\s*"
)
_AS_THIS_OBSERVATION_RE = re.compile(
    r"(?i)\bAs This observation highlights[^.?\n]*[.?]?\s*"
)
_EMPTY_EXCERPT_RE = re.compile(r"(?im)^\s*\*?Excerpt\*?:\s*$")
_EMPTY_QUOTES_RE = re.compile(r'[\"“]\s*[\"”]')
_CERTAINLY_OPENER_RE = re.compile(
    r"(?is)^\s*(?:certainly|sure)[!.,]?\s+here(?:'s| is| are)\s+.{0,180}?:\s*"
)
_SLIDE_WORSHIP_QUOTE_RE = re.compile(
    r'(?is)Pastor Don(?: and Susan)?(?: Nordin)?(?: also)? teach(?:es)?,?\s*'
    r'["“]WORSHIP["”].{0,180}?(?:["”]|$)'
)
_BULLET_GLYPH_RE = re.compile(r"[•▪▫]\s*")
_GLUED_SENTENCE_RE = re.compile(r"([a-z])\.([A-Z])")


def _clip_excerpt(text: str, limit: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    for sep in (". ", "; "):
        idx = cut.rfind(sep)
        if idx >= 80:
            return cut[: idx + 1].strip()
    trimmed = cut.rsplit(" ", 1)[0].strip()
    return (trimmed or cut).rstrip(".,;:") + "…"


def _wording_for_nkjv_ref(ref: str, pairs: list[tuple[str, str]]) -> str:
    wanted = parse_verse_refs(ref)
    if not wanted:
        return ""
    book, chapter, verse = wanted[0]
    want = f"{canonical_book_key(book)}|{int(chapter)}|{int(verse)}"
    for pref, wording in pairs:
        for p_book, p_chapter, p_verse in parse_verse_refs(pref) or []:
            key = f"{canonical_book_key(p_book)}|{int(p_chapter)}|{int(p_verse)}"
            if key == want:
                return _clip_excerpt(wording, 240)
        if normalize_grounding_text(ref) in normalize_grounding_text(pref):
            return _clip_excerpt(wording, 240)
    return ""


def repair_empty_nkjv_citations(
    answer: str,
    nkjv_pairs: Iterable[tuple[str, str]] = (),
) -> str:
    """Fill or rewrite verse lead-ins that never quoted the NKJV wording."""
    text = answer or ""
    if not text:
        return text
    pairs = [(str(ref), str(wording).strip()) for ref, wording in (nkjv_pairs or []) if wording]
    pieces: list[str] = []
    cursor = 0
    for match in _EMPTY_NKJV_CITE_RE.finditer(text):
        if match.start() < cursor:
            continue
        ref = match.group(1)
        tail = text[match.end() :]
        this_m = _THIS_VERSE_PREFIX_RE.match(tail)
        wording = _wording_for_nkjv_ref(ref, pairs)
        pieces.append(text[cursor:match.start()])
        if wording:
            bit = f'{ref} (NKJV) says, "{wording}"'
            if this_m:
                remainder = tail[this_m.end() :]
                joiner = " " if remainder[:1] not in " \n" else ""
                pieces.append(bit + joiner)
                cursor = match.end() + this_m.end()
            elif tail.lstrip()[:1] in '"“':
                pieces.append(bit + " ")
                cursor = match.end()
            else:
                skip = re.match(r"[ \t]*[^\n]{0,220}", tail)
                pieces.append(bit)
                cursor = match.end() + (skip.end() if skip else 0)
            continue
        if this_m:
            pieces.append(f"{ref} (NKJV) teaches that ")
            cursor = match.end() + this_m.end()
        else:
            pieces.append(f"{ref} (NKJV) teaches that ")
            cursor = match.end()
    pieces.append(text[cursor:])
    cleaned = "".join(pieces)
    cleaned = re.sub(r" +", " ", cleaned)
    cleaned = re.sub(r" \n", "\n", cleaned)
    return cleaned.strip()


def strip_retrieval_meta(answer: str) -> str:
    """Drop labeled retrieval dumps so the user only sees the teaching reply."""
    text = answer or ""
    dump = _RETRIEVAL_DUMP_RE.search(text)
    if dump:
        text = text[: dump.start()].rstrip()
    text = _RETRIEVAL_DISCLAIMER_RE.sub("", text)
    text = _TITLE_WEAVE_RE.sub("", text)
    text = _META_OPENER_RE.sub("", text)
    text = _RETRIEVAL_HEADER_RE.sub("", text)
    text = _SLIDE_NOTE_RE.sub("", text)
    text = _GLUED_BOOK_RE.sub(r"\1", text)
    text = normalize_mixed_inner_quotes(text)
    text = _SOURCE_BULLET_RE.sub("", text)
    text = _EMPTY_EXPLAIN_RE.sub("", text)
    text = _EMPTY_ADVISES_RE.sub("", text)
    text = _EMPTY_TEACHES_MEANS_RE.sub("", text)
    text = _CERTAINLY_OPENER_RE.sub("", text)
    text = _AS_THIS_OBSERVATION_RE.sub("", text)
    text = _TEACHINGS_PROVIDED_RE.sub("", text)
    text = _EMPTY_EXCERPT_RE.sub("", text)
    text = _EMPTY_QUOTES_RE.sub("", text)
    text = _SLIDE_WORSHIP_QUOTE_RE.sub("", text)
    text = _BULLET_GLYPH_RE.sub("", text)
    text = _GLUED_SENTENCE_RE.sub(r"\1. \2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return repair_empty_nkjv_citations(text.strip())


def grounded_fallback_answer(
    quotes: Iterable[str],
    nkjv_pairs: Iterable[tuple[str, str]],
) -> str:
    """Attributed Pastor Don / NKJV sentences with no retrieval labels."""
    quote_list = [
        _clip_excerpt(item)
        for item in quotes
        if item
        and str(item).strip()
        and not looks_like_heading_quote(item)
        and is_pastor_own_voice(item)
    ][:2]
    quote_list = [item for item in quote_list if item]
    nkjv_list = [
        (ref, _clip_excerpt(text, 240))
        for ref, text in nkjv_pairs
        if text and str(text).strip()
    ][:1]
    sentences: list[str] = []
    if quote_list:
        sentences.append(f'Pastor Don Nordin teaches, "{quote_list[0]}"')
        if len(quote_list) > 1:
            sentences.append(f'Pastor Don and Susan Nordin also teach, "{quote_list[1]}"')
    if nkjv_list:
        ref, wording = nkjv_list[0]
        sentences.append(f'{ref} (NKJV) says, "{wording}"')
    return " ".join(sentences).strip()


def weave_into_answer(answer: str, snippet: str) -> str:
    """Fold attributed quotes into the opening teaching, not a footer dump."""
    text = strip_retrieval_meta(answer or "")
    extra = (snippet or "").strip()
    if not extra:
        return text
    if extra in text:
        return text
    if not text:
        return extra
    blocks = re.split(r"(\n\n+)", text)
    for index, block in enumerate(blocks):
        body = block.strip()
        if not body or block.startswith("\n"):
            continue
        if _HEADING_BLOCK_RE.match(body) and "\n" not in body:
            continue
        joiner = " " if body[-1:] in '.!?"\'”’)' else ". "
        blocks[index] = block.rstrip() + joiner + extra
        return "".join(blocks).strip()
    return f"{text.rstrip()}\n\n{extra}"


def verse_refs_for_lookup(user_query: str, docs: Iterable[Any], *, limit: int = 8) -> list[tuple[str, int, int]]:
    blobs = [user_query or ""]
    for doc in docs or []:
        blobs.append(chunk_text(doc))
        blobs.append(str(_metadata(doc).get("verse_ref") or ""))
        refs = _metadata(doc).get("scripture_refs") or []
        if isinstance(refs, (list, tuple)):
            blobs.extend(str(item) for item in refs)
    return parse_verse_refs(" ".join(blobs))[:limit]


def _payload_of(point: Any) -> dict:
    payload = getattr(point, "payload", None)
    if isinstance(payload, dict):
        return payload
    return {}


def lookup_nkjv_verses(
    client: Any,
    collection_name: str,
    refs: Iterable[tuple[str, int, int]],
    *,
    retrieved_docs: Optional[Iterable[Any]] = None,
    make_doc: Optional[Callable[[str, dict], Any]] = None,
    limit_per_ref: int = 3,
) -> list[Any]:
    """Return Bible documents for the requested refs from payload lookup or retrieved docs."""
    from types import SimpleNamespace

    factory = make_doc or (
        lambda text, metadata: SimpleNamespace(page_content=text, metadata=metadata)
    )
    found: list[Any] = []
    seen: set[str] = set()

    def add_doc(doc: Any) -> None:
        text = chunk_text(doc)
        key = normalize_grounding_text(text)[:240]
        if not key or key in seen:
            return
        seen.add(key)
        found.append(doc)

    retrieved = [doc for doc in (retrieved_docs or []) if _is_bible_doc(doc)]
    wanted = {(canonical_book_key(book), int(chapter), int(verse)) for book, chapter, verse in refs}

    for doc in retrieved:
        meta = _metadata(doc)
        book = canonical_book_key(str(meta.get("book") or ""))
        chapter = int(meta.get("chapter") or 0)
        start = int(meta.get("verse_start") or 0)
        end = int(meta.get("verse_end") or start)
        if book and chapter and start and any(
            book == w_book and chapter == w_chap and start <= w_verse <= max(start, end)
            for w_book, w_chap, w_verse in wanted
        ):
            add_doc(doc)

    if not wanted:
        return found

    if client is None:
        return found

    from qdrant_client.http import models as qdrant_models

    for book, chapter, verse in list(wanted)[:12]:
        try:
            points, _offset = client.scroll(
                collection_name=collection_name,
                scroll_filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="chunk_kind",
                            match=qdrant_models.MatchValue(value="bible_verse"),
                        ),
                        qdrant_models.FieldCondition(
                            key="book",
                            match=qdrant_models.MatchValue(value=book),
                        ),
                        qdrant_models.FieldCondition(
                            key="chapter",
                            match=qdrant_models.MatchValue(value=int(chapter)),
                        ),
                    ]
                ),
                limit=max(8, limit_per_ref * 4),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            logger.debug("NKJV payload lookup failed for %s %s:%s", book, chapter, verse, exc_info=True)
            points = []
        matched = 0
        for point in points or []:
            payload = _payload_of(point)
            start = int(payload.get("verse_start") or 0)
            end = int(payload.get("verse_end") or start)
            if start and not (start <= verse <= max(start, end)):
                continue
            text = str(payload.get("text") or "").strip()
            if not text:
                continue
            metadata = dict(payload.get("metadata") or {})
            metadata.update({k: v for k, v in payload.items() if k != "metadata"})
            add_doc(factory(text, metadata))
            matched += 1
            if matched >= limit_per_ref:
                break
    return found


GROUNDING_REPAIR_STEER = (
    "A RAG check found quotations or verses that are not in the retrieved notes, "
    "or Scripture / the Lord's words wrapped as Pastor Don quotes. "
    "Do not restart or apologize. Do not say Certainly, Let's continue, or Teaching Points. "
    "Do not repeat headings, numbered points, or rewrite the sermon already on screen. "
    "Drop any quotation or verse that is not copied from ALLOWED SERMON QUOTES or ALLOWED NKJV. "
    "Never attribute NKJV wording or first-person God/Jesus speech to Pastor Don or Susan. "
    "Write only replacement ALLOWED SERMON QUOTES (at least two, attributed as Pastor Don or Susan) "
    "and one ALLOWED NKJV verse if that list is not empty, cited as Scripture."
)


def split_docs_for_grounding(docs: Iterable[Any]) -> tuple[list[Any], list[Any]]:
    sermon: list[Any] = []
    bible: list[Any] = []
    for doc in docs or []:
        if _is_bible_doc(doc):
            bible.append(doc)
        else:
            sermon.append(doc)
    return sermon, bible


def grounding_repair_steer(
    report: GroundingReport,
    quotes: Iterable[str],
    nkjv_pairs: Iterable[tuple[str, str]],
) -> str:
    parts = [GROUNDING_REPAIR_STEER]
    if report.invented_quotes:
        parts.append("Drop these ungrounded quotations:")
        for span in report.invented_quotes[:4]:
            parts.append(f'- "{(span or "")[:220]}"')
    if report.misattributed_quotes:
        parts.append("These quotations are Scripture or the Lord speaking — do not wrap them as Pastor Don:")
        for span in report.misattributed_quotes[:4]:
            parts.append(f'- "{(span or "")[:220]}"')
    dropped = list(report.invented_scripture) + list(report.missing_nkjv_refs)
    if dropped:
        parts.append("Drop these ungrounded Scripture lines or refs:")
        for span in dropped[:6]:
            parts.append(f"- {(span or '')[:220]}")
    quote_list = [item.strip() for item in quotes if item and str(item).strip()][:4]
    if quote_list:
        parts.append("ALLOWED SERMON QUOTES (copy word-for-word):")
        for quote in quote_list:
            parts.append(f'- "{quote[:240]}"')
    nkjv_list = [
        (str(ref), str(text).strip())
        for ref, text in nkjv_pairs
        if text and str(text).strip()
    ][:4]
    if nkjv_list:
        parts.append("ALLOWED NKJV (copy word-for-word):")
        for ref, wording in nkjv_list:
            parts.append(f'- {ref}: "{wording[:240]}"')
    parts.append("Then stop.")
    return "\n".join(parts)


def repair_speaker_attributions(
    answer: str,
    *,
    nkjv_docs: Iterable[Any] = (),
) -> str:
    """Rewrite Pastor Don / he-teaches wraps that are actually Scripture."""
    return rewrite_misattributed_quotes(
        answer or "",
        bible_corpus=nkjv_corpus(nkjv_docs),
        nkjv_pairs=collect_allowed_nkjv(nkjv_docs),
    )
