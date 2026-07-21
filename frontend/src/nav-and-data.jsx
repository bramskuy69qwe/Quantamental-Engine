/* v3.0 — Shared data & nav primitives used across the app.
   Ported from the Meridian reference (QE v2.5 → v3.0). NB: MOCK below + the
   QE_LIVE random-walk are P0 PLACEHOLDERS for the shared chrome tiles — P1
   (Dashboard) binds these to real SSE (window.QE_SSE) + the /api/state poll. */

// ── Shared mock dataset ──────────────────────────────────────────────────
const MOCK = {
  ohlc:    mockOhlc(80, 82.2, 1.8),
  equity:  mockEquity(120, 82.2, 0.6),

  account: { name:'Account 1 (Binance)', env:'LIVE', balance:'82.20', ccy:'USDT' },
  exchange:{
    name:'Binance', market:'USD-M Futures',
    serverTime:'2026-04-25 20:08:36 UTC',
    latency: 93, makerFee: '0.020%', takerFee: '0.050%',
    ws: { connected:true, ping: 93, age:'1s' },
  },

  pnl: {
    daily:    { abs: '-0.00',  pct: '-0.00' },
    weekly:   { abs: '-0.00',  pct: '-0.00' },
    monthly:  { abs: '-11.18', pct: '-11.97' },
    ytd:      { abs: '-11.18', pct: '-11.97' },
    unrealized: '+5.23',
  },

  equityBlocks: [
    { label: 'Available',     value: '43.81' },
    { label: 'Margin Used',   value: '38.39' },
    { label: 'Unrealized',    value: '+5.23' },
    { label: 'BOD Equity',    value: '82.20' },
    { label: 'SOW Equity',    value: '82.20' },
    { label: 'Max Eq (BOD)',  value: '82.20' },
    { label: 'Min Eq (BOD)',  value: '82.20' },
    { label: 'Total IP',      value: '0.00'  },
    { label: 'Total GL',      value: '0.00'  },
  ],

  risk: {
    exposure: { v: 2.93, max: 5.0,  ok: true, current: '2.93×', maxLabel: '5.0×' },
    drawdown: { v: 11.97, max: 10.0, ok: false, current: '11.97%', maxLabel: '10.0%' },
    weeklyDD: { v: 0.0,  max: 5.0,  ok: true, current: '0.00%', maxLabel: '5.0%' },
    positions:{ open: 5, max: 20 },
    fundingExposure: null,
    sectorExposure:  null,
    ddState: 'ok', weeklyState: 'ok',
  },

  params: [
    { label: 'Risk/trade',   value: '1.00%', tone: 'cyan'   },
    { label: 'Max W-loss',   value: '5.0%',  tone: 'text'   },
    { label: 'Max DD',       value: '10.0%', tone: 'text'   },
    { label: 'Max exposure', value: '5.0×',  tone: 'text'   },
    { label: 'Max positions',value: '10',    tone: 'text'   },
    { label: 'Max corr.',    value: '50%',   tone: 'text'   },
  ],

  regime: { tone: 'chop', label: 'RISK-ON CHOPPY', score: 0.62, age:'48s ago' },

  april: {
    label: 'April 2026', pnl: '-11.18', pnlPct: '-11.97',
    trades:31, wins:12, losses:19, winrate:38.7,
    avgRR: 1.20, avgP: 1.23, avgL: -1.02, maxDD: 12.24, vol:'$2,168', fee:'$2.54',
    longs:19, shorts:12,
    topPairs: ['STOUSDT','JCTUSDT','AIOTUSDT'],
  },

  // recent trades for tickers
  recent: [
    {sym:'STOUSDT',  dir:'L', pnl:+0.82, pct:+1.00, t:'04-25 18:43'},
    {sym:'BTCUSDT',  dir:'S', pnl:+1.93, pct:+0.47, t:'04-25 17:25'},
    {sym:'JCTUSDT',  dir:'S', pnl:-1.04, pct:-1.04, t:'04-25 16:22'},
    {sym:'AIOTUSDT', dir:'L', pnl:+0.41, pct:+0.45, t:'04-25 14:08'},
    {sym:'STOUSDT',  dir:'L', pnl:-1.12, pct:-1.32, t:'04-25 11:55'},
    {sym:'ETHUSDT',  dir:'L', pnl:-0.55, pct:-0.36, t:'04-24 22:48'},
  ],

  // mock open positions for variants that show some
  positionsOpen: [
    {sym:'BTCUSDT',  dir:'L', size:'0.012', entry:'93412.10', mark:'93580.40', pnl:+2.02, pct:+0.18, tp:'94100.00', sl:'93180.00', mfe:+2.41, mae:-0.18, fee:'-0.06', age:'1h 12m'},
    {sym:'ETHUSDT',  dir:'S', size:'0.55',  entry:'3214.50',  mark:'3208.20',  pnl:+3.47, pct:+0.19, tp:'3185.00',  sl:'3232.00',  mfe:+4.21, mae:-0.92, fee:'-0.08', age:'42m'},
    {sym:'SOLUSDT',  dir:'L', size:'2.4',   entry:'138.42',   mark:'139.21',   pnl:+1.90, pct:+0.57, tp:'141.10',   sl:'137.20',   mfe:+2.12, mae:-0.34, fee:'-0.04', age:'18m'},
    {sym:'AVAXUSDT', dir:'L', size:'8.2',   entry:'42.18',    mark:'42.04',    pnl:-1.15, pct:-0.33, tp:'43.20',    sl:'41.60',    mfe:+0.84, mae:-1.42, fee:'-0.05', age:'2h 31m'},
    {sym:'LINKUSDT', dir:'S', size:'12.6',  entry:'21.84',    mark:'21.92',    pnl:-1.01, pct:-0.37, tp:'21.20',    sl:'22.10',    mfe:+0.42, mae:-1.18, fee:'-0.06', age:'56m'},
  ],
  ordersOpen: [
    {sym:'DOGEUSDT',side:'SELL', type:'STP', qty:'120',  price:'0.1841', tp:'0.1812', sl:'0.1862', age:'21m'},
    {sym:'WIFUSDT', side:'BUY',  type:'LMT', qty:'24',   price:'2.412',  tp:'2.481',  sl:'2.380',  age:'14m'},
    {sym:'PEPEUSDT',side:'BUY',  type:'LMT', qty:'4.2M', price:'0.00001214', tp:'0.0000128', sl:'0.0000118', age:'3m'},
    {sym:'ARBUSDT', side:'SELL', type:'STP', qty:'80',   price:'0.842',  tp:'0.818',  sl:'0.851',  age:'1h 04m'},
  ],

  signals: [
    {key:'BTC.D',     v:'58.12', d:'+0.21', tone:'up'},
    {key:'USDT.D',    v:'4.81',  d:'-0.03', tone:'dn'},
    {key:'10Y',       v:'4.21%', d:'+2bp',  tone:'up'},
    {key:'DXY',       v:'104.2', d:'-0.18', tone:'dn'},
    {key:'VIX',       v:'13.8',  d:'-0.42', tone:'dn'},
    {key:'BTC.OI',    v:'$32.1B',d:'+1.8%', tone:'up'},
    {key:'FUND·BTC',  v:'+0.012%',d:'+0.001%', tone:'up'},
    {key:'RVOL·1D',   v:'0.84',  d:'-0.06', tone:'dn'},
    {key:'BTC.MCAP',  v:'$1.87T',d:'+0.4%', tone:'up'},
    {key:'ETH.D',     v:'17.4',  d:'+0.08', tone:'up'},
    {key:'GOLD',      v:'2641',  d:'-4.2',  tone:'dn'},
    {key:'WTI',       v:'71.84', d:'+0.42', tone:'up'},
  ],

  logs: [
    {t:'20:08:34', tag:'WS',   msg:'Market WS connected.', tone:'ok'},
    {t:'20:08:34', tag:'WS',   msg:'Market WS connecting (2 streams, attempt 1)', tone:'info'},
    {t:'20:08:32', tag:'REG',  msg:'Regime: neutral ×1.0 (high)', tone:'sub'},
    {t:'20:08:24', tag:'WS',   msg:'No market streams to subscribe — sleeping 10s.', tone:'sub'},
    {t:'20:08:14', tag:'WS',   msg:'No market streams to subscribe — sleeping 10s.', tone:'sub'},
    {t:'20:08:02', tag:'ENG',  msg:'Snapshot persisted (eq=82.20, n=1247).', tone:'sub'},
    {t:'20:07:48', tag:'REG',  msg:'Regime transition: NEUT → CHOP (score 0.62).', tone:'info'},
    {t:'20:07:21', tag:'RISK', msg:'DD 30d 11.97% > 10.0% cap. ADVISORY — no auto-halt.', tone:'sub'},
    {t:'20:06:55', tag:'OM',   msg:'Order 504678492 partial fill 0.42/0.55 @ 3214.50.', tone:'sub'},
    {t:'20:06:11', tag:'EXEC', msg:'calc c-4f29bb → fill linked (∆ entry +0.02%).', tone:'ok'},
  ],
};

