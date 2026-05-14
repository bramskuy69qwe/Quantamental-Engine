"""
Strategy presets — seed values for account_settings at account creation.

The preset name is stored informationally in ``account_settings.strategy_preset``.
After seeding, individual settings are freely editable — the preset doesn't
constrain them.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.db_account_settings import AccountSettings, update_account_settings

STRATEGY_PRESETS: Dict[str, Dict[str, Any]] = {
    "scalping": {
        "dd_rolling_window_days": 14,
        "dd_warning_threshold":   0.04,
        "dd_limit_threshold":     0.08,
        "dd_recovery_threshold":  0.50,
        "analytics_default_period": "weekly",
    },
    "day_trading": {
        "dd_rolling_window_days": 21,
        "dd_warning_threshold":   0.05,
        "dd_limit_threshold":     0.10,
        "dd_recovery_threshold":  0.50,
        "analytics_default_period": "weekly",
    },
    "swing": {
        "dd_rolling_window_days": 45,
        "dd_warning_threshold":   0.06,
        "dd_limit_threshold":     0.12,
        "dd_recovery_threshold":  0.40,
        "analytics_default_period": "monthly",
    },
    "position": {
        "dd_rolling_window_days": 90,
        "dd_warning_threshold":   0.08,
        "dd_limit_threshold":     0.15,
        "dd_recovery_threshold":  0.30,
        "analytics_default_period": "quarterly",
    },
    "custom": {},
}


def apply_preset(
    account_id: int,
    preset_name: str,
    *,
    data_dir: Optional[str] = None,
) -> AccountSettings:
    """Apply a strategy preset to an account's settings.

    Seeds the risk-related columns from the preset table + records the
    preset name.  ``custom`` is a no-op (returns current state).

    Raises ``ValueError`` for unknown preset names.
    """
    if preset_name not in STRATEGY_PRESETS:
        raise ValueError(
            f"Unknown preset {preset_name!r}. "
            f"Valid: {sorted(STRATEGY_PRESETS)}"
        )

    values = STRATEGY_PRESETS[preset_name]
    if not values:
        return update_account_settings(
            account_id, data_dir=data_dir, strategy_preset=preset_name,
        )

    return update_account_settings(
        account_id, data_dir=data_dir, strategy_preset=preset_name, **values,
    )
