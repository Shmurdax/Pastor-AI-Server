"""
Qdrant helpers: after wiping ``qdrant_storage`` the server starts with no collections.
``ensure_sermon_collection`` recreates ``sermon_brain`` with the embedding size used in ingestion/chat.
"""
import logging
import os
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models

logger = logging.getLogger(__name__)

# HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
DEFAULT_VECTOR_SIZE = 384


def get_qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://qdrant:6333")


def get_collection_name() -> str:
    return os.getenv("QDRANT_COLLECTION", "sermon_brain")


def get_vector_size() -> int:
    return int(os.getenv("QDRANT_VECTOR_SIZE", str(DEFAULT_VECTOR_SIZE)))


def collection_exists(client: QdrantClient, collection_name: Optional[str] = None) -> bool:
    name = collection_name or get_collection_name()
    collections = client.get_collections().collections
    return any(c.name == name for c in collections)


def ensure_sermon_collection(client: QdrantClient, collection_name: Optional[str] = None) -> None:
    """Create the vector collection if it was removed (e.g. empty ``qdrant_storage`` volume)."""
    name = collection_name or get_collection_name()
    if collection_exists(client, name):
        return
    size = get_vector_size()
    logger.warning(
        "Qdrant collection %r missing; creating empty collection (vector dim=%s, cosine).",
        name,
        size,
    )
    try:
        client.create_collection(
            collection_name=name,
            vectors_config=qdrant_models.VectorParams(
                size=size,
                distance=qdrant_models.Distance.COSINE,
            ),
        )
    except Exception as exc:
        if collection_exists(client, name):
            return
        logger.error("Failed to create Qdrant collection %r: %s", name, exc)
        raise