// ── TopNav — used in all variants except command-bar variant ─────────────
const NAV_ITEMS = ['Dashboard','Pre-Trade','Linkage','History','Analytics','Models','Regime','Primitives'];

// ── One clock for the whole app ──────────────────────────────────────
// P0: the frozen mock clock (anchored to 2026-04-25) is REMOVED (plan §4).
// Renders real wall-clock UTC now; true server/account-time sync (via the
// ws_status exchange clock offset) is a later refinement. QE_CLOCK_OFFSET is
// kept (=0) because notifications.jsx reads window.QE_CLOCK_OFFSET.
const QE_CLOCK_OFFSET = 0;
const qeClockFmt = (t) => { const s = new Date(t.getTime() + QE_CLOCK_OFFSET).toISOString(); return s.slice(0, 10) + ' ' + s.slice(11, 19) + ' UTC'; };

// ── Shared live metrics — ONE random-walk ticker per metric id ──────────
// P0 PLACEHOLDER (plan §4/§1.2): this random-walk is the TEMPORARY data source
// for the shared chrome tiles (nav latency, status-footer P&L/events). P1
// (Dashboard) replaces it by binding these to the real SSE client-adapter
// (window.QE_SSE — see sse-adapter.js) + the /api/state poll. Kept in P0 so the
// shared nav/footer chrome renders; must NOT ship past P1.
const QE_LIVE = { lat: 93, pnlD: -0.00, pnlW: -0.02, pnlM: -11.18, eventsK: 12.4 };
(function () {
  const subs = new Set();
  const step = (k, jitter, clamp, decimals = 2) => {
    let v = QE_LIVE[k] + (Math.random() - 0.5) * jitter * 2;
    if (clamp) {
      // reflect off the bounds instead of parking on them (no frozen metrics)
      if (v < clamp[0]) v = clamp[0] + (clamp[0] - v);
      if (v > clamp[1]) v = clamp[1] - (v - clamp[1]);
      v = Math.max(clamp[0], Math.min(clamp[1], v));
    }
    QE_LIVE[k] = +v.toFixed(decimals);
  };
  setInterval(() => {
    step('lat', 6, [60, 180], 0);
    step('pnlD', 0.08, [-1.2, 1.2], 2);
    step('pnlW', 0.04, [-2.4, 2.4], 2);
    step('pnlM', 0.05, [-11.5, -10.9], 2);
    step('eventsK', 0.05, [12.4, 99], 1);
    subs.forEach(f => f());
  }, 1300);
  window.useQeLive = (key) => {
    const [, force] = React.useReducer(x => x + 1, 0);
    React.useEffect(() => { subs.add(force); return () => subs.delete(force); }, []);
    return QE_LIVE[key];
  };
})();

