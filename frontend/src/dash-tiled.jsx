/* v3.0 — Dashboard "TILED WORKSPACE" (P1). Ported from the Meridian reference
   and WIRED to real engine data:
     · initial state ← GET /api/dashboard/snapshot
     · live values   ← SSE (window.QE_SSE): equity_update / position_update / dd_state
     · engine log     ← GET /api/engine/log?since= (poll)
     · macro signals  ← GET /api/regime/signals/latest (poll)
     · halt/state      ← GET /api/state (poll, incl. G-O2 `halted`)
     · equity curve   ← GET /api/dashboard/equity_ohlc
   The mock random-walk engine (QE_LIVE/QE_POS), Math.random bars and MOCK.*
   are stripped. TiledGrid stays React.memo (renders ONCE) so GridStack owns the
   DOM; live values flow through leaf LiveValue spans (the "target the value"
   no-flicker contract) fed by a module-level QE_DASH store. */

/* ── QE_DASH — the Dashboard live-data store (snapshot + SSE + polls) ────── */
const QE_DASH = (function () {
  const state = {
    equity: {}, risk: {}, journal: {}, regime: null,
    positions: [],          // snapshot rows; SSE position_update refreshes upnl/pct
    st: {},                 // /api/state (halted, blocked, dd_state, weekly_pnl_state, …)
    // UI state that must be read OUTSIDE the tile that raises it: ModelDialog is
    // position:absolute and Pane is position:relative, so a dialog rendered
    // inside a tile would be CLIPPED to it. The flag lives here so the trigger
    // (RiskMonitorPane, deep in the memoized grid) and the page-level host can
    // meet without making DashTiled/TiledGrid subscribers.
    ui: { ddOverride: false },
    macro: [],              // /api/regime/signals/latest
    log: [],                // engine-log lines, newest-first for the prepend feed
    logCursor: 0,
    loaded: false,
    // per-source data-pipe state for qeFootState (DESIGN.md §5 4-tier foots)
    net: { snapshot: {}, st: {}, macro: {}, log: {} },
  };
  const subs = new Set();
  const notify = () => subs.forEach((f) => { try { f(); } catch (e) { /* isolate */ } });

  /* Poll interval per pipe, keyed by its net key. ONE literal per pipe: the
     setInterval below and the read deadline in _json both read it, so the
     deadline cannot drift away from the cadence it is derived from (pinned by
     tests/test_net_deadline.py against the setInterval calls themselves). */
  const _POLL = { st: 5000, log: 4000, macro: 60000, snapshot: 15000 };

  // net-tracking wrapper over the shared _ptJson plumbing (P8 wave 2: the
  // in-file fetch duplicate collapsed onto primitives' _ptJson — audit N7).
  // Every read carries its pipe's DEADLINE (see _POLL above), so a hung
  // endpoint can no longer hold this net entry at its last-good value while
  // the tiles above render hours-old risk numbers.
  async function _json(url, key) {
    const t0 = performance.now();
    try {
      const d = await _ptJson(url, qePollDeadline(_POLL[key]));
      if (key) state.net[key] = { err: null, ms: performance.now() - t0 };
      return d;
    } catch (err) {
      if (key) { state.net[key] = { ...state.net[key], err }; notify(); }
      throw err;
    }
  }

  // HEDGE-safe row key (audit L3-F1 twin): a symbol can hold a LONG and a
  // SHORT PositionInfo simultaneously — never key by symbol alone.
  const _sideKey = (s) => ((s || '').toLowerCase().startsWith('l') ? 'L' : 'S');
  const _rowKey = (sym, side) => sym + '|' + _sideKey(side);

  async function loadSnapshot() {
    try {
      const s = await _json('/api/dashboard/snapshot', 'snapshot');
      state.equity = s.equity || {};
      state.risk = s.risk || {};
      state.journal = s.journal || {};
      state.regime = s.regime || null;
      if (Array.isArray(s.positions)) {
        state.positions = s.positions.map((r) => ({ ...r, _k: _rowKey(r.sym, r.side) }));
      }
      state.loaded = true;
      notify();
    } catch (e) { /* keep prior state */ }
  }
  async function loadState() {
    try { state.st = await _json('/api/state', 'st'); notify(); } catch (e) { /* keep */ }
  }
  async function loadMacro() {
    try { const m = await _json('/api/regime/signals/latest', 'macro'); state.macro = m.signals || []; notify(); }
    catch (e) { /* keep */ }
  }
  async function loadLog() {
    try {
      const d = await _json('/api/engine/log?since=' + state.logCursor + '&limit=60', 'log');
      const lines = d.lines || [];
      if (lines.length) {
        // server returns oldest-first; prepend newest for the feed display
        state.log = [...lines.slice().reverse(), ...state.log].slice(0, 60);
        state.logCursor = d.latest_id || state.logCursor;
        notify();
      } else if (d.latest_id != null) {
        state.logCursor = d.latest_id;
        notify();   // quiet poll still refreshes net.log (foot recovery) [foot-audit LOW-5]
      }
    } catch (e) { /* keep */ }
  }

  function _wireSSE() {
    if (typeof window.QE_SSE === 'undefined') return;
    window.QE_SSE.onChannel('equity_update', (p) => {
      state.equity = {
        ...state.equity,
        total_equity:     p.total_equity     != null ? p.total_equity     : state.equity.total_equity,
        available_margin: p.available_margin != null ? p.available_margin : state.equity.available_margin,
        unrealized_pnl:   p.unrealized_pnl   != null ? p.unrealized_pnl   : state.equity.unrealized_pnl,
      };
      notify();
    });
    window.QE_SSE.onChannel('position_update', (p) => {
      // The recalc frame publishes ALL open positions, so it is authoritative
      // for MEMBERSHIP: surviving symbols keep their snapshot-enriched static
      // fields (mark/entry/tp/sl/mfe/mae), closed symbols drop immediately, new
      // symbols get minimal rows until the next snapshot enriches them.
      const list = Array.isArray(p.positions) ? p.positions : [];
      // hedge-safe: key the merge by symbol|side, never symbol alone
      // (audit L3-F1: the symbol-keyed merge stamped one leg's uPnL onto
      // both legs of a hedge pair).
      const prev = {};
      state.positions.forEach((r) => { prev[r._k || _rowKey(r.sym, r.side)] = r; });
      state.positions = list.map((x) => {
        const k = _rowKey(x.symbol, x.side);
        const r = prev[k] || {};
        const upnl = x.upnl != null ? x.upnl : r.upnl;
        const notional = r.notional || 0;
        const pct = notional ? +(upnl / Math.abs(notional) * 100).toFixed(2) : (r.pct || 0);
        return { ...r, _k: k, sym: x.symbol, side: x.side != null ? x.side : r.side,
          size: x.size != null ? x.size : r.size, upnl, pct };
      });
      notify();
    });
    window.QE_SSE.onChannel('dd_state', (p) => {
      state.st = { ...state.st,
        dd_state: p.to != null ? p.to : state.st.dd_state,
        drawdown: p.drawdown != null ? p.drawdown : state.st.drawdown };
      notify();
    });
  }

  let started = false, wired = false;
  const _timers = [];
  /* The deadline above bounds a lie only while a request is OUTSTANDING. It
     cannot reach the other half of the same seam: a hidden page's timers are
     throttled to ~1/min (and a frozen one's stop entirely), so no request is
     outstanding at all and the last-painted frame keeps its `connected [12ms]`
     foot over minute-old numbers. The operator's actual pattern makes this the
     common case — they place in Quantower and alt-tab back to a dashboard that
     has been in the background. Refreshing on return beats labelling it: one
     round-trip replaces the stale frame instead of annotating it. (A staleness
     timestamp cannot cover this either — the clock that would evaluate it is
     throttled by exactly the same rule.) */
  let _unVisible = null;
  function refreshAll() { loadSnapshot(); loadState(); loadMacro(); loadLog(); }
  function start() {
    if (!wired) { _wireSSE(); wired = true; }   // SSE stays wired across mounts (idempotent)
    if (started) return;
    started = true;
    _unVisible = qeOnVisible(refreshAll);
    refreshAll();
    _timers.push(setInterval(loadState, _POLL.st));
    _timers.push(setInterval(loadLog, _POLL.log));
    _timers.push(setInterval(loadMacro, _POLL.macro));
    _timers.push(setInterval(loadSnapshot, _POLL.snapshot));  // reconcile non-SSE tiles
  }
  function stop() {   // clear the polls when the Dashboard unmounts (M1); SSE stays wired
    _timers.forEach(clearInterval);
    _timers.length = 0;
    if (_unVisible) { _unVisible(); _unVisible = null; }
    started = false;
    // `ui` is module-level, so a dialog left open would re-raise itself on the
    // next visit to the Dashboard.
    state.ui = { ddOverride: false };
  }

  function setUi(patch) { state.ui = { ...state.ui, ...patch }; notify(); }

  // refreshState: an out-of-band /api/state pull, so a write the operator just
  // made reflects without waiting out the 5 s poll. Fire-and-forget — the
  // DD-override dialog closes immediately and the badge flips when it lands.
  return { start, stop, refreshState: loadState, setUi, get: () => state,
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); } };
})();

