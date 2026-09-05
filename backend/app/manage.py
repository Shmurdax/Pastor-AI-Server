#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    from pastor_ai.gpu_env import apply_hide_gpu
    from pastor_ai.workspace_env import load_workspace_env

    load_workspace_env()
    # Gunicorn/migrate stay off the GPU. Video ingest worker keeps CUDA for Whisper.
    apply_hide_gpu(argv=sys.argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pastor_ai.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
