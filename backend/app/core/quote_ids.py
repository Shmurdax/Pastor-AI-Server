"""Per-request quote IDs so Don/Susan and NKJV lines are copied from retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

SLOT_RE = re.compile(r"\{\{\s*([QVqv])(\d+)\s*\}\}")
INCOMPLETE_SLOT_RE = re.compile(r"\{\{[^}]*$")
_ATTR_QUOTE_RE = re.compile(
    r"((?:Pastor\s+)?(?:Don|Susan)(?:\s+Nordin)?)\s+"
    r"(?:Nordin\s+)?"
    r"(?:teaches|taught|says|said|preaches|preached|reminds|told|tells)"
    r"[^\"“]{0,80}[\"“](.{12,400}?)[\"”]",
    re.IGNORECASE,
)
_MARKUP_RE = re.compile(r"[*_`>#]+")
_PUNCT_RE = re.compile(r"[^\w\s']+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    folded = (text or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    folded = _MARKUP_RE.sub(" ", folded)
    folded = _PUNCT_RE.sub(" ", folded.lower())
    return _SPACE_RE.sub(" ", folded).strip()


@dataclass(frozen=True)
class QuoteSlot:
    slot_id: str
    kind: str
    text: str
    ref: str = ""

    def render(self) -> str:
        wording = (self.text or "").strip()
        if self.kind == "nkjv":
            ref = (self.ref or "NKJV").strip()
            return f'{ref} (NKJV): "{wording}"'
        return f'"{wording}"'

    def to_json(self) -> dict[str, str]:
        payload = {"id": self.slot_id, "kind": self.kind, "text": self.text}
        if self.ref:
            payload["ref"] = self.ref
        return payload


def build_quote_catalog(
    quotes: Iterable[str] | None = None,
    nkjv_pairs: Iterable[tuple[str, str]] | None = None,
) -> dict[str, QuoteSlot]:
    catalog: dict[str, QuoteSlot] = {}
    for index, quote in enumerate(quotes or [], start=1):
        wording = " ".join((quote or "").split()).strip()
        if len(wording) < 12:
            continue
        slot_id = f"Q{index}"
        catalog[slot_id] = QuoteSlot(slot_id, "sermon", wording)
    for index, pair in enumerate(nkjv_pairs or [], start=1):
        ref, wording = pair
        wording = " ".join((wording or "").split()).strip()
        if len(wording) < 8:
            continue
        slot_id = f"V{index}"
        catalog[slot_id] = QuoteSlot(slot_id, "nkjv", wording, ref=str(ref or "NKJV").strip())
    return catalog


def catalog_to_json(catalog: dict[str, QuoteSlot]) -> dict[str, dict[str, str]]:
    return {slot_id: slot.to_json() for slot_id, slot in catalog.items()}


def format_quote_id_block(catalog: dict[str, QuoteSlot]) -> str:
    lines = ["<quote_ids>"]
    lines.append(
        "Write an original sermon in your own words, heavily shaped by REFERENCE NOTES. "
        "When you want Pastor Don or Susan to speak, insert a sermon ID token such as {{Q1}} — "
        "never retype those words. When you want Scripture, insert a verse ID such as {{V1}}. "
        "The server copies the exact retrieved wording. Do not invent a quotation or verse."
    )
    sermon = [slot for slot in catalog.values() if slot.kind == "sermon"]
    nkjv = [slot for slot in catalog.values() if slot.kind == "nkjv"]
    lines.append("SERMON QUOTE IDS (Pastor Don / Susan — insert the token, do not copy the words):")
    if sermon:
        for slot in sermon:
            clipped = slot.text if len(slot.text) <= 400 else slot.text[:397] + "..."
            lines.append(f"{slot.slot_id}: {clipped}")
    else:
        lines.append("(none retrieved — do not invent a Pastor Don or Susan quotation)")
    lines.append("NKJV VERSE IDS (insert the token, do not copy the words):")
    if nkjv:
        for slot in nkjv:
            clipped = slot.text if len(slot.text) <= 400 else slot.text[:397] + "..."
            lines.append(f"{slot.slot_id} {slot.ref}: {clipped}")
    else:
        lines.append("(none retrieved — do not quote Scripture)")
    lines.append(
        "If no ID fits this question, teach from the notes without quotation marks attributed "
        "to Pastor Don, Susan, or a Bible verse. Do not write {{Q}} tokens that are not listed."
    )
    lines.append("</quote_ids>")
    return "\n".join(lines) + "\n"


def expand_quote_ids(text: str, catalog: dict[str, QuoteSlot]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).upper() + match.group(2)
        slot = catalog.get(key)
        if slot is None:
            return ""
        return slot.render()

    return SLOT_RE.sub(repl, text or "")


def drop_unknown_slots(text: str) -> str:
    return SLOT_RE.sub("", text or "")


def drop_ungrounded_attributed_quotes(text: str, catalog: dict[str, QuoteSlot]) -> str:
    """Remove Don/Susan quotations that the model typed instead of using an ID."""
    allowed = {_norm(slot.text) for slot in catalog.values() if slot.kind == "sermon"}

    def repl(match: re.Match[str]) -> str:
        quoted = match.group(2)
        if _norm(quoted) in allowed:
            return match.group(0)
        return match.group(1)

    return _ATTR_QUOTE_RE.sub(repl, text or "")


def finalize_quote_ids(text: str, catalog: dict[str, QuoteSlot]) -> str:
    expanded = expand_quote_ids(text, catalog)
    expanded = INCOMPLETE_SLOT_RE.sub("", expanded)
    return drop_ungrounded_attributed_quotes(expanded, catalog)


def flushable_expanded(raw: str, catalog: dict[str, QuoteSlot]) -> tuple[str, str]:
    """Expand complete IDs; hold a trailing incomplete `{{...` so placeholders never paint."""
    text = raw or ""
    incomplete = INCOMPLETE_SLOT_RE.search(text)
    if incomplete:
        head = text[: incomplete.start()]
        return expand_quote_ids(head, catalog), text[incomplete.start() :]
    return expand_quote_ids(text, catalog), ""


@dataclass
class QuoteIdStreamer:
    catalog: dict[str, QuoteSlot]
    raw: str = ""
    visible: str = ""

    def ingest(self, token: str) -> list[dict[str, Any]]:
        if not token:
            return []
        self.raw += token
        expanded, _held = flushable_expanded(self.raw, self.catalog)
        return self._events_for(expanded)

    def finish(self) -> tuple[str, list[dict[str, Any]]]:
        final = finalize_quote_ids(self.raw, self.catalog)
        events = self._events_for(final)
        self.visible = final
        return final, events

    def _events_for(self, expanded: str) -> list[dict[str, Any]]:
        if expanded == self.visible:
            return []
        if expanded.startswith(self.visible):
            delta = expanded[len(self.visible) :]
            self.visible = expanded
            if not delta:
                return []
            return [{"type": "delta", "text": delta}]
        self.visible = expanded
        return [{"type": "replace", "text": expanded}]
