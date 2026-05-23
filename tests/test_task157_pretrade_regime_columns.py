"""
Task 157 regression tests — per-trade regime decision logging.

Background (T156 investigation):
  The engine computes `regime_label` / `regime_multiplier` /
  `apply_regime_multiplier` / `regime_mode` in `risk_engine.run_risk_
  calculator()` (~line 472-475 + 478) but `insert_pre_trade_log` never
  persisted them. The live engine's exact sizing decision was
  unrecoverable to "what label / multiplier did the engine actually
  apply at trade time?" fidelity for the live-classification fallback
  path (T156 caveat d: `compute_current_regime()`'s fallback returns a
  `RegimeState` but does NOT write `regime_labels`).

T157 fix:
  - Migration 011 + inline shadow-migration + CREATE TABLE addition add
    4 nullable columns to pre_trade_log: regime_label, regime_multiplier,
    regime_mode, apply_regime_multiplier.
  - risk_engine emits regime_mode in the calc dict (threaded from
    `RegimeState.mode`).
  - insert_pre_trade_log persists all four. NULL defaults — distinguishes
    pre-T157 rows (and rows where the caller doesn't supply regime
    fields, e.g. backtest harness) from rows where regime ran and was
    recorded.

What this file pins:
  - Schema: pre_trade_log has the 4 new columns after `initialize()`.
  - Write-path: insert_pre_trade_log persists supplied regime fields
    verbatim.
  - apply_regime_multiplier coerces True/False/None → 1/0/NULL.
  - Toggle-OFF case: multiplier=1.0 + apply=0 is stored (and is
    distinguishable from "regime computed x1 + applied" which would be
    multiplier=1.0 + apply=1).
  - Missing-fields case: calc dict without any regime keys → all four
    columns NULL, no crash.
  - risk_engine emits `regime_mode` in the calc dict (source pin).
  - Migration file present + correctly headered.

Run: pytest tests/test_task157_pretrade_regime_columns.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def test_db():
    """Temp file-backed DatabaseManager — mirrors tests/test_database.py."""
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


# ── Schema pins ─────────────────────────────────────────────────────────────


class TestSchema:
    """The 4 new columns must exist after `initialize()` — covers both
    fresh-install (CREATE TABLE path) and upgrade (shadow ALTER path)
    via the same exit state."""

    @pytest.mark.asyncio
    async def test_regime_columns_present(self, test_db):
        async with test_db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        for col in ("regime_label", "regime_multiplier",
                    "regime_mode", "apply_regime_multiplier"):
            assert col in cols, (
                f"Task 157 regression: pre_trade_log missing column "
                f"{col!r} after initialize()."
            )

    @pytest.mark.asyncio
    async def test_regime_columns_nullable_with_null_default(self, test_db):
        """Default must be NULL, NOT 1.0 — see migration anchor. A 1.0
        default would conflate "pre-T157, unknown" with "toggle OFF,
        used x1" downstream."""
        async with test_db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            info = {row[1]: row for row in await cur.fetchall()}
        for col in ("regime_label", "regime_multiplier",
                    "regime_mode", "apply_regime_multiplier"):
            row = info[col]
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            notnull, dflt = row[3], row[4]
            assert notnull == 0, (
                f"Task 157 regression: {col} declared NOT NULL — "
                "must be nullable so pre-T157 rows can carry NULL."
            )
            assert dflt is None, (
                f"Task 157 regression: {col} has non-NULL default "
                f"{dflt!r} — must default NULL. A 1.0 / 'neutral' "
                "default would falsely read as 'regime ran and chose "
                "x1' for pre-T157 rows in forward analytics."
            )

    @pytest.mark.asyncio
    async def test_insert_with_only_legacy_columns_writes_null_regime(self, test_db):
        """Anti-regression: raw INSERT of pre-T157 column subset still
        works; the regime columns silently land as NULL. Pins backward
        compatibility for any insert path that hasn't been threaded yet
        (e.g. tests, ad-hoc tooling)."""
        await test_db._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker) VALUES (?, ?)",
            ("2026-05-23T00:00:00", "BTCUSDT"),
        )
        await test_db._conn.commit()
        async with test_db._conn.execute(
            "SELECT regime_label, regime_multiplier, regime_mode, "
            "apply_regime_multiplier FROM pre_trade_log WHERE ticker = 'BTCUSDT'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None
        assert row[3] is None


# ── insert_pre_trade_log write-path pins ───────────────────────────────────


def _minimal_calc(**overrides) -> dict:
    """Build a minimal calc dict matching risk_engine's emitted shape.
    Only the regime-relevant + identification fields are filled — every
    other field will land at insert_pre_trade_log's `.get(k, default)`
    default. Override via kwargs."""
    base = {
        "ticker": "BTCUSDT",
        "average": 80000.0,
        "side": "long",
        "size": 0.01,
        "notional": 800.0,
        "tp_price": 82000.0,
        "sl_price": 79000.0,
        "eligible": True,
        "calc_id": "task157-calc-1",
    }
    base.update(overrides)
    return base


class TestInsertWritePath:
    """Drives insert_pre_trade_log with various calc-dict shapes and
    confirms what lands in the 4 new columns."""

    @pytest.mark.asyncio
    async def test_full_regime_payload_persists(self, test_db):
        """Toggle ON + non-neutral regime → all 4 columns populated."""
        calc = _minimal_calc(
            calc_id="task157-full",
            regime_label="risk_off_defensive",
            regime_multiplier=0.7,
            regime_mode="full",
            apply_regime_multiplier=True,
        )
        await test_db.insert_pre_trade_log(calc)

        async with test_db._conn.execute(
            "SELECT regime_label, regime_multiplier, regime_mode, "
            "apply_regime_multiplier FROM pre_trade_log "
            "WHERE calc_id = 'task157-full'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == "risk_off_defensive"
        assert row[1] == pytest.approx(0.7)
        assert row[2] == "full"
        assert row[3] == 1

    @pytest.mark.asyncio
    async def test_toggle_off_distinguishable_from_applied_1x(self, test_db):
        """Operator toggled regime OFF. risk_engine forces
        multiplier=1.0 (post-toggle), but label/mode still carry what
        the regime WOULD have said. The apply flag = 0 lets analytics
        distinguish 'computed but ignored' from 'computed and applied
        x1 because neutral'.

        This is the spec's load-bearing test: 'analytics must
        distinguish regime computed but toggle OFF (used 1x) from
        regime applied.'"""
        calc = _minimal_calc(
            calc_id="task157-toggle-off",
            regime_label="risk_off_panic",       # regime said panic
            regime_multiplier=1.0,                # but toggle forced 1.0
            regime_mode="full",
            apply_regime_multiplier=False,
        )
        await test_db.insert_pre_trade_log(calc)

        async with test_db._conn.execute(
            "SELECT regime_label, regime_multiplier, apply_regime_multiplier "
            "FROM pre_trade_log WHERE calc_id = 'task157-toggle-off'"
        ) as cur:
            toggle_off = await cur.fetchone()

        # And the "regime computed neutral, toggle ON" case for contrast
        calc2 = _minimal_calc(
            calc_id="task157-neutral-applied",
            regime_label="neutral",
            regime_multiplier=1.0,
            regime_mode="macro_only",
            apply_regime_multiplier=True,
        )
        await test_db.insert_pre_trade_log(calc2)

        async with test_db._conn.execute(
            "SELECT regime_label, regime_multiplier, apply_regime_multiplier "
            "FROM pre_trade_log WHERE calc_id = 'task157-neutral-applied'"
        ) as cur:
            neutral_applied = await cur.fetchone()

        # Both have multiplier=1.0 but the apply flag and label tell
        # the analyst what actually happened.
        assert toggle_off[1] == pytest.approx(1.0)
        assert neutral_applied[1] == pytest.approx(1.0)
        assert toggle_off[2] == 0          # toggle-OFF case
        assert neutral_applied[2] == 1     # applied-x1 case
        # Label content is itself diagnostic — toggle-off case preserves
        # what regime WOULD have said.
        assert toggle_off[0] == "risk_off_panic"
        assert neutral_applied[0] == "neutral"

    @pytest.mark.asyncio
    async def test_missing_regime_fields_persist_as_null(self, test_db):
        """Calc dict without regime keys (e.g. backtest harness path
        that builds its own dict) → all 4 columns NULL. No crash."""
        calc = _minimal_calc(calc_id="task157-no-regime")
        # Sanity: calc dict really lacks regime keys
        assert "regime_label" not in calc
        assert "apply_regime_multiplier" not in calc

        await test_db.insert_pre_trade_log(calc)

        async with test_db._conn.execute(
            "SELECT regime_label, regime_multiplier, regime_mode, "
            "apply_regime_multiplier FROM pre_trade_log "
            "WHERE calc_id = 'task157-no-regime'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None
        assert row[3] is None

    @pytest.mark.asyncio
    async def test_apply_regime_multiplier_coerces_truthiness_correctly(self, test_db):
        """Spec rule: True → 1, False → 0, None / missing → NULL.
        Bare truthy/falsy values like 0/1 ints are NOT supported — the
        engine code paths only ever pass True/False/None for this flag.
        Confirm the explicit coercion logic preserves the None
        distinction (which a `1 if X else 0` shortcut would lose)."""
        # None
        await test_db.insert_pre_trade_log(_minimal_calc(
            calc_id="task157-apply-none",
            regime_label="neutral",
            regime_multiplier=1.0,
            apply_regime_multiplier=None,
        ))
        # True
        await test_db.insert_pre_trade_log(_minimal_calc(
            calc_id="task157-apply-true",
            regime_label="neutral",
            regime_multiplier=1.0,
            apply_regime_multiplier=True,
        ))
        # False
        await test_db.insert_pre_trade_log(_minimal_calc(
            calc_id="task157-apply-false",
            regime_label="neutral",
            regime_multiplier=1.0,
            apply_regime_multiplier=False,
        ))

        async with test_db._conn.execute(
            "SELECT calc_id, apply_regime_multiplier FROM pre_trade_log "
            "WHERE calc_id LIKE 'task157-apply-%' ORDER BY calc_id"
        ) as cur:
            rows = {r[0]: r[1] for r in await cur.fetchall()}
        assert rows["task157-apply-none"] is None
        assert rows["task157-apply-true"] == 1
        assert rows["task157-apply-false"] == 0


# ── Source pins on risk_engine + migration file ────────────────────────────


class TestRiskEngineEmitsRegimeMode:
    """T156 found regime_mode was the only field missing from the calc
    dict. T157 threads it through. Source-pin: regime_mode appears in
    the calc-dict return literal."""

    def test_regime_mode_in_calc_dict(self):
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert '"regime_mode":' in src, (
            "Task 157 regression: regime_mode not emitted by "
            "run_risk_calculator(). insert_pre_trade_log will land it "
            "as NULL even when regime decision is otherwise complete."
        )

    def test_regime_mode_threaded_from_state(self):
        """The mode value must come from RegimeState.mode (or its
        fallback), not be a hardcoded literal."""
        src = Path("core/risk_engine.py").read_text(encoding="utf-8")
        assert "regime.mode" in src, (
            "Task 157 regression: regime_mode not pulled from "
            "RegimeState. A hardcoded literal would not reflect the "
            "live classifier's actual mode at decision time."
        )


class TestMigrationFile:
    """The standalone migration file must be present + correctly headered
    for the SQL runner. Belt-and-suspenders alongside the inline shadow
    migrations in DatabaseManager.initialize()."""

    def test_migration_file_present(self):
        p = Path("core/migrations/011_v2_5_pretrade_regime_columns.sql")
        assert p.exists(), (
            "Task 157 regression: standalone migration file missing. "
            "Split-DB setups (with data/.split-complete-v1 marker) rely "
            "on this file via core/migrations/runner.py."
        )

    def test_migration_file_correctly_headered(self):
        src = Path(
            "core/migrations/011_v2_5_pretrade_regime_columns.sql"
        ).read_text(encoding="utf-8")
        assert "-- migration: per_account" in src
        assert "-- name: 011_v2_5_pretrade_regime_columns" in src
        # All four ALTER lines present
        for col in ("regime_label", "regime_multiplier",
                    "regime_mode", "apply_regime_multiplier"):
            assert f"ADD COLUMN {col}" in src, (
                f"Task 157 regression: migration file missing ADD "
                f"COLUMN for {col}."
            )

    def test_inline_shadow_migrations_present(self):
        """initialize()'s inline ALTER list must also include the 4
        new columns so non-split-DB setups upgrade in-place on startup."""
        src = Path("core/database.py").read_text(encoding="utf-8")
        for col in ("regime_label", "regime_multiplier",
                    "regime_mode", "apply_regime_multiplier"):
            assert (
                f"ALTER TABLE pre_trade_log ADD COLUMN {col}" in src
            ), (
                f"Task 157 regression: inline shadow migration for "
                f"{col} missing from DatabaseManager.initialize()."
            )
