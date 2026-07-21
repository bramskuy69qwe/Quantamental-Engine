/* ─────────────────────────────────────────────────────────────────────────
   link-data.jsx — one coherent mock account shared by all 3 cockpit
   directions + every supporting artboard. Binance Futures, equity 82.20 USDT,
   1% risk sized off the SL range, 5-min (300s) link window.

   Causal chain the spec tracks: calc → order → fill → position →
   amendment → close → funding. Every id below threads through that chain so
   the lifecycle view (Direction C) and the per-criterion diff (Needs-Link)
   read from the same source.
   ───────────────────────────────────────────────────────────────────────── */

const NOW = Date.now();
const sec = (s) => NOW + s * 1000;   // expiry helper for live countdowns

const ACCOUNT = {
  id: 1, name: 'Binance Futures', venue: 'BINANCE', mode: 'LIVE',
  equity: 82.20, available: 43.81, window_seconds: 300, risk_pct: 1.0,
  clock_skew_tolerance_sec: 10, entry_tolerance_pct: 0.25,
  deviation: { yellow_pct: 5, red_pct: 15, size_pct: 10 },
  drift_tolerance_pct: 0.5,
  notify: { calc_expired: true, position_liquidated: true, position_size_drift: true,
            duplicate_order_detected: true, near_replacement_match: true },
};

/* ── Active / recent calcs (pre_trade_log) ─────────────────────────────── */
const CALCS = [
  { id: 'CALC-7f3a', sym: 'BTCUSDT', dir: 'LONG',  entry: 93400, tp: 95200, sl: 92600,
    size: 0.0010, status: 'active', expiry: sec(252), window: 300, model: 'momentum_v3',
    tags: ['asia_session'], op: 'op-1', r: 2.25 },
  { id: 'CALC-3b21', sym: 'BTCUSDT', dir: 'LONG',  entry: 93100, tp: 94800, sl: 92400,
    size: 0.0011, status: 'active', expiry: sec(168), window: 300, model: 'mean_rev_v2',
    tags: [], op: 'op-1', r: 2.42 },
  { id: 'CALC-8a12', sym: 'SOLUSDT', dir: 'SHORT', entry: 142.30, tp: 138.00, sl: 144.50,
    size: 0.36,   status: 'active', expiry: sec(54),  window: 300, model: 'trend_v1',
    tags: ['low_vol'], op: 'op-1', r: 1.95 },
  { id: 'CALC-5d91', sym: 'INJUSDT', dir: 'LONG',  entry: 31.18, tp: 31.95, sl: 30.80,
    size: 2.10,   status: 'active', expiry: sec(190), window: 300, model: 'breakout_v1',
    tags: [], op: 'op-1', r: 2.03 },
  { id: 'CALC-2e78', sym: 'MKRUSDT', dir: 'LONG',  entry: 2658.0, tp: 2690.0, sl: 2642.0,
    size: 0.050,  status: 'matched', expiry: sec(-40), window: 300, model: 'momentum_v3',
    tags: ['ny_session'], op: 'op-1', r: 2.00 },
  /* matched calcs behind the live position book + recent closes — every
     LINKED row resolves to one of these (referential integrity for the
     lifecycle drill-down). */
  { id: 'CALC-6b02', sym: 'BTCUSDT', dir: 'LONG',  entry: 93400, tp: 94100, sl: 93180,
    size: 0.012,  status: 'matched', expiry: sec(-4800), window: 300, model: 'momentum_v3',
    tags: [], op: 'op-1', r: 3.18 },
  { id: 'CALC-9d17', sym: 'ETHUSDT', dir: 'SHORT', entry: 3216.0, tp: 3185.0, sl: 3242.0,
    size: 0.55,   status: 'matched', expiry: sec(-7300), window: 300, model: 'mean_rev_v2',
    tags: [], op: 'op-1', r: 1.19 },
  { id: 'CALC-2c55', sym: 'SOLUSDT', dir: 'LONG',  entry: 138.40, tp: 141.10, sl: 137.20,
    size: 2.4,    status: 'matched', expiry: sec(-5400), window: 300, model: 'trend_v1',
    tags: [], op: 'op-1', r: 2.25 },
  { id: 'CALC-7e63', sym: 'LINKUSDT', dir: 'SHORT', entry: 21.86, tp: 21.20, sl: 22.10,
    size: 12.6,   status: 'matched', expiry: sec(-2900), window: 300, model: 'breakout_v1',
    tags: [], op: 'op-1', r: 2.75 },
  { id: 'CALC-3c19', sym: 'BTCUSDT', dir: 'SHORT', entry: 93600, tp: 93140, sl: 93830,
    size: 0.018,  status: 'matched', expiry: sec(-12100), window: 300, model: 'momentum_v3',
    tags: [], op: 'op-1', r: 2.00 },
  { id: 'CALC-4a88', sym: 'SOLUSDT', dir: 'SHORT', entry: 142.30, tp: 138.00, sl: 144.50,
    size: 0.34,   status: 'matched', expiry: sec(-310), window: 300, model: 'trend_v1',
    tags: [], op: 'op-1', r: 1.95 },
  { id: 'CALC-9c44', sym: 'LABUSDT', dir: 'LONG',  entry: 1.842, tp: 1.910, sl: 1.808,
    size: 23.0,   status: 'expired', expiry: sec(-95), window: 300, model: 'breakout_v1',
    tags: [], op: 'op-1', r: 2.00 },
];

