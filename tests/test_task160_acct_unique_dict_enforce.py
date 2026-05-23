"""
Task 160 regression tests — two fix-before-regime correctness items.

Fix 1: MED-024 — accounts UNIQUE constraint on (exchange, broker_account_id).
  Mechanism: find_by_broker_id scans all accounts irrespective of exchange
  and returns the first match. Without UNIQUE, two accounts with the
  same broker_account_id on the same exchange → Quantower fills route
  non-deterministically → fills land on wrong account_id silently
  (unrecoverable after the fact). UNIQUE is partial: (exchange,
  broker_account_id) WHERE broker_account_id IS NOT NULL AND != '' so
  unset accounts don't trip it.

  Duplicate handling: pre-check in DatabaseManager.initialize() raises
  RuntimeError with offending rows listed. Never silently dedupe (the
  data is unrecoverable-sensitive). Standalone migration file
  012_v2_5_accounts_broker_unique.sql for split-DB setups.

Fix 2: calc-dict size enforcement (MED-019 consistency follow-up to T159).
  Mechanism: T159 zeroed size only at template data-* attrs — downstream
  consumers (regime leaderboard, T157 pre_trade_log regime row, API,
  logs) still saw the breaching size in the calc dict. Move enforcement
  to the source.

  Implementation: in run_risk_calculator, compute final_eligible once;
  snapshot size/est_size into would_be_size/would_be_notional; zero
  size+est_size if not final_eligible. Return dict carries both.
  Template simplified — drops redundant `if c.eligible else 0`
  ternaries (dict is source of truth).

  Deviation: spec said "every ineligible path → size=0 + would_be_size=
  <computed>." Sizing-stage rejects (engine-not-ready, capability gate,
  invalid SL, too_volatile, MED-016 slippage>=1) had calculate_position_size
  return size=0 already → would_be_size also = 0 there (no useful
  "would have been" value to surface; nothing was computable). Portfolio-
  stage rejects (at_max_positions / at_max_exposure / exceeds_corr) had
  size > 0 → would_be_size carries the genuine "what would have been"
  value. Documented per T155 deviation discipline.

Run: pytest tests/test_task160_acct_unique_dict_enforce.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fix 1: MED-024 UNIQUE on (exchange, broker_account_id) ──────────────────


@pytest_asyncio.fixture
async def test_db():
    """Temp file-backed DatabaseManager fixture (mirrors test_database.py)."""
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


class TestMed024UniqueIndexPresent:
    """Fresh DB after initialize() has the partial UNIQUE index installed."""

    @pytest.mark.asyncio
    async def test_unique_index_exists(self, test_db):
        async with test_db._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND name = 'idx_accounts_broker_unique'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, (
            "MED-024 regression: idx_accounts_broker_unique not installed "
            "by DatabaseManager.initialize()."
        )

    @pytest.mark.asyncio
    async def test_unique_index_is_partial(self, test_db):
        """Partial WHERE clause is load-bearing — without it, multiple
        accounts with broker_account_id='' would trip UNIQUE."""
        async with test_db._conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE name = 'idx_accounts_broker_unique'"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        sql = row[0]
        assert "WHERE" in sql, (
            "MED-024 regression: index is unconditional UNIQUE — "
            "empty-string broker_account_id rows would conflict."
        )
        assert "broker_account_id IS NOT NULL" in sql
        assert "broker_account_id != ''" in sql

    @pytest.mark.asyncio
    async def test_duplicate_on_same_exchange_rejected(self, test_db):
        """Dangerous-path: try to insert two accounts with same
        broker_account_id on the same exchange. Second insert must fail."""
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, ?)",
            ("A", "binance", "12345"),
        )
        await test_db._conn.commit()
        # Second insert with same (exchange, broker_account_id) → IntegrityError
        with pytest.raises(sqlite3.IntegrityError, match=r"UNIQUE"):
            await test_db._conn.execute(
                "INSERT INTO accounts (name, exchange, broker_account_id) "
                "VALUES (?, ?, ?)",
                ("B", "binance", "12345"),
            )
            await test_db._conn.commit()

    @pytest.mark.asyncio
    async def test_same_broker_id_different_exchange_ok(self, test_db):
        """Cross-exchange duplicate is legitimate — Binance #12345 and
        Bybit #12345 are different real-world accounts."""
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, ?)",
            ("A", "binance", "12345"),
        )
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, ?)",
            ("B", "bybit", "12345"),
        )
        await test_db._conn.commit()
        async with test_db._conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE broker_account_id = '12345'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == 2

    @pytest.mark.asyncio
    async def test_multiple_unset_broker_ids_allowed(self, test_db):
        """Partial WHERE — unset (NULL or '') rows don't trip the
        constraint. Operator may have many accounts without broker
        linkage yet."""
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, NULL)", ("A", "binance"),
        )
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, NULL)", ("B", "binance"),
        )
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, '')", ("C", "binance"),
        )
        await test_db._conn.execute(
            "INSERT INTO accounts (name, exchange, broker_account_id) "
            "VALUES (?, ?, '')", ("D", "binance"),
        )
        await test_db._conn.commit()