// ── Per-position mark walks ───────────────────────────────────────
// One walk per symbol; MARK / PnL / % / Σ-unrealized all DERIVE from it so a
// row can never contradict itself (mark below entry while PnL is green, etc).
const QE_POS = {};
const _posWalk = (sym, base) => QE_POS[sym] || (QE_POS[sym] = { v: base, base, subs: new Set(), lo: null, hi: null });
setInterval(() => {
  Object.values(QE_POS).forEach(w => {
    const lo = w.lo ?? w.base * 0.997, hi = w.hi ?? w.base * 1.003;
    let v = w.v + (Math.random() - 0.5) * w.base * 0.0018;
    if (v > hi) v = hi - (v - hi);   // reflect off the corridor walls
    if (v < lo) v = lo + (lo - v);
    w.v = Math.max(lo, Math.min(hi, v));
    w.subs.forEach(f => f());
  });
}, 1100);
const _posDerive = (r, mark) => {
  const dir = r.dir === 'L' ? 1 : -1, size = parseFloat(r.size);
  const pnl = r.pnl + (mark - parseFloat(r.mark)) * size * dir;
  return { mark, pnl, pct: pnl / (parseFloat(r.entry) * size) * 100 };
};
window.useQePosMark = (r) => {
  const w = _posWalk(r.sym, parseFloat(r.mark));
  // Marks stay strictly INSIDE the TP/SL corridor — a touch would have closed
  // the position. Unplanned rows (no TP/SL) keep the ±0.3% band.
  const tp = parseFloat(r.tp ?? r.tp_live), sl = parseFloat(r.sl ?? r.sl_live);
  if (isFinite(tp) && isFinite(sl)) {
    const hiCap = Math.max(tp, sl), loCap = Math.min(tp, sl), m = (hiCap - loCap) * 0.05;
    w.lo = Math.max(w.base * 0.997, loCap + m); w.hi = Math.min(w.base * 1.003, hiCap - m);
    if (!(w.lo < w.hi)) { w.lo = w.base * 0.999; w.hi = w.base * 1.001; }
  }
  const [, force] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => { w.subs.add(force); return () => w.subs.delete(force); }, [w]);
  return _posDerive(r, w.v);
};
window.useQeUnrealSum = () => {
  const rows = MOCK.positionsOpen;
  const [, force] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => {
    const ws = rows.map(r => _posWalk(r.sym, parseFloat(r.mark)));
    ws.forEach(w => w.subs.add(force));
    return () => ws.forEach(w => w.subs.delete(force));
  }, []);
  return rows.reduce((s, r) => s + _posDerive(r, _posWalk(r.sym, parseFloat(r.mark)).v).pnl, 0);
};

