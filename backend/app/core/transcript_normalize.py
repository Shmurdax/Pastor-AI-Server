"""
Normalize Whisper transcripts before RAG chunking.

Keeps teaching that relates to Christianity, the Bible, or social ideas/issues,
and drops spoken fluff (fillers, channel CTAs, ads, and isolated off-topic talk).
Timestamps stay attached to surviving segments so retrieval can cite a clip.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class NormalizeStats:
    segments_in: int = 0
    fillers_stripped: int = 0
    fluff_segments_removed: int = 0
    off_topic_segments_removed: int = 0
    empty_segments_removed: int = 0

    def as_dict(self) -> dict:
        return {
            "segments_in": self.segments_in,
            "fillers_stripped": self.fillers_stripped,
            "fluff_segments_removed": self.fluff_segments_removed,
            "off_topic_segments_removed": self.off_topic_segments_removed,
            "empty_segments_removed": self.empty_segments_removed,
        }


@dataclass
class NormalizeResult:
    segments: List[TranscriptSegment] = field(default_factory=list)
    stats: NormalizeStats = field(default_factory=NormalizeStats)

    @property
    def text(self) -> str:
        return "\n".join(format_segment_line(seg) for seg in self.segments).strip()


_FILLER_TOKEN_RE = re.compile(
    r"\b(?:um+|uh+|er+|ah+|hmm+|huh+|mm+|mhm+|uh-huh|uh huh)\b[ ,]*",
    re.IGNORECASE,
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:you know|i mean|kind of|sort of|basically|literally|okay|ok|well|alright|all right|right)[,.\s]+)+",
    re.IGNORECASE,
)
_REPEATED_SO_RE = re.compile(r"^(?:so[,.\s]+){2,}", re.IGNORECASE)

_FLUFF_LINE_RE = re.compile(
    r"""(?ix)^
        (?:
            (?:please\s+)?(?:like|subscribe|share|follow|comment)(?:\s+and\s+(?:like|subscribe|share|follow|comment))*\b.*
            | (?:don't|do\s+not)\s+forget\s+to\s+(?:like|subscribe|share|follow|comment|hit|smash).*
            | (?:smash|hit)\s+(?:that\s+)?(?:like|subscribe|bell).*
            | (?:click|hit|ring)\s+(?:the\s+)?bell.*
            | (?:link|links)\s+in\s+(?:the\s+)?(?:description|bio|comments?).*
            | follow\s+(?:us|me)\s+on\s+(?:facebook|instagram|youtube|twitter|tiktok|x)\b.*
            | thanks\s+for\s+watching.*
            | see\s+you\s+(?:guys\s+)?(?:next\s+(?:time|week)|later).*
            | welcome\s+back\s+to\s+(?:the\s+)?(?:channel|stream|podcast|show).*
            | leave\s+a\s+(?:like|comment).*
            | check\s+out\s+(?:my|our)\s+(?:merch|patreon|store|sponsor).*
            | use\s+(?:promo\s+)?code\b.*
            | (?:this\s+(?:video|episode)\s+is\s+)?sponsored\s+by\b.*
            | this\s+episode\s+is\s+brought\s+to\s+you.*
            | before\s+we\s+(?:get\s+started|begin).{0,80}(?:subscribe|like|follow).*
            | make\s+sure\s+(?:you\s+)?(?:hit|smash|click|subscribe).*
            | intro\s+music\.?
            | \[?(?:music|applause|laughter)\]?
        )
    $"""
)
_FLUFF_PHRASE_RE = re.compile(
    r"""(?ix)
        (?:please\s+)?(?:like(?:\s+and\s+subscribe)?|subscribe(?:\s+and\s+like)?)
        | smash\s+that\s+like
        | hit\s+(?:that\s+)?(?:like\s+button|bell)
        | don't\s+forget\s+to\s+subscribe
        | link\s+in\s+(?:the\s+)?(?:description|bio)
        | thanks\s+for\s+watching
        | welcome\s+back\s+to\s+(?:the\s+)?channel
    """
)

_TOPIC_KEYWORDS = {
    # Christianity / Scripture / church
    "jesus",
    "christ",
    "god",
    "lord",
    "father",
    "holy",
    "spirit",
    "ghost",
    "bible",
    "scripture",
    "scriptures",
    "gospel",
    "church",
    "pastor",
    "prayer",
    "pray",
    "praying",
    "faith",
    "salvation",
    "saved",
    "savior",
    "saviour",
    "grace",
    "sin",
    "sinner",
    "repent",
    "repentance",
    "resurrection",
    "cross",
    "calvary",
    "baptism",
    "baptize",
    "baptized",
    "worship",
    "sermon",
    "disciple",
    "discipleship",
    "ministry",
    "minister",
    "kingdom",
    "heaven",
    "hell",
    "amen",
    "hallelujah",
    "verse",
    "chapter",
    "nkjv",
    "kjv",
    "covenant",
    "commandment",
    "tithe",
    "offering",
    "altar",
    "anoint",
    "anointed",
    "anointing",
    "prophecy",
    "prophet",
    "apostle",
    "pentecost",
    "communion",
    "easter",
    "christmas",
    "advent",
    "sabbath",
    "messiah",
    "yahweh",
    "jehovah",
    "trinity",
    "incarnation",
    "atonement",
    "justification",
    "sanctification",
    "holiness",
    "righteousness",
    "mercy",
    "forgiveness",
    "forgive",
    "theology",
    "theological",
    "biblical",
    "christian",
    "christianity",
    "spiritual",
    "soul",
    "devil",
    "satan",
    "demon",
    "demonic",
    "angel",
    "glory",
    "praise",
    "hymn",
    "congregation",
    "fellowship",
    "evangelism",
    "evangelist",
    "missionary",
    "testimony",
    "revival",
    "pentecostal",
    "evangelical",
    "miracle",
    "healing",
    "deliverance",
    "fasting",
    "parable",
    "beatitude",
    "redemption",
    "redeemed",
    "born",
    "again",
    "gospel",
    "nordin",
    "nordins",
    "pulpit",
    "scripture",
    # Bible books / people (high-signal)
    "genesis",
    "exodus",
    "leviticus",
    "numbers",
    "deuteronomy",
    "joshua",
    "judges",
    "ruth",
    "samuel",
    "kings",
    "chronicles",
    "ezra",
    "nehemiah",
    "esther",
    "job",
    "psalm",
    "psalms",
    "proverb",
    "proverbs",
    "ecclesiastes",
    "isaiah",
    "jeremiah",
    "lamentations",
    "ezekiel",
    "daniel",
    "hosea",
    "joel",
    "amos",
    "obadiah",
    "jonah",
    "micah",
    "nahum",
    "habakkuk",
    "zephaniah",
    "haggai",
    "zechariah",
    "malachi",
    "matthew",
    "mark",
    "luke",
    "john",
    "acts",
    "romans",
    "corinthians",
    "galatians",
    "ephesians",
    "philippians",
    "colossians",
    "thessalonians",
    "timothy",
    "titus",
    "philemon",
    "hebrews",
    "james",
    "peter",
    "jude",
    "revelation",
    "moses",
    "abraham",
    "isaac",
    "jacob",
    "david",
    "solomon",
    "elijah",
    "elisha",
    "isaiah",
    "paul",
    "peter",
    "mary",
    "joseph",
    "israel",
    "jerusalem",
    "bethlehem",
    "galilee",
    "calvary",
    # Social ideas / pastoral life issues
    "family",
    "marriage",
    "marry",
    "married",
    "divorce",
    "abortion",
    "culture",
    "cultural",
    "justice",
    "poverty",
    "community",
    "identity",
    "gender",
    "sexuality",
    "race",
    "racial",
    "racism",
    "politics",
    "political",
    "government",
    "addiction",
    "addict",
    "grief",
    "grieving",
    "parenting",
    "parent",
    "parents",
    "children",
    "child",
    "school",
    "education",
    "vocation",
    "calling",
    "depression",
    "anxiety",
    "suicide",
    "loneliness",
    "lonely",
    "hope",
    "purpose",
    "meaning",
    "morality",
    "moral",
    "ethics",
    "ethical",
    "values",
    "virtue",
    "freedom",
    "liberty",
    "truth",
    "honesty",
    "integrity",
    "stewardship",
    "generosity",
    "greed",
    "money",
    "wealth",
    "immigration",
    "refugee",
    "peace",
    "violence",
    "crime",
    "prison",
    "homeless",
    "homelessness",
    "alcohol",
    "drunkenness",
    "pornography",
    "lust",
    "adultery",
    "fornication",
    "homosexuality",
    "transgender",
    "masculinity",
    "manhood",
    "womanhood",
    "fatherhood",
    "motherhood",
    "euthanasia",
    "reconciliation",
    "unity",
    "neighbor",
    "neighbours",
    "neighbors",
    "widow",
    "orphan",
    "oppression",
    "oppressed",
    "trafficking",
    "abuse",
    "wisdom",
    "love",
    "compassion",
    "character",
    "temptation",
    "obedience",
    "disciples",
    "church",
    "congregation",
}

_WORD_RE = re.compile(r"[a-zA-Z']+")
_NEIGHBOR_WINDOW = 1


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_timestamp_range(start: float, end: float) -> str:
    return f"{format_timestamp(start)}–{format_timestamp(end)}"


def format_segment_line(segment: TranscriptSegment) -> str:
    stamp = format_timestamp_range(segment.start, segment.end)
    text = (segment.text or "").strip()
    if not text:
        return f"[{stamp}]"
    return f"[{stamp}] {text}"


def _strip_fillers(text: str, stats: Optional[NormalizeStats] = None) -> str:
    original = text or ""
    cleaned = _FILLER_TOKEN_RE.sub(" ", original)
    cleaned = _REPEATED_SO_RE.sub("", cleaned)
    cleaned = _LEADING_FILLER_RE.sub("", cleaned.strip())
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    cleaned = cleaned.strip(" ,;-")
    if stats is not None and cleaned != original.strip():
        stats.fillers_stripped += 1
    return cleaned.strip()


def _is_fluff_line(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _FLUFF_LINE_RE.match(stripped):
        return True
    remainder = _FLUFF_PHRASE_RE.sub(" ", stripped)
    remainder = re.sub(r"[ \t]+", " ", remainder).strip(" .,;:-")
    # Drop the line when fluff phrases leave almost no teaching content.
    return bool(_FLUFF_PHRASE_RE.search(stripped)) and len(remainder.split()) < 4


def _strip_fluff_phrases(text: str) -> str:
    cleaned = _FLUFF_PHRASE_RE.sub(" ", text or "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip(" .,;:-")


def _is_on_topic(text: str) -> bool:
    words = {token.lower() for token in _WORD_RE.findall(text or "")}
    if not words:
        return False
    return any(word in _TOPIC_KEYWORDS for word in words)


def normalize_transcript_segments(
    segments: Sequence[TranscriptSegment],
    *,
    keep_neighbor_window: int = _NEIGHBOR_WINDOW,
) -> NormalizeResult:
    """
    Clean filler/fluff and drop isolated segments that are unrelated to
    Christianity, Scripture, or social/pastoral ideas.
    """
    stats = NormalizeStats(segments_in=len(segments))
    cleaned: List[TranscriptSegment] = []
    flags: List[str] = []

    for segment in segments:
        text = _strip_fillers(segment.text or "", stats)
        if not text:
            stats.empty_segments_removed += 1
            continue
        if _is_fluff_line(text):
            stats.fluff_segments_removed += 1
            continue
        text = _strip_fluff_phrases(text)
        if not text:
            stats.fluff_segments_removed += 1
            continue
        cleaned.append(TranscriptSegment(start=segment.start, end=segment.end, text=text))
        flags.append("on" if _is_on_topic(text) else "off")

    if not cleaned:
        return NormalizeResult(segments=[], stats=stats)

    keep = [flag == "on" for flag in flags]
    if any(keep):
        for idx, on_topic in enumerate(list(keep)):
            if not on_topic:
                continue
            start = max(0, idx - keep_neighbor_window)
            end = min(len(keep), idx + keep_neighbor_window + 1)
            for neighbor in range(start, end):
                keep[neighbor] = True
    else:
        # Nothing matched the lexicon; keep cleaned speech rather than wiping a
        # whole sermon that used unexpected vocabulary.
        keep = [True] * len(cleaned)

    kept: List[TranscriptSegment] = []
    for segment, should_keep in zip(cleaned, keep):
        if should_keep:
            kept.append(segment)
        else:
            stats.off_topic_segments_removed += 1

    return NormalizeResult(segments=kept, stats=stats)


def segments_from_whisper(raw_segments: Iterable[dict]) -> List[TranscriptSegment]:
    out: List[TranscriptSegment] = []
    for item in raw_segments or []:
        text = str(item.get("text") or "").strip()
        try:
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or start)
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        out.append(TranscriptSegment(start=start, end=end, text=text))
    return out


def format_cleanup_log(stats: NormalizeStats, *, source_label: str = "") -> str:
    parts = [
        f"in={stats.segments_in}",
        f"fillers={stats.fillers_stripped}",
        f"fluff={stats.fluff_segments_removed}",
        f"off_topic={stats.off_topic_segments_removed}",
        f"empty={stats.empty_segments_removed}",
    ]
    prefix = f"Transcript normalize ({source_label}): " if source_label else "Transcript normalize: "
    return prefix + ", ".join(parts)
