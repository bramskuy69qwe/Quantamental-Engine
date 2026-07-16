"""
v2.7 Phase 1 — model-library schema + DB layer.

Covers (docs/design/v2.7_model_library_plan.md, Phase 1):
- migration idempotency: boot twice; new columns exactly once; index exists
- model round-trip with risk_preset/strategy decoded; pre-v2.7 caller
  back-compat (create/update without the new args)
- updated_at semantics: NULL on create, stamped on update
- create_model_backtest -> list_model_backtests; engine sessions keep
  model_id NULL
- task 1.8 filter: imported runs invisible to list_backtest_sessions
- delete_potential_model cascade: model + sessions + trades + equity gone
- get_model_for_calc: hit / miss / dangling ("(deleted model)")
- dual-track .sql pair (013 global / 014 per_account): applies once,
  recorded in migrations_log, skipped on re-apply

Run: pytest tests/test_v27_phase1_model_library_schema.py -v
"""
from __future__ import annotations

import sqlite3

import pytest

from core.database import DatabaseManager
from core.migrations.runner import apply_one, discover


async def _make_init_db(tmp_path):
    """Spin up a real DatabaseManager against a tmp_path .db file.
    Returns the open manager; caller must close conn."""
    db_path = str(tmp_path / "v27_test.db")
    mgr = DatabaseManager(path=db_path)
    await mgr.initialize()
    return mgr


async def _table_cols(mgr, table):
    async with mgr._conn.execute(f"PRAGMA table_info({table})") as cur:
        return [row[1] for row in await cur.fetchall()]


_NORMALIZED = {
    "session_name": "MC @ES import",
    "summary": {
        "net_profit": 1234.5,
        "win_rate": 0.61,
        "profit_factor": 1.8,
        "max_drawdown": 500.0,
        "max_drawdown_pct": 0.05,
        "sharpe": 0.0,
        "total_trades": 2,
        "period_start": "2026-01-01",
        "period_end": "2026-02-01",
    },
    "trades": [
        {
            "symbol": "@ES", "side": "long",
            "entry_dt": "2026-01-02T09:31:00", "exit_dt": "2026-01-02T10:15:00",
            "entry_price": 5000.0, "exit_price": 5010.0, "size_usdt": 250000.0,
            "r_multiple": 0.0, "pnl_usdt": 500.0,
            "regime_label": "", "exit_reason": "take_profit",
        },
        {
            "symbol": "@ES", "side": "short",
            "entry_dt": "2026-01-03T09:31:00", "exit_dt": "2026-01-03T09:45:00",
            "entry_price": 5020.0, "exit_price": 5025.0, "size_usdt": 251000.0,
            "r_multiple": 0.0, "pnl_usdt": -250.0,
            "regime_label": "", "exit_reason": "stop_loss",
        },
    ],
    "equity_curve": [
        {"dt": "2026-01-02T10:15:00", "equity": 100500.0, "drawdown": 0.0},
        {"dt": "2026-01-03T09:45:00", "equity": 100250.0, "drawdown": 250.0},
    ],
}


# ── Schema: columns + index, boot-twice idempotency ──────────────────────────

@pytest.mark.asyncio
async def test_new_columns_and_index_exist_after_double_init(tmp_path):
    """Boot twice on the same file: no raise, each new column exactly once,
    idx_bt_sessions_model present."""
    db_path = str(tmp_path / "v27_test.db")
    mgr1 = DatabaseManager(path=db_path)
    await mgr1.initialize()
    await mgr1._conn.close()

    mgr2 = DatabaseManager(path=db_path)
    await mgr2.initialize()
    try:
        for table, col in [
            ("potential_models", "risk_preset_json"),
            ("potential_models", "strategy_json"),
            ("potential_models", "updated_at"),
            ("backtest_sessions", "model_id"),
            ("backtest_sessions", "source_app"),
            ("pre_trade_log", "model_id"),
            ("closed_positions", "model_id"),
        ]:
            cols = await _table_cols(mgr2, table)
            assert cols.count(col) == 1, f"{table}.{col}: {cols.count(col)} copies"
        async with mgr2._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_bt_sessions_model",),
        ) as cur:
            assert await cur.fetchone() is not None
    finally:
        await mgr2._conn.close()