// signed-percent view over a shared metric (color follows sign)
const SharedPct = ({ id, k }) => {
  const v = window.useQeLive(k);
  const col = v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)';
  return <LiveValue id={id} value={v} format={x => (x > 0 ? '+' : '') + x.toFixed(2) + '%'} style={{ color: col, fontWeight: 700 }}/>;
};

// Dashboard workspace presets — real layouts, keyed to the dashboard's tile
// order (EquityStats · EquityCurve · Risk · Positions · Signals · Monthly ·
// Params · Log). Applied by index via qeWorkspaceSetLayout.
const QE_DASH_PRESETS = {
  Risk: [
    { x: 0, y: 16, w: 8, h: 8 }, { x: 8, y: 9, w: 8, h: 7 }, { x: 0, y: 0, w: 8, h: 16 }, { x: 8, y: 0, w: 16, h: 9 },
    { x: 16, y: 9, w: 8, h: 7 }, { x: 8, y: 16, w: 8, h: 8 }, { x: 16, y: 16, w: 4, h: 8 }, { x: 20, y: 16, w: 4, h: 8 },
  ],
  Execution: [
    { x: 0, y: 10, w: 6, h: 7 }, { x: 16, y: 0, w: 8, h: 10 }, { x: 6, y: 10, w: 5, h: 7 }, { x: 0, y: 0, w: 16, h: 10 },
    { x: 11, y: 10, w: 5, h: 7 }, { x: 0, y: 17, w: 16, h: 7 }, { x: 16, y: 17, w: 8, h: 7 }, { x: 16, y: 10, w: 8, h: 7 },
  ],
  Macro: [
    { x: 0, y: 16, w: 6, h: 8 }, { x: 8, y: 0, w: 16, h: 8 }, { x: 6, y: 16, w: 6, h: 8 }, { x: 12, y: 16, w: 8, h: 8 },
    { x: 0, y: 0, w: 8, h: 16 }, { x: 16, y: 8, w: 8, h: 8 }, { x: 20, y: 16, w: 4, h: 8 }, { x: 8, y: 8, w: 8, h: 8 },
  ],
};

