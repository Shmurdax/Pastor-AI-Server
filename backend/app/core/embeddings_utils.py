"""
Shared embedding helpers.

vLLM owns nearly all GPU VRAM on the RunPod host. Sentence-Transformers /
MiniLM must stay on CPU for both chat retrieval and admin ingestion, or
embedding calls raise CUDA OOM and ingestion jobs fail mid-batch.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")


def _resolve_device() -> str:
    # Prefer explicit env; otherwise always CPU. Never auto-select CUDA while
    # vLLM is occupying the only GPU.
    raw = (os.getenv("EMBEDDING_DEVICE") or "cpu").strip().lower()
    if raw in {"", "auto"}:
        return "cpu"
    return raw


def get_embeddings(*, force_new: bool = False):
    """
    Return a process-wide MiniLM embedding client pinned to CPU by default.
    """
    global _EMBEDDINGS
    if _EMBEDDINGS is not None and not force_new:
        return _EMBEDDINGS

    # Import after env is settled so callers can blank CUDA_VISIBLE_DEVICES first.
    from langchain_huggingface import HuggingFaceEmbeddings

    device = _resolve_device()
    logger.info("Loading embeddings model %s on device=%s", DEFAULT_EMBEDDING_MODEL, device)
    emb = HuggingFaceEmbeddings(
        model_name=DEFAULT_EMBEDDING_MODEL,
        model_kwargs={"device": device},
        encode_kwargs={
            "normalize_embeddings": False,
            "batch_size": int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
        },
    )

    # Belt-and-suspenders: some sentence-transformers builds still land on CUDA
    # when it is visible; force tensors onto CPU when requested.
    if device == "cpu":
        client = getattr(emb, "client", None)
        if client is not None:
            try:
                client.to("cpu")
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not force embedding client to CPU: %s", exc)

    _EMBEDDINGS = emb
    return _EMBEDDINGS


_EMBEDDINGS = None
