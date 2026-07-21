/* QE v2.5 — Secondary pages
   History, Calculator, Analytics, Regime, Config
   All in the tiled-workspace direction. Standardized primitives only —
   no per-page row treatments, no per-page empty states, no per-page period
   selectors. */

// ── shared mock data for these pages ────────────────────────────────────
const MOCK_HISTORY = {
  posClosed: [
    {sym:'STOUSDT', dir:'L', size:'82.4',  entry:'0.07582', exit:'0.07658', pnl:+0.82, pct:+1.00, mfe:+1.21, mae:-0.18, feeExch:-0.04, feeFund:-0.012, feeSwap:0.000, dur:'1h 18m', reason:'TP', t:'04-25 18:43', tp:'0.07650', sl:'0.07540', calc:'c-4f298e', match:'3 / 3', matchOk:true},
    {sym:'BTCUSDT', dir:'S', size:'0.018', entry:'93580.40',exit:'93142.10',pnl:+1.93, pct:+0.47, mfe:+2.18, mae:-0.41, feeExch:-0.08, feeFund:+0.031, feeSwap:0.000, dur:'3h 22m', reason:'TP', t:'04-25 17:25', tp:'93140.00', sl:'93820.00', calc:'c-4f28f0', match:'3 / 3', matchOk:true},
    {sym:'JCTUSDT', dir:'S', size:'1200',  entry:'0.04212', exit:'0.04256', pnl:-1.04, pct:-1.04, mfe:+0.42, mae:-1.18, feeExch:-0.06, feeFund:-0.018, feeSwap:0.000, dur:'42m',    reason:'SL', t:'04-25 16:22', tp:'0.04150', sl:'0.04256', calc:'c-4f296a', match:'2 / 3', matchOk:false},
    {sym:'AIOTUSDT',dir:'L', size:'320',   entry:'0.18242', exit:'0.18324', pnl:+0.41, pct:+0.45, mfe:+0.81, mae:-0.12, feeExch:-0.02, feeFund:-0.006, feeSwap:0.000, dur:'2h 04m', reason:'TP', t:'04-25 14:08', tp:'0.18320', sl:'0.18180', calc:'c-4f293a', match:'3 / 3', matchOk:true},
    {sym:'STOUSDT', dir:'L', size:'62',    entry:'0.07712', exit:'0.07610', pnl:-1.12, pct:-1.32, mfe:+0.32, mae:-1.31, feeExch:-0.04, feeFund:-0.002, feeSwap:0.000, dur:'18m',    reason:'SL', t:'04-25 11:55', tp:'0.07810', sl:'0.07610', calc:'c-4f291a', match:'1 / 3', matchOk:false},
    {sym:'ETHUSDT', dir:'L', size:'0.42',  entry:'3220.10', exit:'3208.40', pnl:-0.55, pct:-0.36, mfe:+0.41, mae:-0.78, feeExch:-0.04, feeFund:-0.014, feeSwap:0.000, dur:'2h 14m', reason:'SL', t:'04-24 22:48', tp:'3245.00', sl:'3208.00', calc:'c-4f28c2', match:'2 / 3', matchOk:false},
  ],
  orders: [
    {id:'algo:3000412', sym:'BTCUSDT', side:'BUY',  type:'LMT', qty:'0.012', price:'93412.10', tpTrig:'94100.00', slTrig:'93180.00', status:'FILLED', t:'04-25 19:01'},
    {id:'504678492',    sym:'ETHUSDT', side:'SELL', type:'LMT', qty:'0.55',  price:'3214.50',  tpTrig:'3185.00',  slTrig:'3232.00',  status:'FILLED', t:'04-25 19:18'},
    {id:'algo:3000418', sym:'SOLUSDT', side:'BUY',  type:'STP', qty:'0.42',  price:'138.42',   tpTrig:'141.10',   slTrig:'137.20',   status:'NEW',    t:'04-25 19:52'},
  ],
  trades: [
    {sym:'BTCUSDT', action:'CLOSE', dir:'S', qty:'0.018', price:'93142.10', fee:'-0.041', pnl:+1.93, type:'TAKER', t:'04-25 19:42:18'},
    {sym:'BTCUSDT', action:'OPEN',  dir:'S', qty:'0.018', price:'93580.40', fee:'-0.038', pnl: 0.00, type:'MAKER', t:'04-25 16:20:01'},
    {sym:'ETHUSDT', action:'CLOSE', dir:'L', qty:'0.42',  price:'3208.40',  fee:'-0.020', pnl:-0.55, type:'TAKER', t:'04-25 19:02:47'},
  ],
  events: [
    {t:'04-25 19:42:18', type:'position_closed', sym:'BTCUSDT', src:'order_manager', calcId:'c-4f29a1', summary:'PnL +1.93 USDT · reason=TP', tone:'ok'},
    {t:'04-25 19:18:02', type:'order_filled',    sym:'ETHUSDT', src:'reconciler',    calcId:'c-4f29bb', summary:'qty 0.55 @ 3214.50',         tone:'info'},
    {t:'04-25 19:01:08', type:'order_placed',    sym:'BTCUSDT', src:'risk_engine',   calcId:'c-4f29a1', summary:'LMT 0.012 @ 93412.10',       tone:'info'},
    {t:'04-25 18:43:12', type:'tp_hit',          sym:'STOUSDT', src:'order_state',   calcId:'c-4f298e', summary:'+0.82 · tp=0.07650',          tone:'ok'},
    {t:'04-25 16:22:55', type:'sl_hit',          sym:'JCTUSDT', src:'order_state',   calcId:'c-4f296a', summary:'-1.04 · sl=0.04256',          tone:'err'},
  ],
  // Pre-trade calc log — every sizing calc submitted from Pre-Trade in the
  // window (mirrors linkage CALC ids · 5-min link windows · 1% risk gate).
  pretrade: [
    {t:'04-25 19:48', id:'CALC-2c55', sym:'SOLUSDT',  dir:'L', entry:'138.40',   tp:'141.10',   sl:'137.20',   size:'2.4',   model:'trend_v1',    status:'LINKED'},
    {t:'04-25 19:14', id:'CALC-9d17', sym:'ETHUSDT',  dir:'S', entry:'3216.00',  tp:'3185.00',  sl:'3242.00',  size:'0.55',  model:'mean_rev_v2', status:'LINKED'},
    {t:'04-25 18:57', id:'CALC-6b02', sym:'BTCUSDT',  dir:'L', entry:'93400.00', tp:'94100.00', sl:'93180.00', size:'0.012', model:'momentum_v3', status:'LINKED'},
    {t:'04-25 18:31', id:'CALC-88d1', sym:'STOUSDT',  dir:'L', entry:'0.07580',  tp:'0.07650',  sl:'0.07510',  size:'82.4',  model:'breakout_v1', status:'LINKED'},
    {t:'04-25 16:44', id:'CALC-51b0', sym:'AVAXUSDT', dir:'L', entry:'42.30',    tp:'43.10',    sl:'41.85',    size:'8.2',   model:'momentum_v3', status:'EXPIRED'},
    {t:'04-25 16:12', id:'CALC-3c19', sym:'BTCUSDT',  dir:'S', entry:'93600.00', tp:'93140.00', sl:'93830.00', size:'0.018', model:'momentum_v3', status:'LINKED'},
    {t:'04-25 15:38', id:'CALC-0f9a', sym:'JCTUSDT',  dir:'S', entry:'0.04210',  tp:'0.04110',  sl:'0.04262',  size:'1200',  model:'mean_rev_v2', status:'LINKED'},
    {t:'04-25 14:02', id:'CALC-7e63', sym:'LINKUSDT', dir:'S', entry:'21.86',    tp:'21.20',    sl:'22.10',    size:'12.6',  model:'breakout_v1', status:'LINKED'},
  ],
};

// ─────────────────────────────────────────────────────────────────────────
// HISTORY PAGE
// ─────────────────────────────────────────────────────────────────────────
// Per-position fee model: all-in = exchange + funding + swap (negative = cost).
const feeTot = p => (p.feeExch||0) + (p.feeFund||0) + (p.feeSwap||0);
const fmtFee = v => (v > 0 ? '+' : '') + v.toFixed(2);
const fmtSig = v => (v >= 0 ? '+' : '') + (+v).toFixed(2);

// Inline excursion (heat) bar — center = entry, red extent = MAE (heat against),
// green extent = MFE (heat in favor), bright tick = where the trade actually
// closed (realized pnl) within its range. Div-based cell formatting (no chart).
const HistHeat = ({mfe, mae, pnl, w = 84, h = 12}) => {
  const span = Math.max(Math.abs(mfe), Math.abs(mae), Math.abs(pnl)) || 1;
  const half = v => (v / span) * 50;
  const maeW = Math.max(1.5, -half(mae));
  const mfeW = Math.max(1.5,  half(mfe));
  const exit = 50 + half(pnl);
  return (
    <div style={{position:'relative', width:w, height:h, background:'var(--qe-panel)', border:'1px solid var(--qe-faint)', flexShrink:0}}>
      <div style={{position:'absolute', left:'50%', top:0, bottom:0, width:1, background:'var(--qe-line-2)'}}/>
      <div style={{position:'absolute', top:2, bottom:2, right:'50%', width:maeW + '%', background:'var(--qe-red)', opacity:0.42}}/>
      <div style={{position:'absolute', top:2, bottom:2, left:'50%',  width:mfeW + '%', background:'var(--qe-green)', opacity:0.42}}/>
      <div style={{position:'absolute', top:-1, bottom:-1, left:exit + '%', width:2, marginLeft:-1, background: pnl >= 0 ? 'var(--qe-green)' : 'var(--qe-red)'}}/>
    </div>
  );
};

// Larger, labelled heat bar for the detail pane.
const HistHeatLarge = ({p}) => (
  <div>
    <div style={{display:'flex', justifyContent:'space-between', fontFamily:'var(--qe-mono)', fontSize:'0.5rem', letterSpacing:'0.06em', marginBottom:3}}>
      <span style={{color:'var(--qe-red)'}}>MAE {p.mae.toFixed(2)}</span>
      <span style={{color:'var(--qe-muted)'}}>ENTRY</span>
      <span style={{color:'var(--qe-green)'}}>MFE +{p.mfe.toFixed(2)}</span>
    </div>
    <HistHeat mfe={p.mfe} mae={p.mae} pnl={p.pnl} w={'100%'} h={16}/>
    <div style={{textAlign:'center', fontFamily:'var(--qe-mono)', fontSize:'0.5rem', color: p.pnl>=0?'var(--qe-green)':'var(--qe-red)', marginTop:3}}>
      ▲ exit {fmtSig(p.pnl)} ({p.pct>=0?'+':''}{p.pct.toFixed(2)}%)
    </div>
  </div>
);

// Plan-vs-actual reconciliation block for the selected position.
const HistExecLink = ({p}) => (
  <div style={{display:'grid', gridTemplateColumns:'80px 1fr', gap:'4px 8px', fontSize:'0.66rem', fontFamily:'var(--qe-mono)'}}>
    <span style={{color:'var(--qe-muted)'}}>calc_id</span><span style={{color:'var(--qe-cyan)'}}>{p.calc}</span>
    <span style={{color:'var(--qe-muted)'}}>match</span><span><Badge tone={p.matchOk?'ok':'warn'}>{p.match} criteria</Badge></span>
    <span style={{color:'var(--qe-muted)'}}>entry diff</span><span style={{color:'var(--qe-green)'}}>+0.02%</span>
    <span style={{color:'var(--qe-muted)'}}>tp diff</span><span style={{color:'var(--qe-green)'}}>±0.00%</span>
    <span style={{color:'var(--qe-muted)'}}>sl diff</span><span style={{color: p.matchOk?'var(--qe-green)':'var(--qe-red)'}}>{p.matchOk?'±0.00%':'-0.14%'}</span>
  </div>
);

// Fills reconstructed from a closed position (two opening makers + the close).
const histFillsFor = (p) => {
  const h = parseFloat(p.size) / 2;
  const hs = Number.isFinite(h) ? (Number.isInteger(h) ? String(h) : h.toFixed(h < 1 ? 3 : 1)) : p.size;
  return [
    {t:`${p.t}:11`, qty:hs,     price:p.entry, fee:fmtFee((p.feeExch||0)/2), type:'MAKER'},
    {t:`${p.t}:14`, qty:hs,     price:p.entry, fee:fmtFee((p.feeExch||0)/2), type:'MAKER'},
    {t:`${p.t}:41`, qty:p.size, price:p.exit,  fee:fmtFee(p.feeExch||0),     type:p.reason==='TP'?'MAKER':'TAKER'},
  ];
};

// Per-tab records-pane footer — mirrors the engine event that last refreshed the
// pane (every History pane now carries one). Positions stats are computed live.
const histRecordsFoot = (tab) => {
  if (tab === 'orders') {
    const o = MOCK_HISTORY.orders, filled = o.filter(x => x.status === 'FILLED').length;
    return {tone:'info', id:4002, msg:`${o.length} orders · ${filled} filled · ${o.length-filled} working · order_manager synced`, ms:8};
  }
  if (tab === 'trades') return {tone:'info', id:4003, msg:`${MOCK_HISTORY.trades.length} fills · reconciled from agg_trades · maker/taker tagged`, ms:6};
  if (tab === 'events') return {tone:'info', id:4004, msg:`${MOCK_HISTORY.events.length} events · engine_events stream · newest first`, ms:4};
  if (tab === 'pretrade') {
    const p = MOCK_HISTORY.pretrade, linked = p.filter(x => x.status === 'LINKED').length;
    return {tone:'info', id:4005, msg:`${p.length} pre-trade calcs · ${linked} linked · ${p.length - linked} expired unused · risk 1.00%/trade`, ms:3};
  }
  const r = MOCK_HISTORY.posClosed;
  const net = r.reduce((s, p) => s + p.pnl, 0);
  const wins = r.filter(p => p.pnl >= 0).length;
  return {tone: net >= 0 ? 'ok' : 'warn', id:4001,
    msg:`${r.length} closed · Σ net ${fmtFee(net)} · winrate ${Math.round(wins/r.length*100)}% · last ${r[0].t}`, ms:5};
};

// mock clock anchor — the engine's frozen "now" (matches the top-nav server time)
const HIST_NOW = Date.parse('2026-04-25T20:08:36Z');
const histDate = (t) => { const [md, hm = '00:00'] = String(t).split(' '); return Date.parse(`2026-${md}T${hm.length === 5 ? hm + ':00' : hm}Z`); };
const histInPeriod = (t, period) => {
  if (period === 'all') return true;
  const d = histDate(t);
  if (period === 'ytd') return d >= Date.parse('2026-01-01T00:00:00Z');
  const days = { '7d': 7, '15d': 15, '30d': 30, '90d': 90 }[period] || 30;
  return HIST_NOW - d <= days * 86400000;
};