/* ── Orders — link_status drives every badge in the engine ─────────────── */
const ORDERS = [
  { id: 1188, sym: 'BTCUSDT', dir: 'LONG', type: 'LIMIT', price: 93420, size: 0.0010,
    ts_age_s: 41, link_status: 'NEEDS_MANUAL_REVIEW', calc_id: null, op: 'op-1' },
  { id: 1186, sym: 'MKRUSDT', dir: 'LONG', type: 'LIMIT', price: 2658.4, size: 0.050,
    ts_age_s: 312, link_status: 'LINKED', calc_id: 'CALC-2e78', op: 'op-1' },
  { id: 1175, sym: 'BTCUSDT', dir: 'LONG', type: 'LIMIT', price: 92980, size: 0.0010,
    ts_age_s: 880, link_status: 'UNLINKED', calc_id: null, op: 'op-1' },
  { id: 1190, sym: 'LABUSDT', dir: 'SHORT', type: 'MARKET', price: 1.846, size: 21.0,
    ts_age_s: 22, link_status: 'UNPLANNED', calc_id: null, op: 'op-1' },
  { id: 1181, sym: 'SOLUSDT', dir: 'SHORT', type: 'LIMIT', price: 142.28, size: 0.34,
    ts_age_s: 540, link_status: 'LINKED', calc_id: 'CALC-4a88', op: 'op-1' },
];

/* ── Needs-link queue: per-criterion match audit per candidate ──────────
   criterion order = ticker, direction, window, entry, tp, sl (spec §4.1).
   matched=false on the criterion that knocked the order out of 6/6.        */
