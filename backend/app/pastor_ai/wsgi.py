"""
WSGI config for pastor_ai project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

# Hide GPUs from this Django/gunicorn process BEFORE torch/transformers import.
# vLLM keeps the GPU in a separate process; ingestion embeddings must stay on CPU
# or they CUDA-OOM against the chat model.
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ.setdefault("EMBEDDING_DEVICE", "cpu")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pastor_ai.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
