"""
WSGI config for pastor_ai project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from pastor_ai.gpu_env import apply_hide_gpu

# Hide GPUs from gunicorn BEFORE torch/transformers import. vLLM keeps the GPU
# in its own process; chat MiniLM embeddings stay on CPU. Video ingest is a
# separate manage.py worker and does not use this WSGI path.
apply_hide_gpu(argv=["gunicorn"])
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pastor_ai.settings")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
