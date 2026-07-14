import logging
from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import IngestedDocument

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=IngestedDocument)
def remove_admin_ingestion_upload(sender, instance, **kwargs):
    """Uploaded copies live under uploads/admin_ingestion; DB/Qdrant cleanup did not remove them."""
    filename = Path(instance.source_name).name
    path = Path(settings.BASE_DIR) / "uploads" / "admin_ingestion" / filename
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove ingestion upload file %s: %s", path, exc)
