# `_current_priority` Test Failure Audit

**Date:** 2026-05-15
**Outcome:** B — regression introduced by Task 33, fixed in this audit task.

## Failing Tests

| Test | File |
|---|---|
| `test_equivalence_short_trade` | `tests/test_sr7_step4_price_extremes.py:134` |
| `test_equivalence_very_short_trade` | `tests/test_sr7_step4_price_extremes.py:148` |
| `test_equivalence_empty_agg_ohlcv_fallback` | `tests/test_sr7_step4_price_extremes.py:162` |

All three assert behavioral equivalence of `BinanceUSDMAdapter.fetch_price_extremes()`
using mock data. They construct an adapter via `__new__` (bypassing `__init__`) and
manually assign `_ex` and `_markets_loaded`.

## Error

```
AttributeError: 'BinanceUSDMAdapter' object has no attribute '_current_priority'
```

at `core/adapters/base.py:86` in `_run()`:

```python
effective_priority = priority or self._current_priority or "normal"
```

## Root Cause

The tests use `BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)` which skips `__init__`.
`BaseExchangeAdapter.__init__` initializes `_weight_tracker` and `_current_priority`,
but the test setup only assigned `_ex` and `_markets_loaded`. When `_run()` was extended
to access these attributes, the partial initialization caused AttributeError.

## Branch Walkback

| Branch | Pass/Fail | Error |
|---|---|---|
| `v2.4/parent-reenrich-prod` (Task 28) | PASS | — |
| `v2.4/oneway-isclose-snapshots` (Task 29) | PASS | — |
| `v2.4/equity-backfill-wire` (Task 32) | PASS | — |
| **`7ff2ed5` (Task 33 — weight-tracker)** | **FAIL** | `_weight_tracker` |
| `e1c3bb6` (Task 34 — fanout) | FAIL | `_weight_tracker` |
| `45af050` (Task 35 — priority plumbing) | FAIL | `_current_priority` |
| `v2.4/mexc-adapter` (Task 36) | FAIL | `_current_priority` |
| All subsequent branches through `v2.4/positions-rows-only` | FAIL | `_current_priority` |

**Regression commit:** `7ff2ed5` — "add proactive API weight tracker (Priority 3b)"

The initial error was `_weight_tracker` (Task 33 added `self._get_weight_tracker()` to
`_run()`). Task 35 then added `_current_priority` to `_run()`, which executes first in
code order, changing the error message. Same root cause throughout.

## Fix

Extracted a `_make_test_adapter()` helper that sets all base-class attributes:

```python
def _make_test_adapter(mock_ex=None):
    adapter = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
    adapter._ex = mock_ex or MagicMock()
    adapter._markets_loaded = True
    adapter._weight_tracker = None
    adapter._current_priority = "normal"
    return adapter
```

All 3 tests updated to use this helper. 11/11 tests now pass.