/* Subscribe a component to QE_DASH updates. Used at the LEAF level so the
   memoized TiledGrid never re-renders. */
/* Pane foot over one OR MORE pipes: derive the 4-tier model per pipe off the
 * tracked {err, ms} (qeFootState from primitives), then report the WORST.
 *
 * A pane fed by more than one pipe must report the worst of them. Naming only
 * one leaves the others free to fail behind a green `connected`: Risk Monitor
 * reported /api/state while FOUR of its five readouts (exposure, drawdown,
 * weekly loss, positions) come from /api/dashboard/snapshot, so a snapshot
 * outage painted all four stale under an affirmative healthy foot. An
 * affirmative WRONG signal is worse than no signal — the operator who learned
 * to trust the foot is worse off than one who never had it.
 *
 * ★ hasData IS PER-PIPE, AND IT IS ONLY MEANINGFUL ONCE THE PIPE HAS ANSWERED.
 * qeFootState pivots BOTH decisions on hasData: tier 4 is gated behind
 * `loading && !hasData` (primitives.jsx:641) and the tier-2-vs-3 split is
 * `if (hasData)` (:645). Two drafts of this helper died on that:
 *
 *   1. ONE OR'd hasData for N pipes judged every pipe by another pipe's data.
 *   2. Per-pipe hasData, but taken at face value — and the callers' hasData
 *      expressions are PROXIES with a SECOND WRITER. SSE writes st.dd_state
 *      and equity.total_equity straight into the store, so a /api/state that
 *      has hung since page load still satisfied `d.st.dd_state != null`.
 *
 * Both produced the same observable, and it is the one this helper exists to
 * kill: a pipe that had NEVER answered rendered green `connected [Nms]` with
 * the ms measured on its healthy sibling. A hung /api/state (blocked loop,
 * deadlocked DB, black-holed TCP) never filled net.st, while Risk Monitor
 * showed ADVISORY/OK badges built from an empty `st` — during a real enforced
 * DD halt, with every affirmative signal on the tile saying otherwise. Hence
 * `answered` below: a pipe that has not reported has no data OF ITS OWN,
 * whatever else painted the view. The 2-vs-3 rule is per-PANE in the doctrine
 * but the DATA is per-PIPE.
 *
 * ⚠ `answered` IS STILL A LATCH, AND MUST NOT BE RELIED ON AS A FRESHNESS
 * TEST. It answers "has this pipe EVER reported", never "recently". What
 * bounds the gap is upstream: every read now carries a DEADLINE (primitives'
 * _ptJson + qePollDeadline, wired to _POLL above), so a pipe that hangs
 * rejects within its own poll interval and lands in `n.err` — which this
 * helper already ranks correctly. Before that deadline existed, a promise that
 * never settled ran neither branch and this entry kept `{err:null, ms}`
 * forever: 24 h of hanging still read `ok · connected [12ms]`. Anything added
 * here that infers freshness from the net entry alone is re-deriving a fact
 * this file does not hold — the timestamp is not missing by oversight, it was
 * judged the wrong layer (DESIGN.md § the deadline rule).
 *
 * Reported tone = worst by _FOOT_RANK; within a tone a real FAILURE outranks
 * mere slowness, then the slower pipe wins. A slow pipe surfaces on its own
 * (>500ms is already a warn), so no max() is needed.
 */
/* Worst-first severity. NOT a plain tone ranking: tone `warn` covers two very
 * different states — "errored · showing last data" and a merely slow
 * "delayed [Nms]" — and both make an AFFIRMATIVE claim that data is on screen.
 * A pipe that has never answered has none, so it outranks both.
 *
 * The order follows the doctrine's own tiering: tiers 3 and 4 are alike in
 * having nothing usable to show (3 knows why, 4 is still trying), while tier 2
 * does have something. So: err → never-answered → errored-with-data → delayed.
 * Two earlier orders were wrong here. Ranking by tone alone put `sub` under
 * both warns, so any sibling measured >500ms masked a hung pipe with
 * `delayed [640ms]`. Putting `sub` between them still let
 * `… · showing last data · retrying` — a stronger claim than `delayed` — win
 * over a pipe with no data at all, while the body beneath rendered a
 * fabricated `0/20` for Positions and the literal string "Loading equity…".
 */
const _FOOT_SEVERITY = ({ foot, failed }) => (
  foot.tone === 'err' ? 0                       // nothing usable, cause named
    : foot.tone === 'sub' ? 1                   // never answered — nothing yet
    : foot.tone === 'warn' && failed ? 2        // errored · showing last data
    : foot.tone === 'warn' ? 3                  // merely delayed
    : 4                                         // connected
);

