"""Deprecated Chroma indexer.

Sermon RAG now uses Qdrant. Prefer:

    python ingest_qdrant.py

or:

    bash ingest_sermons.sh
"""

from ingest_qdrant import run_ingestion


if __name__ == "__main__":
    print("sermon_indexer.py now delegates to ingest_qdrant.py (Qdrant).")
    run_ingestion()
