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

from langchain_huggingface import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")
# Always default to CPU so ingestion/chat never fight vLLM for CUDA memory.
DEFAULT_EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

_EMBEDDINGS: Optional[HuggingFaceEmbeddings] = None


def get_embeddings(*, force_new: bool = False) -> HuggingFaceEmbeddings:
    """
    Return a process-wide MiniLM embedding client pinned to ``EMBEDDING_DEVICE``
    (CPU by default).
    """
    global _EMBEDDINGS
    if _EMBEDDINGS is not None and not force_new:
        return _EMBEDDINGS

    device = (DEFAULT_EMBEDDING_DEVICE or "cpu").strip() or "cpu"
    logger.info("Loading embeddings model %s on device=%s", DEFAULT_EMBEDDING_MODEL, device)
    _EMBEDDINGS = HuggingFaceEmbeddings(
        model_name=DEFAULT_EMBEDDING_MODEL,
        model_kwargs={"device": device},
        encode_kwargs={
            "normalize_embeddings": False,
            # Keep encode batches modest to limit RAM spikes during large ingest jobs.
            "batch_size": int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
        },
    )
    return _EMBEDDINGS