const _dashFootWorst = (d, sources) => {
  // An empty list would make the reduce below throw, and the foot is computed
  // in the PANE's render — outside Pane's PaneErrorBoundary — so the throw
  // would take down the whole GridWorkspace subtree instead of one tile. No
  // current caller passes one; a pane assembling its sources conditionally
  // could.
  if (!sources || !sources.length) return qeFootState({ loading: true });
  const derived = sources.map(({ src, hasData }) => {
    // A source is either a QE_DASH net key, or a raw {err, ms} for a pipe a
    // pane owns itself (EquityCurvePane's chart child reports its own onNet).
    const n = (typeof src === 'string' ? (d.net && d.net[src]) : src) || {};
    // ★ Has THIS pipe ever reported? hasData is the CALLER's claim about what
    // is on screen, and several of those claims are satisfiable by a SECOND
    // WRITER: SSE sets st.dd_state and equity.total_equity directly, so a
    // /api/state that has hung since page load still looks "hasData" to the
    // gate. qeFootState's tier-4 test is `loading && !hasData`, so that alone
    // pushed a never-answered pipe through to tier 1 `connected` — carrying
    // the SIBLING's ms, because the -1 sentinel loses every tie. A pipe that
    // has not answered has no data OF ITS OWN, whatever else painted the view.
    const answered = n.ms != null || !!n.err;
    return {
      failed: !!n.err,
      ms: n.ms == null ? -1 : n.ms,
      // every QE_DASH source is on a poll interval → retrying is truthful
      foot: qeFootState({
        loading: !answered, err: n.err,
        hasData: answered && !!hasData, ms: n.ms, retrying: true,
      }),
    };
  });
  return derived.reduce((a, b) => {
    const sev = _FOOT_SEVERITY(a) - _FOOT_SEVERITY(b);
    if (sev !== 0) return sev < 0 ? a : b;
    // equal severity → the SLOWER pipe, so `connected [Nms]` is never
    // flattered by the faster one
    return a.ms >= b.ms ? a : b;
  }).foot;
};

// Single-pipe panes delegate, so there is exactly one derivation path.
const _dashFoot = (d, key, hasData) => _dashFootWorst(d, [{ src: key, hasData }]);

const useDash = () => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => QE_DASH.subscribe(force), []);
  return QE_DASH.get();
};

/* small formatting helpers (null-safe — values are undefined before the first
   snapshot resolves) */
