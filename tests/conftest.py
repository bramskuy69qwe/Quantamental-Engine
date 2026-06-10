import sys
import os
import sqlite3

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
    yield
    _cl.close(timeout=2.0)
    while True:
        try:
            _cl._queue.get_nowait()
        except Exception:
            break