class TestMed024DuplicatePreCheckFailsLoud:
    """When duplicates exist BEFORE the index install fires, the inline
    initialize() pre-check raises with the offending rows listed —
    never silently dedupe."""

    @pytest.mark.asyncio
    async def test_initialize_raises_on_preexisting_duplicates(self):
        """Construct a DB that has the accounts table + duplicate rows,
        then call initialize() — must raise RuntimeError listing the
        duplicate tuple. Never silently drop or merge rows."""
        from core.database import DatabaseManager

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            # Bootstrap: open raw sqlite3, create accounts table with
            # duplicate broker_account_id rows BEFORE the UNIQUE index
            # would land.
            raw = sqlite3.connect(tmp.name)
            raw.execute("""
                CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT 'binance',
                    market_type TEXT NOT NULL DEFAULT 'future',
                    api_key_enc TEXT NOT NULL DEFAULT '',
                    api_secret_enc TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    broker_account_id TEXT,
                    link_window_seconds INTEGER NOT NULL DEFAULT 21600
                )
            """)
            raw.execute(
                "INSERT INTO accounts (name, exchange, broker_account_id) "
                "VALUES (?, ?, ?)", ("A", "binance", "DUP123"),
            )
            raw.execute(
                "INSERT INTO accounts (name, exchange, broker_account_id) "
                "VALUES (?, ?, ?)", ("B", "binance", "DUP123"),
            )
            raw.commit()
            raw.close()

            db = DatabaseManager(path=tmp.name)
            with pytest.raises(RuntimeError, match=r"MED-024.*duplicate"):
                await db.initialize()
            # Don't close() — initialize raised, may not have set _conn fully
        finally:
            try:
                os.unlink(tmp.name)
                for ext in ("-wal", "-shm"):
                    p = tmp.name + ext
                    if os.path.exists(p):
                        os.unlink(p)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_error_message_lists_offending_rows(self):
        """Pre-check error must name the offending (exchange, broker_id)
        tuple so the operator knows which rows to resolve."""
        from core.database import DatabaseManager

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            raw = sqlite3.connect(tmp.name)
            raw.execute("""
                CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT 'binance',
                    market_type TEXT NOT NULL DEFAULT 'future',
                    api_key_enc TEXT NOT NULL DEFAULT '',
                    api_secret_enc TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    broker_account_id TEXT,
                    link_window_seconds INTEGER NOT NULL DEFAULT 21600
                )
            """)
            raw.execute(
                "INSERT INTO accounts (name, exchange, broker_account_id) "
                "VALUES (?, ?, ?)", ("A", "binance", "SAME_KEY"),
            )
            raw.execute(
                "INSERT INTO accounts (name, exchange, broker_account_id) "
                "VALUES (?, ?, ?)", ("B", "binance", "SAME_KEY"),
            )
            raw.commit()
            raw.close()

            db = DatabaseManager(path=tmp.name)
            with pytest.raises(RuntimeError) as exc:
                await db.initialize()
            msg = str(exc.value)
            # Offending tuple + the resolution hint must both be present
            assert "binance" in msg
            assert "SAME_KEY" in msg
            assert "resol" in msg.lower() or "config ui" in msg.lower()
        finally:
            try:
                os.unlink(tmp.name)
                for ext in ("-wal", "-shm"):
                    p = tmp.name + ext
                    if os.path.exists(p):
                        os.unlink(p)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_clean_db_migrates_without_error(self, test_db):
        """Single-account install (default case) has no duplicates →
        initialize() succeeds. test_db fixture itself proves this; the
        explicit assertion makes it un-skippable."""
        async with test_db._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE name = 'idx_accounts_broker_unique'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == 1, (
            "MED-024 regression: clean DB didn't get the UNIQUE index"
        )


