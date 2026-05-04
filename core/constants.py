"""
Shared constants for the Quantamental Engine.

Centralizes magic numbers that appear across multiple modules.
"""

# ── Time conversions (milliseconds) ─────────────────────────────────────────
MS_PER_SECOND = 1_000
MS_PER_MINUTE = 60_000
MS_PER_HOUR   = 3_600_000
MS_PER_DAY    = 86_400_000
MS_PER_WEEK   = 604_800_000

# ── Time conversions (seconds) ──────────────────────────────────────────────
SECONDS_PER_DAY  = 86_400
SECONDS_PER_HOUR = 3_600

# ── Timeframe -> minutes lookup ─────────────────────────────────────────────
TIMEFRAME_MINUTES = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "30m": 30,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
    "1w":  10080,
}
