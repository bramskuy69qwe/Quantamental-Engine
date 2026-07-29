# Phase-6 trade scenarios — operator checklist

> GENERATED from `e2e/scenarios/trade-scenarios.ts` — do not edit by hand.
> Regenerate: `node e2e/scripts/gen-checklist.mjs`
>
> Use this when running the scenarios BY HAND. The semi-automated runner
> (`npm --prefix e2e run e2e:trade`) executes the same steps with an on-screen
> prompt and asserts every oracle for you.

**Standing rules** (make-or-break, from the verified lifecycle map):

- Auto-link needs **both** a TP and an SL live on Binance — a naked entry never reaches the matcher, and never appears in the Linkage inbox.
- A **TP ladder blocks auto-link** (ambiguity bail) — single TP for link scenarios.
- `NEEDS_MANUAL_REVIEW` is **sticky**: always calc FIRST, order second.
- Leave **>2s between identical orders** (duplicate-order detector).
- Stay in **HEDGE** mode throughout (one-way breaks position-id attribution).
- `—` in an excursion column means *not measured*, not zero.

## H1-happy-path — Calc → open with TP+SL → auto-link → force close

**Group**: `happy`  •  **Why**: The spine: proves calc→fill attribution end-to-end. Also the FIRST live proof that the repaired user-data WS carries fills (source=binance_ws).

**Preconditions**
- Use a SMALL size — this opens a REAL position.
- Place the entry AND both protective legs (TP + SL): without both, the matcher never runs.
- Single TP only — a TP ladder blocks auto-link by design.

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | script | Open Pre-Trade. | — |
| 2 | script | Script submits a calc for the scenario ticker (MARKET, BY-%, TP 2% / SL 1%). | — |
| 3 | assert | _check_ `chip-linkable` | Chip shows ✓ LINKABLE with time remaining. _(allow 15s)_ |
| 4 | **YOU** | On BINANCE: open the position at ~the calc entry (MARKET), then immediately place a TP and an SL<br>at ~the calc levels shown in Setup Summary. Confirm the entry FILLED, then press DONE. | — |
| 5 | assert | _check_ `ws-sourced-fill` | Engine recorded the fill via the user-data WS (source=binance_ws) — the P5-001 proof. _(allow 30s)_ |
| 6 | assert | _check_ `chip-linked` | Pre-Trade chip flips to ✓ LINKED (poller stops). Order-form TP/SL adds the 15 s algo-sweep hop. _(allow 40s)_ |
| 7 | script | Script opens Linkage. | — |
| 8 | assert | _check_ `position-linked-onplan` | Open Positions row shows LINKED + ON-PLAN. _(allow 20s)_ |
| 9 | assert | _check_ `calc-row-absent` | THIS calc (by calc_id) leaves Active Calcs (status → matched). _(allow 20s)_ |
| 10 | **YOU** | On BINANCE: CLOSE the position at market (cancel leftover TP/SL). Press DONE when flat. | — |
| 11 | assert | _check_ `closed-row-present` | History shows the closed row (2s build + 30s poll; pane ↻ to hurry). _(allow 40s)_ |
| 12 | assert | _check_ `closed-row-reason` | REASON reads Manual (a market close is MANUAL_OTHER). _(allow 40s)_ |

**Cleanup**
- [ ] Position flat; leftover TP/SL cancelled on Binance.
- [ ] No active calc remains (it completed via the position).

## L1-no-calc-unplanned — Open WITHOUT a calc → position reads UNPLANNED

**Group**: `linkage`  •  **Why**: Proves the engine does not invent a link — and that a naked entry never reaches the inbox.

**Preconditions**
- NO calc for this ticker/side beforehand (that is the point).

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | **YOU** | On BINANCE: open a small position with NO calc first. TP/SL optional. Press DONE when filled. | — |
| 2 | script | Script opens Linkage. | — |
| 3 | assert | _check_ `position-unplanned` | Open Positions shows UNPLANNED (+ OFF-PLAN deviation). _(allow 15s)_ |
| 4 | **YOU** | On BINANCE: close the position. Press DONE when flat. | — |

**Cleanup**
- [ ] Position flat.

## L2-near-miss-review — Calc first, then entry with TP/SL OFF by >1 tick → inbox [REVIEW] → manual link

**Group**: `linkage`  •  **Why**: The manual-link recovery path. NEEDS_MANUAL_REVIEW is STICKY, so calc must come FIRST; a later calc can never rescue the order.