const NEEDS_LINK = [
  {
    order_id: 1188, sym: 'BTCUSDT', dir: 'LONG', type: 'LIMIT', price: 93420,
    size: 0.0010, notional: 93.42, age_s: 41, ts: '20:07:55', operator: 'op-1',
    client_oid: 'x-QT-7f3a91', status: 'NEEDS_MANUAL_REVIEW',
    candidates: [
      { calc_id: 'CALC-7f3a', model: 'momentum_v3', created: '20:07:35', age_s: 61, r: 2.25, tags: ['asia_session'], score: '5 / 6', best: true, released: false,
        crit: [
          { k: 'ticker',    calc: 'BTCUSDT', order: 'BTCUSDT', tol: '—',        ok: true },
          { k: 'direction', calc: 'LONG',    order: 'LONG',    tol: '—',        ok: true },
          { k: 'window',    calc: 'Δ 41s',   order: '≤ 310s',  tol: '300+10s',  ok: true },
          { k: 'entry',     calc: '93,400',  order: '93,420',  tol: '0.25%',    ok: true,  diff: '+0.021%' },
          { k: 'tp',        calc: '95,200',  order: '95,200',  tol: '1 tick',   ok: true,  diff: '0 ticks' },
          { k: 'sl',        calc: '92,600',  order: '92,580',  tol: '1 tick',   ok: false, diff: '2 ticks' },
        ] },
      { calc_id: 'CALC-3b21', model: 'mean_rev_v2', created: '20:07:43', age_s: 53, r: 2.42, tags: [], score: '3 / 6', best: false, released: false,
        crit: [
          { k: 'ticker',    calc: 'BTCUSDT', order: 'BTCUSDT', tol: '—',        ok: true },
          { k: 'direction', calc: 'LONG',    order: 'LONG',    tol: '—',        ok: true },
          { k: 'window',    calc: 'Δ 41s',   order: '≤ 310s',  tol: '300+10s',  ok: true },
          { k: 'entry',     calc: '93,100',  order: '93,420',  tol: '0.25%',    ok: false, diff: '+0.344%' },
          { k: 'tp',        calc: '94,800',  order: '95,200',  tol: '1 tick',   ok: false, diff: '40 ticks' },
          { k: 'sl',        calc: '92,400',  order: '92,580',  tol: '1 tick',   ok: false, diff: '18 ticks' },
        ] },
    ],
  },
  {
    // operator chased a SHORT entry past the loose-entry band (LIMIT → order.price)
    order_id: 1192, sym: 'SOLUSDT', dir: 'SHORT', type: 'LIMIT', price: 142.95,
    size: 0.34, notional: 48.60, age_s: 88, ts: '20:07:08', operator: 'op-1',
    client_oid: 'x-QT-8a12c4', status: 'NEEDS_MANUAL_REVIEW',
    candidates: [
      { calc_id: 'CALC-8a12', model: 'trend_v1', created: '20:05:53', age_s: 163, r: 1.95, tags: ['low_vol'], score: '5 / 6', best: true, released: false,
        crit: [
          { k: 'ticker',    calc: 'SOLUSDT', order: 'SOLUSDT', tol: '—',       ok: true },
          { k: 'direction', calc: 'SHORT',   order: 'SHORT',   tol: '—',       ok: true },
          { k: 'window',    calc: 'Δ 88s',   order: '≤ 310s',  tol: '300+10s', ok: true },
          { k: 'entry',     calc: '142.30',  order: '142.95',  tol: '0.25%',   ok: false, diff: '+0.457%' },
          { k: 'tp',        calc: '138.00',  order: '138.00',  tol: '1 tick',  ok: true,  diff: '0 ticks' },
          { k: 'sl',        calc: '144.50',  order: '144.50',  tol: '1 tick',  ok: true,  diff: '0 ticks' },
        ] },
    ],
  },
  {
    // bare entry — no TP/SL on the order yet (Q27: nullable → manual-link)
    order_id: 1195, sym: 'INJUSDT', dir: 'LONG', type: 'LIMIT', price: 31.18,
    size: 2.10, notional: 65.48, age_s: 150, ts: '20:06:06', operator: 'op-1',
    client_oid: 'x-QT-5d9100', status: 'NEEDS_MANUAL_REVIEW',
    candidates: [
      { calc_id: 'CALC-5d91', model: 'breakout_v1', created: '20:03:46', age_s: 290, r: 2.03, tags: [], score: '4 / 6', best: true, released: false,
        crit: [
          { k: 'ticker',    calc: 'INJUSDT', order: 'INJUSDT', tol: '—',       ok: true },
          { k: 'direction', calc: 'LONG',    order: 'LONG',    tol: '—',       ok: true },
          { k: 'window',    calc: 'Δ 150s',  order: '≤ 310s',  tol: '300+10s', ok: true },
          { k: 'entry',     calc: '31.18',   order: '31.18',   tol: '0.25%',   ok: true,  diff: '0.000%' },
          { k: 'tp',        calc: '31.95',   order: '—',       tol: '1 tick',  ok: false, diff: 'no tp on order' },
          { k: 'sl',        calc: '30.80',   order: '—',       tol: '1 tick',  ok: false, diff: 'no sl on order' },
        ] },
    ],
  },
  {
    // MARKET — entry compared to avg fill (§4.1); fill slipped past the band
    order_id: 1198, sym: 'BTCUSDT', dir: 'LONG', type: 'MARKET', price: 93720,
    size: 0.0010, notional: 93.72, age_s: 19, ts: '20:08:17', operator: 'op-1',
    client_oid: 'x-QT-7f3a92', status: 'NEEDS_MANUAL_REVIEW',
    candidates: [
      { calc_id: 'CALC-7f3a', model: 'momentum_v3', created: '20:07:35', age_s: 61, r: 2.25, tags: ['asia_session'], score: '5 / 6', best: true, released: false,
        crit: [
          { k: 'ticker',    calc: 'BTCUSDT', order: 'BTCUSDT', tol: '—',            ok: true },
          { k: 'direction', calc: 'LONG',    order: 'LONG',    tol: '—',            ok: true },
          { k: 'window',    calc: 'Δ 19s',   order: '≤ 310s',  tol: '300+10s',      ok: true },
          { k: 'entry',     calc: '93,400',  order: '93,720',  tol: '0.25% avg-fill', ok: false, diff: '+0.343%' },
          { k: 'tp',        calc: '95,200',  order: '95,200',  tol: '1 tick',       ok: true,  diff: '0 ticks' },
          { k: 'sl',        calc: '92,600',  order: '92,600',  tol: '1 tick',       ok: true,  diff: '0 ticks' },
        ] },
    ],
  },
  {
    order_id: 1175, sym: 'BTCUSDT', dir: 'LONG', type: 'LIMIT', price: 92980,
    size: 0.0010, notional: 92.98, age_s: 880, ts: '19:53:56', operator: 'op-1',
    client_oid: 'x-QT-1175ab', status: 'UNLINKED',
    candidates: [],   // window long expired; operator downgraded. No live candidates.
  },
];

