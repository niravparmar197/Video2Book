from dataclasses import replace

import api.signup_limit as signup_limit


class _FakeRedis:
    def __init__(self):
        self.counts, self.expiries = {}, {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        self.expiries[key] = seconds


def test_allow_signup_counts_per_ip_within_the_hour(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(signup_limit, "_client", lambda: fake)
    monkeypatch.setattr(signup_limit, "settings", replace(signup_limit.settings, signup_limit_per_ip_per_hour=2))

    results = [signup_limit.allow_signup("1.2.3.4") for _ in range(3)]

    assert results == [True, True, False]
    assert signup_limit.allow_signup("5.6.7.8") is True
    assert set(fake.expiries.values()) == {3600}


def test_allow_signup_fails_open_when_redis_is_down(monkeypatch):
    def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(signup_limit, "_client", broken)
    monkeypatch.setattr(signup_limit, "settings", replace(signup_limit.settings, signup_limit_per_ip_per_hour=2))

    assert signup_limit.allow_signup("1.2.3.4") is True
