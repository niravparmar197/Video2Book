import api.worker as worker


def test_housekeeping_runs_retention_and_backup_and_survives_failures(monkeypatch):
    calls = []

    def failing_retention():
        calls.append("retention")
        raise RuntimeError("s3 down")

    monkeypatch.setattr(worker, "run_retention", failing_retention)
    monkeypatch.setattr(worker, "run_backup", lambda: calls.append("backup"))

    worker.run_housekeeping()

    assert calls == ["retention", "backup"]


def test_only_one_claim_per_interval(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.keys = {}

        def set(self, key, value, nx=False, ex=None):
            if nx and key in self.keys:
                return None
            self.keys[key] = (value, ex)
            return True

    fake = FakeRedis()
    monkeypatch.setattr(worker.heartbeat, "_client", lambda: fake)

    assert worker._claim_housekeeping() is True
    assert worker._claim_housekeeping() is False
    assert fake.keys[worker._HOUSEKEEPING_KEY][1] == 24 * 3600
