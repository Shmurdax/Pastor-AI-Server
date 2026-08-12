"""Best-effort dump of the app database onto the RunPod persistent volume.

Live Postgres cannot use the network volume as PGDATA (chown to postgres fails).
start.sh / install.sh restore this dump after a container recreate so the
ingested-document catalog and sermon-library links survive remigration.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DUMP = "/workspace/persistent/postgres/ai_db.dump"
_DB_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def dump_path() -> Path:
    raw = (os.environ.get("PERSIST_PG_DUMP") or "").strip()
    return Path(raw or DEFAULT_DUMP)


def dump_persistent_postgres() -> bool:
    db = (os.environ.get("POSTGRES_DB") or "ai_db").strip()
    if not _DB_NAME_RE.match(db):
        logger.warning("Postgres persist dump skipped: invalid POSTGRES_DB %r", db)
        return False
    dest = dump_path()
    tmp = Path(f"/tmp/pastor_ai_db.{os.getpid()}.dump")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "su",
                "-s",
                "/bin/bash",
                "postgres",
                "-c",
                f"pg_dump -Fc --no-owner -d {db} -f {tmp}",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            logger.warning(
                "Postgres persist dump failed: %s",
                (result.stderr or result.stdout or "")[:500],
            )
            return False
        shutil.copyfile(tmp, dest)
        dest.chmod(0o644)
        return True
    except Exception:
        logger.warning("Postgres persist dump failed", exc_info=True)
        return False
    finally:
        tmp.unlink(missing_ok=True)
