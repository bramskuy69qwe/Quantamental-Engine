"""Tests for startup equity delta warning (v2.4 Priority 2d).

**v3.0 operator-bug #4 rewrote how these seed the snapshot.** They used to
INSERT a row into the per-account DB and assert the check found it — which
passed only because the check read that same (wrong) store. The snapshot
WRITER (`db.insert_account_snapshot`) goes through the legacy combined DB,
so the per-account `account_snapshots` copy is an orphan frozen at the split
date. Live, that made every startup compare against a three-month-old row:

    Startup equity delta: live=307.59 snapshot=82.19 delta=274.2304%

repeated verbatim across every restart while crash recovery — reading the
legacy store correctly — logged the true ~306 in the same boot.

Seeding the store the reader happened to use is precisely how a
reader/writer split survives a green suite, so the snapshot is now STUBBED
at the public helper and the store choice is pinned separately at the
source. Same shape as the Task-102 fixture correction in operator-bug #1.
"""
import asyncio
import inspect
import json
import os
import sqlite3

import pytest

from core.event_log import query_events
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1):
    """Per-account DB + migrated schema, so log_event/query_events resolve to
    a throwaway data dir. Deliberately seeds NO account_snapshots row — the
    snapshot comes from the stubbed reader (see module docstring)."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    return str(data), db_path


def _stub_snapshot(monkeypatch, snap):
    """Stub the public reader the check now goes through. `snap` is the row
    dict (or None for "no prior snapshot")."""
    from core.database import db

    async def _fake(account_id=1):
        return snap
    monkeypatch.setattr(db, "get_last_account_state", _fake, raising=True)


def _run_check():
    from core.schedulers import _check_startup_equity_delta
    asyncio.run(_check_startup_equity_delta())


class TestEquityDeltaStartup:
    def test_large_delta_logs_warning(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        _stub_snapshot(monkeypatch, {
            "total_equity": 10000.0, "snapshot_ts": "2026-07-23T20:45:14+00:00",
        })

        from core.state import app_state
        app_state.account_state.total_equity = 9800.0  # 2% delta

        _run_check()

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 1
        payload = json.loads(events[0]["payload_json"])
        assert payload["live"] == 9800.0
        assert payload["snapshot"] == 10000.0
        assert payload["delta_pct"] == pytest.approx(0.02)
        assert payload["snapshot_ts"] == "2026-07-23T20:45:14+00:00"

    def test_small_delta_no_log(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        _stub_snapshot(monkeypatch, {"total_equity": 10000.0, "snapshot_ts": "t"})

        from core.state import app_state
        app_state.account_state.total_equity = 9950.0  # 0.5% delta

        _run_check()

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0

    def test_no_prior_snapshot_no_error(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        _stub_snapshot(monkeypatch, None)

        from core.state import app_state
        app_state.account_state.total_equity = 10000.0

        _run_check()  # should not raise

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0

    def test_zero_equity_no_check(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        _stub_snapshot(monkeypatch, {"total_equity": 10000.0, "snapshot_ts": "t"})

        from core.state import app_state
        app_state.account_state.total_equity = 0.0

        _run_check()  # should not raise or log

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0

    def test_zero_snapshot_equity_no_log(self, tmp_path, monkeypatch):
        """A snapshot row present but zero-equity must not divide by zero."""
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        _stub_snapshot(monkeypatch, {"total_equity": 0.0, "snapshot_ts": "t"})

        from core.state import app_state
        app_state.account_state.total_equity = 10000.0

        _run_check()  # must not raise ZeroDivisionError

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0


class TestReadsTheStoreTheWriterUses:
    """v3.0 operator-bug #4 — the load-bearing pins.

    The behavioural tests above stub the reader, so they cannot by themselves
    catch a regression that re-points the check at a different database.
    These do.
    """

    def _src(self):
        """Function body WITHOUT the docstring — the docstring names the old
        defect in prose, and a source-grep pin must test the executable code,
        not its own explanation of the bug it prevents."""
        from core.schedulers import _check_startup_equity_delta

        # Executable body only — the docstring names the old defect in prose
        # (`_resolve_db_path`, `sqlite3.connect`), and a source-grep pin must
        # test the code, not its own explanation. Split off the triple-quoted
        # docstring rather than str.replace(__doc__): getsource returns
        # dedented source that no longer matches __doc__ verbatim.
        src = inspect.getsource(_check_startup_equity_delta)
        parts = src.split('"""')
        return '"""'.join(parts[2:]) if len(parts) >= 3 else src

    def test_reads_via_the_public_snapshot_helper(self):
        assert "get_last_account_state" in self._src(), (
            "operator-bug #4 regression: the startup delta check must read "
            "snapshots through db.get_last_account_state — the same "
            "DatabaseManager the snapshot WRITER uses."
        )

    def test_does_not_resolve_the_per_account_db(self):
        """The literal defect: `_resolve_db_path(aid)` pointed this check at
        the per-account DB, whose account_snapshots is an orphan frozen at
        the split date (live: equity 82.19, 2026-04-28)."""
        assert "_resolve_db_path" not in self._src(), (
            "operator-bug #4 regression: _resolve_db_path routes to the "
            "PER-ACCOUNT db, but account_snapshots is written to the legacy "
            "combined db — the two disagree by three months of live data."
        )

    def test_does_not_open_its_own_connection(self):
        """A hand-rolled sqlite3 connection is how the store drifted apart
        from the writer in the first place; it also duplicated the query."""
        assert "sqlite3.connect" not in self._src()

    def test_reader_and_writer_are_the_same_manager(self):
        """The invariant, stated directly: whatever object owns
        insert_account_snapshot must also own get_last_account_state."""
        from core.database import db

        assert hasattr(db, "insert_account_snapshot")
        assert hasattr(db, "get_last_account_state")
        assert (
            db.insert_account_snapshot.__self__
            is db.get_last_account_state.__self__
        ), "snapshot reader and writer must bind to the same DatabaseManager"

    def test_snapshot_ordering_is_insertion_order_not_text_ts(self):
        """`snapshot_ts` is TEXT and the live table holds two ISO widths (25-
        and 32-char), so ordering on it is fragile by construction. The
        helper orders by id — pin that it stays that way."""
        from core.database import db

        src = inspect.getsource(db.get_last_account_state.__func__)
        assert "ORDER BY id DESC" in src
        assert "ORDER BY snapshot_ts" not in src


class TestAwaitedByTheStartupPath:
    def test_startup_awaits_the_check(self):
        """The check became a coroutine; an un-awaited call would silently
        never run (and emit a RuntimeWarning rather than fail)."""
        import core.schedulers as sch

        src = inspect.getsource(sch)
        assert "await _check_startup_equity_delta()" in src, (
            "the startup path must AWAIT the delta check — a bare call now "
            "creates a coroutine that is never executed."
        )
        assert asyncio.iscoroutinefunction(sch._check_startup_equity_delta)