/* ── Open positions — deviation badge per row (spec §4.4) ───────────────
   dev: 'green'|'yellow'|'red'.  tp_drift_pct / sl_drift_pct power the
   numeric drift on the badge (the variant the operator picked).            */
const POSITIONS = [
  { id: 'P-3041', sym: 'BTCUSDT', dir: 'LONG', size: 0.012, entry: 93412.1, mark: 93580.4,
    notional: 1123.0, upnl: 2.02, fees: 0.04, mfe: 2.31, mae: -0.44,
    tp_plan: 94100.0, tp_live: 94100.0, sl_plan: 93180.0, sl_live: 93180.0,
    dev: 'green', size_delta_pct: 0.0, tp_drift_pct: 0.0, sl_drift_pct: 0.0, amendments: 0,
    calc_id: 'CALC-6b02', link: 'LINKED', lifecycle: 'a3f-9341',
    funding_rate: 0.00012, funding_cum: -0.012, funding_next: '00:00' },
  { id: 'P-3038', sym: 'ETHUSDT', dir: 'SHORT', size: 0.55, entry: 3214.5, mark: 3208.2,
    notional: 1764.5, upnl: 3.47, fees: 0.09, mfe: 4.12, mae: -1.05,
    tp_plan: 3185.0, tp_live: 3172.0, sl_plan: 3242.0, sl_live: 3242.0,
    dev: 'yellow', size_delta_pct: 0.0, tp_drift_pct: -0.41, sl_drift_pct: 0.0, amendments: 1,
    amends: [{ ts: '18:55', field: 'tp', old: 3185.0, neo: 3172.0, pct: -0.41 }],
    calc_id: 'CALC-9d17', link: 'LINKED', lifecycle: 'b71-3214',
    funding_rate: 0.00008, funding_cum: 0.031, funding_next: '00:00' },
  { id: 'P-3040', sym: 'SOLUSDT', dir: 'LONG', size: 2.4, entry: 138.42, mark: 139.21,
    notional: 334.1, upnl: 1.90, fees: 0.03, mfe: 2.21, mae: -0.38,
    tp_plan: 141.10, tp_live: 141.10, sl_plan: 137.20, sl_live: 137.20,
    dev: 'green', size_delta_pct: 0.0, tp_drift_pct: 0.0, sl_drift_pct: 0.0, amendments: 0,
    calc_id: 'CALC-2c55', link: 'LINKED', lifecycle: 'c44-1384',
    funding_rate: -0.00004, funding_cum: 0.004, funding_next: '00:00' },
  { id: 'P-3044', sym: 'AVAXUSDT', dir: 'LONG', size: 8.2, entry: 42.18, mark: 42.04,
    notional: 344.7, upnl: -1.15, fees: 0.02, mfe: 0.31, mae: -1.29,
    tp_plan: null, tp_live: null, sl_plan: null, sl_live: null,
    dev: 'red', size_delta_pct: null, tp_drift_pct: null, sl_drift_pct: null, amendments: 0,
    calc_id: null, link: 'UNPLANNED', lifecycle: 'c09-4218',
    funding_rate: 0.00006, funding_cum: -0.008, funding_next: '00:00' },
  { id: 'P-3046', sym: 'LINKUSDT', dir: 'SHORT', size: 12.6, entry: 21.84, mark: 21.92,
    notional: 276.2, upnl: -1.01, fees: 0.02, mfe: 0.44, mae: -1.12,
    tp_plan: 21.20, tp_live: 21.20, sl_plan: 22.10, sl_live: 22.10,
    dev: 'green', size_delta_pct: 0.0, tp_drift_pct: 0.0, sl_drift_pct: 0.0, amendments: 0,
    calc_id: 'CALC-7e63', link: 'LINKED', lifecycle: 'd58-2184',
    funding_rate: 0.00009, funding_cum: 0.012, funding_next: '00:00' },
];

