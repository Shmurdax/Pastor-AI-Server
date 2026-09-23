"""Serve the shared GPU BGE embedder and sermon reranker."""

from __future__ import annotations

import logging
import os

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Load bge-base and bge-reranker once on CUDA and serve embed/rerank "
        "for the chat workers. Gunicorn stays off the GPU."
    )

    def add_arguments(self, parser):
        parser.add_argument("--host", default=os.environ.get("SEARCH_SIDECAR_HOST", "127.0.0.1"))
        parser.add_argument(
            "--port",
            type=int,
            default=int(os.environ.get("SEARCH_SIDECAR_PORT", "8012")),
        )

    def handle(self, *args, **options):
        from core.search_sidecar import load_models, serve

        host = str(options["host"])
        port = int(options["port"])
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        encode, predict = load_models()
        self.stdout.write(f"Sermon search sidecar on http://{host}:{port}")
        serve(host, port, encode, predict)