const HistoryPage = () => {
  const [tab, setTab] = React.useState('positions');
  const [period, setPeriod] = React.useState('30d');
  const [q, setQ] = React.useState('');
  const [sel, setSel] = React.useState(null);
  const dp = sel != null ? MOCK_HISTORY.posClosed[sel] : null;
  const detailFoot = dp
    ? {tone: dp.matchOk ? 'ok' : 'warn', id:4010, msg:`exec ${dp.calc} · ${dp.match} match · entry/exit reconciled`, ms:7}
    : {tone:'sub', id:4010, msg:'select a closed position to inspect its fills + exec link', ms:0};

  // period + free-text filter, applied to every records tab (search spans all fields)
  const needle = q.trim().toLowerCase();
  const hFilter = rows => rows.filter(r => histInPeriod(r.t, period) && (!needle || JSON.stringify(r).toLowerCase().includes(needle)));
  const fPos    = hFilter(MOCK_HISTORY.posClosed.map((p, i) => ({ ...p, _i: i })));
  const fOrders = hFilter(MOCK_HISTORY.orders);
  const fTrades = hFilter(MOCK_HISTORY.trades);
  const fEvents = hFilter(MOCK_HISTORY.events);
  const fPre    = hFilter(MOCK_HISTORY.pretrade);

  // Export CSV — downloads the visible (filtered) rows of the active tab
  const exportCsv = () => {
    const sets = { positions: fPos, orders: fOrders, trades: fTrades, events: fEvents, pretrade: fPre };
    const rows = sets[tab] || [];
    if (!rows.length) return;
    const cols = Object.keys(rows[0]).filter(k => k !== '_i');
    const esc = v => { const s = String(v ?? ''); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const csv = [cols.join(','), ...rows.map(r => cols.map(c => esc(r[c])).join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `qe-history-${tab}-${period}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="qe-scope" data-screen-label="04 History" style={{
      width:'100%', height:'100%', background:'var(--qe-bg)',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      <TopNavStd page="History" variant="line" dense/>

      {/* Page header */}
      <PageHeader title="History" subtitle="closed positions · orders · fills · events · pre-trade log">
        <PeriodSelector options={[['7d','7D'],['15d','15D'],['30d','30D'],['90d','90D'],['ytd','YTD'],['all','ALL']]} value={period} onChange={setPeriod}/>
        <input className="qe-input" placeholder="filter SYM / id / reason…" value={q} onChange={e=>setQ(e.target.value)}
          onKeyDown={e=>{ if (e.key==='Escape') setQ(''); }}
          style={{width:200, height:22, boxSizing:'border-box'}}/>
        <button className="qe-btn qe-btn-sm" onClick={exportCsv} title="Download the visible rows as CSV">Export CSV</button>
      </PageHeader>

      {/* Summary strip */}
      <Strip dense style={{margin:6, marginBottom:0}} items={[
        {label:'TRADES', value:'31'},
        {label:'WINS',   value:'12', color:'var(--qe-green)'},
        {label:'LOSSES', value:'19', color:'var(--qe-red)'},
        {label:'WINRATE',value:'38.7%'},
        {label:'AVG R',  value:'1.20R'},
        {label:'GROSS',  value:'-8.64', color:'var(--qe-red)'},
        {label:'FEES',   value:'-2.54', color:'var(--qe-sub)'},
        {label:'NET',    value:'-11.18', color:'var(--qe-red)'},
      ]}/>

      <TabStrip value={tab} onChange={setTab} tabs={[
        ['positions','Closed Positions', fPos.length],
        ['orders',   'Orders',           fOrders.length],
        ['trades',   'Fills',            fTrades.length],
        ['events',   'Trade Events',     fEvents.length],
        ['pretrade', 'Pre-Trade Log',    fPre.length],
      ]}/>

      <div style={{flex:1, minHeight:0, display:'flex', flexDirection:'column'}}>
        <GridWorkspace>
          {/* Records table tile */}
          <GridItem x={0} y={0} w={16} h={24} minW={8} minH={6}>
          <Pane title={({positions:'Closed Positions', orders:'Orders', trades:'Fills', events:'Trade Events', pretrade:'Pre-Trade Log'})[tab]} foot={histRecordsFoot(tab)} style={{height:'100%'}} bodyStyle={{padding:0, display:'flex', flexDirection:'column'}}>
            {tab==='positions' && (
              <div style={{flex:1, overflow:'auto'}}>
                <DataList
                  dense
                  selKey="_i" selected={sel}
                  onClick={(_,i)=>setSel(sel===i?null:i)}
                  columns={[
                    {key:'t',     label:'CLOSED', cell:'dim'},
                    {key:'sym',   label:'SYM',    cell:'sym'},
                    {key:'dir',   label:'SIDE',   render:p=><Badge tone={p.dir==='L'?'ok':'err'}>{p.dir==='L'?'LONG':'SHORT'}</Badge>},
                    {key:'size',  label:'SIZE',   align:'right'},
                    {key:'entry', label:'ENTRY',  cell:'dim'},
                    {key:'exit',  label:'EXIT',   cell:'dim'},
                    {key:'heat',  label:'MAE ◂ HEAT ▸ MFE', sort:false, search:false, filter:false, render:p=><HistHeat mfe={p.mfe} mae={p.mae} pnl={p.pnl}/>},
                    {key:'pnl',   label:'NET',    align:'right', render:p=><span style={{color:p.pnl>=0?'var(--qe-green)':'var(--qe-red)',fontWeight:700}}>{p.pnl>=0?'+':''}{p.pnl.toFixed(2)}</span>},
                    {key:'pct',   label:'%',      align:'right', render:p=><span style={{color:p.pct>=0?'var(--qe-green)':'var(--qe-red)'}}>{p.pct>=0?'+':''}{p.pct.toFixed(2)}%</span>},
                    {key:'feeAll',label:<span title="all-in: exchange + funding + swap">FEE</span>, align:'right', render:p=><span className="qe-mono" style={{color:'var(--qe-sub)'}} title={`exch ${fmtFee(p.feeExch)} · funding ${fmtFee(p.feeFund)} · swap ${fmtFee(p.feeSwap)}`}>{fmtFee(feeTot(p))}</span>},
                    {key:'dur',   label:'DUR',    cell:'dim'},
                    {key:'reason',label:'REASON', render:p=><Badge tone={p.reason==='TP'?'ok':'err'}>{p.reason}</Badge>},
                  ]}
                  rows={fPos}
                  emptyMsg="no closed positions match the filter"
                />
              </div>
            )}
            {tab==='orders' && (
              <div style={{flex:1, overflow:'auto'}}>
                <DataList
                  dense
                  columns={[
                    {key:'t',     label:'TIME',     cell:'dim'},
                    {key:'id',    label:'ORDER ID', cell:'dim'},
                    {key:'sym',   label:'SYM',      cell:'sym'},
                    {key:'side',  label:'SIDE',     render:o=><Badge tone={o.side==='BUY'?'ok':'err'}>{o.side}</Badge>},
                    {key:'type',  label:'TYPE',     render:o=><Badge tone="mute">{o.type}</Badge>},
                    {key:'qty',   label:'QTY'},
                    {key:'price', label:'PRICE'},
                    {key:'tpTrig',label:'TP',       cell:'up'},
                    {key:'slTrig',label:'SL',       cell:'dn'},
                    {key:'status',label:'STATUS',   render:o=><Badge tone={o.status==='FILLED'?'ok':o.status==='NEW'?'info':'mute'}>{o.status}</Badge>},
                  ]}
                  rows={fOrders}
                  emptyMsg="no orders match the filter"
                />
              </div>
            )}
            {tab==='trades' && (
              <div style={{flex:1, overflow:'auto'}}>
                <DataList
                  dense
                  columns={[
                    {key:'t',     label:'TIME',   cell:'dim'},
                    {key:'sym',   label:'SYM',    cell:'sym'},
                    {key:'action',label:'ACTION', render:t=><Badge tone={t.action==='OPEN'?'info':'mute'}>{t.action}</Badge>},
                    {key:'dir',   label:'SIDE',   render:t=><Badge tone={t.dir==='L'?'ok':'err'}>{t.dir==='L'?'LONG':'SHORT'}</Badge>},
                    {key:'qty',   label:'QTY'},
                    {key:'price', label:'PRICE',  cell:'dim'},
                    {key:'fee',   label:'FEE',    cell:'dim'},
                    {key:'pnl',   label:'PnL',    render:t=><span style={{color:t.pnl>=0?'var(--qe-green)':t.pnl<0?'var(--qe-red)':'var(--qe-muted)'}}>{t.pnl===0?'—':(t.pnl>=0?'+':'')+t.pnl.toFixed(2)}</span>},
                    {key:'type',  label:'TYPE',   render:t=><Badge tone="mute">{t.type}</Badge>},
                  ]}
                  rows={fTrades}
                  emptyMsg="no fills match the filter"
                />
              </div>
            )}
            {tab==='events' && (
              <div style={{flex:1, overflow:'auto'}}>
                <DataList
                  dense
                  columns={[
                    {key:'t',      label:'TIME',    cell:'dim'},
                    {key:'type',   label:'TYPE',    render:e=><Badge tone={e.tone}>{e.type}</Badge>},
                    {key:'sym',    label:'SYM',     cell:'sym'},
                    {key:'src',    label:'SRC',     cell:'dim'},
                    {key:'calcId', label:'CALC',    cell:'dim'},
                    {key:'summary',label:'SUMMARY'},
                  ]}
                  rows={fEvents}
                  emptyMsg="no events match the filter"
                />
              </div>
            )}
            {tab==='pretrade' && (
              <div style={{flex:1, overflow:'auto'}}>
                <DataList
                  selKey="id" dense
                  columns={[
                    {key:'t',      label:'TIME',    cell:'dim'},
                    {key:'id',     label:'CALC ID', render:r=><span style={{color:'var(--qe-cyan)', fontFamily:'var(--qe-mono)'}}>{r.id}</span>},
                    {key:'sym',    label:'SYM',     render:r=><span style={{color:'var(--qe-cyan)', fontWeight:700}}>{r.sym}</span>},
                    {key:'dir',    label:'SIDE',    render:r=><Badge tone={r.dir==='L'?'ok':'err'}>{r.dir==='L'?'LONG':'SHORT'}</Badge>},
                    {key:'entry',  label:'ENTRY',   align:'right', cell:'dim'},
                    {key:'tp',     label:'TP',      align:'right', render:r=><span style={{color:'var(--qe-green)'}}>{r.tp}</span>},
                    {key:'sl',     label:'SL',      align:'right', render:r=><span style={{color:'var(--qe-red)'}}>{r.sl}</span>},
                    {key:'size',   label:'SIZE',    align:'right'},
                    {key:'model',  label:'MODEL',   cell:'dim'},
                    {key:'status', label:'LINK',    render:r=><Badge tone={r.status==='LINKED'?'ok':r.status==='EXPIRED'?'mute':'info'}>{r.status}</Badge>},
                  ]}
                  rows={fPre}
                  emptyMsg="no pre-trade calcs match the filter"
                />
              </div>
            )}
          </Pane>
          </GridItem>

          {/* Detail tile */}
          <GridItem x={16} y={0} w={8} h={24} minW={6} minH={6}>
          <Pane title="Position Detail" foot={detailFoot} style={{height:'100%'}}>
            {dp ? (
            <div style={{display:'flex', flexDirection:'column', gap:8}}>
              <SecLbl rule
                right={<button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={()=>setSel(null)}>✕</button>}>
                {dp.sym} · CLOSED · {dp.dir==='L'?'LONG':'SHORT'}
              </SecLbl>
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
                <div><Lbl>Net</Lbl><Delta value={dp.pnl.toFixed(2)} pct={dp.pct.toFixed(2)} size="1.2rem"/></div>
                <div><Lbl>Duration</Lbl><div className="qe-mono" style={{fontSize:'0.86rem', fontWeight:700}}>{dp.dur}</div></div>
              </div>
              <HistHeatLarge p={dp}/>
              <div className="qe-divider-h"/>
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'6px 10px'}}>
                <KV l="Entry" v={dp.entry}/>
                <KV l="Exit"  v={dp.exit}/>
                <KV l="TP plan" v={dp.tp} color="var(--qe-green)"/>
                <KV l="SL plan" v={dp.sl} color="var(--qe-red)"/>
                <KV l="Size"  v={dp.size}/>
                <KV l="Fee · all-in" v={fmtFee(feeTot(dp))} color="var(--qe-sub)"/>
              </div>
              <div className="qe-divider-h"/>
              <SecLbl rule>Exec Link</SecLbl>
              <HistExecLink p={dp}/>
              <div className="qe-divider-h"/>
              <SecLbl rule>Fills</SecLbl>
              <DataList
                dense tools={false}
                columns={[
                  {key:'t',    label:'TIME',  cell:'dim'},
                  {key:'qty',  label:'QTY',   align:'right'},
                  {key:'price',label:'PRICE', align:'right'},
                  {key:'fee',  label:'FEE',   align:'right', cell:'dim'},
                  {key:'type', label:'TYPE',  render:f=><Badge tone="mute">{f.type}</Badge>},
                ]}
                rows={histFillsFor(dp)}
              />
            </div>
            ) : (
              <EmptyState tone="neutral" glyph="◎" msg="Select a closed position"
                hint="Click a row in the table to inspect its fills and exec link."/>
            )}
          </Pane>
          </GridItem>
        </GridWorkspace>
      </div>
      <StatusFooter/>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// CALCULATOR PAGE — mirrors templates/calculator.html + calc_result.html
// ─────────────────────────────────────────────────────────────────────────
const CALC_RECENT = [
  {age:20,  ticker:'BTCUSDT',  type:'market', side:'LONG',  entry:93412.10, tp:94100.00, sl:93180.00, regime:'risk_on_choppy',   mult:0.6},
  {age:140, ticker:'STOUSDT',  type:'limit',  side:'LONG',  entry:0.07582,  tp:0.07650,  sl:0.07540,  regime:'risk_on_choppy',   mult:0.6},
];
// Ticking relative age for recent setups — anchored at page load, advances live.
const SetupAge = ({sec}) => {
  const [, force] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => { const iv = setInterval(force, 15000); return () => clearInterval(iv); }, []);
  const t0 = window.__qeSetupT0 || (window.__qeSetupT0 = Date.now());
  const s = sec + Math.round((Date.now() - t0) / 1000);
  return <>{s < 60 ? 'Just now' : s < 3600 ? Math.floor(s / 60) + 'm ago' : Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm ago'}</>;
};

const CalculatorPage = () => {
  const [orderType, setOrderType] = React.useState('market'); // market | limit | stop
  const [tpslMode,  setTpslMode]  = React.useState('price');  // price | pct
  const [side,      setSide]      = React.useState('long');   // long | short  (only for pct mode)
  const [sizeUnit,  setSizeUnit]  = React.useState('notional');// notional | contracts | lot
  const [priceUnit, setPriceUnit] = React.useState('price');  // price | ticks
  const [copiedCell, setCopiedCell] = React.useState(null);   // Setup Summary: label of last-copied field
  const copyCell = (label, value) => {
    const clean = String(value).replace(/,/g, '');             // paste-safe · no commas
    try { navigator.clipboard && navigator.clipboard.writeText(clean).catch(() => {}); } catch (e) {}
    setCopiedCell(label);
    setTimeout(() => setCopiedCell(c => c === label ? null : c), 1200);
  };
  const [applyMult, setApplyMult] = React.useState(true);
  const [autoRate,  setAutoRate]  = React.useState(1);        // 1 | 5 | 10 | 30 | 0 (paused)

  // mock derived numbers
  const calc = {
    ticker:'BTCUSDT', side:'LONG', orderType:'MARKET',
    avgEntry:'93,412.10', riskUsdt:'0.82', baseSize:'1,124.50',
    entryPx:93412.10, tpPx:94100.00, slPx:93180.00, tickSize:0.10,
    estFill:'93,418.62', depthMid:'2.4M USDT', bestBid:'93,411.80', bestAsk:'93,412.40',
    size:'0.012',      sizeRaw:'0.020',  notional:'1,120.94',
    tpUsdt:'+1.65',    slUsdt:'-0.82',
    slipPct:'0.007%',  slipUsdt:'0.08',
    netProfit:'+1.57', netLoss:'-0.90', estR:'1.91',
    estExp:'0.014×',   feeRtPct:'0.100%',
    eligible:true,
    atrC:1.84,         atrCategory:'NORMAL', atr14:'0.0421', atr100:'0.0512',
    sectors: [['BTC.Majors','+1,120.94'], ['Total','+1,120.94']],
    bids: [
      ['93,411.80','0.842'],['93,411.20','1.214'],['93,410.50','2.418'],['93,410.10','0.642'],['93,409.80','3.124'],
    ],
    asks: [
      ['93,412.40','1.024'],['93,413.10','0.812'],['93,413.80','1.418'],['93,414.20','2.018'],['93,415.10','0.724'],
    ],
  };

  // hard stop banner state (mock — would come from params)
  const halt = null; // 'weekly' | 'dd' | null
  const haltTime = React.useMemo(() => new Date().toLocaleTimeString('en-GB', { hour12:false }), []);

  return (
    <div className="qe-scope" data-screen-label="02 Pre-Trade" style={{
      width:'100%', height:'100%', background:'var(--qe-bg)',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      <TopNavStd page="Pre-Trade" variant="line" dense/>

      {/* Page header */}
      <PageHeader title="Pre-Trade" subtitle="position sizing · TP/SL · risk gate · exec link">
        <StatusDot tone="ok" label="GATE" value="READY"/>
        <StatusDot tone="info" label="REGIME" value="CHOP ×0.6"/>
        <StatusDot tone="info" label="LINK" value="5m window"/>
        <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-muted)'}}>risk/trade <span style={{color:'var(--qe-cyan)', fontWeight:700}}>1.00%</span></span>
      </PageHeader>

      {/* Hard-stop alert row */}
      {halt && (
        <Banner tone="err" tag="HALT" time={haltTime}
          title="TRADING HALTED"
          detail={`${halt==='weekly'?'weekly loss':'drawdown'} hard stop active · positions frozen · review Dashboard`}/>
      )}

      {/* Auto-refresh + link window strip */}
      <div style={{display:'flex', alignItems:'center', gap:8, padding:'2px 8px', background:'var(--qe-page)', borderBottom:'1px solid var(--qe-line)'}}>
        <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-muted)', letterSpacing:'0.1em'}}>↻ AUTO-REFRESH</span>
        <PeriodSelector options={[[1,'1s'],[5,'5s'],[10,'10s'],[30,'30s'],[0,'⏸']]} value={autoRate} onChange={setAutoRate}/>
        <div className="qe-grow"/>
        <div style={{display:'flex', alignItems:'center', gap:6, padding:'2px 8px', border:'1px solid var(--qe-green)', borderLeft:'3px solid var(--qe-green)', fontSize:'0.62rem', fontFamily:'var(--qe-mono)'}}>
          <span style={{color:'var(--qe-green)', fontWeight:700}}>✓ LINKABLE</span>
          <span style={{color:'var(--qe-text)'}}>4m 12s left</span>
          <span style={{color:'var(--qe-muted)'}}>(window 5 min)</span>
        </div>
      </div>

      <GridWorkspace>

          {/* INPUTS pane */}
          <GridItem x={0} y={0} w={10} h={12} minW={6} minH={8}>
          <Pane title="Order Inputs" style={{height:'100%'}}
            right={<>
              <Badge tone={orderType==='market'?'warn':'ok'}>{orderType==='market'?'TAKER FEE':'MAKER FEE'}</Badge>
            </>}
            foot={{tone:'info', id:2001, msg:'price poll 1s · ws fresh · last $93,412.10', ms:18}}>
            <div style={{display:'flex', flexDirection:'column', gap:8}}>

              {/* Order type buttons */}
              <div>
                <Lbl>Order Type</Lbl>
                <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:4, marginTop:3}}>
                  {[['market','MARKET'],['limit','LIMIT'],['stop','STOP']].map(([k,l]) => (
                    <button key={k} onClick={()=>setOrderType(k)} className={`qe-btn ${orderType===k?'qe-btn-primary':''}`} style={{height:26, justifyContent:'center'}}>{l}</button>
                  ))}
                </div>
              </div>

              {/* Ticker + Entry */}
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
                <div><Lbl>Ticker</Lbl><input className="qe-input" defaultValue="BTCUSDT"/></div>
                <div>
                  <Lbl>Entry Price{orderType==='market' && <span style={{color:'var(--qe-green)', marginLeft:4}}>(live)</span>}</Lbl>
                  <input className="qe-input" defaultValue="93412.10" style={orderType==='market'?{color:'var(--qe-green)', borderColor:'var(--qe-bg-green)'}:{}}/>
                </div>
              </div>

              {/* TP/SL mode toggle + side selector */}
              <div>
                <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:4}}>
                  <Lbl>TP / SL</Lbl>
                  <PeriodSelector options={[['price','BY PRICE'],['pct','BY %']]} value={tpslMode} onChange={setTpslMode}/>
                  {tpslMode==='pct' && (
                    <>
                      <span style={{color:'var(--qe-muted)', fontSize:'0.56rem'}}>side</span>
                      <PeriodSelector options={[['long','LONG'],['short','SHORT']]} value={side} onChange={setSide}/>
                    </>
                  )}
                </div>
                {tpslMode==='price' ? (
                  <>
                    <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
                      <div><Lbl>TP Price</Lbl><StepperInput defaultValue="94100.00" step={calc.tickSize} decimals={2} min={0} color="var(--qe-green)"/></div>
                      <div><Lbl>SL Price</Lbl><StepperInput defaultValue="93180.00" step={calc.tickSize} decimals={2} min={0} color="var(--qe-red)"/></div>
                    </div>
                    <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.6rem', color:'var(--qe-sub)', marginTop:3, padding:'2px 4px', background:'var(--qe-panel)'}}>
                      TP <span style={{color:'var(--qe-green)'}}>+0.74%</span>  ·  SL <span style={{color:'var(--qe-red)'}}>-0.25%</span>
                    </div>
                  </>
                ) : (
                  <>
                    <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
                      <div><Lbl>TP %</Lbl><StepperInput defaultValue="2.5" step={0.1} decimals={1} min={0} color="var(--qe-green)"/></div>
                      <div><Lbl>SL %</Lbl><StepperInput defaultValue="1.5" step={0.1} decimals={1} min={0} color="var(--qe-red)"/></div>
                    </div>
                    <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.6rem', color:'var(--qe-sub)', marginTop:3, padding:'2px 4px', background:'var(--qe-panel)'}}>
                      TP <span style={{color:'var(--qe-green)'}}>95,747.40</span>  ·  SL <span style={{color:'var(--qe-red)'}}>92,010.92</span>
                    </div>
                  </>
                )}
              </div>

              {/* Amounts */}
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
                <div><Lbl>TP Amount %</Lbl><input className="qe-input" defaultValue="100"/></div>
                <div><Lbl>SL Amount %</Lbl><input className="qe-input" defaultValue="100"/></div>
              </div>

              {/* Model name/desc */}
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
                <div><Lbl>Model Name</Lbl><input className="qe-input" placeholder="e.g. MA-Cross-V2"/></div>
                <div><Lbl>Model Description</Lbl><input className="qe-input" placeholder="optional notes"/></div>
              </div>

              {/* Link window override */}
              <div>
                <Lbl>Link Window Override <span style={{color:'var(--qe-muted)'}}>(blank → account default)</span></Lbl>
                <select className="qe-input qe-select" defaultValue="">
                  <option value="">(use account default — 5 min)</option>
                  <option value="1800">30 min</option>
                  <option value="3600">1 h</option>
                  <option value="14400">4 h</option>
                  <option value="21600">6 h</option>
                  <option value="43200">12 h</option>
                  <option value="86400">24 h</option>
                </select>
              </div>

              {/* Regime multiplier toggle */}
              <div style={{display:'flex', alignItems:'center', gap:6, padding:'3px 6px', background:'var(--qe-panel)', border:'1px solid var(--qe-line)'}}>
                <label style={{display:'flex', alignItems:'center', gap:6, cursor:'pointer', fontSize:'0.62rem', color:'var(--qe-text)', fontFamily:'var(--qe-mono)'}}>
                  <input type="checkbox" checked={applyMult} onChange={e=>setApplyMult(e.target.checked)} style={{accentColor:'var(--qe-cyan)'}}/>
                  Apply regime multiplier
                </label>
                <div className="qe-grow"/>
                <RegimeBadge tone="chop"/>
                <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.62rem', color:'var(--qe-cyan)', fontWeight:700}}>×0.6 size</span>
              </div>

              {/* CTA buttons */}
              <div style={{display:'flex', gap:6}}>
                <button className="qe-btn qe-btn-primary qe-btn-lg" style={{flex:1, justifyContent:'center'}}>Calculate</button>
                <button className="qe-btn qe-btn-lg">Clear</button>
              </div>
              <span style={{fontSize:'0.54rem', color:'var(--qe-muted)', textAlign:'center', fontFamily:'var(--qe-mono)'}}>
                ⌘+enter to submit · esc to clear · tab through fields
              </span>
            </div>
          </Pane>
          </GridItem>

          {/* SETUP SUMMARY pane */}
          <GridItem x={0} y={12} w={10} h={6} minW={6} minH={5}>
          <Pane title="Setup Summary" tag="CLICK TO COPY" style={{height:'100%'}}
            right={
              <div style={{display:'flex', gap:8, alignItems:'center'}}>
                <PeriodSelector options={[['price','PRICE'],['ticks','TICKS']]} value={priceUnit} onChange={setPriceUnit}/>
                <PeriodSelector options={[['notional','NOTIONAL'],['contracts','CONTRACTS'],['lot','LOT']]} value={sizeUnit} onChange={setSizeUnit}/>
              </div>
            }
            foot={{tone:'sub', id:2002, msg: priceUnit==='ticks' ? `ticks = |Δprice| ÷ tick size (${calc.tickSize}) · ${calc.ticker}` : 'paste-safe values · no commas · matches QT order-entry', ms:0}}>
            {(() => {
              const tpTicks = Math.round(Math.abs(calc.tpPx - calc.entryPx) / calc.tickSize);
              const slTicks = Math.round(Math.abs(calc.entryPx - calc.slPx) / calc.tickSize);
              const fmt = n => n.toLocaleString('en-US');
              const tpCell = priceUnit==='ticks' ? fmt(tpTicks) : '94,100.00';
              const slCell = priceUnit==='ticks' ? fmt(slTicks) : '93,180.00';
              const Cell = ({label, value, color}) => {
                const done = copiedCell === label;
                return (
                <div>
                  <Lbl>{label}</Lbl>
                  <div onClick={() => copyCell(label, value)} title={`Copy ${label}`} style={{
                    display:'flex', alignItems:'stretch', height:22, cursor:'pointer',
                    background:'var(--qe-panel)', border:`1px solid ${done ? 'var(--qe-green)' : 'var(--qe-line)'}`,
                  }}>
                    <div style={{
                      flex:1, minWidth:0, padding:'0 7px', display:'flex', alignItems:'center',
                      fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:600,
                      color, whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis',
                    }}>{value}</div>
                    <button title={`Copy ${label}`} onClick={(e) => { e.stopPropagation(); copyCell(label, value); }} style={{
                      width:22, flex:'0 0 22px', padding:0,
                      display:'flex', alignItems:'center', justifyContent:'center',
                      background:'transparent', border:'none', borderLeft:`1px solid ${done ? 'var(--qe-green)' : 'var(--qe-line)'}`,
                      color: done ? 'var(--qe-green)' : 'var(--qe-muted)', cursor:'pointer', fontSize:'0.72rem', lineHeight:1,
                    }}><span style={{display:'block', transform:'translateY(1px)'}}>{done ? '✓' : '⧉'}</span></button>
                  </div>
                </div>
              );};
              return (
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', columnGap:6}}>
              {/* left column */}
              <div style={{display:'flex', flexDirection:'column', gap:6}}>
                <Cell label="Symbol"    value={calc.ticker} color="var(--qe-cyan)"/>
                <Cell label="Direction" value={calc.side}   color={calc.side==='SHORT' ? 'var(--qe-red)' : 'var(--qe-green)'}/>
                <Cell label={`Size (${sizeUnit.toUpperCase()})`} value={sizeUnit==='notional' ? calc.notional : calc.size} color="var(--qe-cyan)"/>
              </div>
              {/* right column */}
              <div style={{display:'flex', flexDirection:'column', gap:6}}>
                <Cell label="Entry" value={calc.avgEntry} color="var(--qe-text)"/>
                <Cell label={priceUnit==='ticks'?'TP (ticks)':'TP Price'} value={tpCell} color="var(--qe-green)"/>
                <Cell label={priceUnit==='ticks'?'SL (ticks)':'SL Price'} value={slCell} color="var(--qe-red)"/>
              </div>
            </div>
              );
            })()}
          </Pane>
          </GridItem>

          {/* RECENT pane — left of Regime */}
          <GridItem x={10} y={0} w={7} h={5} minW={5} minH={4}>
          <Pane title="Recent Setups" count={CALC_RECENT.length} style={{height:'100%'}}
            foot={{tone:'sub', id:2003, msg:'localStorage · last 2 · click to recall', ms:0}}>
            <div style={{display:'flex', flexDirection:'column', gap:3}}>
              {CALC_RECENT.map((r,i) => (
                <div key={i} style={{
                  padding:'4px 7px', border:'1px solid var(--qe-line)',
                  background:'var(--qe-panel)', cursor:'pointer',
                }}>
                  <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:2}}>
                    <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.68rem', fontWeight:700, color:'var(--qe-cyan)'}}>{r.ticker}</span>
                    <Badge tone={r.side==='LONG'?'ok':'err'}>{r.side}</Badge>
                    <span style={{fontSize:'0.54rem', color:'var(--qe-muted)', textTransform:'uppercase'}}>{r.type}</span>
                    <div className="qe-grow"/>
                    <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)'}}><SetupAge sec={r.age}/></span>
                  </div>
                  <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.6rem', color:'var(--qe-sub)'}}>
                    Entry {r.entry} · TP <span style={{color:'var(--qe-green)'}}>{r.tp}</span> · SL <span style={{color:'var(--qe-red)'}}>{r.sl}</span>
                  </div>
                  <div style={{fontSize:'0.54rem', marginTop:1, fontFamily:'var(--qe-mono)'}}>
                    <span style={{color:'var(--qe-cyan)'}}>RISK ON CHOPPY</span>
                    <span style={{color:'var(--qe-muted)'}}> ×{r.mult.toFixed(1)} size</span>
                  </div>
                </div>
              ))}
            </div>
          </Pane>
          </GridItem>

          {/* REGIME + ATR pane — right of Recent */}
          <GridItem x={17} y={0} w={7} h={5} minW={5} minH={4}>
          <Pane title="Regime · ATR Volatility" hot style={{height:'100%'}}
            foot={{tone:'info', id:2010, msg:'regime fresh · atr_c=1.84 · within normal band', ms:42}}>
            <div style={{display:'flex', flexDirection:'column', gap:10}}>
              <div>
                <Lbl>Current Regime</Lbl>
                <div style={{display:'flex', alignItems:'center', gap:6, marginTop:4, flexWrap:'wrap'}}>
                  <RegimeBadge tone="chop" label="RISK ON CHOPPY"/>
                  <span className="qe-mono" style={{fontSize:'0.78rem', fontWeight:700, color:'var(--qe-cyan)'}}>×0.6 size</span>
                </div>
                <div style={{fontSize:'0.56rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', marginTop:2}}>fresh · 48s ago · 1.00% → 0.60% risk</div>
              </div>
              <div className="qe-divider-h" style={{margin:0}}/>
              <div>
                <Lbl>Volatility (atr_c)</Lbl>
                <div style={{display:'flex', alignItems:'center', gap:6, marginTop:4, flexWrap:'wrap'}}>
                  <span className="qe-mono" style={{fontSize:'1rem', fontWeight:700}}>{calc.atrC}</span>
                  <Badge tone="ok">{calc.atrCategory}</Badge>
                </div>
                <div style={{fontSize:'0.56rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', marginTop:2}}>
                  ATR(100,4h) {calc.atr100} · ATR(14,4h) {calc.atr14}
                </div>
              </div>
            </div>
          </Pane>
          </GridItem>

          {/* POSITION RESULT pane — 3 FieldList sub-panes: Position · Pricing · After Costs */}
          <GridItem x={10} y={5} w={14} h={7} minW={8} minH={7}>
          <Pane title="Position Result" style={{height:'100%'}}
            right={<Badge tone={calc.eligible?'ok':'err'}>{calc.eligible?'✓ ELIGIBLE':'⛔ INELIGIBLE'}</Badge>}
            foot={{tone:'ok', id:2011, msg:`sized 0.012 BTC · notional 1,120.94 · risk 0.82 · R:R ${calc.estR}`, ms:6}}
            bodyStyle={{padding:0}}>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1px 1.05fr 1px 1fr', gap:0, height:'100%'}}>

              {/* ── Sub-pane 1 · Position ─────────────────────────── */}
              <div style={{padding:'7px 12px 7px 8px', display:'flex', flexDirection:'column'}}>
                <SecLbl rule>Position</SecLbl>
                <div style={{marginBottom:4}}>
                  <Lbl>Size (Contracts) <span style={{color:'var(--qe-muted)'}}>×0.6 regime</span></Lbl>
                  <div className="qe-mono" style={{fontSize:'1.5rem', fontWeight:700, color:'var(--qe-cyan)', lineHeight:1.05}}>{calc.size}</div>
                  <div style={{fontSize:'0.54rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>without regime: {calc.sizeRaw}</div>
                </div>
                <FieldList rows={[
                  {label:'Notional',    value:<>{calc.notional} <span style={{fontSize:'0.6rem', color:'var(--qe-sub)'}}>USDT</span></>},
                  {label:'Leverage',    value:'13.6×'},
                  {label:'TP → Profit', value:calc.tpUsdt, color:'green'},
                  {label:'SL → Loss',   value:calc.slUsdt, color:'red'},
                ]}/>
              </div>

              <div style={{background:'var(--qe-line)'}}/>

              {/* ── Sub-pane 2 · Pricing ──────────────────────────── */}
              <div style={{padding:'7px 12px', display:'flex', flexDirection:'column'}}>
                <SecLbl rule>Pricing</SecLbl>
                <FieldList dense rows={[
                  {label:'Ticker',         value:calc.ticker, color:'cyan'},
                  {label:'Side',           value:calc.side,   color:'green'},
                  {label:'Order Type',     value:calc.orderType},
                  {label:'Avg Entry',      value:calc.avgEntry},
                  {label:'Risk USDT',      value:calc.riskUsdt},
                  {label:'Base Size',      value:calc.baseSize, hint:'USDT'},
                  {label:'Est. Fill',      value:calc.estFill},
                  {label:'1% Depth / Mid', value:calc.depthMid},
                  {label:'Best Bid / Ask', value:<><span style={{color:'var(--qe-green)'}}>{calc.bestBid}</span><span style={{color:'var(--qe-muted)'}}> / </span><span style={{color:'var(--qe-red)'}}>{calc.bestAsk}</span></>},
                ]}/>
              </div>

              <div style={{background:'var(--qe-line)'}}/>

              {/* ── Sub-pane 3 · After Costs ──────────────────────── */}
              <div style={{padding:'7px 8px 7px 12px', display:'flex', flexDirection:'column'}}>
                <SecLbl rule right={<span style={{fontSize:'0.5rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)', textTransform:'none', letterSpacing:0}}>n=20</span>}>After Costs</SecLbl>
                <FieldList dense rows={[
                  {label:'Est. Slippage', value:calc.slipPct, color:'amber'},
                  {label:'Slip USDT',     value:calc.slipUsdt},
                  {label:'Net Profit',    value:calc.netProfit, color:'green'},
                  {label:'Net Loss',      value:calc.netLoss, color:'red'},
                  {label:'Est. R : R',    value:calc.estR, color:'green'},
                  {label:'Portfolio Exp.', value:calc.estExp},
                  {label:'RT Fee (Taker)', value:calc.feeRtPct, color:'sub'},
                ]}/>
              </div>
            </div>
          </Pane>
          </GridItem>

          {/* CORRELATED EXPOSURE pane */}
          <GridItem x={10} y={12} w={7} h={6} minW={5} minH={4}>
          <Pane title="Correlated Sector Exposure" style={{height:'100%'}}
            foot={{tone:'ok', id:2014, msg:'all sectors within 50% cap · no breach', ms:3}}>
            <FieldList rows={[
              ...[
                ['Crypto · Majors',  '+1,120.94', '50.0% cap', 'green'],
                ['Crypto · Alt-L1',  '+0',        '50.0% cap', null],
                ['Crypto · DeFi',    '+0',        '50.0% cap', null],
                ['Crypto · Meme',    '+0',        '50.0% cap', null],
              ].map(([s,v,cap,color]) => ({label:s, value:v, meta:cap, color})),
              {label:`New (${calc.ticker})`, value:'+1,120.94 USDT', emphasis:true},
            ]}/>
          </Pane>
          </GridItem>

          {/* LIVE ORDERBOOK pane */}
          <GridItem x={17} y={12} w={7} h={6} minW={5} minH={4}>
          <Pane title="Live Orderbook" tag="2s" style={{height:'100%'}}
            right={<StatusDot tone="ok" label="LIVE"/>}
            foot={{tone:'info', id:2015, msg:'depth_n=20 · spread 0.60 USDT · 0.0006%', ms:18}}>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
              <div>
                <div style={{fontSize:'0.56rem', fontWeight:700, color:'var(--qe-green)', letterSpacing:'0.1em', marginBottom:3}}>BIDS</div>
                {calc.bids.map(([p,s], i) => (
                  <div key={i} style={{display:'flex', justifyContent:'space-between', fontFamily:'var(--qe-mono)', fontSize:'0.62rem', padding:'1px 0', position:'relative'}}>
                    <span style={{position:'absolute', right:0, top:0, bottom:0, width:`${parseFloat(s)*25}%`, background:'color-mix(in srgb, var(--qe-green) 6%, transparent)'}}/>
                    <span style={{color:'var(--qe-green)', position:'relative'}}>{p}</span>
                    <span style={{color:'var(--qe-sub)', position:'relative'}}>{s}</span>
                  </div>
                ))}
              </div>
              <div>
                <div style={{fontSize:'0.56rem', fontWeight:700, color:'var(--qe-red)', letterSpacing:'0.1em', marginBottom:3}}>ASKS</div>
                {calc.asks.map(([p,s], i) => (
                  <div key={i} style={{display:'flex', justifyContent:'space-between', fontFamily:'var(--qe-mono)', fontSize:'0.62rem', padding:'1px 0', position:'relative'}}>
                    <span style={{position:'absolute', right:0, top:0, bottom:0, width:`${parseFloat(s)*25}%`, background:'color-mix(in srgb, var(--qe-red) 6%, transparent)'}}/>
                    <span style={{color:'var(--qe-red)', position:'relative'}}>{p}</span>
                    <span style={{color:'var(--qe-sub)', position:'relative'}}>{s}</span>
                  </div>
                ))}
              </div>
            </div>
          </Pane>
          </GridItem>

      </GridWorkspace>
      <StatusFooter/>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// ANALYTICS PAGE — full 9-tab implementation
// Mirrors templates/analytics.html + 8 fragments in templates/fragments/analytics/
// ─────────────────────────────────────────────────────────────────────────

const ANALYTICS_TABS = [
  ['overview',   'Overview'],
  ['equity',     'Equity Curve'],
  ['dist',       'Distributions'],
  ['calendar',   'Calendar PnL'],
  ['pairs',      'Traded Pairs'],
  ['excursions', 'MFE / MAE'],
  ['rmultiples', 'R-Multiples'],
  ['risk',       'Risk Metrics'],
  ['execution',  'Execution Quality'],
  ['funding',    'Funding'],
  ['beta',       'Beta Exposure'],
];
// Per FE-MED-018 (Task 135): these tabs consume the page-level `period` param.
// Others (equity, calendar, funding, beta, execution) get the page-period bar dimmed.
const PERIOD_TABS = new Set(['overview','dist','pairs','excursions','rmultiples','risk']);

// ─── Mock analytics data ─────────────────────────────────────────────────
const MOCK_ANALYTICS = {
  overview: {
    volume: { tradingVolume: 134720, fee: 2.54, longs: 19, shorts: 12, topPairs: ['STOUSDT','JCTUSDT','AIOTUSDT'] },
    equity: { initial:93.38, final:82.20, monthlyPnl:-11.18, monthlyPct:-11.97, avgDaily:-0.37, avgDailyPct:-0.399, tradingDays:30 },
    trades: { total:31, wins:12, losses:19, winrate:38.7, avgWin:1.23, avgLoss:-1.02, rr:1.20, biggestWin:3.42, biggestLoss:-2.84, maxDD:12.24 },
    cash:   { deposit:0, withdraw:0, cumPnl:-11.18, cumPct:-11.97 },
    ratios: { sharpe:2.18, sharpeMfe:9.55, sortino:2.48, sortinoMae:null, pf:0.74, expectancy:-0.36 },
  },
  pairs: [
    {sym:'STOUSDT', total:8, longs:5, shorts:3, pnlL:+1.26, pnlS:-0.42, pnlT:+0.84, wr:50.0, avgW:0.82, avgL:-0.61, fees:0.41, vol:18420},
    {sym:'BTCUSDT', total:5, longs:2, shorts:3, pnlL:+0.18, pnlS:+1.75, pnlT:+1.93, wr:60.0, avgW:1.21, avgL:-0.65, fees:1.02, vol:54200},
    {sym:'AIOTUSDT',total:6, longs:4, shorts:2, pnlL:+0.32, pnlS:+0.09, pnlT:+0.41, wr:33.3, avgW:0.54, avgL:-0.17, fees:0.18, vol:8420},
    {sym:'JCTUSDT', total:4, longs:1, shorts:3, pnlL:-0.98, pnlS:-4.34, pnlT:-5.32, wr:25.0, avgW:0.42, avgL:-1.91, fees:0.32, vol:12420},
    {sym:'ETHUSDT', total:3, longs:2, shorts:1, pnlL:-3.12, pnlS:-1.74, pnlT:-4.86, wr:33.3, avgW:0.18, avgL:-2.52, fees:0.47, vol:32480},
    {sym:'SOLUSDT', total:2, longs:1, shorts:1, pnlL:+0.42, pnlS:-2.04, pnlT:-1.62, wr:50.0, avgW:0.42, avgL:-2.04, fees:0.08, vol:4820},
    {sym:'DOGEUSDT',total:2, longs:0, shorts:2, pnlL: 0.00, pnlS:-1.24, pnlT:-1.24, wr:0.0,  avgW:null, avgL:-0.62, fees:0.04, vol:2120},
    {sym:'XRPUSDT', total:1, longs:0, shorts:1, pnlL: 0.00, pnlS:-1.32, pnlT:-1.32, wr:0.0,  avgW:null, avgL:-1.32, fees:0.02, vol:1840},
  ],
  excursions: {
    // summary stats are computed live from the direction filter (see TabExcursions)
    points: (() => Array.from({length:30}, () => {
      const x = Math.random()*4;
      const y = -(Math.random()*3 + 0.1);
      const z = (Math.random()-0.55)*2;
      return {x, y, label:'Trade', profit: z>=0, dir: Math.random() > 0.5 ? 'LONG' : 'SHORT'};
    }))(),
    trades: [
      {id:'x1', sym:'BTCUSDT', dir:'SHORT', entry:93580.40, mfe:+1.21, mae:-0.18, mer:6.72,  pnl:+1.93, hold:'3h 22m'},
      {id:'x2', sym:'ETHUSDT', dir:'SHORT', entry:3214.50,  mfe:+0.84, mae:-0.92, mer:0.91,  pnl:-0.55, hold:'2h 14m'},
      {id:'x3', sym:'STOUSDT', dir:'LONG',  entry:0.07582,  mfe:+0.94, mae:-0.31, mer:3.03,  pnl:+0.82, hold:'1h 18m'},
      {id:'x4', sym:'JCTUSDT', dir:'SHORT', entry:0.04212,  mfe:+0.42, mae:-1.18, mer:0.36,  pnl:-1.04, hold:'42m'},
      {id:'x5', sym:'AIOTUSDT',dir:'LONG',  entry:0.18242,  mfe:+0.81, mae:-0.12, mer:6.75,  pnl:+0.41, hold:'2h 04m'},
      {id:'x6', sym:'STOUSDT', dir:'LONG',  entry:0.07712,  mfe:+0.32, mae:-1.31, mer:0.24,  pnl:-1.12, hold:'18m'},
    ],
  },
  rmult: {
    bins:[
      {label:'-3R',  c:1, pos:false},
      {label:'-2R',  c:3, pos:false},
      {label:'-1R',  c:8, pos:false},
      {label:'-0.5R',c:5, pos:false},
      {label:'0',    c:2, pos:false},
      {label:'+0.5R',c:3, pos:true},
      {label:'+1R',  c:5, pos:true},
      {label:'+2R',  c:3, pos:true},
      {label:'+3R',  c:1, pos:true},
    ],
    stats:{ count:31, winRate:0.387, expectancy:-0.36, pf:0.74, avgWinR:1.42, avgLossR:-1.18, best:3.21, worst:-2.84, median:-0.21, mean:-0.42 },
  },
  var: {
    hasData:true, var95:0.038, var99:0.062, cvar95:0.052, pvar95:0.041, curEquity:82.20,
    bins: Array.from({length:14}, (_, i) => {
      const x = -7 + i*1.0;
      const y = Math.max(1, Math.round(10 * Math.exp(-Math.pow((x+0.5)/2.4, 2))));
      return {x, y};
    }),
  },
  funding: [
    {sym:'BTCUSDT', dir:'LONG',  notional:1120,  rate:+0.00012, per8h:-0.134, perDay:-0.402, perWeek:-2.82, next:'04-26 00:00', adverse:true},
    {sym:'ETHUSDT', dir:'SHORT', notional:1764,  rate:+0.00008, per8h:+0.141, perDay:+0.423, perWeek:+2.96, next:'04-26 00:00', adverse:false},
    {sym:'SOLUSDT', dir:'LONG',  notional:334,   rate:-0.00004, per8h:+0.013, perDay:+0.040, perWeek:+0.28, next:'04-26 00:00', adverse:false},
    {sym:'AVAXUSDT',dir:'LONG',  notional:345,   rate:+0.00006, per8h:-0.021, perDay:-0.062, perWeek:-0.44, next:'04-26 00:00', adverse:true},
    {sym:'LINKUSDT',dir:'SHORT', notional:276,   rate:+0.00009, per8h:+0.025, perDay:+0.075, perWeek:+0.52, next:'04-26 00:00', adverse:false},
  ],
  beta: {
    rows: [
      {sym:'BTCUSDT', dir:'LONG',  sector:'BTC/ETH',     notional:1120, beta:1.00, betaAdj:1120},
      {sym:'ETHUSDT', dir:'SHORT', sector:'BTC/ETH',     notional:1764, beta:1.10, betaAdj:-1940},
      {sym:'SOLUSDT', dir:'LONG',  sector:'Top-20 Alts', notional:334,  beta:1.65, betaAdj:551},
      {sym:'AVAXUSDT',dir:'LONG',  sector:'Top-20 Alts', notional:345,  beta:1.72, betaAdj:593},
      {sym:'LINKUSDT',dir:'SHORT', sector:'Top-20 Alts', notional:276,  beta:1.45, betaAdj:-400},
    ],
    totalNotional: 3839, totalBetaExp:-76, portBeta:-0.02,
    sectorTotals: {'BTC/ETH':-820, 'Top-20 Alts':744, 'Commodities':0, 'Other Alts':0},
  },
};

// ─── Pieces ──────────────────────────────────────────────────────────────
const PeriodNav = ({period, offset, onPeriod, onNav, disabled}) => {
  const presets = [['monthly','Month'],['weekly','Week'],['quarterly','Quarter'],['yearly','Year'],['rolling_30d','30D'],['rolling_90d','90D'],['all_time','All']];
  const noNav   = new Set(['rolling_30d','rolling_90d','all_time']);
  const lbl     = (() => {
    const d = new Date(2026,3,25);
    if (period==='monthly')   { d.setMonth(d.getMonth()+offset);   return d.toLocaleString('en',{month:'long'})+' '+d.getFullYear(); }
    if (period==='weekly')    { d.setDate(d.getDate()+offset*7);   return 'Week of '+d.toLocaleString('en',{month:'short'})+' '+d.getDate(); }
    if (period==='quarterly') { d.setMonth(d.getMonth()+offset*3); return 'Q'+(Math.floor(d.getMonth()/3)+1)+' '+d.getFullYear(); }
    if (period==='yearly')    { return String(d.getFullYear()+offset); }
    if (period==='rolling_30d') return 'Rolling 30 Days';
    if (period==='rolling_90d') return 'Rolling 90 Days';
    return 'All Time';
  })();
  // Offset nav is disabled: the demo dataset is a fixed Apr-2026 window, so
  // stepping months would relabel the header without changing any data.
  const navDisabled = true;
  const navTitle = 'Demo dataset covers the April 2026 window only';
  return (
    <div title={disabled ? "Period filter doesn't apply to this sub-tab — use the chart's own period buttons." : ''}
      style={{display:'flex', alignItems:'center', gap:6, opacity: disabled ? 0.4 : 1, pointerEvents: disabled ? 'none' : 'auto'}}>
      <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={navDisabled} title={navTitle} style={{opacity:0.45}} onClick={()=>onNav(-1)}>‹</button>
      <span className="qe-mono" style={{fontSize:'0.74rem', fontWeight:700, minWidth:120, textAlign:'center', color:'var(--qe-text)'}}>{lbl}</span>
      <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={navDisabled} title={navTitle} style={{opacity:0.45}} onClick={()=>onNav(+1)}>›</button>
      <span style={{color:'var(--qe-muted)', margin:'0 2px'}}>│</span>
      <PeriodSelector options={presets} value={period} onChange={onPeriod}/>
    </div>
  );
};

const KvCell = ({label, value, color}) => (
  <div style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
    <Lbl>{label}</Lbl>
    <span className="qe-mono" style={{fontSize:'0.82rem', fontWeight:700, color: color||'var(--qe-text)'}}>{value}</span>
  </div>
);
const pnlColor = (v) => v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)';

// ─── Tab contents ────────────────────────────────────────────────────────

// VRow — vertical stat row (label left, value right) for tall narrow panes
// VRow — single key→value row. Thin wrapper over the FieldList row vocabulary
// so the standalone analytics rows share the FieldList rhythm (20px = pane head).
const VRow = ({label, value, color}) => (
  <div className="qe-fl-row">
    <div className="qe-fl-l"><span style={{overflow:'hidden', textOverflow:'ellipsis'}}>{label}</span></div>
    <div className="qe-fl-v" style={color?{color}:undefined}>{value}</div>
  </div>
);

const TabOverview = ({periodLbl}) => {
  const o = MOCK_ANALYTICS.overview;
  return (
    <GridWorkspace>

      {/* COLUMN 1 — Volume & Activity */}
      <GridItem x={0} y={0} w={8} h={6} minW={5} minH={5}>
      <Pane title="Volume & Activity" tag={periodLbl} style={{height:'100%'}}
        foot={{tone:'sub', id:3001, msg:`${o.volume.longs} longs · ${o.volume.shorts} shorts · top ${o.volume.topPairs[0]}`, ms:4}}>
        <VRow label="Trading Volume"  value={`$${o.volume.tradingVolume.toLocaleString()}`}/>
        <VRow label="Est. Broker Fee" value={`$${o.volume.fee.toFixed(2)}`}/>
        <VRow label="No. of Longs"    value={o.volume.longs}   color="var(--qe-green)"/>
        <VRow label="No. of Shorts"   value={o.volume.shorts}  color="var(--qe-red)"/>
        <div style={{marginTop:8}}>
          <Lbl>Top Pairs</Lbl>
          <div className="qe-mono" style={{fontSize:'0.68rem', color:'var(--qe-sub)', marginTop:2}}>{o.volume.topPairs.join(' · ')}</div>
        </div>
      </Pane>
      </GridItem>

      {/* COLUMN 2-3 — Equity & PnL · data (left) + equity curve (right) */}
      <GridItem x={8} y={0} w={16} h={7} minW={8} minH={5}>
      <Pane title="Equity & PnL" tag={periodLbl} style={{height:'100%'}}
        foot={{tone:'warn', id:3002, msg:`monthly pnl -11.18 · -11.97% · ${o.equity.tradingDays} trading days`, ms:3}}
        bodyStyle={{padding:0}}>
        <div style={{display:'grid', gridTemplateColumns:'minmax(200px,0.9fr) 1px 1.3fr', gap:0, height:'100%'}}>
          {/* left · stats */}
          <div style={{padding:'7px 12px 7px 8px'}}>
            <FieldList rows={[
              {label:'Initial Equity',  value:`$${o.equity.initial.toFixed(2)}`},
              {label:'Final Equity',    value:`$${o.equity.final.toFixed(2)}`},
              {label:'Period PnL',      value:`$${o.equity.monthlyPnl.toFixed(2)}`,   color:pnlColor(o.equity.monthlyPnl)},
              {label:'Period PnL %',    value:`${o.equity.monthlyPct.toFixed(2)}%`,   color:pnlColor(o.equity.monthlyPct)},
              {label:'Daily Avg PnL',   value:`$${o.equity.avgDaily.toFixed(2)}`,     color:pnlColor(o.equity.avgDaily)},
              {label:'Daily Avg PnL %', value:`${o.equity.avgDailyPct.toFixed(3)}%`,  color:pnlColor(o.equity.avgDailyPct)},
              {label:'Trading Days',    value:o.equity.tradingDays},
            ]}/>
          </div>
          {/* divider */}
          <div style={{background:'var(--qe-line)'}}/>
          {/* right · equity curve */}
          <div style={{padding:'7px 8px 7px 12px', display:'flex', flexDirection:'column', minHeight:0}}>
            <Lbl>Equity Curve · {periodLbl}</Lbl>
            <div style={{flex:1, minHeight:0, marginTop:2}}>
              <EquityChart data={MOCK.equity} color={pnlColor(o.equity.monthlyPnl)} baseline={o.equity.initial} height="100%"/>
            </div>
            <div className="qe-mono" style={{display:'flex', justifyContent:'space-between', fontSize:'0.56rem', color:'var(--qe-muted)', marginTop:2}}>
              <span>start ${o.equity.initial.toFixed(2)}</span>
              <span style={{color:pnlColor(o.equity.monthlyPnl)}}>{o.equity.monthlyPct.toFixed(2)}%</span>
              <span>end ${o.equity.final.toFixed(2)}</span>
            </div>
          </div>
        </div>
      </Pane>
      </GridItem>

      {/* COLUMN 2-3 — Cash & Cumulative (full-width bottom strip) */}
      <GridItem x={8} y={12} w={16} h={4} minW={8} minH={4}>
      <Pane title="Cash & Cumulative" style={{height:'100%'}}
        foot={{tone:'sub', id:3004, msg:'no deposits or withdrawals in window', ms:1}}>
        <FieldList cols={2} rows={[
          {label:'Deposit',          value:`$${o.cash.deposit.toFixed(2)}`},
          {label:'Withdrawal',       value:`$${o.cash.withdraw.toFixed(2)}`},
          {label:'Cumulative PnL',   value:`$${o.cash.cumPnl.toFixed(2)}`,  color:pnlColor(o.cash.cumPnl)},
          {label:'Cumulative PnL %', value:`${o.cash.cumPct.toFixed(2)}%`,  color:pnlColor(o.cash.cumPct)},
        ]}/>
      </Pane>
      </GridItem>

      {/* COLUMN 1 — Trade Statistics (10 fields stack tall) */}
      <GridItem x={0} y={6} w={8} h={10} minW={5} minH={6}>
      <Pane title="Trade Statistics" style={{height:'100%'}}
        foot={{tone:'info', id:3003, msg:`winrate 38.7% · avg R 1.20 · max DD 12.24%`, ms:8}}>
        <VRow label="Total Trades"   value={o.trades.total}/>
        <VRow label="Winning"        value={o.trades.wins}   color="var(--qe-green)"/>
        <VRow label="Losing"         value={o.trades.losses} color="var(--qe-red)"/>
        <VRow label="Win Rate"       value={`${o.trades.winrate}%`} color={o.trades.winrate>=50?'var(--qe-green)':'var(--qe-red)'}/>
        <VRow label="Avg R / R"      value={`${o.trades.rr.toFixed(2)}R`}/>
        <VRow label="Avg Profit"     value={`$${o.trades.avgWin.toFixed(2)}`}      color="var(--qe-green)"/>
        <VRow label="Avg Loss"       value={`$${o.trades.avgLoss.toFixed(2)}`}     color="var(--qe-red)"/>
        <VRow label="Biggest Win"    value={`$${o.trades.biggestWin.toFixed(2)}`}  color="var(--qe-green)"/>
        <VRow label="Biggest Loss"   value={`$${o.trades.biggestLoss.toFixed(2)}`} color="var(--qe-red)"/>
        <VRow label="Max Drawdown"   value={`${o.trades.maxDD.toFixed(2)}%`}        color="var(--qe-red)"/>
      </Pane>
      </GridItem>

      {/* COLUMNS 2-3 — Performance Ratios (spans 2 cols for breathing room) */}
      <GridItem x={8} y={7} w={16} h={5} minW={8} minH={5}>
      <Pane title="Performance Ratios" style={{height:'100%'}}
        foot={{tone:'info', id:3005, msg:`sharpe 2.18 · sortino 2.48 · pf 0.74 · exp -0.36R`, ms:12}}>
        <FieldList cols={2} rows={[
          ['Sharpe',         o.ratios.sharpe,     'annualized'],
          ['Sharpe (MFE)',   o.ratios.sharpeMfe,  'mfe / notional'],
          ['Sortino',        o.ratios.sortino,    'downside σ'],
          ['Sortino (MAE)',  o.ratios.sortinoMae, 'mae / notional'],
          ['Profit Factor',  o.ratios.pf,         'Σ gross w / |Σ gross l|'],
          ['Expectancy',     o.ratios.expectancy, 'mean R-multiple', 'R'],
        ].map(([l,v,d,suf]) => {
          const empty = v == null;
          const num = empty ? null : parseFloat(v);
          const color = empty ? 'sub' : (num >= 2 ? 'green' : num >= 1 ? 'amber' : 'red');
          return { label:l, hint:d, value: empty?'—':(num.toFixed(2) + (suf||'')), color };
        })}/>
      </Pane>
      </GridItem>

    </GridWorkspace>
  );
};

const TabEquity = () => {
  const [tf, setTf] = React.useState('1h');
  const [logScale, setLogScale] = React.useState(false);
  const [ddMode, setDdMode] = React.useState(false);
  const last = MOCK.ohlc[MOCK.ohlc.length-1];
  // running drawdown % from close-to-close equity (peak-relative)
  const ddSeries = React.useMemo(() => {
    let peak = -Infinity;
    return MOCK.ohlc.map(d => { peak = Math.max(peak, d[2]); return +(((d[2] - peak) / peak) * 100).toFixed(2); });
  }, []);
  return (
    <div style={{padding:4, height:'100%'}}>
      <Pane title="Equity Curve" hot tag={ddMode ? 'DRAWDOWN %' : 'OHLC'}
        right={
          <>
            <PeriodSelector options={[['1h','1H'],['4h','4H'],['1d','1D'],['1w','1W'],['1mo','1M']]} value={tf} onChange={setTf}/>
            <button className={`qe-btn qe-btn-sm ${logScale && !ddMode ? 'qe-btn-on' : 'qe-btn-ghost'}`}
              disabled={ddMode} style={ddMode ? {opacity:0.4} : undefined}
              onClick={() => setLogScale(v => !v)}>log scale</button>
            <button className={`qe-btn qe-btn-sm ${ddMode ? 'qe-btn-on' : 'qe-btn-ghost'}`}
              onClick={() => setDdMode(v => !v)}>drawdown %</button>
          </>
        }
        foot={{tone:'info', id:3010, msg:'equity_ohlc refresh · 1Hz tick · n=1247 snapshots', ms:14}}
        style={{height:'100%'}}
        bodyStyle={{padding:6}}>
        <div style={{height:'100%', display:'flex', flexDirection:'column'}}>
          <div className="qe-mono" style={{fontSize:'0.62rem', display:'flex', gap:14, flexWrap:'wrap', padding:'2px 4px', alignItems:'baseline'}}>
            <span><span style={{color:'var(--qe-muted)'}}>O</span> <span style={{color:'var(--qe-text)'}}>${last[1].toFixed(2)}</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>H</span> <span style={{color:'var(--qe-green)'}}>${last[4].toFixed(2)}</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>L</span> <span style={{color:'var(--qe-red)'}}>${last[3].toFixed(2)}</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>C</span> <span style={{color:'var(--qe-text)'}}>${last[2].toFixed(2)}</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>Chg</span> <span style={{color:'var(--qe-green)'}}>+$0.10 (+0.12%)</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>Bar Range</span> <span>${(last[4]-last[3]).toFixed(2)}</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>Cash Flow</span> <span style={{color:'var(--qe-blue)'}}>+$0.00</span></span>
            <span><span style={{color:'var(--qe-muted)'}}>Adj Chg</span> <span style={{color:'var(--qe-green)'}}>+$0.10 (+0.12%)</span></span>
          </div>
          <div style={{flex:1, minHeight:0}}>
            {ddMode
              ? <EquityChart data={ddSeries} color="var(--qe-red)" baseline={0}/>
              : <CandlestickChart data={MOCK.ohlc} logScale={logScale}/>}
          </div>
        </div>
      </Pane>
    </div>
  );
};

const TabCalendar = ({offset, onNav}) => {
  // Deterministic per-month mock (seeded by month) — Prev/Next walks real
  // months; days after the mock "now" (2026-04-25) are future ⇒ no data.
  const anchor = 3 + offset;                       // months since 2026-01 · April = 3
  const y = 2026 + Math.floor(anchor / 12);
  const m = ((anchor % 12) + 12) % 12;
  const monthLbl = new Date(Date.UTC(y, m, 1)).toLocaleDateString('en-US', {month:'long', year:'numeric', timeZone:'UTC'});
  const monthAbbr = new Date(Date.UTC(y, m, 1)).toLocaleDateString('en-US', {month:'short', timeZone:'UTC'});
  const nDays = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const NOW_MS = Date.UTC(2026, 3, 25);            // mock today
  const days = React.useMemo(() => {
    let s = ((y * 12 + m) * 7919 + 17) % 233280;   // month-stable seed
    const rnd = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };
    return Array.from({length: nDays}, (_, i) => {
      if (Date.UTC(y, m, i + 1) > NOW_MS) return {day: i + 1, pnl: null, wr: 0, trades: 0}; // future
      const trades = rnd() < 0.24 ? 0 : 1 + Math.floor(rnd() * 4);
      const pnl = trades === 0 ? null : +(((rnd() - 0.48)) * 3.2).toFixed(2);
      return {day: i + 1, pnl, wr: rnd(), trades};
    });
  }, [y, m, nDays]);
  const traded = days.filter(d => d.pnl != null);
  const max = Math.max(...traded.map(d => Math.abs(d.pnl)), 0.01);
  // pad to whole weeks, starting Mon (real weekday of the 1st)
  const firstDow = (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7;
  const cells = Array.from({length: firstDow}, () => null).concat(days.map(d => d));
  while (cells.length % 7 !== 0) cells.push(null);
  const best  = traded.length ? Math.max(...traded.map(d => d.pnl)) : 0;
  const worst = traded.length ? Math.min(...traded.map(d => d.pnl)) : 0;
  const total = traded.reduce((s, d) => s + d.pnl, 0);
  return (
    <div style={{padding:4, height:'100%'}}>
      <Pane title="Calendar PnL"
        right={
          <>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={()=>onNav(-1)}>‹ Prev</button>
            <span className="qe-mono" style={{fontSize:'0.74rem', fontWeight:700, padding:'0 6px'}}>{monthLbl}</span>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={offset >= 0} style={offset >= 0 ? {opacity:0.4} : undefined}
              title={offset >= 0 ? 'Already at the current month' : ''} onClick={()=>onNav(+1)}>Next ›</button>
          </>
        }
        foot={{tone: total>=0?'ok':'warn', id:3020, msg: traded.length ? `${traded.length} trading days · best $${best.toFixed(2)} · worst $${worst.toFixed(2)} · Σ $${total.toFixed(2)}` : `no trading days in ${monthLbl}`, ms:4}}
        style={{height:'100%'}}>
        <div style={{display:'flex', flexDirection:'column', gap:6, height:'100%'}}>
          <div style={{display:'grid', gridTemplateColumns:'repeat(7,1fr)', gap:2}}>
            {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d=>(
              <div key={d} style={{textAlign:'center', fontSize:'0.54rem', color:'var(--qe-muted)', textTransform:'uppercase', padding:'2px 0', letterSpacing:'0.1em'}}>{d}</div>
            ))}
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(7,1fr)', gap:2, flex:1, minHeight:0}}>
            {cells.map((c, i) => {
              if (!c) return <div key={i}/>;
              if (c.pnl == null) return (
                <div key={i} title={`${monthAbbr} ${c.day}: no trades`} style={{
                  background:'var(--qe-panel)', border:'1px solid color-mix(in srgb, var(--qe-text) 4%, transparent)',
                  padding:'4px 6px', minHeight:46, opacity:0.45,
                }}>
                  <span style={{fontSize:'0.6rem', fontFamily:'var(--qe-mono)', color:'var(--qe-muted)'}}>{c.day}</span>
                </div>
              );
              const intensity = Math.min(Math.abs(c.pnl)/max, 1);
              const bg = c.pnl > 0
                ? `rgba(0,255,127,${0.12 + intensity*0.6})`
                : c.pnl < 0
                ? `rgba(255,45,74,${0.12 + intensity*0.6})`
                : 'var(--qe-panel)';
              const tc = c.pnl >= 0 ? 'var(--qe-green)' : 'var(--qe-red)';
              return (
                <div key={i} style={{
                  background: bg, border:'1px solid color-mix(in srgb, var(--qe-text) 4%, transparent)',
                  padding:'4px 6px', display:'flex', flexDirection:'column', minHeight:46,
                }} title={`${monthAbbr} ${c.day}: $${c.pnl.toFixed(2)} · ${c.trades}T · ${(c.wr*100).toFixed(0)}% WR`}>
                  <div style={{display:'flex', justifyContent:'space-between', fontSize:'0.6rem', fontFamily:'var(--qe-mono)'}}>
                    <span style={{color:tc, fontWeight:600}}>{c.day}</span>
                    {c.trades > 0 && <span style={{color:tc, opacity:0.7}}>{(c.wr*100).toFixed(0)}%</span>}
                  </div>
                  <div style={{fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:700, color:tc, marginTop:3}}>
                    {c.pnl>=0?'+':''}${Math.abs(c.pnl).toFixed(2)}
                  </div>
                  <div className="qe-grow"/>
                  {c.trades > 0 && (
                    <div style={{display:'flex', justifyContent:'space-between', fontSize:'0.52rem', color:tc, opacity:0.75, fontFamily:'var(--qe-mono)'}}>
                      <span>{c.trades}T</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:10, padding:'6px 4px', borderTop:'1px solid var(--qe-line)'}}>
            <KvCell label="Trading Days" value={traded.length}/>
            <KvCell label="Avg Daily PnL" value={`$${(traded.length ? total/traded.length : 0).toFixed(2)}`} color={pnlColor(total)}/>
            <KvCell label="Best Day" value={`$${best.toFixed(2)}`} color="var(--qe-green)"/>
            <KvCell label="Worst Day" value={`$${worst.toFixed(2)}`} color="var(--qe-red)"/>
          </div>
        </div>
      </Pane>
    </div>
  );
};

const TabPairs = ({periodLbl}) => {
  const rows = MOCK_ANALYTICS.pairs;
  const totals = {
    trades: rows.reduce((s,r)=>s+r.total, 0),
    pnl:    rows.reduce((s,r)=>s+r.pnlT, 0),
    fees:   rows.reduce((s,r)=>s+r.fees, 0),
    vol:    rows.reduce((s,r)=>s+r.vol, 0),
  };
  return (
    <div style={{padding:4, height:'100%'}}>
      <Pane title="Traded Pairs" count={`${rows.length} symbols`} tag={periodLbl}
        foot={{tone: totals.pnl>=0?'ok':'warn', id:3030, msg:`${totals.trades} trades · Σ $${totals.pnl.toFixed(2)} · fees $${totals.fees.toFixed(2)} · vol $${totals.vol.toLocaleString()}`, ms:7}}
        style={{height:'100%'}}
        bodyStyle={{padding:0}}>
        <DataList
          selKey="sym"
          dense={false}
          columns={[
            {key:'sym',    label:'SYMBOL',   render:r=><span style={{color:'var(--qe-cyan)',fontWeight:700}}>{r.sym}</span>},
            {key:'total',  label:'TRADES',   align:'right'},
            {key:'longs',  label:'LONGS',    align:'right', cell:'up'},
            {key:'shorts', label:'SHORTS',   align:'right', cell:'dn'},
            {key:'pnlL',   label:'PnL (L)',  align:'right', render:r=><span style={{color:r.pnlL>=0?'var(--qe-green)':'var(--qe-red)'}}>{r.pnlL===0?'—':(r.pnlL>=0?'+':'')+r.pnlL.toFixed(2)}</span>},
            {key:'pnlS',   label:'PnL (S)',  align:'right', render:r=><span style={{color:r.pnlS>=0?'var(--qe-green)':'var(--qe-red)'}}>{r.pnlS===0?'—':(r.pnlS>=0?'+':'')+r.pnlS.toFixed(2)}</span>},
            {key:'pnlT',   label:'PnL TOTAL',align:'right', render:r=><span style={{color:r.pnlT>=0?'var(--qe-green)':'var(--qe-red)',fontWeight:700}}>{r.pnlT>=0?'+':''}{r.pnlT.toFixed(2)}</span>},
            {key:'wr',     label:'WIN RATE', align:'right', render:r=><span style={{color:r.wr>=50?'var(--qe-green)':'var(--qe-red)'}}>{r.wr.toFixed(1)}%</span>},
            {key:'avgW',   label:'AVG WIN',  align:'right', render:r=><span style={{color:'var(--qe-green)'}}>{r.avgW==null?'—':r.avgW.toFixed(2)}</span>},
            {key:'avgL',   label:'AVG LOSS', align:'right', cell:'dn', render:r=>r.avgL==null?'—':r.avgL.toFixed(2)},
            {key:'fees',   label:'FEES',     align:'right', cell:'dim', render:r=>r.fees.toFixed(2)},
            {key:'vol',    label:'VOLUME',   align:'right', cell:'dim', render:r=>r.vol.toLocaleString()},
          ]}
          rows={rows}
          summary={<>
            <span><span style={{color:'var(--qe-muted)'}}>TOTAL</span> <span style={{color:'var(--qe-text)', fontWeight:700}}>{totals.trades} trades</span></span>
            <span style={{color: totals.pnl>=0?'var(--qe-green)':'var(--qe-red)', fontWeight:700}}>Σ PnL {totals.pnl>=0?'+':''}{totals.pnl.toFixed(2)}</span>
          </>}
        />
      </Pane>
    </div>
  );
};

const TabExcursions = ({periodLbl}) => {
  const [dir, setDir] = React.useState('all');
  const e = MOCK_ANALYTICS.excursions;
  // direction filter applies to scatter, summary and per-trade table alike
  const pts = dir === 'all' ? e.points : e.points.filter(p => p.dir === dir);
  const trs = dir === 'all' ? e.trades : e.trades.filter(t => t.dir === dir);
  const avgMfe = pts.length ? pts.reduce((s, p) => s + p.x, 0) / pts.length : 0;
  const avgMae = pts.length ? pts.reduce((s, p) => s + Math.abs(p.y), 0) / pts.length : 0;
  const avgMer = avgMae ? avgMfe / avgMae : 0;
  const pctFav = pts.length ? Math.round(pts.filter(p => p.x > 2 * Math.abs(p.y)).length / pts.length * 100) : 0;
  return (
    <GridWorkspace>
      {/* Scatter */}
      <GridItem x={0} y={0} w={16} h={16} minW={8} minH={6}>
      <Pane title="MFE / MAE Scatter" tag={periodLbl}
        right={<PeriodSelector options={[['all','All'],['LONG','Long'],['SHORT','Short']]} value={dir} onChange={setDir}/>}
        foot={{tone:'info', id:3040, msg:`${pts.length} reconciled trades · scatter on USDT axes`, ms:18}}
        style={{height:'100%'}}
        bodyStyle={{padding:6}}>
        <ScatterChart points={pts} xName="MFE ($)" yName="MAE ($)"/>
      </Pane>
      </GridItem>

      {/* Summary */}
      <GridItem x={16} y={0} w={8} h={5} minW={5} minH={4}>
      <Pane title="Excursion Summary" style={{height:'100%'}}
        foot={{tone:'ok', id:3041, msg:`favorable (mfe > 2× mae) on ${pctFav}% of trades`, ms:2}}>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px 14px'}}>
          <KvCell label="Avg MFE"        value={`$${avgMfe.toFixed(2)}`}    color="var(--qe-green)"/>
          <KvCell label="Avg |MAE|"      value={`$${avgMae.toFixed(2)}`} color="var(--qe-red)"/>
          <KvCell label="Avg ME-Ratio"   value={avgMer.toFixed(2)}/>
          <KvCell label="MFE > 2× MAE"   value={`${pctFav}%`} color="var(--qe-green)"/>
        </div>
      </Pane>
      </GridItem>

      {/* Per-trade table */}
      <GridItem x={16} y={5} w={8} h={11} minW={5} minH={5}>
      <Pane title="Per-Trade Excursions" count={trs.length} style={{height:'100%'}}
        foot={{tone:'sub', id:3042, msg:'reconciled from agg_trades · hold-time included', ms:9}}
        bodyStyle={{padding:0}}>
        <DataList
          selKey="id"
          columns={[
            {key:'sym',  label:'SYMBOL', render:r=><span style={{color:'var(--qe-cyan)',fontWeight:700}}>{r.sym}</span>},
            {key:'dir',  label:'DIR',    render:r=><Badge tone={r.dir==='LONG'?'ok':'err'}>{r.dir}</Badge>},
            {key:'mfe',  label:'MFE',    align:'right', cell:'up'},
            {key:'mae',  label:'MAE',    align:'right', cell:'dn'},
            {key:'mer',  label:'ME-R',   align:'right'},
            {key:'pnl',  label:'PnL',    align:'right', render:r=><span style={{color:r.pnl>=0?'var(--qe-green)':'var(--qe-red)',fontWeight:700}}>{r.pnl>=0?'+':''}{r.pnl.toFixed(2)}</span>},
            {key:'hold', label:'HOLD',   align:'right', cell:'dim'},
          ]}
          rows={trs}
        />
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

const TabRMultiples = ({periodLbl}) => {
  const r = MOCK_ANALYTICS.rmult;
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={16} h={12} minW={8} minH={6}>
      <Pane title="R-Multiple Distribution" tag={periodLbl}
        foot={{tone: r.stats.expectancy>=0?'ok':'warn', id:3050, msg:`${r.stats.count} trades · expectancy ${r.stats.expectancy.toFixed(3)}R · pf ${r.stats.pf.toFixed(2)}`, ms:6}}
        style={{height:'100%'}}>
        <BarChart
          data={r.bins.map(b => b.pos ? b.c : -b.c)}
          categories={r.bins.map(b => b.label)}
        />
      </Pane>
      </GridItem>
      <GridItem x={16} y={0} w={8} h={12} minW={5} minH={6}>
      <Pane title="R-Multiple Stats"
        foot={{tone:'sub', id:3051, msg:'positional R from pre-trade SL plan', ms:1}}
        style={{height:'100%'}}>
        <div style={{display:'flex', flexDirection:'column', gap:8}}>
          <KvCell label="Total Trades"  value={r.stats.count}/>
          <KvCell label="Win Rate"      value={`${(r.stats.winRate*100).toFixed(1)}%`} color={r.stats.winRate>=0.5?'var(--qe-green)':'var(--qe-red)'}/>
          <KvCell label="Expectancy"    value={`${r.stats.expectancy.toFixed(3)}R`} color={pnlColor(r.stats.expectancy)}/>
          <KvCell label="Profit Factor" value={r.stats.pf.toFixed(2)} color={r.stats.pf>=1.5?'var(--qe-green)':r.stats.pf>=1?'var(--qe-amber)':'var(--qe-red)'}/>
          <KvCell label="Avg Win R"     value={`${r.stats.avgWinR.toFixed(2)}R`}  color="var(--qe-green)"/>
          <KvCell label="Avg Loss R"    value={`${r.stats.avgLossR.toFixed(2)}R`} color="var(--qe-red)"/>
          <KvCell label="Best R"        value={`${r.stats.best.toFixed(2)}R`}  color="var(--qe-green)"/>
          <KvCell label="Worst R"       value={`${r.stats.worst.toFixed(2)}R`} color="var(--qe-red)"/>
          <KvCell label="Median R"      value={`${r.stats.median.toFixed(2)}R`}/>
          <KvCell label="Mean R"        value={`${r.stats.mean.toFixed(3)}R`}/>
        </div>
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

const TabRisk = ({periodLbl}) => {
  const v = MOCK_ANALYTICS.var;
  const VarCard = ({label, val, desc}) => {
    const pct = val * 100;
    const usdt = val * v.curEquity;
    return (
      <div style={{display:'flex', flexDirection:'column', gap:4, padding:10, background:'var(--qe-panel)', border:'1px solid var(--qe-line)'}} title={desc}>
        <Lbl>{label}</Lbl>
        <span className="qe-mono" style={{fontSize:'1rem', fontWeight:700, color:'var(--qe-red)'}}>{Math.abs(pct).toFixed(2)}%</span>
        <span style={{fontSize:'0.62rem', color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>${Math.abs(usdt).toFixed(0)}</span>
      </div>
    );
  };
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={24} h={5} minW={10} minH={5}>
      <Pane title="Value at Risk · Risk Metrics" tag={periodLbl} style={{height:'100%'}}
        foot={{tone:'warn', id:3060, msg:'95% VaR -3.80% · CVaR -5.20% · n=20+ days', ms:11}}>
        <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:8}}>
          <VarCard label="Historical VaR (95%)"  val={v.var95}  desc="Worst daily loss exceeded 5% of the time"/>
          <VarCard label="Historical VaR (99%)"  val={v.var99}  desc="Worst daily loss exceeded 1% of the time"/>
          <VarCard label="CVaR / ES (95%)"        val={v.cvar95} desc="Expected Shortfall — average loss on worst 5% of days"/>
          <VarCard label="Parametric VaR (95%)"  val={v.pvar95} desc="Gaussian VaR (μ − 1.645σ)"/>
        </div>
      </Pane>
      </GridItem>
      <GridItem x={0} y={5} w={24} h={12} minW={10} minH={6}>
      <Pane title="Daily Return Distribution"
        foot={{tone:'info', id:3061, msg:'red = below 95% VaR threshold · n=20 days', ms:4}}
        style={{height:'100%'}}>
        <BarChart
          data={v.bins.map(b => b.x <= -3.8 ? -b.y : b.y)}
          categories={v.bins.map(b => `${b.x.toFixed(1)}%`)}
        />
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

const TabFunding = () => {
  const rows = MOCK_ANALYTICS.funding;
  const tot8h  = rows.reduce((s,r)=>s+r.per8h, 0);
  const totDay = rows.reduce((s,r)=>s+r.perDay, 0);
  return (
    <div style={{padding:4, height:'100%'}}>
      <Pane title="Funding Rate Exposure · Live"
        right={<StatusDot tone="info" label="30s refresh"/>}
        foot={{tone: tot8h>=0?'ok':'warn', id:3070, msg:`Σ per 8h ${tot8h>=0?'+':''}$${tot8h.toFixed(4)} · per day $${totDay.toFixed(3)} · next settle 00:00 UTC`, ms:42}}
        style={{height:'100%'}}
        bodyStyle={{padding:0}}>
        <DataList
          selKey="sym"
          dense={false}
          columns={[
            {key:'sym',    label:'SYMBOL',   render:r=><span style={{color:'var(--qe-cyan)',fontWeight:700}}>{r.sym}</span>},
            {key:'dir',    label:'DIR',      render:r=><Badge tone={r.dir==='LONG'?'ok':'err'}>{r.dir}</Badge>},
            {key:'notional',label:'NOTIONAL',align:'right', cell:'dim', render:r=>`$${r.notional.toLocaleString()}`},
            {key:'rate',   label:'FUNDING RATE', align:'right', render:r=><span style={{color: r.adverse?'var(--qe-red)':'var(--qe-green)'}}>{(r.rate*100).toFixed(4)}%</span>},
            {key:'per8h',  label:'PER 8h',  align:'right', render:r=><span style={{color: r.per8h>=0?'var(--qe-green)':'var(--qe-red)'}}>${r.per8h.toFixed(4)}</span>},
            {key:'perDay', label:'PER DAY', align:'right', render:r=><span style={{color: r.perDay>=0?'var(--qe-green)':'var(--qe-red)'}}>${r.perDay.toFixed(3)}</span>},
            {key:'perWeek',label:'PER WEEK', align:'right', cell:'dim', render:r=>`$${r.perWeek.toFixed(2)}`},
            {key:'next',   label:'NEXT FUNDING', cell:'dim'},
            {key:'impact', label:'IMPACT',  render:r=>r.adverse?<Badge tone="err">PAY</Badge>:<Badge tone="ok">EARN</Badge>},
          ]}
          rows={rows}
          summary={<>
            <span style={{color:'var(--qe-muted)'}}>Σ TOTAL EXPOSURE</span>
            <span style={{color:tot8h>=0?'var(--qe-green)':'var(--qe-red)', fontWeight:700}}>per 8h {tot8h>=0?'+':''}${tot8h.toFixed(4)} · per day ${totDay>=0?'+':''}${totDay.toFixed(3)}</span>
          </>}
        />
        <div style={{padding:'4px 8px', borderTop:'1px solid var(--qe-line)', fontSize:'0.56rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>
          Binance settles funding every 8h (00:00 · 08:00 · 16:00 UTC). LONG pays when rate &gt; 0; SHORT pays when rate &lt; 0.
        </div>
      </Pane>
    </div>
  );
};

const TabBeta = () => {
  const b = MOCK_ANALYTICS.beta;
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={14} h={13} minW={8} minH={6}>
      <Pane title="Beta-Weighted Exposure vs BTC" count={b.rows.length}
        right={<span style={{fontSize:'0.54rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>beta from 30d OHLCV · fallback to sector presets</span>}
        foot={{tone:'info', id:3080, msg:`portfolio β ${b.portBeta.toFixed(2)} · Σ beta-adj $${b.totalBetaExp.toFixed(0)} · Σ notional $${b.totalNotional.toLocaleString()}`, ms:22}}
        style={{height:'100%'}}
        bodyStyle={{padding:0}}>
        <DataList
          selKey="sym"
          dense={false}
          columns={[
            {key:'sym',     label:'SYMBOL',     render:r=><span style={{color:'var(--qe-cyan)',fontWeight:700}}>{r.sym}</span>},
            {key:'dir',     label:'DIR',        render:r=><Badge tone={r.dir==='LONG'?'ok':'err'}>{r.dir}</Badge>},
            {key:'sector',  label:'SECTOR',     cell:'dim'},
            {key:'notional',label:'NOTIONAL',   align:'right', render:r=>`$${r.notional.toLocaleString()}`},
            {key:'beta',    label:'β vs BTC',   align:'right', render:r=><span style={{color: r.beta>1.5?'var(--qe-amber)':r.beta<=1?'var(--qe-green)':'var(--qe-text)'}}>{r.beta.toFixed(2)}</span>},
            {key:'betaAdj', label:'β-ADJ. EXP.',align:'right', render:r=><span style={{fontWeight:700, color:r.betaAdj>=0?'var(--qe-green)':'var(--qe-red)'}}>${r.betaAdj.toLocaleString()}</span>},
          ]}
          rows={b.rows}
          summary={<>
            <span><span style={{color:'var(--qe-muted)'}}>PORTFOLIO TOTAL</span> <span style={{color:'var(--qe-text)', fontWeight:700}}>${b.totalNotional.toLocaleString()}</span></span>
            <span style={{fontWeight:700}}>β = <span style={{color: Math.abs(b.portBeta)>1.5?'var(--qe-amber)':'var(--qe-text)'}}>{b.portBeta.toFixed(2)}</span> · β-adj. ${b.totalBetaExp.toLocaleString()}</span>
          </>}
        />
      </Pane>
      </GridItem>
      <GridItem x={14} y={0} w={10} h={7} minW={6} minH={4}>
      <Pane title="Sector β-Adjusted Breakdown" style={{height:'100%'}}
        foot={{tone:'sub', id:3081, msg:'Σ across sectors · % of total beta-adj exposure', ms:2}}>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:6}}>
          {Object.entries(b.sectorTotals).map(([sec, exp]) => {
            const pct = b.totalBetaExp !== 0 ? Math.abs(exp/b.totalBetaExp*100) : 0;
            return (
              <div key={sec} style={{padding:6, background:'var(--qe-panel)', border:'1px solid var(--qe-line)'}}>
                <Lbl>{sec}</Lbl>
                <div className="qe-mono" style={{fontSize:'0.86rem', fontWeight:700, color: exp>=0?'var(--qe-green)':'var(--qe-red)'}}>${exp.toLocaleString()}</div>
                <div style={{fontSize:'0.54rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>{pct.toFixed(1)}%</div>
              </div>
            );
          })}
        </div>
      </Pane>
      </GridItem>
      <GridItem x={14} y={7} w={10} h={6} minW={6} minH={4}>
      <Pane title="Sector Preset Betas · Fallback" style={{height:'100%'}}
        foot={{tone:'sub', id:3082, msg:'used when 30d OHLCV insufficient for empirical beta', ms:0}}>
        <div style={{display:'flex', flexDirection:'column', gap:4, fontSize:'0.62rem', fontFamily:'var(--qe-mono)'}}>
          {[['BTC/ETH','1.0'],['Top-20 Alts','1.5'],['Commodities','0.4'],['Other Alts','2.0']].map(([s,v]) => (
            <div key={s} style={{display:'flex', justifyContent:'space-between', padding:'3px 0', borderBottom:'1px dotted var(--qe-faint)'}}>
              <span style={{color:'var(--qe-sub)'}}>{s}</span>
              <span style={{color:'var(--qe-text)', fontWeight:700}}>{v}</span>
            </div>
          ))}
        </div>
      </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

const AnalyticsPage = () => {
  const [tab,    setTab]    = React.useState('overview');
  const [period, setPeriod] = React.useState('monthly');
  const [offset, setOffset] = React.useState(0);
  const periodEnabled = PERIOD_TABS.has(tab);

  // labels per period for "tag" decoration
  const lbl = period === 'monthly' ? 'APRIL 2026'
            : period === 'weekly'  ? 'WEEK 17'
            : period === 'quarterly' ? 'Q2 2026'
            : period === 'yearly' ? '2026'
            : period === 'rolling_30d' ? 'ROLLING 30D'
            : period === 'rolling_90d' ? 'ROLLING 90D'
            : 'ALL TIME';

  const tabContent = {
    overview:   <TabOverview   periodLbl={lbl}/>,
    equity:     <TabEquity/>,
    dist:       <TabDistributions periodLbl={lbl}/>,
    calendar:   <TabCalendar   offset={offset} onNav={d=>setOffset(o=>o+d)}/>,
    pairs:      <TabPairs      periodLbl={lbl}/>,
    excursions: <TabExcursions periodLbl={lbl}/>,
    rmultiples: <TabRMultiples periodLbl={lbl}/>,
    risk:       <TabRisk       periodLbl={lbl}/>,
    execution:  <TabExecution/>,
    funding:    <TabFunding/>,
    beta:       <TabBeta/>,
  };

  return (
    <div className="qe-scope" data-screen-label="05 Analytics" style={{
      width:'100%', height:'100%', background:'var(--qe-bg)',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      <TopNavStd page="Analytics" variant="line" dense/>

      {/* Page header — period nav lives here, dims when tab ignores period */}
      <PageHeader title="Analytics" subtitle="portfolio performance · equity curve · pairs · MFE/MAE · funding · beta">
        <PeriodNav period={period} offset={offset} onPeriod={p=>{setPeriod(p);setOffset(0);}} onNav={d=>setOffset(o=>o+d)} disabled={!periodEnabled}/>
      </PageHeader>

      {/* Tabs */}
      <TabStrip value={tab} onChange={setTab} tabs={ANALYTICS_TABS.map(([id,l]) => [id, l])}/>

      {/* Tab content fills remaining */}
      <div style={{flex:1, minHeight:0, overflow:'auto', display:'flex', flexDirection:'column'}}>
        {tabContent[tab]}
      </div>
      <StatusFooter/>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────
// REGIME PAGE — lives in pages-regime.jsx
// ─────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────
// CONFIG PAGE
// ─────────────────────────────────────────────────────────────────────────
const ConfigPage = () => {
  const [tab, setTab] = React.useState('accounts');
  const [acct, setAcct] = React.useState(1);
  const accounts = [
    {id:1, name:'Account 1 (Binance Futures)', exch:'Binance', mkt:'USD-M Futures', env:'live', active:true},
    {id:2, name:'Bybit Linear (Testnet)',       exch:'Bybit',   mkt:'Linear',        env:'testnet', active:false},
  ];
  const conns = [
    {id:'fred',     name:'FRED', cat:'Macro Data',  conn:true,  key:'••••••a1b2c3'},
    {id:'finnhub',  name:'Finnhub', cat:'Market Data', conn:true,  key:'••••••d4e5f6'},
    {id:'binance',  name:'Binance Market', cat:'Exchange', conn:true,  key:'via account key'},
    {id:'bwe',      name:'BWE News',  cat:'News Feed', conn:false, key:''},
    {id:'cg',       name:'CoinGecko', cat:'On-chain',  conn:false, key:''},
  ];
  return (
    <div className="qe-scope" data-screen-label="08 Config" style={{
      width:'100%', height:'100%', background:'var(--qe-bg)',
      display:'flex', flexDirection:'column', overflow:'hidden',
    }}>
      <TopNavStd page="Config" variant="line" dense/>
      <PageHeader title="Configuration" subtitle="accounts · connections · risk parameters · presets"/>

      <TabStrip value={tab} onChange={setTab} tabs={[
        ['accounts','Accounts'], ['connections','Connections'], ['presets','Presets'], ['system','System'],
      ]}/>

      <div style={{flex:1, minHeight:0, display:'flex', flexDirection:'column', overflow:'auto'}}>
        {tab==='accounts' && (
          <GridWorkspace>
            <GridItem x={0} y={0} w={6} h={20} minW={4} minH={6}>
            <Pane title="Accounts" style={{height:'100%'}}>
            <div style={{display:'flex', flexDirection:'column', gap:4}}>
              {accounts.map(a => (
                <Card key={a.id} tight style={{
                  cursor:'pointer',
                  borderColor: acct===a.id ? 'var(--qe-cyan)' : 'var(--qe-line)',
                  background: acct===a.id ? 'var(--qe-active)' : 'var(--qe-card)',
                }} onClick={()=>setAcct(a.id)}>
                  <div style={{display:'flex', gap:6, alignItems:'center'}}>
                    <StatusDot tone={a.active?'ok':'off'} label=""/>
                    <div style={{flex:1, minWidth:0}}>
                      <div style={{fontSize:'0.72rem', fontWeight:700, color:'var(--qe-text)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{a.name}</div>
                      <div style={{fontSize:'0.58rem', color:'var(--qe-sub)', fontFamily:'var(--qe-mono)'}}>{a.exch} · {a.mkt}</div>
                    </div>
                    <Badge tone={a.env==='live'?'err':a.env==='testnet'?'info':'warn'}>{a.env.toUpperCase()}</Badge>
                  </div>
                </Card>
              ))}
              <button className="qe-btn qe-btn-primary qe-btn-sm" style={{marginTop:4, justifyContent:'center'}}>+ Add Account</button>
            </div>
            </Pane>
            </GridItem>

            <GridItem x={6} y={0} w={18} h={20} minW={8} minH={6}>
            <Pane title="Account Settings" style={{height:'100%'}} bodyStyle={{overflow:'auto'}}>
              <div style={{display:'flex', alignItems:'center', gap:10, marginBottom:10}}>
                <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.9rem', fontWeight:700}}>{accounts.find(a=>a.id===acct).name}</span>
                <Badge tone="ok">Active</Badge>
                <Badge tone="err">LIVE</Badge>
                <div className="qe-grow"/>
                <button className="qe-btn qe-btn-sm">Test Connection</button>
              </div>

              <SecLbl rule>Credentials</SecLbl>
              <div style={{display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:8, marginBottom:10}}>
                <div><Lbl>Exchange</Lbl><select className="qe-input qe-select" defaultValue="binance"><option value="binance">Binance</option><option value="bybit">Bybit</option><option value="mexc">MEXC (read-only)</option></select></div>
                <div><Lbl>Market Type</Lbl><select className="qe-input qe-select"><option>USD-M Futures</option><option>Spot</option></select></div>
                <div><Lbl>Environment</Lbl><select className="qe-input qe-select"><option>Live</option><option>Paper</option><option>Testnet</option></select></div>
                <div><Lbl>API Key</Lbl><input className="qe-input" type="password" placeholder="Leave blank to keep current"/></div>
                <div><Lbl>API Secret</Lbl><input className="qe-input" type="password" placeholder="Leave blank to keep current"/></div>
                <div><Lbl>Broker Account ID</Lbl><input className="qe-input" defaultValue="binancefutures_1234"/></div>
              </div>

              <SecLbl rule>Risk Parameters</SecLbl>
              <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:8, marginBottom:10}}>
                <div><Lbl>Risk / Trade</Lbl><input className="qe-input" defaultValue="0.01"/></div>
                <div><Lbl>Max Weekly Loss</Lbl><input className="qe-input" defaultValue="0.05"/></div>
                <div><Lbl>Max Drawdown</Lbl><input className="qe-input" defaultValue="0.10"/></div>
                <div><Lbl>DD Window (days)</Lbl><input className="qe-input" defaultValue="30"/></div>
                <div><Lbl>Max Exposure ×</Lbl><input className="qe-input" defaultValue="5.0"/></div>
                <div><Lbl>Max Positions</Lbl><input className="qe-input" defaultValue="10"/></div>
                <div><Lbl>Max Corr. Exposure</Lbl><input className="qe-input" defaultValue="0.50"/></div>
                <div><Lbl>Strategy Preset</Lbl><select className="qe-input qe-select"><option>Swing</option><option>Scalping</option><option>Day Trading</option><option>Position</option><option>Custom</option></select></div>
              </div>

              <SecLbl rule>Enforcement &amp; Recovery</SecLbl>
              <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:8, marginBottom:10}}>
                <div><Lbl>DD Enforcement Mode</Lbl><select className="qe-input qe-select"><option>Advisory (shadow)</option><option>Enforced</option></select></div>
                <div><Lbl>DD Recovery</Lbl><input className="qe-input" defaultValue="0.50"/></div>
                <div><Lbl>DD Warning Threshold</Lbl><input className="qe-input" defaultValue="0.80"/></div>
                <div><Lbl>Hard-stop Threshold</Lbl><input className="qe-input" defaultValue="0.95"/></div>
              </div>

              <div style={{display:'flex', gap:6, marginTop:8}}>
                <button className="qe-btn qe-btn-primary">Save</button>
                <button className="qe-btn">Activate</button>
                <div className="qe-grow"/>
                <button className="qe-btn qe-btn-danger">Delete Account</button>
              </div>
            </Pane>
            </GridItem>
          </GridWorkspace>
        )}

        {tab==='connections' && (
          <GridWorkspace>
            <GridItem x={0} y={0} w={24} h={20} minW={10} minH={6}>
            <Pane title="Data & Exchange Connections" style={{height:'100%'}} bodyStyle={{padding:0}}>
            <DataList
              dense={false}
              selKey="id"
              columns={[
                {key:'name', label:'PROVIDER', cell:'sym'},
                {key:'cat',  label:'CATEGORY', cell:'dim'},
                {key:'status', label:'STATUS', render:c=>c.conn ? <StatusDot tone="ok" label="CONNECTED"/> : <StatusDot tone="off" label="NOT SET"/>},
                {key:'key',  label:'KEY', cell:'dim', render:c=>c.conn ? c.key : <input className="qe-input" placeholder="API Key" style={{width:200, height:22, fontSize:'0.62rem'}}/>},
                {key:'act',  label:'', align:'right', render:c=>c.conn
                  ? <span style={{display:'inline-flex', gap:4}}>
                      <button className="qe-btn qe-btn-sm">Test</button>
                      <button className="qe-btn qe-btn-sm qe-btn-ghost">Edit</button>
                      <button className="qe-btn qe-btn-sm qe-btn-danger">Remove</button>
                    </span>
                  : <button className="qe-btn qe-btn-sm qe-btn-primary">Save &amp; Test</button>},
              ]}
              rows={conns}
            />
            </Pane>
            </GridItem>
          </GridWorkspace>
        )}

        {tab==='presets' && (
          <GridWorkspace>
            <GridItem x={0} y={0} w={24} h={14} minW={10} minH={6}>
            <Pane title="Risk Presets" style={{height:'100%'}}>
            <div style={{display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:6}}>
            {[
              {name:'SCALPING', window:14, warn:'4%',  limit:'8%',  rec:'50%', period:'weekly'},
              {name:'DAY',      window:21, warn:'5%',  limit:'10%', rec:'50%', period:'weekly'},
              {name:'SWING',    window:45, warn:'6%',  limit:'12%', rec:'40%', period:'monthly'},
              {name:'POSITION', window:90, warn:'8%',  limit:'15%', rec:'30%', period:'quarterly'},
            ].map(p => (
              <Card key={p.name} ticks>
                <div style={{display:'flex', alignItems:'baseline', gap:6, marginBottom:4}}>
                  <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.78rem', fontWeight:700, color:'var(--qe-cyan)', letterSpacing:'0.08em'}}>{p.name}</span>
                  {p.name==='SWING' && <Badge tone="info">CURRENT</Badge>}
                </div>
                <div style={{display:'flex', flexDirection:'column', gap:4, fontSize:'0.66rem', fontFamily:'var(--qe-mono)'}}>
                  <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'var(--qe-muted)'}}>DD window</span><span style={{fontWeight:700}}>{p.window}d</span></div>
                  <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'var(--qe-muted)'}}>warn</span><span style={{fontWeight:700, color:'var(--qe-amber)'}}>{p.warn}</span></div>
                  <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'var(--qe-muted)'}}>limit</span><span style={{fontWeight:700, color:'var(--qe-red)'}}>{p.limit}</span></div>
                  <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'var(--qe-muted)'}}>recovery</span><span style={{fontWeight:700, color:'var(--qe-green)'}}>{p.rec}</span></div>
                  <div style={{display:'flex', justifyContent:'space-between'}}><span style={{color:'var(--qe-muted)'}}>period</span><span style={{fontWeight:700}}>{p.period}</span></div>
                </div>
                <button className="qe-btn qe-btn-sm" style={{width:'100%', marginTop:8, justifyContent:'center'}}>Apply Preset</button>
              </Card>
            ))}
          </div>
            </Pane>
            </GridItem>
          </GridWorkspace>
        )}

        {tab==='system' && (
          <GridWorkspace>
            <GridItem x={0} y={0} w={24} h={12} minW={10} minH={5}>
            <Pane title="System" style={{height:'100%'}}>
            <SecLbl rule>System</SecLbl>
            <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:8}}>
              <div><Lbl>Engine Version</Lbl><div className="qe-mono">v3.0.0</div></div>
              <div><Lbl>Event Bus</Lbl><div className="qe-mono qe-info">InProcess (Redis available)</div></div>
              <div><Lbl>Pub/Sub Backend</Lbl><select className="qe-input qe-select"><option>InProcess (default)</option><option>Redis</option></select></div>
              <div><Lbl>Timezone</Lbl><select className="qe-input qe-select"><option>UTC+7 (Asia/Bangkok)</option><option>UTC</option></select></div>
              <div><Lbl>Logging Level</Lbl><select className="qe-input qe-select"><option>INFO</option><option>DEBUG</option><option>WARNING</option></select></div>
              <div><Lbl>Snapshot Cadence</Lbl><input className="qe-input" defaultValue="60s"/></div>
            </div>
            </Pane>
            </GridItem>
          </GridWorkspace>
        )}
      </div>
      <StatusFooter/>
    </div>
  );
};

Object.assign(window, { HistoryPage, CalculatorPage, AnalyticsPage, ConfigPage });