/* ── Recent closes — exit_reason enum (spec §3.4). reason=null ⇒ the
   manual-close nudge: engine saw an opposite-side close with no calc and
   wants a category (never blocks; can be set later from History).          */
const CLOSES = [
  { id: 'C-2209', sym: 'BTCUSDT', dir: 'SHORT', pnl: 1.93, pct: 0.47, exit_reason: 'TP_PLANNED',
    entry: 93580.4, exit: 93142.1, hold: '3h 22m', realized_r: 1.85, planned_r: 2.00,
    amendments: 0, funding: -0.012, note: null, ts: '17:25', calc_id: 'CALC-3c19', lifecycle: 'e22-9311' },
  { id: 'C-2207', sym: 'SOLUSDT', dir: 'SHORT', pnl: -0.62, pct: -0.74, exit_reason: 'SL_AMENDED',
    entry: 143.10, exit: 144.62, hold: '12m 03s', realized_r: -0.95, planned_r: 1.95,
    amendments: 2, funding: 0.018, note: 'trailed stop up, clipped', ts: '16:48', calc_id: 'CALC-1b56', lifecycle: 'd14-7740' },
  { id: 'C-2204', sym: 'INJUSDT', dir: 'SHORT', pnl: 0.34, pct: 0.55, exit_reason: null,
    entry: 31.42, exit: 31.20, hold: '6m 18s', realized_r: 0.60, planned_r: null,
    amendments: 0, funding: 0.003, note: null, ts: '16:12', calc_id: null, lifecycle: 'c09-2940', pending_reason: true },
  { id: 'C-2201', sym: 'LABUSDT', dir: 'LONG', pnl: 0.08, pct: 0.42, exit_reason: 'MANUAL_NEW_OPPORTUNITY',
    entry: 1.838, exit: 1.846, hold: '1m 55s', realized_r: 0.21, planned_r: 2.00,
    amendments: 0, funding: 0.000, note: 'flipped to short setup', ts: '15:30', calc_id: 'CALC-0f22', lifecycle: 'a90-5521' },
  { id: 'C-2211', sym: 'SOLUSDT', dir: 'SHORT', pnl: -0.18, pct: -0.34, exit_reason: null,
    entry: 140.80, exit: 141.30, hold: '3m 12s', realized_r: -0.42, planned_r: null,
    amendments: 0, funding: 0.002, note: null, ts: '17:08', calc_id: null, lifecycle: 'f33-1180', pending_reason: true },
  { id: 'C-2213', sym: 'LABUSDT', dir: 'LONG', pnl: 0.22, pct: 1.10, exit_reason: null,
    entry: 1.835, exit: 1.855, hold: '2m 40s', realized_r: 0.55, planned_r: null,
    amendments: 0, funding: 0.000, note: null, ts: '16:55', calc_id: null, lifecycle: 'g70-2204', pending_reason: true },
];

