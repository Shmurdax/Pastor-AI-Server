"""Two-step supporting Scripture for chat REFERENCE NOTES.

Lane 1 looks up NKJV wording for verses named in the retrieved sermon windows.
Lane 2 runs only when those windows name no verses and coverage is full: embed
the question against ingested ``bible_verse`` chunks and rerank. Greetings and
empty/off-topic coverage stay silent. Document-level ``scripture_refs`` lists
are ignored so a 400-ref index cannot flood the prompt.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Optional

from .bible_refs import format_verse_ref, parse_verse_refs
from .chat_retrieval import chunk_text, is_bible_source, metadata_source_hint
from .chat_system_prompt import looks_like_brief_social
from .notes_coverage import COVERAGE_FULL, COVERAGE_NONE

logger = logging.getLogger(__name__)

SCRIPTURE_REF_LIMIT = 8
SCRIPTURE_KEEP = 3
SCRIPTURE_SERMON_KEEP = 4
SCRIPTURE_CANDIDATES = 16
SCRIPTURE_MIN_SCORE = 0.2
LANE_SERMON = "sermon"
LANE_NKJV_FALLBACK = "nkjv_fallback"


def _metadata(doc: Any) -> dict:
    return dict(getattr(doc, "metadata", None) or {})


def is_bible_chunk(doc: Any) -> bool:
    """True for ingested NKJV / bible_verse windows, not sermon notes."""
    meta = _metadata(doc)
    kind = str(meta.get("chunk_kind") or "").lower()
    if kind.startswith("bible"):
        return True
    hint = metadata_source_hint(doc) or str(meta.get("source") or "")
    return is_bible_source(hint)


def sermon_window_verse_refs(
    docs: Iterable[Any],
    *,
    limit: int = SCRIPTURE_REF_LIMIT,
) -> list[tuple[str, int, int]]:
    """Parse verse refs from sermon chunk text and per-chunk ``verse_ref`` only."""
    blobs: list[str] = []
    for doc in docs or []:
        if is_bible_chunk(doc):
            continue
        blobs.append(chunk_text(doc))
        verse_ref = str(_metadata(doc).get("verse_ref") or "").strip()
        if verse_ref:
            blobs.append(verse_ref)
    cap = max(1, int(limit))
    return parse_verse_refs(" ".join(blobs))[:cap]


def format_nkjv_scripture_block(docs: Iterable[Any]) -> str:
    """Labeled NKJV block inserted after the notes attribution preface."""
    lines: list[str] = []
    seen: set[str] = set()
    for doc in docs or []:
        meta = _metadata(doc)
        quote = str(meta.get("quote_text") or "").strip() or chunk_text(doc)
        if not quote:
            continue
        ref = str(meta.get("verse_ref") or "").strip()
        if not ref:
            book = meta.get("book")
            chapter = meta.get("chapter")
            start = meta.get("verse_start")
            end = meta.get("verse_end") or start
            if book and chapter and start:
                try:
                    ref = format_verse_ref(book, int(chapter), int(start), verse_end=int(end))
                except (TypeError, ValueError):
                    ref = ""
        key = (ref or quote).strip().lower()[:240]
        if not key or key in seen:
            continue
        seen.add(key)
        if ref:
            lines.append(f"{ref} (NKJV): {quote}")
        else:
            lines.append(f"(NKJV): {quote}")
    if not lines:
        return ""
    return "[NKJV SCRIPTURE]\n" + "\n".join(lines)


def _payload_of(point: Any) -> dict:
    payload = getattr(point, "payload", None)
    if isinstance(payload, dict):
        return payload
    if isinstance(point, dict):
        inner = point.get("payload")
        if isinstance(inner, dict):
            return inner
        return point
    return {}


def _point_score(point: Any) -> float:
    raw = getattr(point, "score", None)
    if raw is None and isinstance(point, dict):
        raw = point.get("score")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _point_to_doc(
    point: Any,
    *,
    make_doc: Optional[Callable[[str, dict], Any]] = None,
) -> Optional[Any]:
    from types import SimpleNamespace

    factory = make_doc or (
        lambda text, metadata: SimpleNamespace(page_content=text, metadata=metadata)
    )
    payload = _payload_of(point)
    text = str(payload.get("text") or "").strip()
    if not text:
        return None
    metadata = dict(payload.get("metadata") or {})
    metadata.update({key: value for key, value in payload.items() if key != "metadata"})
    return factory(text, metadata)


def _bible_verse_filter():
    from qdrant_client.http import models as qdrant_models

    return qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(
                key="chunk_kind",
                match=qdrant_models.MatchValue(value="bible_verse"),
            )
        ]
    )


def _search_bible_points(client: Any, collection_name: str, vector: list[float], limit: int) -> list[Any]:
    bible_filter = _bible_verse_filter()
    cap = max(1, int(limit))
    try:
        result = client.query_points(
            collection_name=collection_name,
            query=vector,
            query_filter=bible_filter,
            limit=cap,
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(result, "points", None)
        if points is None:
            points = result
        return list(points or [])
    except (TypeError, AttributeError):
        pass
    except Exception:
        logger.debug("NKJV query_points failed", exc_info=True)
    try:
        return list(
            client.search(
                collection_name=collection_name,
                query_vector=vector,
                query_filter=bible_filter,
                limit=cap,
                with_payload=True,
                with_vectors=False,
            )
            or []
        )
    except Exception:
        logger.debug("NKJV vector search failed", exc_info=True)
        return []


def search_supporting_nkjv_verses(
    query: str,
    client: Any,
    collection_name: str,
    embeddings: Any,
    *,
    candidates: int = SCRIPTURE_CANDIDATES,
    keep: int = SCRIPTURE_KEEP,
    min_score: float = SCRIPTURE_MIN_SCORE,
    rerank_hits: Optional[Callable[..., list[tuple[Any, float]]]] = None,
    make_doc: Optional[Callable[[str, dict], Any]] = None,
) -> list[Any]:
    """Embed the question against bible_verse chunks; keep a short high-scoring set."""
    topic = (query or "").strip()
    if not topic or client is None or embeddings is None or not collection_name:
        return []
    try:
        vector = list(embeddings.embed_query(topic) or [])
    except Exception:
        logger.debug("NKJV embed_query failed", exc_info=True)
        return []
    if not vector:
        return []
    points = _search_bible_points(client, collection_name, vector, candidates)
    hits: list[tuple[Any, float]] = []
    for point in points:
        doc = _point_to_doc(point, make_doc=make_doc)
        if doc is None or not is_bible_chunk(doc):
            continue
        hits.append((doc, _point_score(point)))
    if not hits:
        return []
    ranker = rerank_hits
    if ranker is None:
        from .rerank import rerank_scored_hits

        ranker = rerank_scored_hits
    try:
        ranked = list(ranker(topic, hits) or hits)
    except Exception:
        logger.debug("NKJV rerank failed; keeping ANN order", exc_info=True)
        ranked = hits
    kept: list[Any] = []
    floor = float(min_score)
    cap = max(1, int(keep))
    for doc, raw_score in ranked:
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        if score < floor:
            continue
        kept.append(doc)
        if len(kept) >= cap:
            break
    return kept


def attach_supporting_scripture(
    query: str,
    sermon_docs: Iterable[Any],
    coverage: str,
    client: Any = None,
    collection_name: str = "",
    embeddings: Any = None,
    *,
    lookup: Optional[Callable[..., list[Any]]] = None,
    search_nkjv: Optional[Callable[..., list[Any]]] = None,
) -> tuple[list[Any], str]:
    """Return ``(nkjv_docs, lane)`` without mixing Scripture into sermon chips.

    Lane is ``sermon``, ``nkjv_fallback``, or empty when nothing should be attached.
    """
    docs = [doc for doc in (sermon_docs or []) if doc is not None]
    if coverage == COVERAGE_NONE or not docs:
        return [], ""
    if looks_like_brief_social(query):
        return [], ""

    refs = sermon_window_verse_refs(docs)
    if refs:
        finder = lookup
        if finder is None:
            from .grounding import lookup_nkjv_verses

            finder = lookup_nkjv_verses
        try:
            found = list(
                finder(
                    client,
                    collection_name,
                    refs,
                    retrieved_docs=None,
                    limit_per_ref=1,
                )
                or []
            )
        except Exception:
            logger.debug("Sermon-named NKJV lookup failed", exc_info=True)
            found = []
        found = [doc for doc in found if is_bible_chunk(doc)][:SCRIPTURE_SERMON_KEEP]
        if found:
            logger.warning(
                "Scripture lane=%s refs=%s docs=%s query=%s",
                LANE_SERMON,
                len(refs),
                len(found),
                (query or "")[:80],
            )
            return found, LANE_SERMON
        return [], ""

    if coverage != COVERAGE_FULL:
        return [], ""

    searcher = search_nkjv or search_supporting_nkjv_verses
    try:
        found = list(
            searcher(
                query,
                client,
                collection_name,
                embeddings,
            )
            or []
        )
    except Exception:
        logger.debug("NKJV embedding fallback failed", exc_info=True)
        return [], ""
    found = [doc for doc in found if is_bible_chunk(doc)][:SCRIPTURE_KEEP]
    if not found:
        return [], ""
    logger.warning(
        "Scripture lane=%s docs=%s query=%s",
        LANE_NKJV_FALLBACK,
        len(found),
        (query or "")[:80],
    )
    return found, LANE_NKJV_FALLBACK
