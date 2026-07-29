"""Carry-forward pins — the startup singleton guard + credential log hygiene.

1. PID guard (recommended by the E2E program, never built): nothing stopped
   a second engine instance from sharing the live data dir — doubled
   schedulers with real API keys, SQLite contention, a split fill pipeline.
   The guard refuses at lifespan when a LIVE pid holds config.DATA_DIR,
   clears stale files, and releases only its own pid. Gated OFF under
   pytest like every lifespan step that touches the live data dir (F5).

   The Windows liveness probe is the load-bearing subtlety: os.kill(pid, 0)
   on Windows routes to TerminateProcess — the "probe" would KILL the other
   engine. Pinned by source (never regress to os.kill on nt) and behavior.

2. httpx/httpcore log levels: httpx echoed every request URL at INFO —
   including Finnhub's token query param — into the root JSON log
   (data/logs/risk_engine.jsonl) in cleartext.
"""
from __future__ import annotations

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import main  # noqa: E402  (import is side-effect-safe under pytest — F5 gates)


class TestPidAlive:
    def test_own_pid_is_alive(self):
        assert main._pid_alive(os.getpid()) is True

    def test_bogus_pid_is_dead(self):
        # PID 4_000_000 exceeds Windows' practical pid space and any Linux
        # default pid_max; if it ever collides, the probe still only READS.
        assert main._pid_alive(4_000_000) is False

    def test_windows_probe_never_signals(self):
        # THE trap: os.kill(pid, 0) on Windows == TerminateProcess.
        import inspect
        src = inspect.getsource(main._pid_alive)
        nt_branch = src.split('os.name == "nt"')[1].split("try:")[0]
        assert "os.kill" not in nt_branch
        assert "OpenProcess" in nt_branch or "OpenProcess" in src


class TestPidLock:
    @pytest.fixture
    def pid_file(self, tmp_path, monkeypatch):
        p = str(tmp_path / "engine.pid")
        monkeypatch.setattr(main, "_PID_FILE", p)
        return p

    def test_acquires_when_absent(self, pid_file):
        main._acquire_pid_lock()
        assert open(pid_file).read().strip() == str(os.getpid())

    def test_refuses_when_live_pid_holds_the_dir(self, pid_file, monkeypatch):
        with open(pid_file, "w") as fh:
            fh.write("12345")
        monkeypatch.setattr(main, "_pid_alive", lambda pid: True)
        with pytest.raises(RuntimeError, match="another engine instance"):
            main._acquire_pid_lock()
        # The refusal must not clobber the holder's file.
        assert open(pid_file).read().strip() == "12345"

    def test_stale_pid_is_cleared_and_taken(self, pid_file, monkeypatch):
        with open(pid_file, "w") as fh:
            fh.write("12345")
        monkeypatch.setattr(main, "_pid_alive", lambda pid: False)
        main._acquire_pid_lock()
        assert open(pid_file).read().strip() == str(os.getpid())

    def test_release_removes_only_own_pid(self, pid_file):
        with open(pid_file, "w") as fh:
            fh.write(str(os.getpid()))
        main._release_pid_lock()
        assert not os.path.exists(pid_file)
        # Someone else's file survives a release.
        with open(pid_file, "w") as fh:
            fh.write("12345")
        main._release_pid_lock()
        assert os.path.exists(pid_file)

    def test_garbage_file_does_not_block_startup(self, pid_file):
        with open(pid_file, "w") as fh:
            fh.write("not-a-pid")
        main._acquire_pid_lock()
        assert open(pid_file).read().strip() == str(os.getpid())

    def test_lifespan_gates_guard_off_under_pytest(self):
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "main.py"), encoding="utf-8").read()
        i = src.index("_acquire_pid_lock()", src.index("async def lifespan"))
        gate = src[i - 200:i]
        assert "_TESTING" in gate, (
            "the PID guard must stay behind the F5 pytest gate — a suite "
            "run must never contend with the live engine's pid file"
        )


class TestCredentialLogHygiene:
    def test_httpx_loggers_capped_at_warning(self):
        # Importing main applies the levels; INFO request-URL echo (which
        # carries the Finnhub token query param) must not reach the root
        # JSON handler.
        assert logging.getLogger("httpx").level >= logging.WARNING
        assert logging.getLogger("httpcore").level >= logging.WARNING
