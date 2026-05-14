"""
One-shot data migration: convert legacy account_params threshold ratios
to absolute values in per-account account_settings.

Option A math (preserves the user's tuned ratios):
    dd_warning_threshold         = max_dd_percent × max_dd_warning_pct
    dd_limit_threshold           = max_dd_percent × max_dd_limit_pct
    weekly_pnl_warning_threshold = max_w_loss_percent × weekly_loss_warning_pct
    weekly_pnl_limit_threshold   = max_w_loss_percent × weekly_loss_limit_pct

Records in each per-account DB's migrations_log for idempotency.
If the legacy DB is missing or has no rows, thresholds stay NULL
(engine treats NULL as "use defaults").
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

log = logging.getLogger("migration_runner")

MIGRATION_NAME = "convert_thresholds_from_account_params_v1"


def _read_legacy_params(legacy_path: str, account_id: int) -> Dict[str, float]:
    """Read account_params from legacy risk_engine.db (read-only)."""
    if not os.path.exists(legacy_path):
        log.warning("[convert] legacy DB not found: %s", legacy_path)
        return {}
    try:
        conn = sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT key, value FROM account_params WHERE account_id=?",
            (account_id,),
        ).fetchall()
        conn.close()
        return {k: v for k, v in rows}
    except Exception as exc:
        log.warning("[convert] cannot read legacy params: %s", exc)
        return {}


def _compute(params: Dict[str, float]) -> Tuple[
    Optional[float], Optional[float], Optional[float], Optional[float]
]:
    """Option A: absolute = base × ratio.

    Returns (dd_warn, dd_limit, weekly_warn, weekly_limit).
    Any component missing → that threshold is None.
    """
    max_dd = params.get("max_dd_percent")
    dd_warn_pct = params.get("max_dd_warning_pct")
    dd_limit_pct = params.get("max_dd_limit_pct")
    max_w = params.get("max_w_loss_percent")
    w_warn_pct = params.get("weekly_loss_warning_pct")
    w_limit_pct = params.get("weekly_loss_limit_pct")

    dd_warn = (max_dd * dd_warn_pct) if (max_dd is not None and dd_warn_pct is not None) else None
    dd_limit = (max_dd * dd_limit_pct) if (max_dd is not None and dd_limit_pct is not None) else None
    w_warn = (max_w * w_warn_pct) if (max_w is not None and w_warn_pct is not None) else None
    w_limit = (max_w * w_limit_pct) if (max_w is not None and w_limit_pct is not None) else None

    return dd_warn, dd_limit, w_warn, w_limit


def convert_thresholds(data_dir: Optional[str] = None) -> int:
    """Convert account_params thresholds → account_settings for every
    per-account DB.  Returns number of DBs converted."""
    if data_dir is None:
        import config
        data_dir = config.DATA_DIR

    if not os.path.exists(os.path.join(data_dir, ".split-complete-v1")):
        return 0

    pa_dir = os.path.join(data_dir, "per_account")
    if not os.path.isdir(pa_dir):
        return 0

    legacy_path = os.path.join(data_dir, "risk_engine.db")
    converted = 0

    for fname in sorted(os.listdir(pa_dir)):
        if not fname.endswith(".db"):
            continue
        pa_path = os.path.join(pa_dir, fname)
        pa_conn = sqlite3.connect(pa_path)
        try:
            # Idempotency: already applied?
            if pa_conn.execute(
                "SELECT 1 FROM migrations_log WHERE name=?", (MIGRATION_NAME,)
            ).fetchone():
                continue

            # Which account lives in this DB?
            acct_row = pa_conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()
            if not acct_row:
                log.warning("[convert] no accounts row in %s — skipping", fname)
                continue
            account_id = acct_row[0]

            # Read source params from legacy DB (read-only handle)
            params = _read_legacy_params(legacy_path, account_id)

            # Compute absolute thresholds
            dd_warn, dd_limit, w_warn, w_limit = _compute(params)

            # Populate account_settings
            pa_conn.execute(
                """UPDATE account_settings SET
                       dd_warning_threshold         = ?,
                       dd_limit_threshold           = ?,
                       weekly_pnl_warning_threshold = ?,
                       weekly_pnl_limit_threshold   = ?
                   WHERE account_id = ?""",
                (dd_warn, dd_limit, w_warn, w_limit, account_id),
            )

            # Record in this DB's migrations_log
            pa_conn.execute(
                "INSERT INTO migrations_log (name, applied_at) VALUES (?, ?)",
                (MIGRATION_NAME, datetime.now(timezone.utc).isoformat()),
            )
            pa_conn.commit()
            converted += 1
            log.info(
                "[convert] account %d → dd_warn=%s dd_limit=%s w_warn=%s w_limit=%s",
                account_id, dd_warn, dd_limit, w_warn, w_limit,
            )
        except Exception:
            log.error("[convert] failed on %s", fname, exc_info=True)
            try:
                pa_conn.rollback()
            except Exception:
                pass
        finally:
            pa_conn.close()

    return converted
