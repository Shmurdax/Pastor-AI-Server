import logging
from pathlib import Path

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import IngestedDocument
from .persist_db import dump_persistent_postgres
from .storage_paths import ingested_media_path

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=IngestedDocument)
def remove_admin_ingestion_upload(sender, instance, **kwargs):
    """Uploaded copies live under admin ingestion dirs; DB/Qdrant cleanup did not remove them."""
    filename = Path(instance.source_name).name
    path = ingested_media_path(filename, instance.source_kind)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove ingestion upload file %s: %s", path, exc)
    if instance.source_kind == "video":
        sidecar = path.with_suffix(".transcript.json")
        try:
            sidecar.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove transcript sidecar %s: %s", sidecar, exc)
    dump_persistent_postgres()
