"""
Per-account config helper — spec §3.3 reader with default fallbacks.

P1.T2 (plan §1 task 1.2): single source of truth for reading
``accounts.config_json`` and resolving spec §3.3 defaults. Replaces
the inline ``_read_account_config`` previously living in
``core/order_enrichment.py``.

Two flavors with identical return shape (:class:`AccountConfig`):

- :func:`read_account_config_sync` — opens a fresh ``sqlite3``
  connection at the given ``db_path``. Used by the matcher's sync
  decision path (``core/calc_correlation.correlate_order_to_calc``
  is pure-sync; its caller in ``order_enrichment._try_correlate``
  reads config before calling).

- :func:`read_account_config_async` — uses the long-lived
  ``aiosqlite`` connection on a :class:`DatabaseManager` instance.
  Used by ``handle_risk_calculated`` and any future Database-aware
  code path that needs config at calc-creation time.

Both delegate the actual JSON parsing to :func:`_parse_config_json`
which is pure and testable without a DB.

Spec §3.3 defaults (verbatim from ``docs/design/calc_linkage_spec.md``):
  window_seconds                 = 300     (5 min)
  clock_skew_tolerance_sec       = 10
  entry_tolerance_pct            = 0.25    (percent, not ratio)
  snapshot_drift_tolerance_pct   = 0.5
  deviation_thresholds.yellow_pct = 5
  deviation_thresholds.red_pct   = 15
  size_deviation_threshold_pct   = 10
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, Optional

log = logging.getLogger("account_config")


# Spec §3.3 defaults — kept as module constants so both this module
# and consumers (matcher, handlers) reference the same numbers.
DEFAULT_WINDOW_SECONDS               = 300
DEFAULT_CLOCK_SKEW_TOLERANCE_SEC     = 10
DEFAULT_ENTRY_TOLERANCE_PCT          = 0.25
DEFAULT_SNAPSHOT_DRIFT_TOLERANCE_PCT = 0.5
DEFAULT_YELLOW_DEVIATION_PCT         = 5.0
DEFAULT_RED_DEVIATION_PCT            = 15.0
DEFAULT_SIZE_DEVIATION_THRESHOLD_PCT = 10.0
# P6.T6: feature flag (config_json.feature_flags.snapshot_wins_drift). Default
# OFF — the inversion of the WS-fills-win policy + the position:size_drift event
# are opt-in per account (spec §12.6 / plan §6 row 6.8).
DEFAULT_SNAPSHOT_WINS_DRIFT          = False


@dataclass(frozen=True)
class AccountConfig:
    """Resolved per-account config from ``accounts.config_json``.

    All fields carry spec §3.3 defaults when the source JSON omits
    them (or when config_json itself is missing / malformed). Frozen
    so consumers can't accidentally mutate; re-read from DB to pick
    up operator changes.

    Field naming follows the spec JSON keys with one exception:
    ``deviation_thresholds`` is flattened into ``yellow_deviation_pct``
    and ``red_deviation_pct`` here, since callers always want one or
    the other and the nested form is awkward in code.
    """
    window_seconds: int                 = DEFAULT_WINDOW_SECONDS
    clock_skew_tolerance_sec: int       = DEFAULT_CLOCK_SKEW_TOLERANCE_SEC
    entry_tolerance_pct: float          = DEFAULT_ENTRY_TOLERANCE_PCT
    snapshot_drift_tolerance_pct: float = DEFAULT_SNAPSHOT_DRIFT_TOLERANCE_PCT
    yellow_deviation_pct: float         = DEFAULT_YELLOW_DEVIATION_PCT
    red_deviation_pct: float            = DEFAULT_RED_DEVIATION_PCT
    size_deviation_threshold_pct: float = DEFAULT_SIZE_DEVIATION_THRESHOLD_PCT
    # P6.T6 feature flag — read from config_json.feature_flags.snapshot_wins_drift.
    snapshot_wins_drift: bool           = DEFAULT_SNAPSHOT_WINS_DRIFT


def _parse_config_json(blob: Optional[str]) -> AccountConfig:
    """Parse a JSON blob into :class:`AccountConfig` with defaults.

    Pure — testable without a DB. Returns a fully-defaulted config
    when the blob is empty / non-JSON / not a dict. Per-field
    parse errors fall back to that field's spec default; we never
    raise from here.
    """
    if not blob:
        return AccountConfig()
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, TypeError):
        log.warning("config_json malformed; using spec §3.3 defaults")
        return AccountConfig()
    if not isinstance(parsed, dict):
        log.warning("config_json wasn't a dict; using spec §3.3 defaults")
        return AccountConfig()

    deviation = parsed.get("deviation_thresholds")
    if not isinstance(deviation, dict):
        deviation = {}

    # P6.T6: feature_flags.snapshot_wins_drift (nested dict, default off).
    # STRICT bool — only a genuine JSON boolean enables the inversion; any other
    # type (a string "false"/"0", a number, null) falls back to OFF. bool("false")
    # would be True, which must NOT silently enable a risky money-path inversion.
    flags = parsed.get("feature_flags")
    if not isinstance(flags, dict):
        flags = {}
    _swd = flags.get("snapshot_wins_drift", DEFAULT_SNAPSHOT_WINS_DRIFT)
    snapshot_wins_drift = _swd if isinstance(_swd, bool) else DEFAULT_SNAPSHOT_WINS_DRIFT

    def _int(key: str, default: int) -> int:
        try:
            return int(parsed.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float, source: Dict[str, Any] = parsed) -> float:
        try:
            return float(source.get(key, default))
        except (TypeError, ValueError):
            return default

    return AccountConfig(
        window_seconds               = _int("window_seconds", DEFAULT_WINDOW_SECONDS),
        clock_skew_tolerance_sec     = _int("clock_skew_tolerance_sec", DEFAULT_CLOCK_SKEW_TOLERANCE_SEC),
        entry_tolerance_pct          = _float("entry_tolerance_pct", DEFAULT_ENTRY_TOLERANCE_PCT),
        snapshot_drift_tolerance_pct = _float("snapshot_drift_tolerance_pct", DEFAULT_SNAPSHOT_DRIFT_TOLERANCE_PCT),
        yellow_deviation_pct         = _float("yellow_pct", DEFAULT_YELLOW_DEVIATION_PCT, source=deviation),
        red_deviation_pct            = _float("red_pct", DEFAULT_RED_DEVIATION_PCT, source=deviation),
        size_deviation_threshold_pct = _float("size_deviation_threshold_pct", DEFAULT_SIZE_DEVIATION_THRESHOLD_PCT),
        snapshot_wins_drift          = snapshot_wins_drift,
    )


def read_account_config_sync(db_path: str, account_id: int) -> AccountConfig:
    """Sync read of ``accounts.config_json`` for the matcher path.

    Opens a short-lived sqlite3 connection with ``timeout=10.0`` so
    contention with the long-lived aiosqlite writer on the same DB
    file is handled by SQLite's busy-wait (see T212 M2). Returns a
    fully-defaulted :class:`AccountConfig` on any DB error.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT config_json FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        log.warning(
            "read_account_config_sync DB error for account=%s (db=%s)",
            account_id, db_path, exc_info=True,
        )
        return AccountConfig()
    if not row:
        return AccountConfig()
    return _parse_config_json(row[0])


async def read_account_config_async(db: Any, account_id: int) -> AccountConfig:
    """Async read of ``accounts.config_json`` via :class:`DatabaseManager`.

    Uses the long-lived aiosqlite connection (no new file handle).
    Returns a fully-defaulted :class:`AccountConfig` on any error.

    The ``db`` parameter is intentionally typed as ``Any`` to avoid a
    circular import on :class:`core.database.DatabaseManager`. Caller
    passes either the module-level singleton (``core.database.db``)
    or a per-account instance.
    """
    try:
        async with db._conn.execute(
            "SELECT config_json FROM accounts WHERE id = ?",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
    except Exception:
        log.warning(
            "read_account_config_async DB error for account=%s",
            account_id, exc_info=True,
        )
        return AccountConfig()
    if not row:
        return AccountConfig()
    return _parse_config_json(row[0])