@pytest.mark.asyncio
async def test_initialize_upgrades_legacy_shaped_db(tmp_path):
    """The bug this pins: idx_bt_sessions_model must NOT live inside
    _CREATE_STATEMENTS — on a legacy DB (backtest_sessions exists WITHOUT
    model_id) executescript runs BEFORE the ALTER loop, so an index line
    there kills boot with "no such column: model_id" (executescript-
    before-ALTER ordering trap). The app's per-account shadow DBs are
    exactly this shape, so test_routes' real-app boot exercises it.
    initialize() on a legacy-shaped DB must upgrade cleanly."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE backtest_sessions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " name TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'macro',"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " date_from TEXT NOT NULL DEFAULT '', date_to TEXT NOT NULL DEFAULT '',"
        " config_json TEXT NOT NULL DEFAULT '{}',"
        " summary_json TEXT NOT NULL DEFAULT '{}')"
    )
    conn.execute(
        "CREATE TABLE potential_models ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " name TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'both',"
        " description TEXT NOT NULL DEFAULT '',"
        " config_json TEXT NOT NULL DEFAULT '{}')"
    )
    conn.commit()
    conn.close()

    mgr = DatabaseManager(path=db_path)
    await mgr.initialize()  # must not raise
    try:
        bt_cols = await _table_cols(mgr, "backtest_sessions")
        assert "model_id" in bt_cols and "source_app" in bt_cols
        pm_cols = await _table_cols(mgr, "potential_models")
        assert {"risk_preset_json", "strategy_json", "updated_at"} <= set(pm_cols)
        async with mgr._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_bt_sessions_model",),
        ) as cur:
            assert await cur.fetchone() is not None, (
                "post-ALTER index block must create idx_bt_sessions_model "
                "on legacy DBs too"
            )
    finally:
        await mgr._conn.close()


# ── ModelsMixin round-trips ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_model_roundtrip_with_new_fields_and_updated_at(tmp_path):
    mgr = await _make_init_db(tmp_path)
    try:
        preset = {"risk_pct": 1.0, "apply_regime_multiplier": True}
        strat = {"entry_logic": "OR breakout", "notes": "v1"}
        mid = await mgr.create_potential_model(
            "M1", "micro", "desc", {"legacy": 1},
            risk_preset=preset, strategy=strat,
        )
        d = await mgr.get_potential_model(mid)
        assert d["risk_preset"] == preset
        assert d["strategy"] == strat
        assert d["config"] == {"legacy": 1}
        assert d["updated_at"] is None, "updated_at must be NULL on create"

        await mgr.update_potential_model(
            mid, "M1b", "macro", "desc2", {"legacy": 2},
            risk_preset={"risk_pct": 2.0}, strategy={"notes": "v2"},
        )
        d = await mgr.get_potential_model(mid)
        assert d["name"] == "M1b"
        assert d["risk_preset"] == {"risk_pct": 2.0}
        assert d["strategy"] == {"notes": "v2"}
        assert d["updated_at"], "updated_at must be stamped on update"

        listed = await mgr.list_potential_models()
        assert listed[0]["risk_preset"] == {"risk_pct": 2.0}
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_model_backcompat_old_call_shapes(tmp_path):
    """Pre-v2.7 callers (no risk_preset/strategy args) keep working:
    create writes '{}'; update leaves the stored values untouched."""
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("Old", "both", "d", {"a": 1})
        d = await mgr.get_potential_model(mid)
        assert d["risk_preset"] == {} and d["strategy"] == {}

        await mgr.update_potential_model(
            mid, "Old", "both", "d", {"a": 1},
            risk_preset={"risk_pct": 0.5}, strategy={"notes": "keep me"},
        )
        # Old-style update (no new args) must NOT wipe the stored dicts.
        await mgr.update_potential_model(mid, "Old2", "both", "d2", {"a": 2})
        d = await mgr.get_potential_model(mid)
        assert d["name"] == "Old2"
        assert d["risk_preset"] == {"risk_pct": 0.5}
        assert d["strategy"] == {"notes": "keep me"}
    finally:
        await mgr._conn.close()


# ── Imported runs: create/list wrappers + the 1.8 filter ─────────────────────

@pytest.mark.asyncio
async def test_create_and_list_model_backtests(tmp_path):
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        sid = await mgr.create_model_backtest(mid, "multicharts", _NORMALIZED)

        runs = await mgr.list_model_backtests(mid)
        assert len(runs) == 1
        run = runs[0]
        assert run["id"] == sid
        assert run["status"] == "completed"
        assert run["source_app"] == "multicharts"
        assert run["type"] == "imported"
        assert run["date_from"] == "2026-01-01" and run["date_to"] == "2026-02-01"
        assert run["summary"]["net_profit"] == 1234.5
        assert run["summary"]["max_drawdown_pct"] == 0.05

        trades = await mgr.get_backtest_trades(sid)
        assert len(trades) == 2
        assert {t["exit_reason"] for t in trades} == {"take_profit", "stop_loss"}
        equity = await mgr.get_backtest_equity(sid)
        assert len(equity) == 2

        # Engine-run session (old call shape) stays model-less.
        eng_sid = await mgr.create_backtest_session(
            "engine run", "macro", "2026-01-01", "2026-02-01", {}
        )
        eng = await mgr.get_backtest_session(eng_sid)
        assert eng["model_id"] is None
        assert eng["source_app"] == ""
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_create_model_backtest_failure_leaves_no_phantom_session(tmp_path):
    """Audit fold (P1 audit finding 4): a mid-import failure must not
    leave a committed 'running' session with model_id set — the wrapper
    deletes the session and re-raises."""
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        bad = dict(_NORMALIZED)
        bad["equity_curve"] = [{"dt": "2026-01-02"}]  # missing equity/drawdown
        with pytest.raises(KeyError):
            await mgr.create_model_backtest(mid, "multicharts", bad)
        assert await mgr.list_model_backtests(mid) == []
        async with mgr._conn.execute(
            "SELECT COUNT(*) FROM backtest_sessions"
        ) as cur:
            assert (await cur.fetchone())[0] == 0
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_create_model_backtest_empty_trades_and_equity_ok(tmp_path):
    """Sparse adapter output (tolerance contract): empty trades/equity
    still yields a completed session."""
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        sparse = {"session_name": "sparse", "summary": {"net_profit": 0.0},
                  "trades": [], "equity_curve": []}
        sid = await mgr.create_model_backtest(mid, "multicharts", sparse)
        runs = await mgr.list_model_backtests(mid)
        assert len(runs) == 1 and runs[0]["status"] == "completed"
        assert await mgr.get_backtest_trades(sid) == []
        assert await mgr.get_backtest_equity(sid) == []
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_list_model_backtests_newest_first(tmp_path):
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        sid1 = await mgr.create_model_backtest(mid, "multicharts", _NORMALIZED)
        sid2 = await mgr.create_model_backtest(mid, "multicharts", _NORMALIZED)
        runs = await mgr.list_model_backtests(mid)
        assert [r["id"] for r in runs] == [sid2, sid1]
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_backtest_tab_filter_excludes_imported_runs(tmp_path):
    """Task 1.8: list_backtest_sessions must not surface imported model
    runs (the Backtest tab's templates read keys imported runs don't
    carry); list_model_backtests is their only listing surface."""
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        imported_sid = await mgr.create_model_backtest(mid, "multicharts", _NORMALIZED)
        engine_sid = await mgr.create_backtest_session(
            "engine run", "macro", "2026-01-01", "2026-02-01", {}
        )

        listed_ids = {s["id"] for s in await mgr.list_backtest_sessions()}
        assert engine_sid in listed_ids
        assert imported_sid not in listed_ids

        model_ids = {s["id"] for s in await mgr.list_model_backtests(mid)}
        assert model_ids == {imported_sid}
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_delete_model_cascades_imported_runs_only(tmp_path):
    """Task 1.6: deleting a model removes its sessions; ON DELETE CASCADE
    (foreign_keys=ON on this conn) clears trades + equity. Engine
    sessions (model_id NULL) survive."""
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        sid = await mgr.create_model_backtest(mid, "multicharts", _NORMALIZED)
        eng_sid = await mgr.create_backtest_session(
            "engine run", "macro", "", "", {}
        )

        await mgr.delete_potential_model(mid)

        assert await mgr.get_potential_model(mid) is None
        assert await mgr.get_backtest_session(sid) is None
        assert await mgr.get_backtest_trades(sid) == []
        assert await mgr.get_backtest_equity(sid) == []
        assert (await mgr.get_backtest_session(eng_sid)) is not None
    finally:
        await mgr._conn.close()


# ── get_model_for_calc: hit / miss / dangling ───────────────────────────────

@pytest.mark.asyncio
async def test_get_model_for_calc_hit_miss_and_dangling(tmp_path):
    mgr = await _make_init_db(tmp_path)
    try:
        mid = await mgr.create_potential_model("M1", "micro", "", {})
        await mgr._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, calc_id, model_id) "
            "VALUES (?, ?, ?, ?)",
            ("2026-07-16T00:00:00", "BTCUSDT", "calc-hit", mid),
        )
        await mgr._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, calc_id) "
            "VALUES (?, ?, ?)",
            ("2026-07-16T00:00:01", "BTCUSDT", "calc-untagged"),
        )
        await mgr._conn.commit()

        hit = await mgr.get_model_for_calc("calc-hit")
        assert hit == {"model_id": mid, "name": "M1"}

        assert await mgr.get_model_for_calc("calc-untagged") is None
        assert await mgr.get_model_for_calc("calc-unknown") is None
        assert await mgr.get_model_for_calc("") is None

        # Dangling by design: model deleted, the id survives on the row.
        await mgr.delete_potential_model(mid)
        dangling = await mgr.get_model_for_calc("calc-hit")
        assert dangling == {"model_id": mid, "name": "(deleted model)"}
    finally:
        await mgr._conn.close()


# ── Dual-track .sql pair (task 1.9) ─────────────────────────────────────────

def _legacy_global_db(path):
    """global.db shaped like a pre-v2.7 split DB (old column sets)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE potential_models ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " name TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'both',"
        " description TEXT NOT NULL DEFAULT '',"
        " config_json TEXT NOT NULL DEFAULT '{}')"
    )
    conn.execute(
        "CREATE TABLE backtest_sessions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " name TEXT NOT NULL DEFAULT '', type TEXT NOT NULL DEFAULT 'macro',"
        " status TEXT NOT NULL DEFAULT 'pending',"
        " date_from TEXT NOT NULL DEFAULT '', date_to TEXT NOT NULL DEFAULT '',"
        " config_json TEXT NOT NULL DEFAULT '{}',"
        " summary_json TEXT NOT NULL DEFAULT '{}')"
    )
    conn.commit()
    conn.close()


