import glob
import hashlib
import sys
import os
import sqlite3
import warnings

import pytest

# Ensure project root is on the path for all test modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


_ISO_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO accounts (id) VALUES (1);
CREATE TABLE IF NOT EXISTS trade_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  calc_id TEXT,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  source TEXT NOT NULL,
  timestamp TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS engine_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  source TEXT NOT NULL
);
"""


@pytest.fixture(autouse=True)
def _isolate_live_per_account_logs(monkeypatch, tmp_path):
    """Guard the operator's LIVE per-account DB from test event-log writes.

    Two append-only audit logs live in the per-account DB and are written by
    the calc / fill / close paths via a ``log_*`` helper that resolves
    ``config.DATA_DIR`` at RUNTIME (no ``data_dir`` arg):
      - ``trade_events``  via ``core.trade_event_log._resolve_db_path``
        (order_filled / position_closed / position_opened / partial_close / …)
      - ``engine_events`` via ``core.event_log._resolve_db_path``
        (calc_blocked_contract / dd_state_transition / close_row_build_failed / …)
    For account 1 (which exists live) both resolve to
    ``data/per_account/quantower__binancefutures__binance.db``, so any
    un-isolated process_fill / close-row / calc test silently appended real
    rows there (8k+ trade_events incl. ``calc_id=C1`` fixtures, plus
    engine_events) — pure test pollution of operator data.

    Fix: patch BOTH ``_resolve_db_path`` resolvers (the single read+write funnel
    for each log) so the UN-ISOLATED case — no explicit ``data_dir`` AND
    ``config.DATA_DIR`` still the real data dir — redirects to a throwaway
    per-test DB. Reads and writes both flow through the resolver, so a
    write-then-query-read in one test stays consistent.

    Why patch the resolvers and NOT redirect ``config.DATA_DIR`` session-wide:
    many tests (routes, ``account_config``, ``pre_trade_log`` / calc-revision /
    lifecycle) resolve OTHER DBs off ``config.DATA_DIR`` at runtime; pointing it
    at an empty tmp breaks those reads with ``OperationalError`` (a session-wide
    redirect was tried and broke 36 tests). This guard leaves
    ``config.DATA_DIR`` (and the baked ``config.DB_PATH`` / ``db_router`` paths)
    untouched, and passes through any test that isolates itself (its own
    ``config.DATA_DIR`` tmp, or an explicit ``data_dir=``).

    Scope: trade_events + engine_events (the two per-account logs on the
    hot paths). The transactional tables (``closed_positions``, ``orders``,
    ``fills`` …) live in ``config.DB_PATH`` and are already isolated by the
    tests that patch ``config.DB_PATH`` themselves.

    ⚠ THIRD RESOLVER OF THIS FAMILY, DELIBERATELY NOT REDIRECT-GUARDED
    HERE (v2.7 Task E; both holistic-audit passes flagged it):
    ``core.db_account_settings._resolve_db_path`` is the SHARED
    transactional per-account resolver (also imported by
    ``data_cache`` / ``order_manager`` / ``calc_correlation`` /
    ``schedulers`` / ``equity_gap_detector``). It is NOT redirected to
    ``_ISO_SCHEMA`` like the two log resolvers above BECAUSE its callers
    touch many tables AND read real account rows — a minimal-schema
    redirect would ``OperationalError`` on the reads (the empty-DATA_DIR
    redirect that broke 36 tests, above, is the same failure shape), and
    a full-data copy reintroduces cross-test accumulation. So the class
    is guarded structurally per-test (each test that drives the
    transactional layer isolates its own DB / DATA_DIR) and caught
    globally by the SESSION content-hash tripwire
    (``_live_data_dir_tripwire``). The one live-write site the tripwire
    surfaced — ``OrderManager._snapshot_and_fix_isclose`` persisting
    ``position_fill_snapshots`` — is closed in
    ``tests/test_phase0_0_4_reversal_split.py``'s ``test_db`` fixture and
    hard-pinned by ``test_snapshot_resolver_isolated_from_live_db``. A
    future unisolated writer through this resolver reopens the class:
    the tripwire WARNS (naming the file) — treat that as a finding.
    """
    import config
    import core.trade_event_log as tel
    import core.event_log as evl

    real_data_dir = os.path.abspath(config.DATA_DIR)
    iso = tmp_path / "per_account_iso.db"
    created = {"done": False}

    def _ensure_iso():
        if not created["done"]:
            conn = sqlite3.connect(str(iso))
            conn.executescript(_ISO_SCHEMA)
            conn.commit()
            conn.close()
            created["done"] = True

    def _make_guard(real_resolve):
        def _resolve(account_id, data_dir=None):
            # Un-isolated (no explicit data_dir, real DATA_DIR) → would hit the
            # live per-account DB → redirect to the throwaway. Everything else
            # (a test's own tmp DATA_DIR, or an explicit data_dir) flows to the
            # real resolver.
            if data_dir is None and os.path.abspath(config.DATA_DIR) == real_data_dir:
                _ensure_iso()
                return str(iso)
            return real_resolve(account_id, data_dir)
        return _resolve

    monkeypatch.setattr(tel, "_resolve_db_path", _make_guard(tel._resolve_db_path))
    monkeypatch.setattr(evl, "_resolve_db_path", _make_guard(evl._resolve_db_path))


@pytest.fixture(autouse=True)
def _isolate_credential_audit_log(monkeypatch, tmp_path):
    """Guard the live ``data/logs/audit.jsonl`` from test writes (F5,
    v2.7 holistic audit Task E).

    ``core.audit._AUDIT_PATH`` is a module-level HARDCODED live path (not
    even config-derived) read at call time by ``log_event`` — connection /
    account lifecycle tests were appending real audit rows there (observed:
    live-file mtime bumped mid-gate on 2026-07-17). Same guard family as
    ``_isolate_live_per_account_logs``: patch the module attribute to a
    per-test throwaway."""
    import core.audit as _audit
    from pathlib import Path

    monkeypatch.setattr(_audit, "_AUDIT_PATH", Path(tmp_path) / "audit.jsonl")


def _hash_live_data_files():
    """{path: sha256} of the live data-dir DB files + engine logs.

    Content hashes, not mtimes — read-only sqlite connections can bump
    mtime via WAL checkpointing on close, which is not a write in the
    sense this tripwire polices."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = os.path.join(root, "data")
    targets = (
        [os.path.join(data, "risk_engine.db"),
         os.path.join(data, "global.db"),
         os.path.join(data, "logs", "risk_engine.jsonl"),
         os.path.join(data, "logs", "audit.jsonl")]
        + sorted(glob.glob(os.path.join(data, "per_account", "*.db")))
    )
    out = {}
    for p in targets:
        if not os.path.isfile(p):
            continue
        h = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[p] = h.hexdigest()
        except OSError:
            continue  # locked/unreadable — skip rather than fail the session
    return out


