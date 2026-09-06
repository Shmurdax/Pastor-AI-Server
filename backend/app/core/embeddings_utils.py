"""
Shared embedding helpers.

vLLM owns most GPU VRAM on a combined GPU host (including 24GB MIG slices).
On a CPU web pod, vLLM is remote (RunPod Serverless) and there is no local GPU.
Sentence-Transformers embeddings stay on CPU for chat retrieval and Django
admin ingestion so they cannot CUDA-OOM against the chat model. Whisper
transcription runs in a separate worker that may use leftover CUDA.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-base-en-v1.5")

_EMBEDDINGS = None


def _resolve_device() -> str:
    # Prefer explicit env; otherwise always CPU. Never auto-select CUDA while
    # vLLM is occupying the only GPU.
    raw = (os.getenv("EMBEDDING_DEVICE") or "cpu").strip().lower()
    if raw in {"", "auto"}:
        return "cpu"
    return raw


def get_embeddings(*, force_new: bool = False):
    """
    Return a process-wide embedding client pinned to CPU by default.
    """
    global _EMBEDDINGS
    if _EMBEDDINGS is not None and not force_new:
        return _EMBEDDINGS

    # Ensure GPU is invisible before sentence-transformers/torch initialize.
    if _resolve_device() == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    from langchain_huggingface import HuggingFaceEmbeddings

    device = _resolve_device()
    logger.info("Loading embeddings model %s on device=%s", DEFAULT_EMBEDDING_MODEL, device)
    emb = HuggingFaceEmbeddings(
        model_name=DEFAULT_EMBEDDING_MODEL,
        model_kwargs={"device": device},
        encode_kwargs={
            # BGE + Qdrant cosine similarity expect unit-length vectors.
            "normalize_embeddings": True,
            "batch_size": int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
        },
    )

    # Belt-and-suspenders: force tensors onto CPU when requested.
    if device == "cpu":
        client = getattr(emb, "client", None) or getattr(emb, "_client", None)
        if client is not None:
            try:
                client.to("cpu")
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not force embedding client to CPU: %s", exc)

    _EMBEDDINGS = emb
    return _EMBEDDINGS