def _legacy_per_account_db(path):
    """per-account DB shaped pre-v2.7 (pre_trade_log without model_id)."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE pre_trade_log ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " timestamp TEXT NOT NULL, ticker TEXT NOT NULL, calc_id TEXT)"
    )
    conn.commit()
    conn.close()


def _cols(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        conn.close()


def test_migration_013_global_applies_once(tmp_path):
    migs = {m.name: m for m in discover()}
    m = migs["013_v2_7_model_library_global"]
    assert m.scope == "global"

    db_path = str(tmp_path / "global.db")
    _legacy_global_db(db_path)

    assert apply_one(db_path, m) is True
    for col in ("risk_preset_json", "strategy_json", "updated_at"):
        assert col in _cols(db_path, "potential_models")
    for col in ("model_id", "source_app"):
        assert col in _cols(db_path, "backtest_sessions")
    conn = sqlite3.connect(db_path)
    try:
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_bt_sessions_model'"
        ).fetchone()
        assert idx is not None
    finally:
        conn.close()

    # Recorded in migrations_log → second apply is a skip, not a re-run.
    assert apply_one(db_path, m) is False


def test_migration_014_per_account_applies_once(tmp_path):
    migs = {m.name: m for m in discover()}
    m = migs["014_v2_7_model_library_per_account"]
    assert m.scope == "per_account"

    db_path = str(tmp_path / "acct.db")
    _legacy_per_account_db(db_path)

    assert apply_one(db_path, m) is True
    assert "model_id" in _cols(db_path, "pre_trade_log")
    assert apply_one(db_path, m) is False