**Preconditions**
- Calc FIRST, order second (sticky review status).
- Deviate the TP/SL by MORE than one tick so the strict 6/6 matcher rejects it, but keep it within 5% so the loose finder still offers it as a candidate.

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | script | Open Pre-Trade. | — |
| 2 | script | Script submits the calc. | — |
| 3 | assert | _check_ `chip-linkable` | Chip shows ✓ LINKABLE. _(allow 15s)_ |
| 4 | **YOU** | On BINANCE: open the position, but set TP and SL a few ticks AWAY from the calc levels.<br>Press DONE when the entry has filled. | — |
| 5 | script | Script opens Linkage. | — |
| 6 | assert | _check_ `inbox-review-row` | Inbox shows the order as [REVIEW]; resolver shows N/6 below threshold with the failing legs red. _(allow 20s)_ |
| 7 | **YOU** | In the UI: select the inbox item, pick the candidate calc, click Link and ACCEPT the confirm. Press DONE. | — |
| 8 | assert | _check_ `position-linked-onplan` | Position flips to LINKED (junction replay attaches it post-fill). _(allow 20s)_ |
| 9 | **YOU** | On BINANCE: close the position and cancel leftover legs. Press DONE when flat. | — |

**Cleanup**
- [ ] Position flat; inbox clear for this order.

## A1-tpsl-amended — Move the TP >0.1% → plan badge goes AMENDED (amber)

**Group**: `amendment`  •  **Why**: Drift-compare is the ONLY amendment detector on Binance (a TP edit is a venue cancel+create, so the order_amendments ledger stays EMPTY — never assert the drilldown here).

**Preconditions**
- Requires a LINKED position (run H1 first, or link one).

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | **YOU** | On BINANCE: move the TP more than 0.1% away from the planned level. Press DONE. | — |
| 2 | script | Script opens Linkage. | — |
| 3 | assert | _check_ `plan-badge-amended` | Plan deviation shows AMENDED (amber) with a tp drift %. Budget covers the 15s algo REST sync + 5s poll. _(allow 25s)_ |

**Cleanup**
- [ ] Leave the position for A2, or close it.

## A2-sl-removed — Cancel the SL entirely → OFF-PLAN (red), and it STAYS red in History

**Group**: `amendment`  •  **Why**: Level-2 severity is sticky: the max severity seen during the position life is what History shows, even if you re-add the SL.

**Preconditions**
- Requires a LINKED position with both legs (continue from A1).

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | **YOU** | On BINANCE: CANCEL the SL, leaving the TP live. Press DONE. | — |
| 2 | assert | _check_ `plan-badge-offplan` | Plan deviation goes OFF-PLAN (red); TP/SL cell shows <tp> / —. _(allow 25s)_ |
| 3 | **YOU** | OPTIONAL: re-add the SL. The live badge should relax to AMENDED while History keeps OFF-PLAN. Press DONE. | — |
| 4 | **YOU** | On BINANCE: close the position. Press DONE when flat. | — |
| 5 | assert | _check_ `closed-row-present` | History row exists… _(allow 40s)_ |
| 6 | assert | _check_ `plan-badge-offplan` | …and its PLAN column is OFF-PLAN (worst-during-life, the sticky stash). _(allow 40s)_ |

**Cleanup**
- [ ] Position flat; all legs cancelled.

## X1-partial-scaleout — Partial close → one History row PER closing order

**Group**: `exit-structure`  •  **Why**: The engine writes one closed_positions row per closing ORDER; only the FINAL row gets the ladder-aware reason, funding sum and calc completion.

**Preconditions**
- An open position (linked or not).

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | **YOU** | On BINANCE: close roughly HALF the position. Press DONE. | — |
| 2 | assert | _check_ `closed-row-present` | History shows a PARTIAL row with the partial qty. _(allow 40s)_ |
| 3 | **YOU** | On BINANCE: close the REMAINDER. Press DONE when flat. | — |
| 4 | assert | _check_ `closed-row-present` | A SECOND row appears (one per closing order — not a single merged row). _(allow 40s)_ |

**Cleanup**
- [ ] Position flat.

## X2-hedge-both-sides — Long AND short the same symbol → independent rows, no cross-contamination

**Group**: `exit-structure`  •  **Why**: Hedge mode keys everything by (symbol, side). One leg amended must NOT move the other leg badge — a direct regression assertion.

**Preconditions**
- Account must stay in HEDGE mode (a one-way switch breaks tpid attribution — known latent gap).
- TWO calcs — one long, one short (they do not supersede each other; supersede is scoped per side).

| # | Who | Step | Expected |
|---|---|---|---|
| 1 | **YOU** | On BINANCE: open a SMALL LONG and a SMALL SHORT on the same symbol (>2s apart — duplicate-order detector). Press DONE. | — |
| 2 | script | Script opens Linkage. | — |
| 3 | assert | _check_ `position-unplanned` | BOTH legs appear as separate rows (selected by symbol AND side badge). _(allow 20s)_ |
| 4 | **YOU** | On BINANCE: amend the TP on ONE leg only. Press DONE. | — |
| 5 | assert | _check_ `plan-badge-amended` | Only the amended leg changes badge — the other stays put. _(allow 25s)_ |
| 6 | **YOU** | On BINANCE: close BOTH legs. Press DONE when flat. | — |

**Cleanup**
- [ ] Both legs flat.

