from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import api.backup as backup


class _Done:
    def __init__(self, returncode=0, stderr=""):
        self.returncode, self.stderr = returncode, stderr


def test_run_backup_dumps_gzips_uploads_and_prunes(monkeypatch):
    uploaded, deleted = [], []
    existing = [f"backups/video2book-2026100{day}T000000Z.sql.gz" for day in range(1, 5)]
    monkeypatch.setattr(backup, "settings", replace(backup.settings, backup_command="pg_dump", backups_to_keep=3))
    monkeypatch.setattr(backup.shutil, "which", lambda command: "/usr/bin/pg_dump")
    monkeypatch.setattr(backup.storage, "upload_object", lambda key, path, content_type=None: uploaded.append((key, Path(path).read_bytes()[:2])))
    monkeypatch.setattr(backup.storage, "list_keys", lambda prefix: [*existing, *(key for key, _ in uploaded)])
    monkeypatch.setattr(backup.storage, "delete_object", deleted.append)

    def fake_pg_dump(args, **kwargs):
        Path(args[args.index("--file") + 1]).write_text("CREATE TABLE users ();", encoding="utf-8")
        return _Done()

    key = backup.run_backup(runner=fake_pg_dump, now=datetime(2026, 10, 5, tzinfo=timezone.utc))

    assert key == "backups/video2book-20261005T000000Z.sql.gz"
    assert uploaded == [(key, b"\x1f\x8b")]  # gzip magic
    assert deleted == existing[:2]


def test_run_backup_is_skipped_when_off_missing_or_failing(monkeypatch):
    monkeypatch.setattr(backup, "settings", replace(backup.settings, backup_command=""))
    assert backup.run_backup(runner=lambda *a, **k: _Done()) is None

    monkeypatch.setattr(backup, "settings", replace(backup.settings, backup_command="pg_dump"))
    monkeypatch.setattr(backup.shutil, "which", lambda command: None)
    assert backup.run_backup(runner=lambda *a, **k: _Done()) is None

    monkeypatch.setattr(backup.shutil, "which", lambda command: "/usr/bin/pg_dump")
    assert backup.run_backup(runner=lambda *a, **k: _Done(returncode=1, stderr="no db")) is None