class TestMed024MigrationFiles:
    """Belt-and-suspenders: standalone migration file + CREATE INDEX in
    canonical schema + inline pre-check all present."""

    def test_standalone_migration_present_and_headered(self):
        p = Path("core/migrations/012_v2_5_accounts_broker_unique.sql")
        assert p.exists()
        src = p.read_text(encoding="utf-8")
        assert "-- migration: global" in src
        assert "-- name: 012_v2_5_accounts_broker_unique" in src
        assert "CREATE UNIQUE INDEX" in src
        assert "WHERE" in src  # partial index

    def test_canonical_schema_has_create_index(self):
        src = Path("core/database.py").read_text(encoding="utf-8")
        # CREATE UNIQUE INDEX inside _CREATE_STATEMENTS
        assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_broker_unique" in src
        # In two places: the canonical schema (CREATE TABLE block) AND the
        # initialize() inline path (which actually fires the duplicate
        # pre-check)
        count = src.count("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_broker_unique")
        assert count >= 2, (
            f"MED-024 regression: index DDL appears {count}× — expected "
            "≥2 (canonical schema + inline initialize() path)"
        )

    def test_inline_path_has_duplicate_pre_check(self):
        src = Path("core/database.py").read_text(encoding="utf-8")
        # The pre-check raises RuntimeError with "MED-024" prefix
        assert "MED-024 migration aborted" in src, (
            "MED-024 regression: inline duplicate pre-check missing — "
            "split-DB error message would be the generic sqlite3.IntegrityError"
        )


# ── Fix 2: calc-dict size enforcement ──────────────────────────────────────