/* ── Funding book — 4 scopes the tracker surfaces (spec §3.2) ───────────
   Binance settles every 8h at 00:00 / 08:00 / 16:00 UTC.
   pays: who is charged at this rate sign (LONG pays when rate>0).          */
const FUNDING = {
  next_settlement: '00:00 UTC',
  countdown_s: 13920,                      // ~3h 52m to next settlement
  schedule: ['00:00', '08:00', '16:00'],
  rows: [
    { pos: 'P-3041', sym: 'BTCUSDT', dir: 'LONG',  size: 0.012, notional: 1123.0,
      rate: 0.00012, pays: 'you',   est_next: -0.134, cum: -0.012 },
    { pos: 'P-3038', sym: 'ETHUSDT', dir: 'SHORT', size: 0.55,  notional: 1764.5,
      rate: 0.00008, pays: 'venue', est_next: 0.141,  cum: 0.031 },
    { pos: 'P-3040', sym: 'SOLUSDT', dir: 'LONG',  size: 2.4,   notional: 334.1,
      rate: -0.00004, pays: 'venue', est_next: 0.013, cum: 0.004 },
    { pos: 'P-3044', sym: 'AVAXUSDT', dir: 'LONG', size: 8.2,   notional: 344.7,
      rate: 0.00006, pays: 'you',   est_next: -0.021, cum: -0.008 },
    { pos: 'P-3046', sym: 'LINKUSDT', dir: 'SHORT', size: 12.6, notional: 276.2,
      rate: 0.00009, pays: 'venue', est_next: 0.025,  cum: 0.012 },
  ],
  net_next: 0.024,     // sum est_next
  net_cum: 0.027,
};

/* exit_reason enum → label + tone, for the badge + reason modal */
const EXIT_REASONS = {
  TP_PLANNED:            { label: 'TP · plan',     tone: 'ok'   },
  TP_AMENDED:            { label: 'TP · amended',  tone: 'warn' },
  SL_PLANNED:            { label: 'SL · plan',     tone: 'err'  },
  SL_AMENDED:            { label: 'SL · amended',  tone: 'warn' },
  TP_LADDER_COMPLETE:    { label: 'TP ladder',     tone: 'ok'   },
  MIXED:                 { label: 'Mixed',         tone: 'warn' },
  MANUAL_INTERVENTION:   { label: 'Intervention',  tone: 'mag'  },
  MANUAL_DISCIPLINE_BREAK:{ label: 'Discipline',   tone: 'err'  },
  MANUAL_NEW_OPPORTUNITY:{ label: 'New opp',       tone: 'blue' },
  MANUAL_OTHER:          { label: 'Manual',        tone: 'mute' },
  LIQUIDATION:           { label: 'Liquidation',   tone: 'err'  },
  ADL:                   { label: 'ADL',           tone: 'err'  },
  EXPIRED:               { label: 'Expired',       tone: 'mute' },
};

const MANUAL_REASONS = [
  { key: 'INTERVENTION',   label: 'Intervention',    hint: 'Judgement call — exited against the plan deliberately' },
  { key: 'DISCIPLINE_BREAK',label: 'Discipline break', hint: 'Fear / impatience — broke the plan, logging it honestly' },
  { key: 'NEW_OPPORTUNITY',label: 'New opportunity', hint: 'Freed capital for a better setup' },
  { key: 'OTHER',          label: 'Other',           hint: 'Free-text rationale below' },
];

Object.assign(window, {
  L_NOW: NOW, L_ACCOUNT: ACCOUNT, L_CALCS: CALCS, L_ORDERS: ORDERS,
  L_NEEDS_LINK: NEEDS_LINK, L_POSITIONS: POSITIONS, L_CLOSES: CLOSES,
  L_FUNDING: FUNDING, L_EXIT_REASONS: EXIT_REASONS, L_MANUAL_REASONS: MANUAL_REASONS,
});
