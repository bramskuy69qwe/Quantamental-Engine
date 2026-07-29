/**
 * Phase-6 trade scenarios — the SINGLE SOURCE for both the semi-automated spec
 * (specs/phase6-trade) and the generated operator checklist
 * (scripts/gen-checklist.mjs → checklist.generated.md).
 *
 * Every assertion budget comes from the verified lifecycle map (2026-07-28):
 *   inbox [REVIEW] 8s · LINKED badge 10s · chip LINKED 10s · amend badge 20s
 *   (15s algo REST sync + 5s poll) · closed row / SET REASON 35s (or pane ↻)
 *   · MFE/MAE 60s and `—` = legitimately-unknown, not a bug.
 *
 * Preconditions encoded here because they are make-or-break:
 *  - auto-link needs BOTH a TP and an SL live on Binance (order_enrichment.py
 *    :316-323 hard-returns otherwise → the matcher never runs and the order does
 *    NOT reach the inbox);
 *  - a TP LADDER blocks auto-link (ambiguity bail, :184-185);
 *  - NEEDS_MANUAL_REVIEW is STICKY (:313-315) → always calc FIRST, order second;
 *  - hedge mode: two calcs for both-sides; select rows by symbol AND side;
 *  - >2s between identical orders (duplicate-order detector, ~2s window).
 */

export type StepKind = 'auto' | 'operator' | 'assert';

export interface Step {
  kind: StepKind;
  /** Operator-facing text (also the checklist line). */
  manual: string;
  /** Automated action id, for kind='auto'. */
  action?: 'submit-calc' | 'goto-linkage' | 'goto-history' | 'goto-pretrade' | 'refresh-pane';
  /** Oracle id, for kind='assert'. */
  oracle?:
    | 'chip-linkable'
    | 'chip-linked'
    | 'calc-row-present'
    | 'calc-row-absent'
    | 'position-linked-onplan'
    | 'position-unplanned'
    | 'inbox-review-row'
    | 'inbox-empty-of'
    | 'plan-badge-amended'
    | 'plan-badge-offplan'
    | 'closed-row-present'
    | 'closed-row-reason'
    | 'ws-sourced-fill';
  budgetMs?: number;
  params?: Record<string, string | number>;
}

export interface Scenario {
  id: string;
  group: 'happy' | 'amendment' | 'linkage' | 'exit-structure';
  title: string;
  why: string;
  preconditions: string[];
  steps: Step[];
  cleanup: string[];
}

