# MN-2 Phase 1: Monthly Drawdown Investigation

**Date**: 2026-05-13
**Branch**: `fix/MN-2-monthly-drawdown-diagnostic`
**Status**: Root cause identified — definition mismatch + transient observation

---

## Finding

The engine does NOT compute monthly drawdown. It computes **intraday
drawdown** that resets at BOD (midnight UTC+7). There are two drawdown
displays on the dashboard, neither shows month-to-date drawdown:

1. **Real-time gauge** (dashboard top): `pf.drawdown` — intraday
   peak-to-trough, resets to 0 at BOD. Label says "Drawdown" (no
   time qualifier). After BOD reset, shows 0 until equity drops
   below that day's peak.

2. **Journal section** (monthly stats): `max_dd_month` — worst
   single-day intraday drawdown across the month. Currently 11.74%
   (from May 5). NOT 0.

The user's "monthly drawdown shows 0" likely refers to the real-time
gauge observed after BOD reset — expected behavior, but misleading
without a "today" qualifier on the label.

---

## Data Verification

```
=== May 2026 daily snapshot summary ===
Day          | Snapshots | Max DD   | Min Eq     | Max Eq
2026-05-04   |      1488 |    2.13% |      79.89 |      81.63
2026-05-05   |      1957 |   11.74% |      74.97 |      84.26
2026-05-06   |       825 |    2.89% |      77.51 |      79.79
...
2026-05-10   |      1844 |    2.78% |      76.18 |      78.80  ← discovery date
...
2026-05-13   |       333 |    3.40% |      80.62 |      80.62  ← current

MAX(drawdown) this month: 11.74% (May 5)
True monthly peak-to-trough: (84.26 - 74.97) / 84.26 = 11.03%
Journal "Max DD" would show: 11.74% (NOT 0)
```

---

## Root Cause: Definition Mismatch (Layer e)

### What the engine computes

**Real-time drawdown** (`pf.drawdown`):
```
Formula: (max_total_equity - total_equity) / max_total_equity
Reset:   max_total_equity = total_equity at midnight UTC+7 (BOD)
Scope:   INTRADAY only — resets to 0 every day
```

**dd_state thresholds**:
```
dd_ratio = pf.drawdown / max_dd_percent (user param, default 10%)
"ok"      when dd_ratio < 0.80
"warning" when dd_ratio >= 0.80
"limit"   when dd_ratio >= 0.95
```

**Journal "Max DD"** (`max_dd_month`):
```
SQL: MAX(drawdown) FROM account_snapshots WHERE ts IN [month_start, month_end]
Returns: worst single-day intraday drawdown stored in any snapshot
```

### What the user expects

**Monthly drawdown**: how far below the month's peak equity the account
currently is. Formula: `(month_peak_equity - current_equity) / month_peak_equity`.

This metric does NOT exist in the engine. Neither `pf.drawdown` nor
`max_dd_month` represents it.

### Why the user saw 0

Most likely: checked the real-time gauge after BOD reset. `max_total_equity`
had just been reset to `current_equity`, so `pf.drawdown = 0`. The gauge
label says "Drawdown" with no time qualifier — looks like it should be
cumulative.

---

## Auto-Resolution Check

**PA-1 + AN-2 impact**: These fixes cleaned trade data but don't affect
the drawdown computation path. Drawdown is computed from `account_snapshots`
equity values, not from trade records.

**MP-1 impact**: Added dd_state + drawdown restore on crash recovery. This
ensures drawdown survives restarts but doesn't change the daily-reset
behavior.

**Conclusion**: MN-2 was NOT auto-resolved by other fixes. The definition
mismatch has always existed — it's a design gap, not a regression.

---

## v2.4 Gate Impact

dd_state is planned for promotion from advisory to enforcement gate.
Current dd_state behavior:
- Intraday only — resets to "ok" at midnight regardless of cumulative loss
- A trader losing 5% per day for 10 days would never trigger "limit"
  if each individual day's loss is below the threshold

For v2.4 gate promotion, a monthly (or rolling-window) drawdown metric
is needed. The current intraday metric is insufficient for enforcement.

---

## Severity

**MEDIUM** (revised from potentially HIGH). Rationale:
- Not a bug — working as designed, but design doesn't match user expectation
- Dashboard label is misleading (no "today" qualifier)
- Journal "Max DD" works correctly (shows 11.74%, not 0)
- v2.4 gate promotion requires monthly metric (but that's a feature addition)

**For v2.4**: Severity escalates to HIGH — monthly drawdown metric is a
prerequisite for gate promotion.

---

## Fix Options

### Option A: Label fix only (5 min, Bucket 5)
Change "Drawdown" label to "Today's Drawdown" on the real-time gauge.
Clarifies the daily-reset behavior without changing computation.

### Option B: Monthly drawdown metric (Bucket 4, ~30-50 LOC)
Add a month-to-date drawdown computation:
- Track `month_peak_equity` (separate from daily `max_total_equity`)
- Reset on 1st of month only (in `_bod_scheduler`)
- Compute `monthly_drawdown = (month_peak - current) / month_peak`
- Display alongside or replacing the daily gauge
- dd_state uses monthly metric for threshold checks

### Option C: Rolling-window drawdown (v2.4 scope)
Replace fixed monthly window with configurable rolling window (e.g., 30 days).
More flexible for gate promotion. Higher complexity.

**Recommendation**: Option B for immediate fix (monthly metric), Option A
as quick win if Option B is deferred. Option C for v2.4 design phase.

---

## Files Referenced

| File | Function | Role |
|------|----------|------|
| `core/data_cache.py` | `_do_recalculate_portfolio()` | Drawdown computation |
| `core/state.py` | `perform_bod_reset()` | Daily reset of max_total_equity |
| `core/state.py` | `PortfolioStats` | dd_state, drawdown fields |
| `core/db_analytics.py` | `get_equity_period_boundaries()` | Journal Max DD query |
| `api/routes_dashboard.py` | `frag_dashboard()`, `frag_dashboard_journal_stats()` | Template context |
| `templates/fragments/dashboard_body.html` | Lines 27-42 | Drawdown gauge render |
| `templates/fragments/dashboard_journal_stats.html` | Line 27 | Max DD display |
