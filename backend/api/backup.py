"""Daily Postgres backup: `pg_dump` -> gzip -> S3 `backups/`, keeping the
newest BACKUPS_TO_KEEP. Run by the worker's housekeeping loop; also
`python -m api.backup` by hand.

On AWS, RDS automated backups are the better tool -- set BACKUP_COMMAND=""
there to turn this off. This exists so a self-hosted or local deployment
is never without one (backend/AGENTS.md: daily backups before real users).
"""

import gzip
import shutil
import subprocess  # nosec B404 - fixed argument list, never shell=True
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from api import storage
from api.config import settings
from api.logging import get_logger

BACKUP_PREFIX = "backups/"


def _conninfo() -> str:
    return settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def backup_key(now: datetime) -> str:
    return f"{BACKUP_PREFIX}video2book-{now.strftime('%Y%m%dT%H%M%SZ')}.sql.gz"


def run_backup(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    now: datetime | None = None,
) -> str | None:
    """Dump, upload and prune; returns the new object key, or None when
    backups are off or pg_dump is missing (logged, never raised -- a failed
    backup must not stop the worker)."""
    logger = get_logger(step="backup")
    command = settings.backup_command.strip()
    if not command:
        return None
    if shutil.which(command) is None:
        logger.warning("backup skipped: command not found", extra={"command": command})
        return None

    now = now or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        dump_path = Path(tmp) / "dump.sql"
        result = runner(
            [command, "--no-owner", "--no-privileges", "--file", str(dump_path), _conninfo()],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0 or not dump_path.exists():
            logger.error("backup failed", extra={"stderr": (result.stderr or "")[-500:]})
            return None
        gz_path = Path(tmp) / "dump.sql.gz"
        with dump_path.open("rb") as source, gzip.open(gz_path, "wb") as target:
            shutil.copyfileobj(source, target)
        key = backup_key(now)
        storage.upload_object(key, gz_path, content_type="application/gzip")

    removed = prune_backups(settings.backups_to_keep)
    logger.info("backup uploaded", extra={"key": key, "old_backups_removed": removed})
    return key


def prune_backups(keep: int) -> int:
    """Delete all but the newest `keep` backups (keys sort by time)."""
    keys = sorted(storage.list_keys(BACKUP_PREFIX))
    old = keys[:-keep] if keep > 0 else []
    for key in old:
        storage.delete_object(key)
    return len(old)


if __name__ == "__main__":
    print(run_backup() or "No backup made (see the log).")
