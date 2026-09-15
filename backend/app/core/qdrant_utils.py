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

# HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")
DEFAULT_VECTOR_SIZE = 768


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
        ensure_payload_indexes(client, name)
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
    ensure_payload_indexes(client, name)


def ensure_payload_indexes(client: QdrantClient, collection_name: Optional[str] = None) -> None:
    """Keyword/integer indexes so NKJV verse lookup can filter without a full scan."""
    name = collection_name or get_collection_name()
    specs = (
        ("chunk_kind", qdrant_models.PayloadSchemaType.KEYWORD),
        ("book", qdrant_models.PayloadSchemaType.KEYWORD),
        ("file_hash", qdrant_models.PayloadSchemaType.KEYWORD),
        ("source", qdrant_models.PayloadSchemaType.KEYWORD),
        ("chapter", qdrant_models.PayloadSchemaType.INTEGER),
        ("verse_start", qdrant_models.PayloadSchemaType.INTEGER),
        ("verse_end", qdrant_models.PayloadSchemaType.INTEGER),
    )
    for field_name, schema in specs:
        try:
            client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=schema,
                wait=False,
            )
        except Exception:
            logger.debug("Payload index %s on %s already present or skipped", field_name, name)


def delete_sermon_collection(client: QdrantClient, collection_name: Optional[str] = None) -> bool:
    """Delete the sermon collection if it exists. Returns True when a delete was issued."""
    name = collection_name or get_collection_name()
    if not collection_exists(client, name):
        logger.info("Qdrant collection %r already absent.", name)
        return False
    client.delete_collection(collection_name=name)
    logger.warning("Deleted Qdrant collection %r.", name)
    return True


def reset_sermon_collection(client: QdrantClient, collection_name: Optional[str] = None) -> None:
    """Drop and recreate the sermon collection at the configured vector size."""
    name = collection_name or get_collection_name()
    delete_sermon_collection(client, name)
    ensure_sermon_collection(client, name)