const _n  = (v, d = 2) => (v == null || isNaN(v)) ? '—' : (+v).toFixed(d);
const _sn = (v, d = 2) => (v == null || isNaN(v)) ? '—' : (v >= 0 ? '+' : '') + (+v).toFixed(d);
const _loc = (v, d = 2) => (v == null || isNaN(v)) ? '—' : (+v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

/* ── Equity hero + deltas (leaf spans; only the digits morph) ───────────── */
const EquityHero = () => {
  const d = useDash();
  const v = d.equity.total_equity;
  const [int, dec] = (v != null && !isNaN(v) ? (+v).toFixed(2) : '0.00').split('.');
  return (
    <div className="qe-hero-val" style={{ fontSize: '1.9rem' }}>
      <LiveValue id="acct.eq.int" value={+int} format={(x) => x.toLocaleString()} />
      <span className="qe-hero-cents">.<LiveValue id="acct.eq.cents" value={dec} format={(x) => x} /></span>
      <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.36em', color: 'var(--qe-sub)', fontWeight: 600, marginLeft: 8, verticalAlign: 'middle' }}>USDT</span>
    </div>
  );
};

const DeltaPct = ({ id, value, suffix = '%' }) => {
  const v = value;
  const dir = v == null ? 'flat' : v > 0.001 ? 'up' : v < -0.001 ? 'dn' : 'flat';
  const col = dir === 'up' ? 'var(--qe-green)' : dir === 'dn' ? 'var(--qe-red)' : 'var(--qe-sub)';
  return (
    <span className="qe-mono" style={{ color: col, fontSize: 'var(--qe-fs-md)', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      {dir === 'up' ? <span className="qe-tick qe-tick-up" /> : dir === 'dn' ? <span className="qe-tick qe-tick-dn" /> : null}
      <LiveValue id={id} value={v == null ? 0 : v} format={(x) => _sn(x) + suffix} style={{ color: col, fontWeight: 700 }} />
    </span>
  );
};

/* ── Position row cells (live upnl/pct from the merged store row) ─────────
   P8 wave 2: lookups + LiveValue ids ride the hedge-safe composite `_k`
   (symbol|side) — symbol-keyed ids collide on hedge pairs. Mark null-guards
   render '—' instead of a fabricated 0.00 on SSE-minimal rows (audit F9). */
const _findPos = (positions, k) => positions.find((p) => p._k === k) || {};
const PosMark = ({ r }) => { const d = useDash(); const p = _findPos(d.positions, r._k);
  return <LiveValue id={`pos.${r._k}.mark`} value={p.mark != null ? p.mark : '—'} format={(x) => (p.mark == null ? '—' : _loc(x, 2))} style={{ color: 'var(--qe-text)', fontWeight: 700 }} />; };
const PosPnl = ({ r }) => { const d = useDash(); const p = _findPos(d.positions, r._k); const pnl = p.upnl != null ? p.upnl : 0;
  return <LiveValue id={`pos.${r._k}.pnl`} value={pnl} format={(x) => _sn(x)} style={{ color: pnl >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700 }} />; };
const PosPct = ({ r }) => { const d = useDash(); const p = _findPos(d.positions, r._k); const pct = p.pct != null ? p.pct : 0;
  return <LiveValue id={`pos.${r._k}.pct`} value={pct} format={(x) => _sn(x) + '%'} style={{ color: pct >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 600 }} />; };
/* live-ticking age from the row's entry_ms (audit F5 — the field was
   serialized on every snapshot row and never read).
   NB `entry_ms` is MISNAMED: the serializer passes PositionInfo.
   entry_timestamp through, which is an ISO-8601 STRING on every
   production writer (wave-2 audit F1 — a numeric assumption rendered
   "NaNm" on every real row; the P1 test stub had baked the wrong type).
   Parse-tolerant: accept epoch-ms OR ISO; anything else → '—'. */
const PosAge = ({ r }) => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => { const t = setInterval(force, 60_000); return () => clearInterval(t); }, []);
  const raw = r.entry_ms;
  const t = typeof raw === 'number' ? raw : (raw ? Date.parse(raw) : NaN);
  if (!t || isNaN(t)) return <span style={{ color: 'var(--qe-muted)' }}>—</span>;
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  const dd = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  const txt = dd ? `${dd}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  return <span style={{ color: 'var(--qe-muted)' }}>{txt}</span>;
};
const PosMfeMae = ({ r }) => {
  const mfe = r.mfe, mae = r.mae;
  return <span style={{ fontSize: '0.6rem' }}><span style={{ color: 'var(--qe-green)' }}>{mfe == null ? '—' : '+' + (+mfe).toFixed(2)}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span style={{ color: 'var(--qe-red)' }}>{mae == null ? '—' : (+mae).toFixed(2)}</span></span>;
};
const PosUnrealSum = () => { const d = useDash(); const s = d.positions.reduce((a, p) => a + (p.upnl || 0), 0);
  return <span style={{ color: s >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }}>Σ unrealized {_sn(s)} USDT</span>; };

/* ── Tile: Equity stats ─────────────────────────────────────────────────── */
const EquityStatsPane = () => {
  const d = useDash();
  const eq = d.equity;
  // dashboard-2: month-to-date lives in the JOURNAL block of the same snapshot,
  // not the equity block — which is why the ladder's third rung went missing.
  const j = d.journal || {};
  const blocks = [
    ['Available',    eq.available_margin],
    ['Margin Used',  eq.margin_used],
    ['Unrealized',   eq.unrealized_pnl],
    ['BOD Equity',   eq.bod_equity],
    ['SOW Equity',   eq.sow_equity],
    ['Max Eq (BOD)', eq.max_equity],
    ['Min Eq (BOD)', eq.min_equity],
  ];
  return (
    <Pane title="Equity" style={{ height: '100%' }}
      right={<Badge tone="ok">LIVE</Badge>}
      foot={_dashFoot(d, 'snapshot', eq.total_equity != null)}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div><Lbl>Total</Lbl><EquityHero /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div><Lbl>Daily</Lbl><DeltaPct id="eq.daily" value={eq.daily_pnl_pct} /></div>
          <div><Lbl>Weekly</Lbl><DeltaPct id="eq.weekly" value={eq.weekly_pnl_pct} /></div>
          <div><Lbl>Monthly</Lbl><DeltaPct id="eq.monthly" value={j.monthly_pnl_pct} /></div>
          <div><Lbl>Unrealized</Lbl><LiveValue id="eq.unreal" value={eq.unrealized_pnl == null ? 0 : eq.unrealized_pnl} format={(x) => _sn(x)} style={{ color: (eq.unrealized_pnl || 0) >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700, fontSize: 'var(--qe-fs-md)' }} /></div>
        </div>
        <div className="qe-divider-h" />
        <FieldList cols={2} dense rows={blocks.map(([label, v]) => ({ label, value: _n(v) }))} />
      </div>
    </Pane>
  );
};

/* ── Tile: Equity curve — self-fetching OHLC chart + a live header ──────── */
const EQUITY_OHLC_MS = 5000;
const EquityOhlcChart = React.memo(function EquityOhlcChart({ tf, onNet, onBar }) {
  const [data, setData] = React.useState([]);
  React.useEffect(() => {
    let alive = true;
    const load = async () => {
      const t0 = performance.now();
      try {
        const j = await _ptJson('/api/dashboard/equity_ohlc?tf=' + tf, qePollDeadline(EQUITY_OHLC_MS));
        // CandlestickChart wants [[t, o, c, l, h], …]; snapshot candle = {x,o,h,l,c}
        const rows = (j.candles || []).map((c) => [c.x, c.o, c.c, c.l, c.h]);
        if (alive) {
          setData(rows);
          if (onNet) onNet({ err: null, ms: performance.now() - t0 });
          // lift the latest bar for the pane's O/H/L/Chg header (audit F6)
          if (onBar) {
            const n = j.candles || [];
            const last = n[n.length - 1] || null;
            const prev = n.length > 1 ? n[n.length - 2] : last;
            onBar(last ? { o: last.o, h: last.h, l: last.l, prevC: prev ? prev.c : null, cf: last.cf } : null);
          }
        }
      } catch (err) { if (alive && onNet) onNet((n) => ({ ...n, err })); }
    };
    load();
    const id = setInterval(load, EQUITY_OHLC_MS);
    return () => { alive = false; clearInterval(id); };
  }, [tf]);
  return data.length ? <CandlestickChart data={data} /> : <EmptyState tone="neutral" glyph="〰" msg="Loading equity…" />;
});

const EquityCurvePane = () => {
  const [tf, setTf] = React.useState('1h');
  const [net, setNet] = React.useState({});   // the chart child reports its 5s pipe up
  const [bar, setBar] = React.useState(null); // latest candle O/H/L (+prev close)
  const d = useDash();
  const c = d.equity.total_equity;
  const chg = (c != null && bar && bar.prevC != null) ? c - bar.prevC : null;
  /* TWO pipes, same rule as Risk Monitor: the candles come from the chart
     child's own equity_ohlc poll (reported up through onNet), but C and Chg
     below are read from d.equity — the SNAPSHOT pipe, refreshed by SSE
     equity_update. Keyed to the chart alone, a snapshot-only outage painted a
     stale current equity under a green `connected`. Found by this fix's own
     coverage pin, not by the audit that reported Risk Monitor.
     Each pipe carries ITS OWN hasData: the chart's stays `net.ms != null`,
     exactly as before this change. An earlier draft OR'd the two, which made
     the pane claim `connected` over a body reading "Loading equity…" on every
     re-entry to the Dashboard (QE_DASH.stop() leaves d.loaded and d.net
     populated while the chart's React state resets), and downgraded a failed
     chart fetch from tier 3 to "showing last data" over a chart showing
     none. */
  return (
    <Pane title="Equity Curve" hot tag="OHLC" style={{ height: '100%' }}
      right={<PeriodSelector options={[['1h', '1H'], ['4h', '4H'], ['1d', '1D'], ['1w', '1W']]} value={tf} onChange={setTf} />}
      foot={_dashFootWorst(d, [
        { src: 'snapshot', hasData: c != null },
        { src: net, hasData: net.ms != null },
      ])}
      bodyStyle={{ padding: 6 }}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        {/* O/H/L from the latest fetched candle, C live from SSE equity, Chg vs
            the prior candle close (audit F6 — the header had degraded to a
            lone C + a fabricated "streaming" label on a 5s poll). */}
        <div className="qe-mono" style={{ fontSize: '0.62rem', display: 'flex', gap: 14, flexWrap: 'wrap', padding: '2px 4px', alignItems: 'baseline' }}>
          <span><span style={{ color: 'var(--qe-muted)' }}>O</span> <span style={{ color: 'var(--qe-text)' }}>{bar ? '$' + _n(bar.o) : '—'}</span></span>
          <span><span style={{ color: 'var(--qe-muted)' }}>H</span> <span style={{ color: 'var(--qe-green)' }}>{bar ? '$' + _n(bar.h) : '—'}</span></span>
          <span><span style={{ color: 'var(--qe-muted)' }}>L</span> <span style={{ color: 'var(--qe-red)' }}>{bar ? '$' + _n(bar.l) : '—'}</span></span>
          <span><span style={{ color: 'var(--qe-muted)' }}>C</span> <LiveValue id="ohlc.c" value={c == null ? 0 : c} format={(x) => '$' + _n(x)} style={{ color: 'var(--qe-text)', fontWeight: 700 }} /></span>
          <span><span style={{ color: 'var(--qe-muted)' }}>Chg</span> <span style={{ color: chg == null ? 'var(--qe-muted)' : chg >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }}>{chg == null ? '—' : _sn(chg)}</span></span>
          <span><span style={{ color: 'var(--qe-muted)' }}>Bar Range</span> <span>{bar ? '$' + _n(bar.h - bar.l) : '—'}</span></span>
          {/* dashboard-5: a jump in the curve is either performance or a
              transfer — without this the two are indistinguishable. */}
          <span><span style={{ color: 'var(--qe-muted)' }}>Cash Flow</span> <span style={{ color: 'var(--qe-blue)' }}>{bar && bar.cf ? `${bar.cf >= 0 ? '+' : '-'}$${_n(Math.abs(+bar.cf))}` : '$0.00'}</span></span>
          <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ color: net.err ? 'var(--qe-red)' : 'var(--qe-muted)' }}>{net.err ? 'stalled' : 'poll 5s'}</span>
          </span>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          {/* onNet is the raw setState — success passes a VALUE, failure an
              UPDATER fn; both are valid setState forms */}
          <EquityOhlcChart tf={tf} onNet={setNet} onBar={setBar} />
        </div>
      </div>
    </Pane>
  );
};

/* ── Tile: Risk monitor ─────────────────────────────────────────────────── */
const _stateTone = (s) => s === 'limit' ? 'err' : s === 'warning' ? 'warn' : 'ok';
const _stateLabel = (s) => s === 'limit' ? 'LIMIT' : s === 'warning' ? 'WARN' : 'OK';

/* JSON POST — the dd_override door takes a JSON body (not form-encoded like
   the /orders/* actions), so it gets its own tiny helper rather than reusing
   pages-linkage's `_lkForm`. Returns {ok, data}; a non-2xx carries
   `data.error` (the engine's operator-facing string). */
const _dashPostJson = async (url, payload) => {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  let data = {};
  // `|| {}`: JSON.parse('null') SUCCEEDS and yields null, so a bare-null body
  // would make the caller's `data.error` throw and get mislabelled "engine
  // unreachable".
  try { data = JSON.parse(await r.text()) || {}; } catch (e) { /* non-JSON body */ }
  return { ok: r.ok, data };
};

/* DD-gate manual override (ported from the retired Jinja fragment, 2026-07-30).
   The engine requires a reason of >= 10 chars, refuses unless dd_state is
   'limit', and refuses any account that is not the ACTIVE one; all three rules
   are mirrored here so the operator is never sent into a guaranteed reject.
   This is the surface Pre-Trade's halt banner points at with "override via
   Dashboard".

   `accountId` MUST come from /api/state (`st.account_id`) — never from
   QE_BOOTSTRAP, which is baked at page load and goes stale the moment an
   account is activated from the Config page (that path refetches data without
   reloading). A stale id used to target the wrong account behind a 200. */
const DD_OVERRIDE_MIN_REASON = 10;
const DdOverrideDialog = ({ accountId, drawdownPct, onClose, onDone }) => {
  const [reason, setReason] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const short = reason.trim().length < DD_OVERRIDE_MIN_REASON;

  const submit = async () => {
    if (busy || short) return;
    setBusy(true); setErr(null);
    try {
      const { ok, data } = await _dashPostJson(`/account/${accountId}/dd_override`,
        { reason: reason.trim() });
      if (ok) { if (onDone) onDone(); onClose(); return; }
      setErr(data.error || 'override rejected');
    } catch (e) { setErr('override failed — engine unreachable?'); }
    setBusy(false);
  };

  return (
    <ModelDialog title="Override DD gate" width={430} onClose={() => { if (!busy) onClose(); }}
      footer={<React.Fragment>
        <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy} onClick={onClose}>Keep gate</button>
        <button className="qe-btn qe-btn-sm qe-btn-danger" disabled={busy || short} onClick={submit}
          title={short ? `reason must be at least ${DD_OVERRIDE_MIN_REASON} characters` : 'Unblock new sizing calcs'}>
          {busy ? <Spinner size="0.62rem" /> : 'Override gate'}
        </button>
      </React.Fragment>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <Badge tone="err">DD LIMIT</Badge>
          <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-sub)' }}>
            drawdown {drawdownPct == null ? '—' : _n(drawdownPct) + '%'}
          </span>
        </div>
        <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', lineHeight: 1.5 }}>
          Unblocks NEW sizing calcs until the drawdown recovers — the next limit
          episode re-engages the gate automatically. Open positions are not
          affected. The reason is written to the account event log.
        </div>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.52rem', fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: 'var(--qe-sub)' }}>
            Reason (required)
          </span>
          <input className="qe-input" autoFocus value={reason} placeholder="why the gate is being overridden…"
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); submit(); }
              if (e.key === 'Escape' && !busy) onClose();
            }}
            style={{ height: 22, boxSizing: 'border-box' }} />
          <span className="qe-mono" style={{ fontSize: '0.52rem', color: short ? 'var(--qe-amber)' : 'var(--qe-green)' }}>
            {reason.trim().length}/{DD_OVERRIDE_MIN_REASON} min
          </span>
        </label>
        {err ? <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-red)' }}>{err}</span> : null}
      </div>
    </ModelDialog>
  );
};

const RiskMonitorPane = () => {
  const d = useDash();
  const rk = d.risk, st = d.st;
  const ddState = st.dd_state || rk.dd_state || 'ok';
  const enforced = st.dd_enforcement_mode === 'enforced';
  const ddOverridden = !!st.dd_manually_unblocked;
  // Offer the override only where it BOTH applies and does something: the route
  // refuses unless dd_state is 'limit', and in advisory mode dd_gate already
  // allows entries, so an "override" there would persist an approval for a gate
  // that is not gating. (The fail-closed settings-unreadable lane halts with
  // dd_state != 'limit'; the route would reject it, so no button — filed.)
  const canOverride = ddState === 'limit' && enforced;
  /* TWO pipes, so the foot reports the WORSE of them (see _dashFootWorst).
     The four gauges below are snapshot-fed; only the DD-state badge, the
     ENFORCED chip and the override button come from /api/state. Keying the
     foot to 'st' alone let a snapshot outage paint four stale risk readouts
     under a green `connected`. */
  return (
    <Pane title="Risk Monitor" style={{ height: '100%' }}
      right={<Badge tone={enforced ? 'err' : 'info'}>{enforced ? 'ENFORCED' : 'ADVISORY'}</Badge>}
      foot={_dashFootWorst(d, [
        { src: 'snapshot', hasData: d.loaded },
        { src: 'st', hasData: d.st && d.st.dd_state != null },
      ])}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Gauge label="Net Exposure" value={rk.exposure_pct != null ? rk.exposure_pct / 100 : 0} max={(rk.max_exposure_pct || 500) / 100} current={rk.exposure_pct != null ? _n(rk.exposure_pct / 100, 2) + '×' : '—'} maxLabel={`${_n(rk.max_exposure_pct / 100, 1)}× cap`} />
        {/* ticks proportional to the REAL cap (audit N6 — hardcoded [5,8]
            mispositioned whenever max_dd_pct ≠ 10) */}
        <Gauge label="Drawdown 30d" value={Math.min(rk.drawdown_pct || 0, rk.max_dd_pct || 10)} max={rk.max_dd_pct || 10} current={_n(rk.drawdown_pct) + '%'} maxLabel={`${_n(rk.max_dd_pct)}% limit`} ticks={[0.5, 0.8].map((f) => f * (rk.max_dd_pct || 10))} />
        {/* Weekly-Loss gauge restored (audit F4 — one of the two P&L
            guardrails had no magnitude readout). weekly_pnl_pct is already
            %, params.max_weekly_loss_pct a fraction. */}
        <Gauge label="Weekly Loss" value={Math.max(0, -(d.equity.weekly_pnl_pct || 0))} max={((d.journal.params || {}).max_weekly_loss_pct || 0.05) * 100} current={d.equity.weekly_pnl_pct != null ? _sn(d.equity.weekly_pnl_pct) + '%' : '—'} maxLabel={`${_n(((d.journal.params || {}).max_weekly_loss_pct || 0.05) * 100, 1)}% cap`} />
        <Gauge label="Positions" value={rk.positions_open || 0} max={rk.positions_max || 20} current={`${rk.positions_open || 0}/${rk.positions_max || 20}`} maxLabel="capacity" />
        <div className="qe-divider-h" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div><Lbl>DD STATE</Lbl>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
              <Badge tone={_stateTone(ddState)}>{enforced && ddState === 'limit' ? 'HALTED' : _stateLabel(ddState)}</Badge>
              {/* DD-override control (ported 2026-07-30). Only reachable in the
                  state the engine accepts: dd_state == 'limit' and not already
                  overridden. Once set it reads OVERRIDDEN until recovery. */}
              {ddOverridden
                ? <span title="Manual override active — new calcs unblocked until the drawdown recovers"><Badge tone="warn">OVERRIDDEN</Badge></span>
                : canOverride
                  ? <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={st.account_id == null}
                      onClick={() => QE_DASH.setUi({ ddOverride: true })}
                      title={st.account_id == null
                        ? 'waiting for engine state…'
                        : 'Manually unblock new sizing calcs (reason required)'}>Override</button>
                  : null}
            </div>
          </div>
          <div><Lbl>WEEKLY</Lbl><Badge tone={_stateTone(st.weekly_pnl_state || rk.weekly_pnl_state)}>{_stateLabel(st.weekly_pnl_state || rk.weekly_pnl_state)}</Badge></div>
        </div>
        {(rk.funding_lines || []).length > 0 &&
          <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)' }}>
            <span style={{ color: 'var(--qe-sub)' }}>FUNDING </span>{(rk.funding_lines || []).join(' · ')}
          </div>}
        {/* sector concentration — the backend computed + shipped this every
            snapshot with zero readers (audit F3) */}
        {(rk.sector_lines || []).length > 0 &&
          <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)' }}>
            <span style={{ color: 'var(--qe-sub)' }}>SECTOR </span>{(rk.sector_lines || []).join(' · ')}
          </div>}
      </div>
    </Pane>
  );
};

/* Page-level host for the DD-override dialog — see the `ui` note in QE_DASH:
   rendering it inside RiskMonitorPane would clip it to that tile. A leaf
   subscriber, so DashTiled/TiledGrid stay unsubscribed + memoized. */
const DdOverrideHost = () => {
  const d = useDash();
  // No live account id → no dialog. Never fall back to a literal id: account 1
  // is the one that exists live, so a fallback would silently unblock a real
  // account's DD gate.
  if (!d.ui || !d.ui.ddOverride || d.st.account_id == null) return null;
  return (
    <DdOverrideDialog
      accountId={d.st.account_id}
      // st.drawdown is SSE-live; risk.drawdown_pct is the 15 s snapshot poll, so
      // it could show a stale figure beside a fresh DD LIMIT badge.
      drawdownPct={d.st.drawdown != null ? d.st.drawdown * 100 : d.risk.drawdown_pct}
      onClose={() => QE_DASH.setUi({ ddOverride: false })}
      onDone={() => QE_DASH.refreshState()} />
  );
};

/* ── Tile: Open positions ───────────────────────────────────────────────── */
const OpenPositionsPane = () => {
  const d = useDash();
  const rows = d.positions;
  const longs = rows.filter((r) => (r.side || '').toLowerCase().startsWith('l')).length;
  return (
    <Pane title="Open Positions" count={rows.length} style={{ height: '100%' }}
      right={<button className="qe-btn qe-btn-sm" title="Size a new position in Pre-Trade" onClick={() => window.qeNav && window.qeNav('Pre-Trade')}>+ Calc</button>}
      foot={_dashFoot(d, 'snapshot', d.loaded)}
      bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
      <DataList
        selKey="_k"
        columns={[
          { key: 'sym',   label: 'SYM',   render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.sym}</span> },
          { key: 'side',  label: 'SIDE',  filter: { label: 'SIDE' },
            filterVal: (r) => ((r.side || '').toLowerCase().startsWith('l') ? 'LONG' : 'SHORT'),
            render: (r) => { const l = (r.side || '').toLowerCase().startsWith('l'); return <Badge tone={l ? 'ok' : 'err'}>{l ? 'LONG' : 'SHORT'}</Badge>; } },
          { key: 'size',  label: 'SIZE',  align: 'right', render: (r) => _loc(r.size, 3) },
          { key: 'entry', label: 'ENTRY', align: 'right', cell: 'dim', render: (r) => _loc(r.entry, 2) },
          { key: 'mark',  label: 'MARK',  align: 'right', render: (r) => <PosMark r={r} /> },
          // PosPnl renders the LIVE upnl; the row's own `pnl` key is not what the
          // cell shows, so sorting used a different number. Bucketing upnl also
          // gives this tile its only stable facet (sym/side go homogeneous on a
          // one-position book, every other column is continuous).
          { key: 'pnl',   label: 'PnL',   align: 'right',
            sortVal: (r) => (r.upnl != null ? r.upnl : null),
            filter: { label: 'PnL' },
            filterVal: (r) => ((r.upnl || 0) >= 0 ? 'UP' : 'DOWN'),
            render: (r) => <PosPnl r={r} /> },
          { key: 'pct',   label: '%',     align: 'right', render: (r) => <PosPct r={r} /> },
          { key: 'tpsl',  label: 'TP / SL', align: 'right', sort: false,
            filter: { label: 'TP/SL' },
            filterVal: (r) => (r.tp != null ? 'TP' : '') + (r.tp != null && r.sl != null ? '+' : '') + (r.sl != null ? 'SL' : '') || 'NONE',
            render: (r) => <span style={{ fontSize: '0.6rem' }}><span style={{ color: 'var(--qe-green)' }}>{r.tp == null ? '—' : _loc(r.tp, 2)}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span style={{ color: 'var(--qe-red)' }}>{r.sl == null ? '—' : _loc(r.sl, 2)}</span></span> },
          { key: 'mm',    label: 'MFE/MAE', align: 'right', render: (r) => <PosMfeMae r={r} /> },
          // AGE had opted out of sort because 'age' is not a row field; PosAge
          // parses entry_ms (a MISNAMED ISO string) at render. Sort on the parsed
          // epoch so the header agrees with the cell — ascending = oldest first.
          { key: 'age',   label: 'AGE',   align: 'right',
            sortVal: (r) => { const t = Date.parse(r.entry_ms); return isNaN(t) ? null : t; },
            render: (r) => <PosAge r={r} /> },
        ]}
        rows={rows}
        emptyMsg="No open positions"
        summary={<>
          <span>{rows.length} / {d.risk.positions_max || 20} positions · {longs} long · {rows.length - longs} short</span>
          <PosUnrealSum />
        </>}
      />
    </Pane>
  );
};

/* ── Tile: Macro signals (the 6 real regime signals) ────────────────────── */
const MacroSignalsPane = () => {
  const d = useDash();
  const sigs = d.macro;
  return (
    <Pane title="Macro Signals" count={sigs.length} style={{ height: '100%' }}
      foot={_dashFoot(d, 'macro', sigs.length > 0)}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sigs.length === 0 && <EmptyState fill tone="warn" glyph="∅" msg="No signal data" hint="Run regime backfill to populate." />}
        {/* 4-col rows: key · 30d sparkline (audit F2 — the endpoint fetched
            the series and discarded it) · value · delta */}
        {sigs.map((s) => (
          <div key={s.key} style={{ display: 'grid', gridTemplateColumns: '84px 1fr 64px 56px', alignItems: 'center', gap: 6, padding: '3px 0', borderBottom: '1px dotted var(--qe-faint)' }}>
            <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.6rem', color: 'var(--qe-sub)', letterSpacing: '0.04em' }}>{s.key}</span>
            <div style={{ height: 18, minWidth: 0 }}>
              {(s.series || []).length > 1
                ? <Sparkline data={s.series} height={18} area={false} color={s.tone === 'dn' ? 'var(--qe-red)' : s.tone === 'up' ? 'var(--qe-green)' : 'var(--qe-sub)'} />
                : null}
            </div>
            <LiveValue id={`sig.${s.key}`} value={s.v == null ? 0 : s.v} format={(x) => s.v == null ? '—' : (+x).toFixed(2)} style={{ fontSize: '0.68rem', fontWeight: 700, textAlign: 'right', display: 'block' }} />
            <span className="qe-mono" style={{ fontSize: '0.56rem', textAlign: 'right', color: s.tone === 'up' ? 'var(--qe-green)' : s.tone === 'dn' ? 'var(--qe-red)' : 'var(--qe-muted)' }}>{s.d == null ? '' : _sn(s.d)}</span>
          </div>
        ))}
      </div>
    </Pane>
  );
};

/* ── Tile: Monthly analytics preview ────────────────────────────────────── */
const MonthlyPane = () => {
  const d = useDash();
  const j = d.journal;
  const daily = j.daily_pnl || [];
  return (
    <Pane title="Monthly Analytics Preview" tag={j.month_label || undefined} style={{ height: '100%' }}
      foot={_dashFoot(d, 'snapshot', d.loaded)}
      bodyStyle={{ padding: '4px 6px', display: 'flex', flexDirection: 'column' }}>
      {/* stats left · the design's daily-PnL bar chart right, now on the REAL
          per-day series (audit F1 — plan §4 mandated substitution, not
          deletion; the array rides the snapshot's journal context) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(190px, 0.9fr) 1.1fr', gap: 10, height: '100%', minHeight: 0 }}>
        <FieldList rows={[
          { label: 'Period PnL',  value: <>{_sn(j.monthly_pnl)} <span style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>({_sn(j.monthly_pnl_pct)}%)</span></>, color: (j.monthly_pnl || 0) < 0 ? 'red' : 'green' },
          { label: 'QTD',         value: <>{_sn(j.quarterly_pnl)} <span style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>({_sn(j.quarterly_pnl_pct)}%)</span></> },
          { label: 'YTD',         value: <>{_sn(j.yearly_pnl)} <span style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>({_sn(j.yearly_pnl_pct)}%)</span></> },
          { label: 'Trades',      value: <>{j.trade_count || 0} <span style={{ color: 'var(--qe-green)', fontSize: '0.62rem' }}>·{j.win_count || 0}W</span> <span style={{ color: 'var(--qe-red)', fontSize: '0.62rem' }}>·{j.loss_count || 0}L</span></> },
          { label: 'Winrate / R', value: `${_n(j.win_rate)}% / ${_n(j.avg_rr)}R` },
          { label: 'Max DD',      value: `-${_n(j.max_dd_month)}%`, color: 'red' },
        ]} />
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <Lbl>Daily PnL · {j.month_label || 'month'}</Lbl>
          <div style={{ flex: 1, minHeight: 0, marginTop: 2 }}>
            {daily.length
              ? <BarChart data={daily.map((r) => r.pnl)} categories={daily.map((r) => String(r.d || '').slice(8))} />
              : <div className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-muted)', padding: 8 }}>no daily snapshots this month</div>}
          </div>
        </div>
      </div>
    </Pane>
  );
};

/* ── Tile: Active parameters ────────────────────────────────────────────── */
const ActiveParamsPane = () => {
  const d = useDash();
  const p = d.journal.params || {};
  const rows = [
    { label: 'Risk / trade',    value: _n((p.individual_risk_per_trade || 0) * 100) + '%', color: 'cyan' },
    { label: 'Max W-loss',      value: _n((p.max_weekly_loss_pct || 0) * 100) + '%' },
    { label: 'Max DD',          value: _n((p.max_drawdown_pct || 0) * 100) + '%' },
    { label: 'Max exposure',    value: _n(p.max_exposure_multiple, 1) + '×' },
    { label: 'Max positions',   value: String(p.max_open_positions != null ? p.max_open_positions : '—') },
    { label: 'Max corr.',       value: _n((p.max_correlated_exposure || 0) * 100) + '%' },
  ];
  // dashboard-4: which named risk preset the account runs. Nothing else on the
  // dashboard names it. Renders only when the backend supplies it — an absent
  // value must not fabricate 'CUSTOM'.
  const preset = p.strategy_preset;
  return (
    <Pane title="Active Parameters" tag="VIEW" style={{ height: '100%' }}
      right={<button className="qe-btn qe-btn-sm qe-btn-ghost" title="Edit risk parameters in Configuration" onClick={() => window.qeNav && window.qeNav('Config')}>Edit</button>}
      foot={_dashFoot(d, 'snapshot', d.loaded)}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <FieldList rows={rows} />
        {preset ? (
          <React.Fragment>
            <div className="qe-divider-h" />
            <div style={{ display: 'flex', gap: 6 }}>
              <Badge tone="info">PRESET: {String(preset).toUpperCase()}</Badge>
            </div>
          </React.Fragment>
        ) : null}
      </div>
    </Pane>
  );
};

/* dashboard-1 — the footer news marquee, wired to the REAL feed.
   Its own tiny poller rather than QE_DASH: this is page chrome, not a tile, and
   useAnaJson lives in a module that loads AFTER this one. 60s because headlines
   are ambient, not actionable — the Regime News tab is the working surface. */
const NEWS_FEED_MS = 60_000;
const DashNewsTicker = () => {
  const [news, setNews] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const d = await _ptJson('/api/news/feed?limit=40', qePollDeadline(NEWS_FEED_MS));
        if (alive) setNews(Array.isArray(d) ? d : (d.news || d.items || []));
      } catch (e) { /* keep last — an absent feed renders quiet by contract */ }
    };
    load();
    const t = setInterval(load, NEWS_FEED_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);
  if (!news || !news.length) return null;   // empty renders quiet, never a bar of nothing
  return <NewsTickerBar news={news} meta="NEWS FEED" />;
};

/* ── Tile: Engine log (real engine_events tail) ─────────────────────────── */
const EngineLogBody = () => {
  const d = useDash();
  const rows = d.log;
  return (
    <div style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.62rem', lineHeight: 1.5 }}>
      {rows.length === 0 && <div style={{ color: 'var(--qe-muted)' }}>— no recent engine events —</div>}
      {rows.map((l, i) => (
        <div key={`${l.id}-${i}`} style={{ display: 'grid', gridTemplateColumns: '56px 44px 1fr', gap: 6, opacity: i === 0 ? 1 : Math.max(0.45, 1 - i * 0.06) }}>
          <span style={{ color: 'var(--qe-muted)' }}>{l.t}</span>
          <span style={{ color: l.tone === 'ok' ? 'var(--qe-green)' : l.tone === 'info' ? 'var(--qe-cyan)' : l.tone === 'err' ? 'var(--qe-red)' : l.tone === 'warn' ? 'var(--qe-amber)' : 'var(--qe-sub)' }}>[{l.tag}]</span>
          <span style={{ color: 'var(--qe-text-dim)' }}>{l.msg}</span>
        </div>
      ))}
    </div>
  );
};

/* Engine-Log pane as its own LEAF (subscribes via useDash for the state
   foot) — TiledGrid stays subscription-free/memoized. [foot-audit CRIT-1:
   the foot briefly read an unbound `d` inside the memo component.] */
const EngineLogPane = () => {
  const d = useDash();
  return (
    <Pane title="Engine Log" tag="LIVE" style={{ height: '100%' }}
      right={<StatusDot tone="ok" label="LOG" />}
      foot={_dashFoot(d, 'log', d.log.length > 0)}
      bodyStyle={{ padding: '4px 6px', fontFamily: 'var(--qe-mono)' }}>
      <EngineLogBody />
    </Pane>
  );
};

/* ── TiledGrid — renders once; leaves stream ────────────────────────────── */
const TiledGrid = React.memo(function TiledGrid() {
  return (
    <GridWorkspace persistId="dashboard">
      <GridItem x={0} y={0} w={8} h={8} minW={6} minH={6}><EquityStatsPane /></GridItem>
      <GridItem x={8} y={0} w={16} h={8} minW={8} minH={6}><EquityCurvePane /></GridItem>
      <GridItem x={0} y={8} w={6} h={8} minW={4} minH={6}><RiskMonitorPane /></GridItem>
      <GridItem x={6} y={8} w={12} h={8} minW={8} minH={6}><OpenPositionsPane /></GridItem>
      <GridItem x={18} y={8} w={6} h={8} minW={4} minH={6}><MacroSignalsPane /></GridItem>
      <GridItem x={0} y={16} w={12} h={8} minW={8} minH={6}><MonthlyPane /></GridItem>
      <GridItem x={12} y={16} w={6} h={8} minW={4} minH={6}><ActiveParamsPane /></GridItem>
      <GridItem x={18} y={16} w={6} h={8} minW={4} minH={6}><EngineLogPane /></GridItem>
    </GridWorkspace>
  );
});

/* ── Dashboard header status dots (real state) ──────────────────────────── */
const DashHeaderDots = () => {
  const d = useDash();
  const st = d.st, rg = d.regime;
  const sse = typeof window.QE_SSE !== 'undefined' ? window.QE_SSE.status() : 'idle';
  const wsTone = sse === 'open' ? 'ok' : sse === 'error' ? 'err' : 'warn';
  const gateHalted = !!st.halted;
  return (
    <>
      <StatusDot tone={wsTone} label="STREAM" value={sse === 'open' ? 'live' : sse} />
      <StatusDot tone="info" label="REGIME" value={rg && rg.label ? `${rg.label.replace(/_/g, ' ')} ×${_n(rg.multiplier, 1)}` : '—'} />
      <StatusDot tone={gateHalted ? 'err' : 'ok'} label="GATE" value={gateHalted ? 'HALTED' : 'READY'} />
    </>
  );
};

/* ── Halt / advisory banner (G-O2 real state; plan §1.3) ────────────────── */
const DashHaltBanner = () => {
  const d = useDash();
  const st = d.st;
  if (st.halted) {
    return <Banner tone="err" tag="HALT" title="TRADING HALTED — new entries blocked"
      detail={st.halt_reason || 'DD limit breached · enforced mode'} />;
  }
  if (st.blocked) {
    return <Banner tone="warn" tag="LIMIT" title="At risk limit — advisory"
      detail="A drawdown/weekly-loss limit is at cap; advisory mode does not auto-halt." />;
  }
  return null;
};

/* ── Watchlist tape — the operator's OPEN POSITIONS (real marks) ─────────── */
const WatchlistTape = () => {
  const d = useDash();
  const rows = d.positions;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 0,
      background: 'var(--qe-bg)', borderBottom: '1px solid var(--qe-line)',
      padding: '0 4px', height: 22, flexShrink: 0,
      fontFamily: 'var(--qe-mono)', fontSize: '0.62rem', overflow: 'hidden', whiteSpace: 'nowrap',
    }}>
      {rows.length === 0 && <span style={{ color: 'var(--qe-muted)', padding: '0 9px' }}>no open positions</span>}
      {rows.map((r, i) => (
        <span key={r._k || r.sym} style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5, padding: '0 9px', borderRight: i < rows.length - 1 ? '1px solid var(--qe-faint)' : 'none' }}>
          <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.sym || '').replace('USDT', '')}</span>
          <LiveValue id={`tape.${r._k || r.sym}`} value={r.mark != null ? r.mark : '—'} format={(x) => (r.mark == null ? '—' : _loc(x, 2))} style={{ color: 'var(--qe-text)', fontWeight: 600 }} />
          <LiveValue id={`tape.${r._k || r.sym}.pct`} value={r.pct != null ? r.pct : 0} format={(x) => _sn(x) + '%'} style={{ fontSize: '0.56rem', fontWeight: 600, color: (r.pct || 0) >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }} />
        </span>
      ))}
    </div>
  );
};

/* ── Dashboard page ─────────────────────────────────────────────────────── */
const DashTiled = () => {
  React.useEffect(() => { QE_DASH.start(); return () => QE_DASH.stop(); }, []);
  return (
    <div className="qe-scope" data-screen-label="01 Dashboard" style={{
      width: '100%', height: '100%', background: 'var(--qe-bg)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      // anchors DdOverrideHost's absolutely-positioned ModelDialog, matching
      // every other dialog-hosting page root (linkage/models/history)
      position: 'relative',
    }}>
      <TopNavStd page="Dashboard" variant="line" dense />
      <PageHeader title="Dashboard" subtitle="live positions · equity · risk · open orders">
        <DashHeaderDots />
      </PageHeader>
      <DashHaltBanner />
      <WatchlistTape />
      <TiledGrid />
      <DashNewsTicker />
      <DdOverrideHost />
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { DashTiled, QE_DASH });
