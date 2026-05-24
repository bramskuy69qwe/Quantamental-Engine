# T178 — Fills Data Quality Investigation (Read-Only)

**Date**: 2026-05-25
**Status**: Investigation only. No DB writes, no code changes.
**Trigger**: T177 rebuild paused when it surfaced ~2x close-vs-open
inflation in `fills` totals. Root cause needed isolation before any
repair could be safe.

## Top-line summary

The `fills` table has data quality issues at multiple layers. Listed
in order of severity:

1. **`exchange_history_backfill` source creates synthetic duplicates** of real WS/REST fills. ~133 synthetic fills account-wide, 17 for BSBUSDT alone. These are NOT strict duplicates (different timestamps, different fill IDs) — they're *logical* duplicates of trades the real-time WS+REST paths already captured.
2. **`terminal_position_id` is empty for ALL fills** (350/350). It's set by the WS path only when a matching `app_state.positions` entry has `position_id` populated, and that field comes from Quantower's plugin. Without the plugin, no fill gets a pos_id.
3. **`get_position_fills` fallback contamination**: when `pos_id` is empty (always, per #2), the SQL falls back to `(symbol, direction)` matching — returning ALL historical opens of the same direction across distinct positions. The close-row builder then computes nonsense VWAP entry_price + `min(timestamp)` entry_time.
4. **Position reversals collapse lossy** into a single fill record. A LONG→SHORT cross records ONE fill as `is_close=1` against the OLD direction, losing the implicit "open of new direction".
5. **5 strict-duplicate pairs** (same symbol/side/timestamp/price/qty, distinct fill IDs) — 1.4% of total. Likely Binance's matching engine splitting one user order against two counter-party orders. May or may not need dedup — they're real trades from Binance's perspective.

## Layer 1: synthetic-vs-real duplication (biggest impact)

### Account-wide

| source | fills | total qty |
|---|---|---|
| `binance_rest` | 152 | (varies) |
| `exchange_history_backfill` | 133 | (varies) |
| `binance_ws` | 65 | (varies) |
| **total** | **350** | — |

### BSBUSDT specifically

| source | fills | total qty |
|---|---|---|
| `binance_rest` | 51 | 1319 |
| `exchange_history_backfill` | 17 | 566 |
| `binance_ws` | 11 | 228 |
| **total** | **79** | **2113** |

And the relevant cross-check:
- `exchange_history` REALIZED_PNL rows for BSBUSDT: 59 rows, total qty **1476**

### Why the inflation

The `exchange_history_backfill` path at [`db_orders.py:935`](../core/db_orders.py#L935) was designed to import historical trades from Binance's REALIZED_PNL accounting endpoint when the engine was offline. For each REALIZED_PNL row, it:

1. Synthesizes a "fill" record (from accounting data — NOT a real trade event)
2. Calls `upsert_fill()` on it
3. ALSO builds a `closed_positions` row

When the engine ALSO ran with WS/REST live (capturing the same trades through `binance_ws` and `binance_rest` sources), the synthetic fills landed alongside the real ones. They aren't caught by the existing `UNIQUE(account_id, exchange_fill_id)` constraint because each path uses different ID conventions.

### Resulting qty totals (account-wide)

| direction | is_close | qty total |
|---|---|---|
| LONG | 0 (open) | 293 |
| LONG | 1 (close) | **500** ← inflated |
| SHORT | 0 (open) | 443 |
| SHORT | 1 (close) | **877** ← inflated |

Closes ~1.7x opens. Mathematically impossible if all fills were real.

## Layer 2: `terminal_position_id` never populated

[`ws_manager.py:375-379`](../core/ws_manager.py#L375):
```python
pos = next(
    (p for p in app_state.positions if p.ticker == sym and p.direction == direction),
    None,
)
terminal_position_id = pos.position_id if pos else ""
```

The `pos.position_id` field is set by [`platform_bridge.py:623`](../core/platform_bridge.py#L623) — i.e., comes from Quantower's plugin. When the engine runs WITHOUT the plugin connected (or when WS receives a fill before the plugin updates `app_state.positions`), `position_id` is empty.

Verified: **0/350 fills have a non-empty `terminal_position_id`**. Same observation across all `data.backup-*` directories going back to May 14 — this is not migration corruption, it's a never-populated column.

## Layer 3: `get_position_fills` fallback contamination

[`db_orders.py:655-660`](../core/db_orders.py#L655):
```sql
SELECT * FROM fills WHERE account_id=?
  AND (terminal_position_id=? OR
       (COALESCE(terminal_position_id, '') = '' AND symbol=? AND direction=?))
```

When `pos_id=""` (always, per Layer 2), both arms of the OR match every fill of `(symbol, direction)`. The close-row builder receives ALL historical opens of the same direction, computes a cross-position VWAP, and uses `min(timestamp)` for entry_time. This is the direct mechanism behind the visible BSBUSDT row 22037 having `entry_price=0.771, entry_time=2026-05-19 18:11:53` when the actual position opened at 06:10 next day.

## Layer 4: Position-reversal lossiness

[`position_snapshot.py:108-111`](../core/position_snapshot.py#L108):
```python
is_partial = abs_after > 0 and (qty_before * qty_after > 0)  # same sign = partial
# Overshoot: crossing zero means close + new open
if qty_before * qty_after < 0:
    is_open = True  # also opens in opposite direction
```

For a position reversal (LONG → SHORT in a single fill), `is_close=True` AND `is_open=True` are both set, but only ONE fill record gets persisted. The qty of the new opposite-direction position is implicit in the residual — it's never written as a separate `is_close=0` fill of the new direction.

Impact: closes side gets full attribution, opens side under-counts. Compounds Layer 1's inflation.

## Layer 5: strict-duplicate pairs (minor)

5 pairs found via strict-match SQL (same symbol, side, ts_ms, price, qty, is_close, distinct exchange_fill_id):

| symbol | side | ts | price | qty | n | fill IDs | sources |
|---|---|---|---|---|---|---|---|
| BSBUSDT | BUY | 1779257434215 | 0.7710 | 57 | 2 | 178459194, 178459195 | binance_ws, binance_ws |
| LABUSDT | BUY | 1777997893237 | 2.5284 | 2 | 2 | 226460466, 226460467 | binance_rest, binance_rest |
| LABUSDT | BUY | 1777998452905 | 2.5875 | 2 | 2 | 226568148, 226568149 | binance_rest, binance_rest |
| LABUSDT | SELL | 1778184183973 | 4.3240 | 2 | 2 | 268240114, 268240115 | binance_rest, binance_rest |
| NAORISUSDT | SELL | 1778845482180 | 0.0535 | 58 | 2 | 116170705, 116170707 | binance_ws, binance_ws |

Note the fill IDs in each pair are CONSECUTIVE Binance `tradeId` values. This is characteristic of Binance's matching engine splitting one user-side order against two counter-party orders in the same orderbook level — Binance assigns each split a distinct tradeId. These are genuinely two distinct trade events from Binance's perspective. Removing them would lose data (real fills happened); keeping them is correct.

**Verdict for Layer 5**: NOT a bug. Leave as-is.

## What the closed_positions table looks like as a consequence

For BSBUSDT, existing closed_positions has 21 rows. The "real" trade count (per the fills timeline) is closer to 12 distinct positions. The 21 rows come from `exchange_history_backfill` grouping by `(symbol, direction, open_time)` from Binance's REALIZED_PNL events — each REALIZED_PNL event becomes a row, but Binance reports multi-fill closes as multiple events, inflating the count.

Sample contradiction visible in operator's UI:
- Row 22037: `LONG 88qty entry=0.7710 entry_time=2026-05-19 18:11:53 exit=0.7728 exit_time=06:24:22`
- Actual: at 18:11:53 the market price was ~$1.07 (verifiable in the fills stream — SHORT closing at $1.069 around that time). The position that closed at 06:24:22 actually opened at 06:10:34 at $0.771 with qty 114 (verifiable in `fills` rows 20202+20203).
- The bug: `exchange_history`'s REALIZED_PNL row for this had `open_time=18:11:53` (Binance's net-position view) but `entry_price=0.7710` (the actual fill price from the 06:10:34 open). Combined with the (symbol, direction, open_time) grouping at `db_orders.py:940`, the close-row gets stitched from inconsistent fields.

## Repair difficulty assessment

| Layer | What needs to happen | Difficulty | Risk |
|---|---|---|---|
| 1 (synthetic dups) | Stop exchange_history_backfill from inserting fills if WS/REST already captured the trade. Dedup existing synthetic fills against real ones. | High — requires logical-match dedup since IDs differ | Medium — need to confirm dedup rule before wiping anything |
| 2 (no pos_id) | Either populate pos_id from a different source (Binance's `i` order field?) or stop relying on it. | Medium | Low |
| 3 (fallback contamination) | Change `get_position_fills` to return empty when pos_id is empty. Force callers to use a different grouping strategy. | Low (code change) | Medium — breaks the existing close-row builder, which needs a rewrite |
| 4 (reversal lossiness) | Detect reversals in position_snapshot, split into two fill records (one close + one open). | Medium | Low (additive — new code path) |
| 5 (strict dups) | None — not a bug. | — | — |

## Recommended order if/when the repair is taken on

1. **Investigate Layer 1 dedup rule** (this doc + manual cross-check between WS, REST, and synthetic fills for a specific symbol). Goal: a deterministic match-key for "this synthetic fill represents the same trade as this real fill".
2. **Stop the dual-write at source** before touching any data. Modify exchange_history_backfill to call `get_existing_fill(symbol, ts, price, qty)` and skip if found.
3. **Dedup historical fills** using the agreed match-key. Backup first.
4. **Then** rewrite `_build_close_row_for_fill` to use chronological-walk grouping (T177's `core/position_grouping.py` draft is the right shape, but needs the dedup'd input to produce correct output).
5. **Wipe + rebuild closed_positions** from the dedup'd fills.
6. **Address Layer 4** (reversal lossiness) in `_build_close_row_for_fill` — split the reversal fill into two records.

Steps 1-5 are tractable but non-trivial. Estimated 3-5 focused sessions of work. Step 6 is additive and lower priority.

## What was NOT done in T178

- No DB writes.
- No code changes.
- No tests added.
- `core/position_grouping.py` and `scripts/rebuild_closed_positions_dryrun.py` from T177 remain uncommitted as drafts in the working tree. They're still useful but require the dedup-fix prerequisite before they can produce correct output.

## What T175 still buys us in the meantime

T175 (realized-PnL floor) caps the visible MFE/MAE damage from the underlying corruption: MFE can't display below `|gross_pnl|`, MAE can't display above `gross_pnl`. The 42.13 outlier and the entry_price corruption are NOT addressed by T175 — only the "MFE < gross_pnl" math impossibility is.

Operator can keep using the engine with the floor in place; visible numbers won't lie about the floor invariant. Just don't trust entry_price / entry_time on closed_positions rows until the repair lands.
