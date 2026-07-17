"""
v2.7 holistic-audit Task E — conftest isolation-guard pins (F5).

The lifespan-level mechanisms (pytest gates, singleton rebind, root-
logger guard) are pinned in tests/test_routes.py::TestF5IsolationPins —
the module that owns the process's one TestClient lifespan (LOW-023).
This file pins the conftest-level guard: the credential-audit log
redirect. The session tripwire (content-hash WARNING over live data/)
is session infra — it demonstrates itself in every run's warning
summary and has no per-test pin.

Run: pytest tests/test_f5_isolation_guards.py -v
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_LIVE_AUDIT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "logs", "audit.jsonl",
)


def _live_audit_size() -> int:
    try:
        return os.path.getsize(_LIVE_AUDIT)
    except OSError:
        return -1  # absent — any test write would CREATE it (caught below)


def test_audit_log_guard_redirects_writes(tmp_path):
    """core.audit.log_event must land in the conftest-patched throwaway,
    never the live data/logs/audit.jsonl (its module-level hardcoded
    path — the F5 lane observed writing live mid-gate 2026-07-17)."""
    import core.audit as audit

    live_before = _live_audit_size()
    assert str(audit._AUDIT_PATH) != os.path.abspath(_LIVE_AUDIT), (
        "the _isolate_credential_audit_log conftest guard is not active — "
        "this write would have appended to the operator's live audit log"
    )
    audit.log_event("add", "connection", "f5-guard-pin", "isolation test")
    assert audit._AUDIT_PATH.exists(), "guarded write landed nowhere"
    assert "f5-guard-pin" in audit._AUDIT_PATH.read_text(encoding="utf-8")
    assert _live_audit_size() == live_before, (
        "the live data/logs/audit.jsonl changed during a guarded write"
    )
