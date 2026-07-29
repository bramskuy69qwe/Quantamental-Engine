"""E2E-P7-001 pins — settings writes for accounts that have no settings row.

Found by the Phase-7 sandbox re-run: ``POST /api/config/apply-preset`` 500'd
("settings write failed: 'No account_settings row for account_id=2'") for the
seeded second account. Mechanism (two layers, both pinned here):

1. ``update_account_settings`` was UPDATE-only — it raised ``KeyError`` when
   the settings row was missing. ``add_account`` never creates the row and
   migration 001's seed is ``LIMIT 1`` (first account only), so EVERY account
   added after the initial migration had no row: preset apply 500'd loudly and
   the account-update route's settings writes no-opped silently
   (``except Exception: pass``). Now the writer creates the row with the
   table's column defaults iff the ACCOUNT exists.
2. Post-split, ``_resolve_db_path`` scanned ``per_account/*.db`` only — an
   account added after the split (legacy registry row, no per-account file;
   nothing mints one until the deferred R1b lookup) raised
   "No per-account DB found" before the writer even ran. Now it falls back to
   the legacy DB iff the account exists there; per-account resolution for
   split-era accounts is unchanged.

All fixtures are own-tmp-dir sqlite files — never the shared TestClient
(settings writers resolve the live data dir; F5).
"""
import sqlite3

import pytest

from core.db_account_settings import (
    AccountSettings,
    _resolve_db_path,
    get_account_settings,
    update_account_settings,
)

# Canonical account_settings shape = migration 004's rebuild (the shipped
# schema); the AccountSettings dataclass mirrors it field-for-field.
_SETTINGS_SCHEMA = """
CREATE TABLE account_settings (
    account_id                   INTEGER PRIMARY KEY,
    timezone                     TEXT    NOT NULL DEFAULT 'UTC',
    dd_rolling_window_days       INTEGER NOT NULL DEFAULT 30,
    dd_warning_threshold         REAL,
    dd_limit_threshold           REAL,
    dd_recovery_threshold        REAL    NOT NULL DEFAULT 0.50,
    dd_enforcement_mode          TEXT    NOT NULL DEFAULT 'advisory',
    weekly_pnl_warning_threshold REAL,
    weekly_pnl_limit_threshold   REAL,
    weekly_pnl_enforcement_mode  TEXT    NOT NULL DEFAULT 'advisory',
    strategy_preset              TEXT,
    analytics_default_period     TEXT    NOT NULL DEFAULT 'monthly',
    week_start_dow               INTEGER NOT NULL DEFAULT 1
)
"""


def _mk_db(path, account_ids, settings_ids=()):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    for aid in account_ids:
        conn.execute("INSERT INTO accounts (id, name) VALUES (?, ?)", (aid, f"acct {aid}"))
    conn.execute(_SETTINGS_SCHEMA)
    for aid in settings_ids:
        conn.execute(
            "INSERT INTO account_settings (account_id, timezone) VALUES (?, 'Asia/Jakarta')",
            (aid,),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def legacy_dir(tmp_path):
    """Pre-split shape: everything in risk_engine.db, no split marker.
    Accounts 1+2 exist; only account 1 has a settings row."""
    _mk_db(tmp_path / "risk_engine.db", account_ids=(1, 2), settings_ids=(1,))
    return str(tmp_path)


class TestUpsertOnMissingRow:
    def test_update_creates_row_with_table_defaults(self, legacy_dir):
        out = update_account_settings(2, data_dir=legacy_dir, strategy_preset="swing")
        assert out.strategy_preset == "swing"
        # Untouched fields carry the table defaults == dataclass defaults.
        assert out.timezone == "UTC"
        assert out.dd_rolling_window_days == 30
        assert out.dd_enforcement_mode == "advisory"
        assert out.dd_warning_threshold is None

    def test_apply_preset_succeeds_on_rowless_account(self, legacy_dir):
        # The exact E2E-P7-001 shape: preset apply to an account whose
        # settings row was never created.
        from core.strategy_presets import STRATEGY_PRESETS, apply_preset

        out = apply_preset(2, "swing", data_dir=legacy_dir)
        assert out.strategy_preset == "swing"
        for field, value in STRATEGY_PRESETS["swing"].items():
            assert getattr(out, field) == value

    def test_nonexistent_account_still_raises(self, legacy_dir):
        # The upsert must not mint settings for ids with no accounts row —
        # pre-split resolution never checks account existence, so the writer
        # itself carries the guard.
        with pytest.raises(KeyError):
            update_account_settings(999, data_dir=legacy_dir, strategy_preset="swing")

    def test_existing_row_not_reset(self, legacy_dir):
        # Account 1 has a customised row; a partial update must not clobber it.
        out = update_account_settings(1, data_dir=legacy_dir, strategy_preset="swing")
        assert out.strategy_preset == "swing"
        assert out.timezone == "Asia/Jakarta"


class TestPostSplitLegacyFallback:
    @pytest.fixture
    def split_dir(self, tmp_path, monkeypatch):
        """Post-split shape: per-account DB carries account 1 only; account 2
        exists in the legacy registry only (the added-after-split shape)."""
        (tmp_path / ".split-complete-v1").write_text("test")
        _mk_db(tmp_path / "risk_engine.db", account_ids=(1, 2), settings_ids=(1,))
        pa = tmp_path / "per_account"
        pa.mkdir()
        _mk_db(pa / "t__b__x.db", account_ids=(1,), settings_ids=(1,))
        # split_done() reads the LIVE data dir — pin it True so the split
        # branch runs regardless of which tree hosts the suite.
        monkeypatch.setattr("core.db_account_settings.split_done", lambda: True)
        return str(tmp_path)

    def test_split_era_account_still_resolves_per_account(self, split_dir):
        assert _resolve_db_path(1, split_dir).endswith("t__b__x.db")

    def test_added_after_split_falls_back_to_legacy(self, split_dir):
        assert _resolve_db_path(2, split_dir).endswith("risk_engine.db")

    def test_write_lands_in_legacy_and_reads_back(self, split_dir):
        out = update_account_settings(2, data_dir=split_dir, strategy_preset="swing")
        assert out.strategy_preset == "swing"
        conn = sqlite3.connect(split_dir + "/risk_engine.db")
        row = conn.execute(
            "SELECT strategy_preset FROM account_settings WHERE account_id = 2"
        ).fetchone()
        conn.close()
        assert row == ("swing",)
        # Read path resolves identically (symmetry is the fallback's contract).
        assert get_account_settings(2, data_dir=split_dir).strategy_preset == "swing"

    def test_account_in_no_store_still_raises(self, split_dir):
        with pytest.raises(KeyError):
            _resolve_db_path(999, split_dir)


class TestDataclassMirrorsTableDefaults:
    def test_bare_insert_equals_dataclass_defaults(self, tmp_path):
        # The upsert's correctness rests on this equivalence — pin it.
        db = tmp_path / "x.db"
        conn = sqlite3.connect(db)
        conn.execute(_SETTINGS_SCHEMA)
        conn.execute("INSERT INTO account_settings (account_id) VALUES (7)")
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM account_settings WHERE account_id = 7").fetchone()
        conn.close()
        assert AccountSettings(**dict(row)) == AccountSettings(account_id=7)