class TestDictSizeEnforcement:
    """Every ineligible path zeros size + notional in the dict; would_be_*
    carries the computed values for forensic display."""

    @pytest.fixture
    def stub_app_state(self, monkeypatch):
        """Stub app_state enough to run run_risk_calculator without a real
        engine + db setup."""
        from core.state import app_state
        from core import monitoring

        # Engine-ready gate bypass
        monkeypatch.setattr(
            monitoring, "ReadyStateEvaluator",
            lambda: type("R", (), {"evaluate": lambda s: (True, "")})(),
            raising=False,
        )
        # exchange_info stub for fee_rate access
        from types import SimpleNamespace
        monkeypatch.setattr(app_state, "exchange_info",
                            SimpleNamespace(maker_fee=0.0002, taker_fee=0.0005),
                            raising=False)
        # ws_status / data_cache stubs (equity_stale path)
        monkeypatch.setattr(app_state, "ws_status",
                            SimpleNamespace(is_stale=False), raising=False)
        # Account state with adequate equity
        monkeypatch.setattr(app_state, "account_state",
                            SimpleNamespace(total_equity=10000.0), raising=False)
        # Portfolio state
        monkeypatch.setattr(app_state, "portfolio",
                            SimpleNamespace(weekly_pnl_state="ok", dd_state="ok"),
                            raising=False)
        # Risk params
        params = dict(getattr(app_state, "params", {}))
        params.update({
            "individual_risk_per_trade": 0.01,
            "max_position_count": 10,
            "max_exposure": 5.0,
            # Generous correlated cap so the synthetic single-position
            # eligible-baseline test doesn't trip exceeds_corr_limit
            # (BTC trade at $4000 notional vs equity $10000 = 40% → use
            # 5.0× cap so eligible baseline is reachable).
            "max_correlated_exposure": 5.0,
        })
        monkeypatch.setattr(app_state, "params", params, raising=False)
        # Orderbook: clean fill (low slippage so MED-016 doesn't fire)
        monkeypatch.setattr(app_state, "orderbook_cache",
                            {"BTCUSDT": {"bids": [[80000.0, 10.0]],
                                          "asks": [[80000.0, 10.0]]}},
                            raising=False)
        # positions is a property with DataCache-backed getter when
        # _data_cache is set. Clear _data_cache so the legacy-list getter
        # path is used — monkeypatch writes via setter into
        # _positions_legacy, but the getter would otherwise return
        # _data_cache.positions regardless. Without this, prior tests
        # in the full suite leave _data_cache populated and our position
        # overrides silently no-op in the getter.
        monkeypatch.setattr(app_state, "_data_cache", None, raising=False)
        monkeypatch.setattr(app_state, "_positions_legacy", [], raising=False)
        # OHLCV stub for ATR
        monkeypatch.setattr(app_state, "ohlcv_cache", {}, raising=False)
        # Regime state
        monkeypatch.setattr(app_state, "current_regime", None, raising=False)
        # active_account_id is a read-only @property; do not monkeypatch.
        # is_initializing
        monkeypatch.setattr(app_state, "is_initializing", False, raising=False)

        from core import risk_engine
        monkeypatch.setattr(
            risk_engine, "calculate_atr_coefficient",
            lambda symbol: (0.5, "normal", 100.0, 200.0),
        )
        return app_state

    def test_at_max_positions_zeros_size_keeps_would_be(self, stub_app_state, monkeypatch):
        """Portfolio-stage reject: positions == max → size=0 in dict;
        would_be_size carries the computed value > 0."""
        from core import risk_engine
        from types import SimpleNamespace

        # 10 fake positions to hit at_max_positions. Write via
        # _positions_legacy because property setter writes there and
        # _data_cache is None (cleared in stub_app_state).
        fake_positions = [
            SimpleNamespace(
                position_value_usdt=100.0,
                direction="LONG",
                sector="big_two_crypto",
            )
            for _ in range(10)
        ]
        monkeypatch.setattr(
            risk_engine.app_state, "_positions_legacy", fake_positions, raising=False,
        )

        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["eligible"] is False
        assert result["at_max_positions"] is True
        # Dict size + notional zeroed
        assert result["size"] == 0.0, (
            f"Dict size not zeroed on at_max_positions; got {result['size']}"
        )
        assert result["notional"] == 0.0
        # would_be_* carries genuine computed value
        assert result["would_be_size"] > 0, (
            f"would_be_size lost — should carry pre-zero computed value; "
            f"got {result['would_be_size']}"
        )
        assert result["would_be_notional"] > 0

    def test_eligible_calc_size_equals_would_be(self, stub_app_state):
        """Anti-regression: when calc IS eligible, size == would_be_size
        (no spurious zeroing)."""
        from core import risk_engine

        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["eligible"] is True
        assert result["size"] == result["would_be_size"]
        assert result["notional"] == result["would_be_notional"]
        assert result["size"] > 0  # sanity: actual calc produced size

    def test_at_max_exposure_zeros_size(self, stub_app_state, monkeypatch):
        """Portfolio-stage reject via exposure cap."""
        from core import risk_engine
        from types import SimpleNamespace

        # One big position that pushes exposure past 5.0× equity
        # (equity 10000, position_value 60000 → exposure 6.0×).
        # Write via _positions_legacy (see stub_app_state notes).
        monkeypatch.setattr(
            risk_engine.app_state, "_positions_legacy",
            [SimpleNamespace(position_value_usdt=60000.0, direction="LONG",
                              sector="big_two_crypto")],
            raising=False,
        )

        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=79000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["at_max_exposure"] is True
        assert result["eligible"] is False
        assert result["size"] == 0.0
        assert result["notional"] == 0.0
        assert result["would_be_size"] > 0

    def test_sizing_stage_reject_size_and_would_be_both_zero(
        self, stub_app_state, monkeypatch,
    ):
        """Sizing-stage reject (e.g., SL == entry → "zero risk distance"):
        size=0 AND would_be_size=0 because calculate_position_size returned
        early with size=0 — no computation was possible. Documents the
        deviation noted in the task spec."""
        from core import risk_engine

        # SL == entry triggers the "Invalid entry or SL price" path
        # (actually that's the avg/sl<=0 branch). Use sl_pct=0 instead:
        # sl_price == average.
        result = risk_engine.run_risk_calculator(
            ticker="BTCUSDT", average=80000.0, sl_price=80000.0,
            tp_price=82000.0, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert result["eligible"] is False
        assert "zero risk distance" in result["ineligible_reason"].lower() or (
            "invalid" in result["ineligible_reason"].lower()
        )
        # Both zero for sizing-stage rejects — nothing to surface as
        # "would have been"
        assert result["size"] == 0.0
        assert result["would_be_size"] == 0.0


class TestDictEnforcementSourcePins:
    """Source-pin the load-bearing implementation lines so they can't
    silently revert."""

    def test_risk_engine_has_final_eligible_hoist(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "final_eligible = (" in src, (
            "Task 160 regression: final_eligible hoist removed — return-"
            "dict branch and size-zero branch may go out of sync."
        )

    def test_risk_engine_zeros_size_on_ineligible(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # The load-bearing zeroing
        assert "if not final_eligible:" in src
        # Both fields zeroed
        # (match exact lines so a partial revert is caught)
        idx = src.find("if not final_eligible:")
        block = src[idx:idx + 200]
        assert "size = 0.0" in block
        assert "est_size = 0.0" in block

    def test_risk_engine_snapshots_would_be_before_zero(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        # Pattern: would_be_size = size assigned BEFORE the zeroing branch
        assert "would_be_size     = size" in src or "would_be_size = size" in src
        assert "would_be_notional = est_size" in src or "would_be_notional=est_size" in src

    def test_return_dict_includes_would_be_fields(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert '"would_be_size":' in src
        assert '"would_be_notional":' in src

    def test_template_drops_redundant_per_attr_ternaries(self):
        src = Path("templates/fragments/calc_result.html").read_text(
            encoding="utf-8"
        )
        # Pre-T160 ternaries:
        #   data-notional="{{ (c.notional|round(2)) if c.eligible else 0 }}"
        #   data-contracts="{{ (c.size|round(4)) if c.eligible else 0 }}"
        # Post-T160 simplified — dict is the source of truth.
        assert "(c.notional|round(2)) if c.eligible else 0" not in src
        assert "(c.size|round(4)) if c.eligible else 0" not in src
        # New direct reads
        assert 'data-notional="{{ c.notional|round(2) }}"' in src
        assert 'data-contracts="{{ c.size|round(4) }}"' in src

    def test_template_exposes_would_be_attrs(self):
        src = Path("templates/fragments/calc_result.html").read_text(
            encoding="utf-8"
        )
        assert "data-would-be-notional" in src
        assert "data-would-be-contracts" in src


class TestT159AntiRegression:
    """T159's data-eligible attr + ineligible_reason population must
    still hold post-T160."""

    def test_data_eligible_attr_still_present(self):
        src = Path("templates/fragments/calc_result.html").read_text(
            encoding="utf-8"
        )
        assert "data-eligible=" in src

    def test_t159_ineligible_reason_population_intact(self):
        """portfolio_reason + final_reason from T159 still wired."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "portfolio_reason" in src
        assert "final_reason = sizing.get" in src

    def test_t159_med016_slippage_gate_intact(self):
        """MED-016 slippage gate from T159 still fires."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "est_slippage >= 1.0" in src
        assert "Task 159 (MED-016)" in src
