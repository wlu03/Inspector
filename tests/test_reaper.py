"""SessionManager reaper: idle-TTL + absolute-age teardown, deterministic via reap(now)."""

from inspector.config import Config
from inspector.session import SessionManager


class _FakeSession:
    def __init__(self, sid, created_at, touched_at):
        self.record = type("R", (), {"id": sid})()
        self.created_at = created_at
        self.touched_at = touched_at
        self.torn = False

    def teardown(self):
        self.torn = True


def _mgr():
    # idle TTL 100s, sandbox lifetime 1000s; reaper thread never starts (no create()).
    cfg = Config(session_idle_ttl_s=100, sandbox_timeout_s=1000)
    return SessionManager(cfg)


def test_reaps_idle_and_old_keeps_active():
    mgr = _mgr()
    now = 10_000.0
    active = _FakeSession("a", created_at=now - 50, touched_at=now - 5)     # fresh → keep
    idle = _FakeSession("b", created_at=now - 200, touched_at=now - 150)    # idle > 100 → reap
    old = _FakeSession("c", created_at=now - 2000, touched_at=now - 1)      # age > 1000 → reap
    mgr.sessions = {"a": active, "b": idle, "c": old}

    reaped = mgr.reap(now)

    assert set(reaped) == {"b", "c"}
    assert idle.torn and old.torn and not active.torn
    assert set(mgr.sessions) == {"a"}


def test_disabled_when_ttl_zero():
    cfg = Config(session_idle_ttl_s=0, sandbox_timeout_s=0)
    mgr = SessionManager(cfg)
    now = 10_000.0
    s = _FakeSession("a", created_at=now - 99_999, touched_at=now - 99_999)
    mgr.sessions = {"a": s}
    assert mgr.reap(now) == []  # both caps disabled → nothing reaped
    assert not s.torn