export const SCENARIOS: Scenario[] = [
  {
    id: 'H1-happy-path',
    group: 'happy',
    title: 'Calc → open with TP+SL → auto-link → force close',
    why:
      'The spine: proves calc→fill attribution end-to-end. Also the FIRST live ' +
      'proof that the repaired user-data WS carries fills (source=binance_ws).',
    preconditions: [
      'Use a SMALL size — this opens a REAL position.',
      'Place the entry AND both protective legs (TP + SL): without both, the matcher never runs.',
      'Single TP only — a TP ladder blocks auto-link by design.',
    ],
    steps: [
      { kind: 'auto', action: 'goto-pretrade', manual: 'Open Pre-Trade.' },
      {
        kind: 'auto',
        action: 'submit-calc',
        manual: 'Script submits a calc for the scenario ticker (MARKET, BY-%, TP 2% / SL 1%).',
      },
      { kind: 'assert', oracle: 'chip-linkable', budgetMs: 15_000, manual: 'Chip shows ✓ LINKABLE with time remaining.' },
      {
        kind: 'operator',
        manual:
          'On BINANCE: open the position at ~the calc entry (MARKET), then immediately place a TP and an SL\n' +
          'at ~the calc levels shown in Setup Summary. Confirm the entry FILLED, then press DONE.',
      },
      { kind: 'assert', oracle: 'ws-sourced-fill', budgetMs: 30_000, manual: 'Engine recorded the fill via the user-data WS (source=binance_ws) — the P5-001 proof.' },
      // ORDER-FORM budget: TP/SL set in Binance's form are conditional orders
      // INVISIBLE to the WS — the engine only sees them on the 15 s algo sweep,
      // which then re-enriches the entry (E2E-P6-001) before the matcher can
      // run, and the chip polls at 5 s. So the honest bound is ~30 s, not the
      // lifecycle map's 10 s (which assumed WS-visible legs). Measured: a
      // 15 s budget produced a LATE PASS in run 6-20260729-1120.
      { kind: 'assert', oracle: 'chip-linked', budgetMs: 40_000, manual: 'Pre-Trade chip flips to ✓ LINKED (poller stops). Order-form TP/SL adds the 15 s algo-sweep hop.' },
      { kind: 'auto', action: 'goto-linkage', manual: 'Script opens Linkage.' },
      { kind: 'assert', oracle: 'position-linked-onplan', budgetMs: 20_000, manual: 'Open Positions row shows LINKED + ON-PLAN.' },
      { kind: 'assert', oracle: 'calc-row-absent', budgetMs: 20_000, manual: 'THIS calc (by calc_id) leaves Active Calcs (status → matched).' },
      { kind: 'operator', manual: 'On BINANCE: CLOSE the position at market (cancel leftover TP/SL). Press DONE when flat.' },
      { kind: 'assert', oracle: 'closed-row-present', budgetMs: 40_000, manual: 'History shows the closed row (2s build + 30s poll; pane ↻ to hurry).' },
      { kind: 'assert', oracle: 'closed-row-reason', params: { reason: 'Manual' }, budgetMs: 40_000, manual: 'REASON reads Manual (a market close is MANUAL_OTHER).' },
    ],
    cleanup: [
      'Position flat; leftover TP/SL cancelled on Binance.',
      'No active calc remains (it completed via the position).',
    ],
  },
  {
    id: 'H1b-close-tail',
    group: 'happy',
    title: 'Close an EXISTING linked position → closed row + REASON + calc completes',
    why:
      'The tail of H1 without re-opening: verifies the close path on a position that is ' +
      'ALREADY linked. Covers the +2 s close-row build, the History row, MANUAL_OTHER ' +
      'classification, and the calc reaching completed_via_position.',
    preconditions: [
      'An OPEN position you are willing to close (H1 leaves one LINKED / ON-PLAN).',
      'Set E2E_TRADE_TICKER to that position\'s symbol.',
    ],
    steps: [
      { kind: 'auto', action: 'goto-linkage', manual: 'Script opens Linkage.' },
      { kind: 'assert', oracle: 'position-linked-onplan', budgetMs: 20_000, manual: 'Confirm the position is present and linked before closing.' },
      {
        kind: 'operator',
        manual:
          'On BINANCE: CLOSE the position at market and cancel any leftover TP/SL legs.\n' +
          'Press DONE when flat — or SKIP to keep the position and end the scenario.',
      },
      { kind: 'assert', oracle: 'closed-row-present', budgetMs: 45_000, manual: 'History shows the closed row (2 s build + 30 s poll).' },
      { kind: 'assert', oracle: 'closed-row-reason', budgetMs: 45_000, manual: 'REASON reads Manual — a market close is MANUAL_OTHER.' },
    ],
    cleanup: [
      'Position flat; leftover protective legs cancelled.',
      'History row present with a Manual reason.',
    ],
  },
  {
    id: 'L1-no-calc-unplanned',
    group: 'linkage',
    title: 'Open WITHOUT a calc → position reads UNPLANNED',
    why: 'Proves the engine does not invent a link — and that a naked entry never reaches the inbox.',
    preconditions: ['NO calc for this ticker/side beforehand (that is the point).'],
    steps: [
      { kind: 'operator', manual: 'On BINANCE: open a small position with NO calc first. TP/SL optional. Press DONE when filled.' },
      { kind: 'auto', action: 'goto-linkage', manual: 'Script opens Linkage.' },
      { kind: 'assert', oracle: 'position-unplanned', budgetMs: 15_000, manual: 'Open Positions shows UNPLANNED (+ OFF-PLAN deviation).' },
      { kind: 'operator', manual: 'On BINANCE: close the position. Press DONE when flat.' },
    ],
    cleanup: ['Position flat.'],
  },
  {
    id: 'L2-near-miss-review',
    group: 'linkage',
    title: 'Calc first, then entry with TP/SL OFF by >1 tick → inbox [REVIEW] → manual link',
    why:
      'The manual-link recovery path. NEEDS_MANUAL_REVIEW is STICKY, so calc must come ' +
      'FIRST; a later calc can never rescue the order.',
    preconditions: [
      'Calc FIRST, order second (sticky review status).',
      'Deviate the TP/SL by MORE than one tick so the strict 6/6 matcher rejects it, but keep it within 5% so the loose finder still offers it as a candidate.',
    ],
    steps: [
      { kind: 'auto', action: 'goto-pretrade', manual: 'Open Pre-Trade.' },
      { kind: 'auto', action: 'submit-calc', manual: 'Script submits the calc.' },
      { kind: 'assert', oracle: 'chip-linkable', budgetMs: 15_000, manual: 'Chip shows ✓ LINKABLE.' },
      {
        kind: 'operator',
        manual:
          'On BINANCE: open the position, but set TP and SL a few ticks AWAY from the calc levels.\n' +
          'Press DONE when the entry has filled.',
      },
      { kind: 'auto', action: 'goto-linkage', manual: 'Script opens Linkage.' },
      { kind: 'assert', oracle: 'inbox-review-row', budgetMs: 20_000, manual: 'Inbox shows the order as [REVIEW]; resolver shows N/6 below threshold with the failing legs red.' },
      { kind: 'operator', manual: 'In the UI: select the inbox item, pick the candidate calc, click Link, then confirm with "Link calc" in the dialog. Press DONE.' },
      { kind: 'assert', oracle: 'position-linked-onplan', budgetMs: 20_000, manual: 'Position flips to LINKED (junction replay attaches it post-fill).' },
      { kind: 'operator', manual: 'On BINANCE: close the position and cancel leftover legs. Press DONE when flat.' },
    ],
    cleanup: ['Position flat; inbox clear for this order.'],
  },
  {
    id: 'A1-tpsl-amended',
    group: 'amendment',
    title: 'Move the TP >0.1% → plan badge goes AMENDED (amber)',
    why: 'Drift-compare is the ONLY amendment detector on Binance (a TP edit is a venue cancel+create, so the order_amendments ledger stays EMPTY — never assert the drilldown here).',
    preconditions: [
      'Self-contained: opens its own LINKED position first (A2 then continues from it).',
      'Both legs at the calc levels, single TP — same rules as H1.',
    ],
    steps: [
      { kind: 'auto', action: 'goto-pretrade', manual: 'Open Pre-Trade.' },
      { kind: 'auto', action: 'submit-calc', manual: 'Script submits the calc.' },
      { kind: 'assert', oracle: 'chip-linkable', budgetMs: 20_000, manual: 'Chip shows ✓ LINKABLE — the 5-minute window starts NOW.' },
      {
        kind: 'operator',
        manual:
          'On BINANCE: open a SMALL position at ~the calc entry with TP and SL at the calc levels\n' +
          '(order-form TP/SL is fine — that path is fixed). Press DONE when the entry has filled.',
      },
      { kind: 'auto', action: 'goto-linkage', manual: 'Script opens Linkage.' },
      { kind: 'assert', oracle: 'position-linked-onplan', budgetMs: 45_000, manual: 'Position is LINKED + ON-PLAN before we amend anything.' },
      { kind: 'operator', manual: 'On BINANCE: now MOVE the TP more than 0.1% away from the planned level. Press DONE.' },
      { kind: 'assert', oracle: 'plan-badge-amended', budgetMs: 30_000, manual: 'Plan deviation shows AMENDED (amber) with a tp drift %. Budget covers the 15s algo sync + 5s poll.' },
    ],
    cleanup: ['LEAVE the position open — A2 continues from it.'],
  },
  {
    id: 'A2-sl-removed',
    group: 'amendment',
    title: 'Cancel the SL entirely → OFF-PLAN (red), and it STAYS red in History',
    why: 'Level-2 severity is sticky: the max severity seen during the position life is what History shows, even if you re-add the SL.',
    preconditions: ['Requires a LINKED position with both legs (continue from A1).'],
    steps: [
      { kind: 'operator', manual: 'On BINANCE: CANCEL the SL, leaving the TP live. Press DONE.' },
      { kind: 'assert', oracle: 'plan-badge-offplan', budgetMs: 25_000, manual: 'Plan deviation goes OFF-PLAN (red); TP/SL cell shows <tp> / —.' },
      { kind: 'operator', manual: 'OPTIONAL: re-add the SL. The live badge should relax to AMENDED while History keeps OFF-PLAN. Press DONE.' },
      { kind: 'operator', manual: 'On BINANCE: close the position. Press DONE when flat.' },
      { kind: 'assert', oracle: 'closed-row-present', budgetMs: 40_000, manual: 'History row exists…' },
      { kind: 'assert', oracle: 'plan-badge-offplan', budgetMs: 40_000, manual: '…and its PLAN column is OFF-PLAN (worst-during-life, the sticky stash).' },
    ],
    cleanup: ['Position flat; all legs cancelled.'],
  },
  {
    id: 'X1-partial-scaleout',
    group: 'exit-structure',
    title: 'Partial close → one History row PER closing order',
    why: 'The engine writes one closed_positions row per closing ORDER; only the FINAL row gets the ladder-aware reason, funding sum and calc completion.',
    preconditions: ['Self-contained: opens its own position (no calc needed — this tests close structure).'],
    steps: [
      {
        kind: 'operator',
        manual:
          'On BINANCE: open a SMALL position (size divisible in two — e.g. 0.04, so halves are 0.02).\n' +
          'No calc needed for this scenario. Press DONE when filled.',
      },
      { kind: 'operator', manual: 'On BINANCE: close roughly HALF the position. Press DONE.' },
      { kind: 'assert', oracle: 'closed-row-present', budgetMs: 40_000, manual: 'History shows a PARTIAL row with the partial qty.' },
      { kind: 'operator', manual: 'On BINANCE: close the REMAINDER. Press DONE when flat.' },
      { kind: 'assert', oracle: 'closed-row-present', budgetMs: 40_000, manual: 'A SECOND row appears (one per closing order — not a single merged row).' },
    ],
    cleanup: ['Position flat.'],
  },
  {
    id: 'X2-hedge-both-sides',
    group: 'exit-structure',
    title: 'Long AND short the same symbol → independent rows, no cross-contamination',
    why: 'Hedge mode keys everything by (symbol, side). One leg amended must NOT move the other leg badge — a direct regression assertion.',
    preconditions: [
      'Account must stay in HEDGE mode (a one-way switch breaks tpid attribution — known latent gap).',
      'TWO calcs — one long, one short (they do not supersede each other; supersede is scoped per side).',
    ],
    steps: [
      { kind: 'operator', manual: 'On BINANCE: open a SMALL LONG and a SMALL SHORT on the same symbol (>2s apart — duplicate-order detector). Press DONE.' },
      { kind: 'auto', action: 'goto-linkage', manual: 'Script opens Linkage.' },
      { kind: 'assert', oracle: 'position-unplanned', budgetMs: 20_000, manual: 'BOTH legs appear as separate rows (selected by symbol AND side badge).' },
      { kind: 'operator', manual: 'On BINANCE: amend the TP on ONE leg only. Press DONE.' },
      { kind: 'assert', oracle: 'plan-badge-amended', budgetMs: 25_000, manual: 'Only the amended leg changes badge — the other stays put.' },
      { kind: 'operator', manual: 'On BINANCE: close BOTH legs. Press DONE when flat.' },
    ],
    cleanup: ['Both legs flat.'],
  },
];

export const GROUPS = ['happy', 'linkage', 'amendment', 'exit-structure'] as const;
