"""Score one pastor-chat reply against the excerpts that request used.

The suite sends these functions the passages returned by POST /api/chat/
when include_passages is set. Searching Qdrant again would not be the same
excerpts, because HyDE can change the retrieval.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from core.bible_refs import VERSE_REF_RE  # noqa: E402
from core.study_draft import display_scripture_refs  # noqa: E402


ACCURACY_FAIL_BELOW = 60
PASTORAL_MAX_CHARS = 1200
DRAFT_HEADINGS = ("Title:", "Big idea:", "Primary biblical texts:")

_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "being",
    "but",
    "can",
    "could",
    "did",
    "does",
    "doing",
    "from",
    "have",
    "having",
    "into",
    "just",
    "might",
    "must",
    "not",
    "only",
    "over",
    "shall",
    "should",
    "some",
    "such",
    "than",
    "that",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "under",
    "very",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
    "your",
}

_WORD = re.compile(r"[A-Za-z][A-Za-z']{3,}")
_LABEL = re.compile(
    r"^(?:title|subtitle|big idea|primary biblical texts|"
    r"supporting biblical texts|application|gaps)\s*:\s*",
    re.IGNORECASE,
)
_GAP_ADMISSION = re.compile(
    r"do(?:es)?\s+not\s+cover|don'?t\s+cover|not\s+covered|"
    r"not\s+in\s+the\s+(?:excerpts|notes|sermons)|"
    r"no\s+sermon|"
    r"cannot\s+find|can'?t\s+find|"
    r"do(?:es)?\s+not\s+address|not\s+addressed|"
    r"(?:excerpts|notes)\s+do(?:es)?\s+not",
    re.IGNORECASE,
)


def load_cases(path: Path) -> list[dict]:
    """Load the suite's small YAML subset. No PyYAML dependency."""
    turns: list[dict] = []
    current: dict | None = None
    list_key: str | None = None
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        text = raw.strip()
        if indent == 0:
            if text != "turns:":
                raise ValueError(f"{path}:{line_number}: expected turns:")
            continue
        if indent == 2 and text.startswith("- "):
            current = {}
            turns.append(current)
            list_key = None
            key, value = _split_field(text[2:], path, line_number)
            current[key] = _scalar(value)
            continue
        if current is None:
            raise ValueError(f"{path}:{line_number}: field is outside a turn")
        if indent == 6 and text.startswith("- ") and list_key:
            current[list_key].append(_scalar(text[2:]))
            continue
        if indent == 4 and text.endswith(":") and ": " not in text:
            list_key = text[:-1]
            current[list_key] = []
            continue
        if indent == 4:
            list_key = None
            key, value = _split_field(text, path, line_number)
            current[key] = _scalar(value)
            continue
        raise ValueError(f"{path}:{line_number}: unsupported YAML {text!r}")
    if not turns:
        raise ValueError(f"{path}: no turns")
    for turn in turns:
        for key in ("id", "kind", "query", "expect_pipeline"):
            if not turn.get(key):
                raise ValueError(f"{path}: turn {turn.get('id')!r} is missing {key}")
        if turn["kind"] not in {"pastoral", "draft"}:
            raise ValueError(f"{path}: {turn['id']} kind must be pastoral or draft")
        turn["must_mention"] = [str(item) for item in turn.get("must_mention") or []]
        turn["must_not_mention"] = [str(item) for item in turn.get("must_not_mention") or []]
        turn["anaphoric"] = bool(turn.get("anaphoric"))
    return turns


def score_reply(answer: str, passages: list[dict] | None) -> dict:
    """Return a 0-100 accuracy score against the passages from this request."""
    text = (answer or "").strip()
    corpus = _passage_corpus(passages)
    if not corpus:
        admits_gap = bool(text) and _GAP_ADMISSION.search(text) is not None
        sentences = _sentences(text)
        return {
            "accuracy": 100 if admits_gap else 0,
            "unsupported_sentences": [] if admits_gap else sentences,
            "missing_scripture": [],
            "unit_count": 0 if admits_gap else max(1, len(sentences)),
            "supported_units": 1 if admits_gap else 0,
        }

    unsupported_sentences = []
    supported = 0
    total = 0
    for sentence in _sentences(text):
        words = _content_words(sentence)
        if not words:
            continue
        total += 1
        hits = sum(1 for word in words if _contains_word(corpus, word))
        if hits * 2 >= len(words):
            supported += 1
        else:
            unsupported_sentences.append(sentence)

    missing_scripture = []
    for ref in display_scripture_refs(text):
        total += 1
        if _ref_mentioned(corpus, ref):
            supported += 1
        else:
            missing_scripture.append(ref)

    if total == 0:
        return {
            "accuracy": 0,
            "unsupported_sentences": [],
            "missing_scripture": [],
            "unit_count": 0,
            "supported_units": 0,
        }
    return {
        "accuracy": _percent(supported, total),
        "unsupported_sentences": unsupported_sentences,
        "missing_scripture": missing_scripture,
        "unit_count": total,
        "supported_units": supported,
    }


