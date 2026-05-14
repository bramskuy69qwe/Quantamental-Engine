"""
Typed accessor for the per-account ``account_settings`` table.

This module is the source-of-truth interface for v2.4+ account
configuration.  Legacy ``account_params`` reads (via ``db_settings.py``
SettingsMixin) are deprecated but remain active during the v2.4
transition — engine code will be rewired in a follow-up task.

Routing: resolves ``account_id`` to the correct per-account DB using
the same split-layout conventions as ``core.db_router``.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, fields
from typing import Optional

import config
from core.db_router import PER_ACCOUNT_DIR, split_done


# ── Dataclass ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountSettings:
    """Mirrors the per-account ``account_settings`` table exactly."""

    account_id: int
    timezone: str = "UTC"
    dd_rolling_window_days: int = 30
    dd_warning_threshold: Optional[float] = None
    dd_limit_threshold: Optional[float] = None
    dd_recovery_threshold: float = 0.50
    dd_enforcement_mode: str = "advisory"       # "advisory" | "enforced"
    weekly_pnl_warning_threshold: Optional[float] = None
    weekly_pnl_limit_threshold: Optional[float] = None
    weekly_pnl_enforcement_mode: str = "advisory"  # "advisory" | "enforced"
    strategy_preset: Optional[str] = None
    analytics_default_period: str = "monthly"
    week_start_dow: int = 1                     # 1=Monday, 7=Sunday


_FIELDS = {f.name for f in fields(AccountSettings)}
_UPDATABLE = _FIELDS - {"account_id"}


# ── Path resolution ──────────────────────────────────────────────────────────


def _resolve_db_path(account_id: int, data_dir: Optional[str] = None) -> str:
    """Locate the per-account DB file that owns *account_id*.

    Pre-split: falls back to the legacy combined DB.
    Raises ``KeyError`` if no DB contains the account.
    """
    ddir = data_dir or config.DATA_DIR

    if not split_done() or not os.path.exists(os.path.join(ddir, ".split-complete-v1")):
        return os.path.join(ddir, "risk_engine.db")

    pa_dir = os.path.join(ddir, "per_account")
    if os.path.isdir(pa_dir):
        for fname in sorted(os.listdir(pa_dir)):
            if not fname.endswith(".db"):
                continue
            path = os.path.join(pa_dir, fname)
            conn = sqlite3.connect(path)
            try:
                if conn.execute(
                    "SELECT 1 FROM accounts WHERE id = ?", (account_id,)
                ).fetchone():
                    return path
            finally:
                conn.close()

    raise KeyError(f"No per-account DB found for account_id={account_id}")


# ── Read ─────────────────────────────────────────────────────────────────────


def get_account_settings(
    account_id: int, *, data_dir: Optional[str] = None
) -> AccountSettings:
    """Load settings for *account_id*.  Raises ``KeyError`` if missing."""
    db_path = _resolve_db_path(account_id, data_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM account_settings WHERE account_id = ?",
            (account_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise KeyError(f"No account_settings row for account_id={account_id}")

    return AccountSettings(**{k: row[k] for k in row.keys() if k in _FIELDS})


# ── Write ────────────────────────────────────────────────────────────────────


def update_account_settings(
    account_id: int, *, data_dir: Optional[str] = None, **updates
) -> AccountSettings:
    """Partial update.  Validates field names before any SQL runs.

    Returns the refreshed ``AccountSettings`` after the write.
    No-op (no SQL) when *updates* is empty.
    Raises ``ValueError`` for unknown / non-updatable fields.
    Raises ``KeyError`` if the account row doesn't exist.
    """
    bad = set(updates) - _UPDATABLE
    if bad:
        raise ValueError(f"Unknown or non-updatable fields: {bad}")

    if not updates:
        return get_account_settings(account_id, data_dir=data_dir)

    db_path = _resolve_db_path(account_id, data_dir)

    # Column names are drawn from _UPDATABLE (derived from the frozen
    # dataclass).  No user-supplied strings reach the SQL template.
    set_clause = ", ".join(col + " = ?" for col in updates)
    values = list(updates.values()) + [account_id]

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "UPDATE account_settings SET " + set_clause + " WHERE account_id = ?",
            values,
        )
        if cur.rowcount == 0:
            raise KeyError(f"No account_settings row for account_id={account_id}")
        conn.commit()
    finally:
        conn.close()

    return get_account_settings(account_id, data_dir=data_dir)
