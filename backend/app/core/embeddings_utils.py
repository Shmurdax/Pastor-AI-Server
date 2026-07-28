"""Shared embedding helpers for chat retrieval and ingestion.

MiniLM stays on CPU so it never fights vLLM for the single RunPod GPU
(and so ghost-GPU / CUDA-busy failures cannot take down /api/chat/).
"""
from __future__ import annotations

import os
from typing import Optional

from langchain_huggingface import HuggingFaceEmbeddings

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def get_embeddings(model_name: Optional[str] = None) -> HuggingFaceEmbeddings:
    name = model_name or os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    device = os.getenv("EMBEDDING_DEVICE", "cpu").strip() or "cpu"
    return HuggingFaceEmbeddings(
        model_name=name,
        model_kwargs={"device": device},
    )
