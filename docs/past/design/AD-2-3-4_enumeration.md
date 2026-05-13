# AD-2/3/4 Enumeration: Bybit Adapter Polish

**Date**: 2026-05-13
**Branch**: `fix/AD-2-3-4-bybit-adapter-polish`

---

## AD-2: Bybit fetch_income() ignores income_type

**File**: `core/adapters/bybit/rest_adapter.py:262-295`

**Current**: `income_type` parameter accepted but never used. Always calls
`private_get_v5_position_closed_pnl` → always returns `income_type="realized_pnl"`.
Callers (exchange_income.py) pass "REALIZED_PNL", "COMMISSION", "FUNDING_FEE"
but Bybit returns empty for non-PnL types.

**Bybit V5 API reality**: No unified income endpoint like Binance's
`/fapi/v1/income`. Separate endpoints per type:
- Realized PnL: `GET /v5/position/closed-pnl` (currently used)
- Funding: `GET /v5/account/transaction-log` with `type=TRANSFER_IN/OUT`
  (would need investigation — Bybit funding is embedded in transaction log)
- Commission: not separately exposed (part of trade execution)

**Fix**: Route per income_type. For unsupported types (COMMISSION, FUNDING_FEE),
log a debug message and return empty. This is honest — callers already handle
empty responses. Set `income_type` field correctly on returned records.

**LOC**: ~15 lines (add type routing + docs, keep existing PnL path)

---

## AD-3: Bybit hardcoded fees

**File**: `core/adapters/bybit/rest_adapter.py:82-83`

**Current**: `maker_fee=0.0002, taker_fee=0.00055` hardcoded (VIP0 defaults).
`fee_source` field not populated (stays default empty string).

**Bybit V5 API reality**: `GET /v5/account/info` returns `vipLevel` but NOT
commission rates. No per-user rate endpoint exists.

**Fix (minimal, recommended)**: Fetch VIP level from `/v5/account/info`,
lookup in static fee table, set `fee_source="vip_lookup"`. Covers VIP0-4+.
Falls back to VIP0 defaults if API call fails.

**LOC**: ~20 lines (add API call + fee table + fallback)

---

## AD-4: is_close based on realizedPnl (unreliable)

**Files**: `bybit/rest_adapter.py:199`, `binance/rest_adapter.py:200`

**Current**: Both adapters use `is_close=bool(realizedPnl != 0)`. Wrong:
- Close at entry price → realizedPnl=0 → falsely marked as open
- Forced reduction → realizedPnl≠0 → could be misleadingly marked as close

**Fix**: Deterministic check using side + position direction:
- `SELL + LONG → close` (sells out of long)
- `BUY + SHORT → close` (buys out of short)
- Binance: use `positionSide` field directly
- Bybit: use `positionIdx` (1=LONG hedge, 2=SHORT hedge, 0=one-way)
- One-way mode: fall back to current heuristic (no position direction info)

**LOC**: ~10 lines per adapter (~20 total)

---

## Summary

| Finding | LOC | Independent? | Commit Order |
|---------|-----|-------------|--------------|
| AD-4 | ~20 | Yes | 1st (foundational — is_close correctness) |
| AD-3 | ~20 | Yes | 2nd (fee accuracy) |
| AD-2 | ~15 | Yes | 3rd (income type routing) |

All three are independent. Single branch, 3 atomic commits.
AD-4 first because is_close correctness is foundational to trade records.