def render_scorecard(report: dict) -> str:
    """Markdown the chat reply should contain, one section per turn."""
    passed = report.get("passed", 0)
    total = report.get("total", 0)
    session_id = report.get("session_id") or "unknown"
    restored = report.get("restored_active_session") or "none"
    lines = [
        "# Pastor chat test",
        "",
        f"Passed {passed} of {total}.",
        f"Session: `{session_id}`.",
        f"Previous active chat restored to: `{restored}`.",
        "",
    ]
    for turn in report.get("turns") or []:
        lines.extend(_turn_section(turn))
    return "\n".join(lines).rstrip() + "\n"


def _turn_section(turn: dict) -> list[str]:
    passed = bool(turn.get("pass"))
    mark = "PASS" if passed else "FAIL"
    reasons = [str(item) for item in turn.get("reasons") or [] if str(item).strip()]
    result = "passed" if passed else "; ".join(reasons) or "failed"
    return [
        f"## {mark} {turn.get('id') or 'turn'}",
        "",
        f"- Accuracy: {turn.get('accuracy', 0)}",
        f"- Pipeline: {turn.get('pipeline') or 'none'}",
        f"- Anaphoric: {'yes' if turn.get('anaphoric') else 'no'}",
        f"- Prompt: {turn.get('query') or ''}",
        f"- Result: {result}",
        f"- Sources: {_joined(turn.get('sources'))}",
        f"- Passages scored: {_joined(turn.get('passage_titles'))}",
        f"- Unsupported sentences: {_joined(turn.get('unsupported_sentences'))}",
        f"- Scripture not in the passages: {_joined(turn.get('missing_scripture'))}",
        "",
        "### Answer",
        "",
        _fence(str(turn.get("answer") or "")),
        "",
    ]


def _joined(items) -> str:
    values = [str(item).strip() for item in items or [] if str(item).strip()]
    return ", ".join(values) if values else "none"


def _fence(text: str) -> str:
    body = text if text.strip() else "(empty)"
    marker = "````" if "```" in body else "```"
    return f"{marker}text\n{body}\n{marker}"


def grade_turn(turn: dict, answer: str, pipeline: str, passages: list[dict] | None) -> dict:
    """Hard checks for one turn, including the accuracy bar."""
    reasons = []
    text = (answer or "").strip()
    if not text:
        reasons.append("empty answer")
    if pipeline != turn["expect_pipeline"]:
        reasons.append(f"pipeline {pipeline or 'missing'} != {turn['expect_pipeline']}")
    lowered = text.lower()
    for anchor in turn.get("must_mention") or []:
        if anchor.lower() not in lowered:
            reasons.append(f"missing {anchor}")
    for anchor in turn.get("must_not_mention") or []:
        if anchor.lower() in lowered:
            reasons.append(f"still mentions {anchor}")
    if text and turn.get("kind") == "pastoral" and len(text) > PASTORAL_MAX_CHARS:
        reasons.append(f"pastoral reply is {len(text)} characters")
    if text and turn.get("kind") == "draft":
        for heading in DRAFT_HEADINGS:
            if heading.lower() not in lowered:
                reasons.append(f"missing heading {heading}")
        if not display_scripture_refs(text):
            reasons.append("draft has no scripture reference")
    scored = score_reply(text, passages)
    if scored["accuracy"] < ACCURACY_FAIL_BELOW:
        reasons.append(f"accuracy {scored['accuracy']} < {ACCURACY_FAIL_BELOW}")
    return {
        "pass": not reasons,
        "reasons": reasons,
        **scored,
    }


def _passage_corpus(passages: list[dict] | None) -> str:
    parts = []
    for passage in passages or []:
        if not isinstance(passage, dict):
            continue
        title = str(passage.get("title") or "").strip()
        text = str(passage.get("text") or "").strip()
        if title:
            parts.append(title)
        if text:
            parts.append(text)
    return "\n".join(parts).lower()


def _sentences(text: str) -> list[str]:
    sentences = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for part in re.split(r"(?<=[.!?])\s+", line):
            cleaned = _LABEL.sub("", part).strip()
            if cleaned:
                sentences.append(cleaned)
    return sentences


def _content_words(sentence: str) -> list[str]:
    words = []
    for match in _WORD.finditer(sentence):
        word = match.group(0).lower().strip("'")
        if len(word) <= 3 or word in _STOPWORDS:
            continue
        words.append(word)
    return words


def _contains_word(corpus: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", corpus) is not None


def _ref_mentioned(corpus: str, ref: str) -> bool:
    if ref.lower() in corpus:
        return True
    match = VERSE_REF_RE.search(ref)
    if not match:
        return False
    book = re.escape(match.group(1).lower())
    chapter = match.group(2)
    return re.search(rf"\b{book}\s+{chapter}(?!\d)", corpus) is not None


def _percent(supported: int, total: int) -> int:
    return int((supported * 100 + total // 2) // total)


def _split_field(text: str, path: Path, line_number: int) -> tuple[str, str]:
    if ":" not in text:
        raise ValueError(f"{path}:{line_number}: expected key: value")
    key, value = text.split(":", 1)
    return key.strip(), value.strip()


def _scalar(value: str):
    if value == "" or value == "[]":
        return [] if value == "[]" else ""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