@pytest.fixture(scope="session", autouse=True)
def _live_data_dir_tripwire():
    """SESSION tripwire: the test suite must leave the operator's live
    data/ content byte-identical (F5, Task E — the durable detector the
    audit said conftest lacked).

    Hashes the live DB files + engine logs at session start and end; any
    drift raises a loud pytest WARNING (surfaced in the run summary)
    naming the changed files. WARNING and not a hard fail BECAUSE a live
    engine running alongside the suite legitimately writes these files —
    the message disambiguates. A clean run with the engine stopped must
    be drift-free; treat any warning as a finding, not noise."""
    before = _hash_live_data_files()
    yield
    after = _hash_live_data_files()
    drifted = sorted(
        set(k for k in before if after.get(k) != before[k])
        | set(k for k in after if k not in before)
    )
    if drifted:
        warnings.warn(
            "F5 LIVE-DATA TRIPWIRE: live data/ content changed during this "
            f"test session: {drifted}. Either a test wrote to operator data "
            "(a bug — find and isolate it) OR the live engine was running "
            "alongside the suite (expected drift; re-run with the engine "
            "stopped to confirm).",
            UserWarning,
        )


@pytest.fixture(scope="session", autouse=True)
def _corr_log_session_floor(tmp_path_factory):
    """SESSION-scoped floor under ``_isolate_correlation_log_dir`` (CL.T0b
    audit finding 1 — a proven live-dir leak, not hypothetical).

    pytest instantiates higher-scoped fixtures first: a module-scoped
    ``TestClient`` fixture (e.g. tests/test_routes.py) runs the app
    lifespan — and therefore ``correlation_log.start()`` — BEFORE any
    function-scoped patch exists, so the writer thread captured the LIVE
    ``data/logs/correlation`` dir (the suite created a real day file
    there, and the startup prune ran against the live dir). This floor
    guarantees the resolver points at session-tmp from the first moment
    of the session; the function-scoped fixture below then layers a
    per-test dir on top (and its monkeypatch teardown restores THIS
    floor, not the live config value).
    """
    import core.correlation_log as _cl

    mp = pytest.MonkeyPatch()
    floor = tmp_path_factory.mktemp("corr-floor")
    mp.setattr(_cl, "_resolve_sink_dir", lambda: str(floor / "corr"))
    yield
    _cl.close(timeout=2.0)
    mp.undo()


@pytest.fixture(autouse=True)
def _isolate_correlation_log_dir(monkeypatch, tmp_path):
    """Guard the live ``data/logs/correlation/`` dir from test writes
    (CL.T0b, plan task 0.8 / spec §7.6).

    Patches the SINK-DIR RESOLVER on ``core.correlation_log`` — not the
    env var or ``config.CORR_LOG_DIR`` consumers' import-time copies —
    mirroring ``_isolate_live_per_account_logs``'s resolver-patch
    approach. The writer thread re-resolves the dir at start and at every
    rollover. NB this function-scoped patch does NOT cover writers
    started by higher-scoped fixtures (module-scoped TestClient lifespans
    run first) — that hole is closed by ``_corr_log_session_floor``
    above; this fixture provides the tighter per-test dir + cleanup.
    Teardown stops a writer the test left running (no thread leak across
    tests) and drains the module queue (no cross-test envelope leakage
    into a later test that starts the writer).
    """
    import core.correlation_log as _cl

    monkeypatch.setattr(_cl, "_resolve_sink_dir", lambda: str(tmp_path / "corr"))
    # Fresh corr context per test: tick() is deliberately set-only (loop
    # tasks own their context in production), so a test that ticks in the
    # pytest main thread would otherwise leak its corr_id into later tests.
    token = _cl.corr_id_var.set("")
    yield
    try:
        _cl.corr_id_var.reset(token)
    except ValueError:
        pass  # reset in a different context (async test runners) — benign
    _cl.close(timeout=2.0)
    while True:
        try:
            _cl._queue.get_nowait()
        except Exception:
            break
