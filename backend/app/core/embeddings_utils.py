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
# BGE retrieval is asymmetric: prefix queries only. Document vectors stay raw
# so existing Qdrant points do not need a reingest.
BGE_QUERY_INSTRUCTION = os.getenv(
    "EMBEDDING_QUERY_INSTRUCTION",
    "Represent this sentence for searching relevant passages: ",
)

_EMBEDDINGS = None

try:
    from langchain_core.embeddings import Embeddings as LangChainEmbeddings
except Exception:  # pragma: no cover - unit tests without langchain_core
    class LangChainEmbeddings:  # type: ignore[no-redef]
        """Stand-in so tests can construct the wrapper without LangChain."""


class QueryPrefixedEmbeddings(LangChainEmbeddings):
    """Prefix embed_query for BGE; leave embed_documents unchanged for ingest.

    QdrantVectorStore only accepts langchain ``Embeddings`` instances, so this
    wrapper subclasses that ABC instead of being an anonymous helper.
    """

    def __init__(self, inner, instruction: str = BGE_QUERY_INSTRUCTION):
        self._inner = inner
        raw = instruction or ""
        self._instruction = raw if raw.endswith(" ") or not raw else raw + " "

    def _prefixed(self, text: str) -> str:
        body = (text or "").strip()
        if not body or not self._instruction:
            return body
        needle = self._instruction.strip().lower()
        if needle and body.lower().startswith(needle):
            return body
        return f"{self._instruction}{body}"

    def embed_query(self, text: str):
        return self._inner.embed_query(self._prefixed(text))

    def embed_documents(self, texts):
        return self._inner.embed_documents(texts)

    def __getattr__(self, name):
        return getattr(self._inner, name)


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

    wrapped = QueryPrefixedEmbeddings(emb, BGE_QUERY_INSTRUCTION)
    _EMBEDDINGS = wrapped
    return _EMBEDDINGS