// ─────────────────────────────────────────────────────────────────────────
// WorkspaceBar — the workspace + exchange-info strip shown under the top nav on
// EVERY page (so workspace presets and live exchange info are always visible).
// Workspace controls (presets · save · load · create) are only usable on the
// Dashboard; elsewhere they render disabled. ⊞ Pane / ⤢ Pop are planned stubs
// (always disabled). The exchange Strip stays live everywhere.
// ─────────────────────────────────────────────────────────────────────────
const WorkspaceBar = ({ interactive = false, persistId = 'dashboard' }) => {
  const lat = window.useQeLive('lat');
  const pnlM = window.useQeLive('pnlM');   // USDT walk — shown here as % of the 93.38 April open
  const [preset, setPreset] = React.useState('Default');
  const [flash, setFlash] = React.useState(null);          // transient status text
  const flashTimer = React.useRef(null);
  const say = (msg) => {
    setFlash(msg);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 1800);
  };
  React.useEffect(() => () => clearTimeout(flashTimer.current), []);

  const presets = ['Default', 'Risk', 'Execution', 'Macro'];
  const onSave = () => say(window.qeWorkspaceSave(persistId) ? '✓ Saved' : 'Save failed');
  const onLoad = () => say(window.qeWorkspaceHasSaved(persistId)
    ? (window.qeWorkspaceLoad(persistId) ? '✓ Loaded' : 'Load failed')
    : 'No saved layout');
  const onCreate = () => { window.qeWorkspaceReset(persistId); say('New workspace'); };
  const onPreset = (p) => {
    setPreset(p);
    // Default restores the baseline layout; the named presets are real layout
    // maps (dashboard tile order) applied through the workspace registry.
    if (p === 'Default') { window.qeWorkspaceReset(persistId); say('Default layout'); }
    else if (QE_DASH_PRESETS[p] && window.qeWorkspaceSetLayout(persistId, QE_DASH_PRESETS[p])) say(p + ' layout');
    else say('Preset unavailable');
  };

  const dim = interactive ? 1 : 0.4;
  const guard = (fn) => interactive ? fn : undefined;

  return (
    <div className="qe-hscroll" style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '2px 6px', borderBottom: '1px solid var(--qe-line)',
      background: 'var(--qe-page)', height: 22, flexShrink: 0,
    }}>
      <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', letterSpacing: '0.1em' }}>WORKSPACE</span>

      <div className="qe-period" style={{ opacity: dim, pointerEvents: interactive ? 'auto' : 'none' }}>
        {presets.map(p => (
          <button key={p} className={preset === p ? 'on' : ''} onClick={guard(() => onPreset(p))}>{p}</button>
        ))}
      </div>

      {/* Save · Load · Create — workspace layout actions (Dashboard only) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, opacity: dim, pointerEvents: interactive ? 'auto' : 'none' }}>
        <button className="qe-btn qe-btn-sm" onClick={guard(onSave)}   title="Save current layout">⤓ Save</button>
        <button className="qe-btn qe-btn-sm" onClick={guard(onLoad)}   title="Load saved layout">⤒ Load</button>
        <button className="qe-btn qe-btn-sm" onClick={guard(onCreate)} title="New workspace from default" style={{ width: 22, padding: 0, justifyContent: 'center' }}>+</button>
        {flash && <span className="qe-mono" style={{ fontSize: '0.54rem', color: flash[0] === '✓' ? 'var(--qe-green)' : 'var(--qe-amber)' }}>{flash}</span>}
      </div>

      {!interactive && (
        <span className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-faint)', letterSpacing: '0.06em' }}>· dashboard only</span>
      )}

      <div className="qe-grow" />

      <Strip dense items={[
        { label: 'EXCH',   value: 'Binance' },
        { label: 'LAT',    value: <LiveValue id="ws.lat" value={lat} format={x => Math.round(x) + 'ms'} style={{ color: lat < 120 ? 'var(--qe-green)' : 'var(--qe-amber)', fontWeight: 700 }} /> },
        { label: 'REGIME', value: <RegimeBadge tone={MOCK.regime.tone} /> },
        { label: 'P&L·D',  value: <SharedPct id="ws.pnl.d" k="pnlD"/> },
        { label: 'P&L·W',  value: <SharedPct id="ws.pnl.w" k="pnlW"/> },
        { label: 'P&L·M',  value: <LiveValue id="ws.pnl.m" value={pnlM / 93.38 * 100} format={x => (x > 0 ? '+' : '') + x.toFixed(2) + '%'} style={{ color: pnlM < 0 ? 'var(--qe-red)' : 'var(--qe-green)', fontWeight: 700 }}/> },
        { label: 'OPEN',   value: `${MOCK.positionsOpen.length}/20`, color: 'var(--qe-cyan)' },
        { label: 'EXP',    value: <LiveValue id="ws.exp" value={MOCK.risk.exposure.v} format={x => x.toFixed(2) + '×'} /> },
        { label: 'DD',     value: <LiveValue id="ws.dd" value={0.00} format={x => x.toFixed(2) + '%'} /> },
      ]} />

      <button className="qe-btn qe-btn-sm" disabled title="Add pane — planned, not wired in this build" style={{ opacity: 0.4, cursor: 'default' }}>⊞ Pane</button>
      <button className="qe-btn qe-btn-sm" disabled title="Pop out — planned, not wired in this build" style={{ opacity: 0.4, cursor: 'default' }}>⤢ Pop</button>
    </div>
  );
};

const TopNavStd = ({page='Dashboard', onChange, variant='line', dense=false}) => {
  const [locked, toggleLock] = useWorkspaceLock();
  const navLat = window.useQeLive('lat');
  // When a page doesn't pass onChange, delegate to the global app router (app-shell.jsx).
  const nav = onChange || ((p) => { if (window.qeNav) window.qeNav(p); });
  return (
  <React.Fragment>
  <div className="qe-hscroll" style={{
    display:'flex', alignItems:'center', gap:0,
    background:'var(--qe-bg)', borderBottom:'1px solid var(--qe-line)',
    fontFamily:'var(--qe-ui)', height: dense ? 32 : 38, flexShrink:0,
  }}>
    <div style={{padding:'0 14px', display:'flex', alignItems:'baseline', gap:8, borderRight:'1px solid var(--qe-line)', alignSelf:'stretch', alignItems:'center'}}>
      <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:700, color:'var(--qe-cyan)', letterSpacing:'0.08em'}}>{(window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName) || 'QRE'}</span>
      <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-sub)', letterSpacing:'0.06em'}}>{(window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion) || 'v3'}</span>
    </div>
    <div style={{display:'flex', alignSelf:'stretch'}}>
      {NAV_ITEMS.map(it => {
        const on = page === it;
        if (variant==='line') return (
          <React.Fragment key={it}>
            {it==='Primitives' && <div style={{width:1, alignSelf:'center', height:16, background:'var(--qe-line)', margin:'0 6px'}}/>}
            <button onClick={()=>nav(it)} style={{
              background:'transparent', border:'none', cursor:'pointer',
              padding:'0 12px', height:'100%', display:'inline-flex', alignItems:'center', gap:5,
              fontFamily:'var(--qe-ui)', fontSize:'0.72rem', fontWeight:on?700:500,
              color: on ? (it==='Primitives'?'var(--qe-amber)':'var(--qe-cyan)') : 'var(--qe-sub)',
              borderBottom: on ? `2px solid ${it==='Primitives'?'var(--qe-amber)':'var(--qe-cyan)'}` : '2px solid transparent',
              marginBottom: '-1px', letterSpacing:'0.04em',
            }}>
              {it}
              {it==='Primitives' && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.08em', color: on?'var(--qe-bg)':'var(--qe-amber)', background: on?'var(--qe-amber)':'transparent', border:'1px solid var(--qe-amber)', padding:'0 3px', lineHeight:1.4}}>DEV</span>}
            </button>
          </React.Fragment>
        );
        if (variant==='solid') return (
          <button key={it} onClick={()=>nav(it)} style={{
            background: on ? 'var(--qe-cyan)' : 'transparent',
            color: on ? 'var(--qe-bg)' : 'var(--qe-sub)',
            border:'none', cursor:'pointer', padding:'0 14px', height:'100%',
            fontFamily:'var(--qe-ui)', fontSize:'0.72rem', fontWeight:on?700:500,
            letterSpacing:'0.04em',
          }}>{it}</button>
        );
        // bracket
        return (
          <button key={it} onClick={()=>nav(it)} style={{
            background:'transparent', border:'none', cursor:'pointer',
            padding:'0 10px', height:'100%',
            fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:on?700:500,
            color: on ? 'var(--qe-cyan)' : 'var(--qe-sub)',
          }}>
            {on ? <>[<span style={{padding:'0 2px'}}>{it}</span>]</> : it}
          </button>
        );
      })}
    </div>
    <div className="qe-grow"/>
    <div style={{display:'flex', alignItems:'center', gap:8, padding:'0 12px', alignSelf:'stretch'}}>
      <span style={{display:'inline-flex', alignItems:'center', gap:5, alignSelf:'center'}}>
        <LockButton locked={locked} onToggle={toggleLock} compact
          style={{height:22, width:22, padding:0, justifyContent:'center'}}/>
        <select className="qe-input qe-select" style={{height:22, fontSize:'0.62rem', width:175}} defaultValue="acc1">
          <option value="acc1">Account 1 (Binance)</option>
          <option value="acc2" disabled>Bybit Linear (Test) — inactive</option>
        </select>
      </span>
      <StatusDot tone={MOCK.exchange.ws.connected?'ok':'err'} label="WS" value={MOCK.exchange.ws.connected ? <LiveValue id="nav.lat" value={navLat} format={x=>Math.round(x)+'ms'}/> : 'down'}/>
      <span style={{
        fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-muted)',
        letterSpacing:'0.04em',
      }}><LiveClock id="nav.clock" format={qeClockFmt}/></span>
      <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
        <button onClick={()=>nav('Config')} title="Configuration" style={{
          display:'inline-flex', alignItems:'center', justifyContent:'center', width:22, height:22, padding:0,
          background: page==='Config' ? 'var(--qe-bg-cyan)' : 'transparent', cursor:'pointer',
          border:`1px solid ${page==='Config' ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
          color: page==='Config' ? 'var(--qe-cyan)' : 'var(--qe-sub)', fontSize:'0.85rem', lineHeight:1, transition:'all 0.12s',
        }}
          onMouseOver={e => { e.currentTarget.style.color='var(--qe-cyan)'; e.currentTarget.style.borderColor='var(--qe-line-2)'; }}
          onMouseOut={e => { e.currentTarget.style.color = page==='Config'?'var(--qe-cyan)':'var(--qe-sub)'; e.currentTarget.style.borderColor = page==='Config'?'var(--qe-cyan)':'var(--qe-line)'; }}>⚙</button>
        <NotifBell/>
      </span>
    </div>
  </div>
  <NotifBanner/>
  <WorkspaceBar interactive={page === 'Dashboard'} />
  </React.Fragment>
  );
};

// Watchlist data — used in dense tiled view
const MOCK_WATCHLIST = [
  {sym:'BTCUSDT',  last:'93580.40', d:+0.18, vol:'1.2M'},
  {sym:'ETHUSDT',  last:'3208.20',  d:-0.19, vol:'842K'},
  {sym:'SOLUSDT',  last:'139.21',   d:+0.57, vol:'412K'},
  {sym:'AVAXUSDT', last:'42.04',    d:-0.33, vol:'118K'},
  {sym:'LINKUSDT', last:'21.92',    d:+0.18, vol:'88K'},
  {sym:'DOGEUSDT', last:'0.1842',   d:+0.41, vol:'2.1M'},
  {sym:'WIFUSDT',  last:'2.412',    d:+1.84, vol:'620K'},
  {sym:'ARBUSDT',  last:'0.842',    d:-1.18, vol:'318K'},
  {sym:'PEPEUSDT', last:'0.0000121',d:+2.84, vol:'1.8B'},
  {sym:'XRPUSDT',  last:'0.5184',   d:-0.42, vol:'1.1M'},
];

// ── StatusFooter — the bottom status bar shown on EVERY page (no news). ──
const StatusFooter = () => {
  const lat     = window.useQeLive('lat');
  const eventsK = window.useQeLive('eventsK');
  return (
    <div style={{
      display:'flex', alignItems:'center', gap:10,
      background:'var(--qe-bg)', borderTop:'1px solid var(--qe-line)',
      padding:'1px 8px', height:18, flexShrink:0,
      fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)',
    }}>
      <span style={{color:'var(--qe-sub)'}}>{((window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName) || 'QRE') + ' ' + ((window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion) || 'v3')}</span>
      <span>·</span>
      <span>tasks queue 0</span><span>·</span>
      <span>events <LiveValue id="sb.events" value={eventsK} format={x=>x.toFixed(1)+'k'}/></span><span>·</span>
      <span>uptime 13d 4h</span>
      <div className="qe-grow"/>
      <span style={{color:'var(--qe-green)'}}>● bus</span>
      <span style={{color:'var(--qe-green)'}}>● db</span>
      <span style={{color:'var(--qe-green)'}}>● ws <LiveValue id="sb.lat" value={lat} format={x=>Math.round(x)+'ms'} style={{color:'var(--qe-muted)', marginLeft:2}}/></span>
      <LiveClock id="sb.clock" format={qeClockFmt} style={{color:'var(--qe-muted)'}}/>
    </div>
  );
};

Object.assign(window, {
  MOCK, NAV_ITEMS, TopNavStd, WorkspaceBar, StatusFooter, MOCK_WATCHLIST,
  QE_CLOCK_OFFSET, qeClockFmt,
  qeMockClockFmt: qeClockFmt,  // P0 compat alias — drop once all page modules use qeClockFmt
});
