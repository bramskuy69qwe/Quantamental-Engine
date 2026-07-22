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
    macro: [],              // /api/regime/signals/latest
    log: [],                // engine-log lines, newest-first for the prepend feed
    logCursor: 0,
    loaded: false,
  };
  const subs = new Set();
  const notify = () => subs.forEach((f) => { try { f(); } catch (e) { /* isolate */ } });

  async function _json(url) {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(url + ' ' + r.status);
    return r.json();
  }

  async function loadSnapshot() {
    try {
      const s = await _json('/api/dashboard/snapshot');
      state.equity = s.equity || {};
      state.risk = s.risk || {};
      state.journal = s.journal || {};
      state.regime = s.regime || null;
      if (Array.isArray(s.positions)) state.positions = s.positions;
      state.loaded = true;
      notify();
    } catch (e) { /* keep prior state */ }
  }
  async function loadState() {
    try { state.st = await _json('/api/state'); notify(); } catch (e) { /* keep */ }
  }
  async function loadMacro() {
    try { const m = await _json('/api/regime/signals/latest'); state.macro = m.signals || []; notify(); }
    catch (e) { /* keep */ }
  }
  async function loadLog() {
    try {
      const d = await _json('/api/engine/log?since=' + state.logCursor + '&limit=60');
      const lines = d.lines || [];
      if (lines.length) {
        // server returns oldest-first; prepend newest for the feed display
        state.log = [...lines.slice().reverse(), ...state.log].slice(0, 60);
        state.logCursor = d.latest_id || state.logCursor;
        notify();
      } else if (d.latest_id != null) {
        state.logCursor = d.latest_id;
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
      const prev = {};
      state.positions.forEach((r) => { prev[r.sym] = r; });
      state.positions = list.map((x) => {
        const r = prev[x.symbol] || {};
        const upnl = x.upnl != null ? x.upnl : r.upnl;
        const notional = r.notional || 0;
        const pct = notional ? +(upnl / Math.abs(notional) * 100).toFixed(2) : (r.pct || 0);
        return { ...r, sym: x.symbol, side: x.side != null ? x.side : r.side,
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
  function start() {
    if (!wired) { _wireSSE(); wired = true; }   // SSE stays wired across mounts (idempotent)
    if (started) return;
    started = true;
    loadSnapshot(); loadState(); loadMacro(); loadLog();
    _timers.push(setInterval(loadState, 5000));
    _timers.push(setInterval(loadLog, 4000));
    _timers.push(setInterval(loadMacro, 60000));
    _timers.push(setInterval(loadSnapshot, 15000));  // reconcile non-SSE tiles
  }
  function stop() {   // clear the polls when the Dashboard unmounts (M1); SSE stays wired
    _timers.forEach(clearInterval);
    _timers.length = 0;
    started = false;
  }

  return { start, stop, get: () => state, subscribe(fn) { subs.add(fn); return () => subs.delete(fn); } };
})();

/* Subscribe a component to QE_DASH updates. Used at the LEAF level so the
   memoized TiledGrid never re-renders. */
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

/* ── Position row cells (live upnl/pct from the merged store row) ───────── */
const _findPos = (positions, sym) => positions.find((p) => p.sym === sym) || {};
const PosMark = ({ r }) => { const d = useDash(); const p = _findPos(d.positions, r.sym);
  return <LiveValue id={`pos.${r.sym}.mark`} value={p.mark != null ? p.mark : 0} format={(x) => _loc(x, 2)} style={{ color: 'var(--qe-text)', fontWeight: 700 }} />; };
const PosPnl = ({ r }) => { const d = useDash(); const p = _findPos(d.positions, r.sym); const pnl = p.upnl != null ? p.upnl : 0;
  return <LiveValue id={`pos.${r.sym}.pnl`} value={pnl} format={(x) => _sn(x)} style={{ color: pnl >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700 }} />; };
const PosPct = ({ r }) => { const d = useDash(); const p = _findPos(d.positions, r.sym); const pct = p.pct != null ? p.pct : 0;
  return <LiveValue id={`pos.${r.sym}.pct`} value={pct} format={(x) => _sn(x) + '%'} style={{ color: pct >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 600 }} />; };
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
      foot={{ tone: 'info', id: 1841, msg: `equity ${_n(eq.total_equity)} · margin ${_n(eq.available_margin)}`, ms: 8 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div><Lbl>Total</Lbl><EquityHero /></div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div><Lbl>Daily</Lbl><DeltaPct id="eq.daily" value={eq.daily_pnl_pct} /></div>
          <div><Lbl>Weekly</Lbl><DeltaPct id="eq.weekly" value={eq.weekly_pnl_pct} /></div>
          <div><Lbl>Unrealized</Lbl><LiveValue id="eq.unreal" value={eq.unrealized_pnl == null ? 0 : eq.unrealized_pnl} format={(x) => _sn(x)} style={{ color: (eq.unrealized_pnl || 0) >= 0 ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700, fontSize: 'var(--qe-fs-md)' }} /></div>
          <div><Lbl>Available</Lbl><span className="qe-mono" style={{ fontWeight: 700 }}>{_n(eq.available_margin)}</span></div>
        </div>
        <div className="qe-divider-h" />
        <FieldList cols={2} dense rows={blocks.map(([label, v]) => ({ label, value: _n(v) }))} />
      </div>
    </Pane>
  );
};

/* ── Tile: Equity curve — self-fetching OHLC chart + a live header ──────── */
const EquityOhlcChart = React.memo(function EquityOhlcChart({ tf }) {
  const [data, setData] = React.useState([]);
  React.useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch('/api/dashboard/equity_ohlc?tf=' + tf, { headers: { Accept: 'application/json' } });
        if (!r.ok) return;
        const j = await r.json();
        // CandlestickChart wants [[t, o, c, l, h], …]; snapshot candle = {x,o,h,l,c}
        const rows = (j.candles || []).map((c) => [c.x, c.o, c.c, c.l, c.h]);
        if (alive) setData(rows);
      } catch (e) { /* keep */ }
    };
    load();
    const id = setInterval(load, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [tf]);
  return data.length ? <CandlestickChart data={data} /> : <EmptyState tone="neutral" glyph="〰" msg="Loading equity…" />;
});

const EquityCurvePane = () => {
  const [tf, setTf] = React.useState('1h');
  const d = useDash();
  const c = d.equity.total_equity;
  return (
    <Pane title="Equity Curve" hot tag="OHLC" style={{ height: '100%' }}
      right={<PeriodSelector options={[['1h', '1H'], ['4h', '4H'], ['1d', '1D'], ['1w', '1W']]} value={tf} onChange={setTf} />}
      foot={{ tone: 'info', id: 1842, msg: `equity_ohlc · last C=${_n(c)} · tf=${tf}`, ms: 12 }}
      bodyStyle={{ padding: 6 }}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div className="qe-mono" style={{ fontSize: '0.62rem', display: 'flex', gap: 14, flexWrap: 'wrap', padding: '2px 4px', alignItems: 'baseline' }}>
          <span><span style={{ color: 'var(--qe-muted)' }}>C</span> <LiveValue id="ohlc.c" value={c == null ? 0 : c} format={(x) => '$' + _n(x)} style={{ color: 'var(--qe-text)', fontWeight: 700 }} /></span>
          <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span className="qe-live" style={{ color: 'var(--qe-cyan)' }}>streaming</span>
          </span>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          <EquityOhlcChart tf={tf} />
        </div>
      </div>
    </Pane>
  );
};

/* ── Tile: Risk monitor ─────────────────────────────────────────────────── */
const _stateTone = (s) => s === 'limit' ? 'err' : s === 'warning' ? 'warn' : 'ok';
const _stateLabel = (s) => s === 'limit' ? 'LIMIT' : s === 'warning' ? 'WARN' : 'OK';
const RiskMonitorPane = () => {
  const d = useDash();
  const rk = d.risk, st = d.st;
  const ddState = st.dd_state || rk.dd_state || 'ok';
  const enforced = st.dd_enforcement_mode === 'enforced';
  return (
    <Pane title="Risk Monitor" style={{ height: '100%' }}
      right={<Badge tone={enforced ? 'err' : 'info'}>{enforced ? 'ENFORCED' : 'ADVISORY'}</Badge>}
      foot={{ tone: _stateTone(ddState), id: 1843, msg: `exp ${_n(rk.exposure_pct)}% · dd ${_n(rk.drawdown_pct)}% (cap ${_n(rk.max_dd_pct)}%) · ${enforced ? 'enforced' : 'advisory'}`, ms: 3 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Gauge label="Net Exposure" value={rk.exposure_pct != null ? rk.exposure_pct / 100 : 0} max={(rk.max_exposure_pct || 500) / 100} current={rk.exposure_pct != null ? _n(rk.exposure_pct / 100, 2) + '×' : '—'} maxLabel={`${_n(rk.max_exposure_pct / 100, 1)}× cap`} />
        <Gauge label="Drawdown 30d" value={Math.min(rk.drawdown_pct || 0, rk.max_dd_pct || 10)} max={rk.max_dd_pct || 10} current={_n(rk.drawdown_pct) + '%'} maxLabel={`${_n(rk.max_dd_pct)}% limit`} ticks={[5, 8]} />
        <Gauge label="Positions" value={rk.positions_open || 0} max={rk.positions_max || 20} current={`${rk.positions_open || 0}/${rk.positions_max || 20}`} maxLabel="capacity" />
        <div className="qe-divider-h" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div><Lbl>DD STATE</Lbl><Badge tone={_stateTone(ddState)}>{enforced && ddState === 'limit' ? 'HALTED' : _stateLabel(ddState)}</Badge></div>
          <div><Lbl>WEEKLY</Lbl><Badge tone={_stateTone(st.weekly_pnl_state || rk.weekly_pnl_state)}>{_stateLabel(st.weekly_pnl_state || rk.weekly_pnl_state)}</Badge></div>
        </div>
        {(rk.funding_lines || []).length > 0 &&
          <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)' }}>{(rk.funding_lines || []).join(' · ')}</div>}
      </div>
    </Pane>
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
      foot={{ tone: 'info', id: 1844, msg: `reconciler · ${rows.length} positions`, ms: 42 }}
      bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
      <DataList
        selKey="sym"
        columns={[
          { key: 'sym',   label: 'SYM',   render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.sym}</span> },
          { key: 'side',  label: 'SIDE',  render: (r) => { const l = (r.side || '').toLowerCase().startsWith('l'); return <Badge tone={l ? 'ok' : 'err'}>{l ? 'LONG' : 'SHORT'}</Badge>; } },
          { key: 'size',  label: 'SIZE',  align: 'right', render: (r) => _loc(r.size, 3) },
          { key: 'entry', label: 'ENTRY', align: 'right', cell: 'dim', render: (r) => _loc(r.entry, 2) },
          { key: 'mark',  label: 'MARK',  align: 'right', render: (r) => <PosMark r={r} /> },
          { key: 'pnl',   label: 'PnL',   align: 'right', render: (r) => <PosPnl r={r} /> },
          { key: 'pct',   label: '%',     align: 'right', render: (r) => <PosPct r={r} /> },
          { key: 'tpsl',  label: 'TP / SL', align: 'right', render: (r) => <span style={{ fontSize: '0.6rem' }}><span style={{ color: 'var(--qe-green)' }}>{r.tp == null ? '—' : _loc(r.tp, 2)}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span style={{ color: 'var(--qe-red)' }}>{r.sl == null ? '—' : _loc(r.sl, 2)}</span></span> },
          { key: 'mm',    label: 'MFE/MAE', align: 'right', render: (r) => <PosMfeMae r={r} /> },
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
      foot={{ tone: 'info', id: 1845, msg: 'regime signals · fred / yfinance / binance', ms: 118 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sigs.length === 0 && <EmptyState tone="warn" glyph="∅" msg="No signal data" hint="Run regime backfill to populate." />}
        {sigs.map((s) => (
          <div key={s.key} style={{ display: 'grid', gridTemplateColumns: '84px 1fr 56px', alignItems: 'center', gap: 6, padding: '3px 0', borderBottom: '1px dotted var(--qe-faint)' }}>
            <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.6rem', color: 'var(--qe-sub)', letterSpacing: '0.04em' }}>{s.key}</span>
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
  return (
    <Pane title="Monthly Analytics Preview" style={{ height: '100%' }}
      foot={{ tone: (j.monthly_pnl || 0) < 0 ? 'warn' : 'ok', id: 1846, msg: `${j.month_label || '—'} · pnl ${_sn(j.monthly_pnl)} · ${j.trade_count || 0} trades · winrate ${_n(j.win_rate)}%`, ms: 6 }}>
      <div style={{ padding: '4px 6px' }}>
        <FieldList rows={[
          { label: 'Period PnL',  value: <>{_sn(j.monthly_pnl)} <span style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>({_sn(j.monthly_pnl_pct)}%)</span></>, color: (j.monthly_pnl || 0) < 0 ? 'red' : 'green' },
          { label: 'QTD',         value: <>{_sn(j.quarterly_pnl)} <span style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>({_sn(j.quarterly_pnl_pct)}%)</span></> },
          { label: 'YTD',         value: <>{_sn(j.yearly_pnl)} <span style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>({_sn(j.yearly_pnl_pct)}%)</span></> },
          { label: 'Trades',      value: <>{j.trade_count || 0} <span style={{ color: 'var(--qe-green)', fontSize: '0.62rem' }}>·{j.win_count || 0}W</span> <span style={{ color: 'var(--qe-red)', fontSize: '0.62rem' }}>·{j.loss_count || 0}L</span></> },
          { label: 'Winrate / R', value: `${_n(j.win_rate)}% / ${_n(j.avg_rr)}R` },
          { label: 'Max DD',      value: `-${_n(j.max_dd_month)}%`, color: 'red' },
        ]} />
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
  return (
    <Pane title="Active Parameters" tag="VIEW" style={{ height: '100%' }}
      right={<button className="qe-btn qe-btn-sm qe-btn-ghost" title="Edit risk parameters in Configuration" onClick={() => window.qeNav && window.qeNav('Config')}>Edit</button>}
      foot={{ tone: 'sub', id: 1847, msg: 'risk params · from account config', ms: 1 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <FieldList rows={rows} />
      </div>
    </Pane>
  );
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
      <GridItem x={18} y={16} w={6} h={8} minW={4} minH={6}>
        <Pane title="Engine Log" tag="LIVE" style={{ height: '100%' }}
          right={<StatusDot tone="ok" label="LOG" />}
          foot={{ tone: 'ok', id: 1848, msg: 'engine_events tail · /api/engine/log', ms: 0 }}
          bodyStyle={{ padding: '4px 6px', fontFamily: 'var(--qe-mono)' }}>
          <EngineLogBody />
        </Pane>
      </GridItem>
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
      <StatusDot tone="info" label="REGIME" value={rg && rg.label ? `${rg.label} ×${_n(rg.multiplier, 1)}` : '—'} />
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
        <span key={r.sym} style={{ display: 'inline-flex', alignItems: 'baseline', gap: 5, padding: '0 9px', borderRight: i < rows.length - 1 ? '1px solid var(--qe-faint)' : 'none' }}>
          <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.sym || '').replace('USDT', '')}</span>
          <LiveValue id={`tape.${r.sym}`} value={r.mark != null ? r.mark : 0} format={(x) => _loc(x, 2)} style={{ color: 'var(--qe-text)', fontWeight: 600 }} />
          <LiveValue id={`tape.${r.sym}.pct`} value={r.pct != null ? r.pct : 0} format={(x) => _sn(x) + '%'} style={{ fontSize: '0.56rem', fontWeight: 600, color: (r.pct || 0) >= 0 ? 'var(--qe-green)' : 'var(--qe-red)' }} />
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
    }}>
      <TopNavStd page="Dashboard" variant="line" dense />
      <PageHeader title="Dashboard" subtitle="live positions · equity · risk · open orders">
        <DashHeaderDots />
      </PageHeader>
      <DashHaltBanner />
      <WatchlistTape />
      <TiledGrid />
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { DashTiled, QE_DASH });
