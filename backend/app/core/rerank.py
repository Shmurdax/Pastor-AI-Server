"""CPU BGE cross-encoder rerank for retrieved sermon windows.

Runs after embedding search. Does not search Qdrant, does not rewrite the
generated answer, and does not touch embeddings.
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Any, Callable, Iterable, Optional

from .chat_retrieval import chunk_fingerprint, chunk_text

logger = logging.getLogger(__name__)

DEFAULT_RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "40"))
RERANK_MAX_CHARS = int(os.getenv("RERANK_MAX_CHARS", "1024"))

_RERANKER = None
_RERANKER_FAILED = False
_RERANKER_LOCK = threading.Lock()


def rerank_enabled(env: Optional[dict] = None) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get("RERANK_ENABLED", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _rerank_device() -> str:
    raw = (os.getenv("RERANK_DEVICE") or "cpu").strip().lower()
    if raw in {"", "auto"}:
        return "cpu"
    return raw


def _as_score_list(raw_scores) -> list[float]:
    """CrossEncoder.predict returns a numpy array; never use `or []` on it."""
    if raw_scores is None:
        return []
    if hasattr(raw_scores, "tolist"):
        try:
            raw_scores = raw_scores.tolist()
        except Exception:
            pass
    if isinstance(raw_scores, (float, int)):
        return [float(raw_scores)]
    return [float(value) for value in list(raw_scores)]


def _sigmoid(value: float) -> float:
    clipped = max(-30.0, min(30.0, float(value)))
    return 1.0 / (1.0 + math.exp(-clipped))


def _unique_hits(hits: Iterable[tuple[Any, float]]) -> list[tuple[Any, float]]:
    merged: dict[str, tuple[Any, float]] = {}
    order: list[str] = []
    for item in hits or []:
        if not isinstance(item, tuple) or len(item) < 2:
            continue
        doc, raw_score = item[0], item[1]
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            score = 0.0
        fp = chunk_fingerprint(chunk_text(doc))
        if not fp:
            continue
        previous = merged.get(fp)
        if previous is None:
            merged[fp] = (doc, score)
            order.append(fp)
            continue
        if score > previous[1]:
            merged[fp] = (doc, score)
    return [merged[fp] for fp in order]


def _fingerprint_set(docs: Optional[Iterable[Any]]) -> set[str]:
    found: set[str] = set()
    for doc in docs or []:
        fp = chunk_fingerprint(chunk_text(doc))
        if fp:
            found.add(fp)
    return found


def _select_candidates(
    hits: list[tuple[Any, float]],
    *,
    pinned_docs: Optional[Iterable[Any]],
    limit: int,
) -> list[tuple[Any, float]]:
    pinned_fps = _fingerprint_set(pinned_docs)
    forced: list[tuple[Any, float]] = []
    others: list[tuple[Any, float]] = []
    seen_forced: set[str] = set()
    for doc, score in hits:
        fp = chunk_fingerprint(chunk_text(doc))
        if fp in pinned_fps and fp not in seen_forced:
            forced.append((doc, score))
            seen_forced.add(fp)
        else:
            others.append((doc, score))
    others.sort(key=lambda item: item[1], reverse=True)
    cap = max(1, int(limit))
    if len(forced) >= cap:
        return forced
    return forced + others[: cap - len(forced)]


def get_reranker(*, force_new: bool = False):
    """Load the BGE cross-encoder once per process, CPU by default."""
    global _RERANKER, _RERANKER_FAILED
    if force_new:
        with _RERANKER_LOCK:
            _RERANKER = None
            _RERANKER_FAILED = False
    if _RERANKER is not None:
        return _RERANKER
    if _RERANKER_FAILED:
        return None
    with _RERANKER_LOCK:
        if _RERANKER is not None:
            return _RERANKER
        if _RERANKER_FAILED:
            return None
        device = _rerank_device()
        if device == "cpu":
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:  # pragma: no cover - optional local deps
            logger.warning("BGE reranker unavailable (sentence-transformers): %s", exc)
            _RERANKER_FAILED = True
            return None
        model_name = (os.getenv("RERANK_MODEL") or DEFAULT_RERANK_MODEL).strip()
        try:
            logger.info("Loading reranker %s on device=%s", model_name, device)
            _RERANKER = CrossEncoder(model_name, device=device)
        except Exception as exc:
            logger.warning("BGE reranker failed to load: %s", exc)
            _RERANKER_FAILED = True
            return None
        return _RERANKER


def rerank_scored_hits(
    query: str,
    hits: Iterable[tuple[Any, float]],
    *,
    pinned_docs: Optional[Iterable[Any]] = None,
    limit: int = RERANK_CANDIDATES,
    max_chars: int = RERANK_MAX_CHARS,
    predict: Optional[Callable[[list[list[str]]], Any]] = None,
    enabled: Optional[bool] = None,
) -> list[tuple[Any, float]]:
    """Reorder a shortlist of retrieved windows. Fail open to the original hits."""
    original = list(hits or [])
    if enabled is None:
        enabled = rerank_enabled()
    if not enabled:
        return original
    topic = (query or "").strip()
    if not topic or not original:
        return original

    unique = _unique_hits(original)
    chosen = _select_candidates(unique, pinned_docs=pinned_docs, limit=limit)
    if not chosen:
        return original

    pairs = []
    for doc, _score in chosen:
        passage = chunk_text(doc)[: max(64, int(max_chars))]
        pairs.append([topic, passage])

    scorer = predict
    if scorer is None:
        reranker = get_reranker()
        if reranker is None:
            return original
        scorer = reranker.predict

    try:
        raw_scores = _as_score_list(scorer(pairs))
    except Exception as exc:
        logger.warning("BGE reranker predict failed; keeping ANN scores: %s", exc)
        return original

    reranked: list[tuple[Any, float]] = []
    chosen_fps: set[str] = set()
    for index, (doc, _old) in enumerate(chosen):
        logit = raw_scores[index] if index < len(raw_scores) else 0.0
        try:
            value = float(logit)
        except (TypeError, ValueError):
            value = 0.0
        reranked.append((doc, _sigmoid(value)))
        fp = chunk_fingerprint(chunk_text(doc))
        if fp:
            chosen_fps.add(fp)
    reranked.sort(key=lambda item: item[1], reverse=True)
    logger.warning(
        "BGE reranked %s/%s windows query=%s",
        len(reranked),
        len(unique),
        topic[:80],
    )

    rest = [
        (doc, score)
        for doc, score in unique
        if chunk_fingerprint(chunk_text(doc)) not in chosen_fps
    ]
    return reranked + rest
