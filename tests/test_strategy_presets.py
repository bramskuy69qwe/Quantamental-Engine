"""Tests for core.strategy_presets — preset application + validation."""
import os
import sqlite3

import pytest

from core.strategy_presets import STRATEGY_PRESETS, apply_preset
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1):
    """Data dir with split marker + per-account DB with all migrations applied."""
    data = tmp_path / "data"
    data.mkdir()
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir()
    db_path = str(pa / "test__broker__1.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)
    return str(data)


class TestApplyPreset:
    @pytest.mark.parametrize("name", ["scalping", "day_trading", "swing", "position"])
    def test_preset_applies_expected_values(self, tmp_path, name):
        data_dir = _make_env(tmp_path)
        s = apply_preset(1, name, data_dir=data_dir)
        expected = STRATEGY_PRESETS[name]
        assert s.strategy_preset == name
        assert s.dd_rolling_window_days == expected["dd_rolling_window_days"]
        assert s.dd_warning_threshold == pytest.approx(expected["dd_warning_threshold"])
        assert s.dd_limit_threshold == pytest.approx(expected["dd_limit_threshold"])
        assert s.dd_recovery_threshold == pytest.approx(expected["dd_recovery_threshold"])
        assert s.analytics_default_period == expected["analytics_default_period"]

    def test_custom_is_noop(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = apply_preset(1, "custom", data_dir=data_dir)
        assert s.strategy_preset == "custom"
        # Default values unchanged
        assert s.dd_rolling_window_days == 30  # migration default
        assert s.analytics_default_period == "monthly"

    def test_unknown_preset_raises(self, tmp_path):
        data_dir = _make_env(tmp_path)
        with pytest.raises(ValueError, match="Unknown preset"):
            apply_preset(1, "nonexistent", data_dir=data_dir)

    def test_preset_preserves_timezone(self, tmp_path):
        data_dir = _make_env(tmp_path)
        from core.db_account_settings import update_account_settings
        update_account_settings(1, data_dir=data_dir, timezone="Asia/Bangkok")
        s = apply_preset(1, "scalping", data_dir=data_dir)
        assert s.timezone == "Asia/Bangkok"

    def test_preset_overwritable(self, tmp_path):
        data_dir = _make_env(tmp_path)
        apply_preset(1, "scalping", data_dir=data_dir)
        s = apply_preset(1, "position", data_dir=data_dir)
        assert s.dd_rolling_window_days == 90
        assert s.strategy_preset == "position"
