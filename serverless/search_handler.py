"""RunPod serverless worker for sermon embed and rerank.

The chat pod posts {"input": {"texts": [...]}} or {"input": {"pairs": [[query, passage], ...]}}
to /runsync. This process loads the same BGE models the CPU pod was scoring locally.
"""

from __future__ import annotations

import os

import runpod
import torch
from sentence_transformers import CrossEncoder, SentenceTransformer

EMBED_MODEL = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-base-en-v1.5")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
MAX_ITEMS = 64
MAX_CHARS = 8000


def _load(cls, name: str):
    try:
        return cls(name, device="cuda", model_kwargs={"torch_dtype": torch.float16})
    except TypeError:
        return cls(name, device="cuda")


print(f"Loading embedder {EMBED_MODEL}", flush=True)
EMBEDDER = _load(SentenceTransformer, EMBED_MODEL)
print(f"Loading reranker {RERANK_MODEL}", flush=True)
RERANKER = _load(CrossEncoder, RERANK_MODEL)
EMBEDDER.encode(["warmup"], normalize_embeddings=True, show_progress_bar=False)
RERANKER.predict([["warmup", "warmup passage"]], show_progress_bar=False)
print("Sermon search models ready", flush=True)


def handler(job):
    payload = job.get("input") or {}
    if not isinstance(payload, dict):
        return {"error": "input must be an object"}
    if "pairs" in payload:
        raw_pairs = payload.get("pairs") or []
        pairs = []
        for pair in raw_pairs[:MAX_ITEMS]:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            pairs.append([str(pair[0])[:MAX_CHARS], str(pair[1])[:MAX_CHARS]])
        if not pairs:
            return {"scores": []}
        raw = RERANKER.predict(pairs, batch_size=16, show_progress_bar=False)
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if isinstance(raw, (float, int)):
            raw = [raw]
        return {"scores": [float(score) for score in raw]}
    texts = [str(text)[:MAX_CHARS] for text in (payload.get("texts") or [])][:MAX_ITEMS]
    if not texts:
        return {"vectors": []}
    vectors = EMBEDDER.encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )
    return {"vectors": [[float(value) for value in row] for row in vectors]}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
