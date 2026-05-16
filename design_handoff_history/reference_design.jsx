// QE History — synced with templates v2
// Preserves: Position→Fill→ExecLog linkage · adds Exit Reason · PnL% · Trade History (round-trip)
//            Order History · Live Trades · Open Positions panel · Pre-Trade Model col

// ══ EXEC LOG DATA ══════════════════════════════════════════════════════════════
const EXEC_LOG_DATA = [
  {id:'EX-0841', time:'2026-04-04 15:13:51', ticker:'JCTUSDT',    side:'BUY',  entryPrice:0.003201, sizeFilled:3334,  slip:0.031, type:'LIMIT',  makerFee:0.0002, latency:12.4, tp:0.003500, sl:0.002900},
  {id:'EX-0831', time:'2026-04-04 12:44:57', ticker:'BTCUSDT',    side:'BUY',  entryPrice:66868.90, sizeFilled:0.009, slip:0.012, type:'LIMIT',  makerFee:0.0002, latency:8.1,  tp:66950.00, sl:66780.00},
  {id:'EX-0801', time:'2026-04-03 13:09:59', ticker:'STOUSDT',    side:'SELL', entryPrice:0.508300, sizeFilled:257.5, slip:0.018, type:'LIMIT',  makerFee:0.0002, latency:15.2, tp:0.007000, sl:0.540000},
  {id:'EX-0821', time:'2026-04-04 12:42:51', ticker:'AIOTUSDT',   side:'BUY',  entryPrice:0.028700, sizeFilled:1719,  slip:0.041, type:'LIMIT',  makerFee:0.0002, latency:22.7, tp:0.031000, sl:0.026500},
  {id:'EX-0891', time:'2026-04-05 13:10:50', ticker:'PUFFERUSDT', side:'BUY',  entryPrice:0.039800, sizeFilled:32.7,  slip:0.025, type:'MARKET', makerFee:0.0004, latency:5.3,  tp:0.045000, sl:0.036000},
  {id:'EX-0836', time:'2026-04-02 16:36:55', ticker:'STOUSDT',    side:'SELL', entryPrice:0.514200, sizeFilled:36.19, slip:0.021, type:'LIMIT',  makerFee:0.0002, latency:11.8, tp:0.450000, sl:0.580000},
];

// ══ FILLS DATA ═════════════════════════════════════════════════════════════════
const FILLS_DATA = [
  {id:'F-9841', posId:'POS-001', time:'2026-04-04 15:13:53', orderNo:'9841ab', sym:'JCTUSDT',    side:'Open LONG',   price:0.003201, qty:3334,  fee:0.0021, feeAsset:'USDT', role:'Maker', pnl:null,  tp:0.003500, sl:0.002900, orderType:'LIMIT',  execId:'EX-0841'},
  {id:'F-9842', posId:'POS-001', time:'2026-04-04 15:16:03', orderNo:'9842ac', sym:'JCTUSDT',    side:'Close LONG',  price:0.003232, qty:3334,  fee:0.0021, feeAsset:'USDT', role:'Maker', pnl:0.17,  tp:null,     sl:null,    orderType:'LIMIT',  execId:null},
  {id:'F-9831', posId:'POS-002', time:'2026-04-04 12:44:58', orderNo:'9831ba', sym:'BTCUSDT',    side:'Open LONG',   price:66868.90, qty:0.009, fee:0.1203, feeAsset:'USDT', role:'Maker', pnl:null,  tp:66950.00, sl:66780.00, orderType:'LIMIT',  execId:'EX-0831'},
  {id:'F-9832', posId:'POS-002', time:'2026-04-04 12:45:36', orderNo:'9832bb', sym:'BTCUSDT',    side:'Close LONG',  price:66877.80, qty:0.009, fee:0.1202, feeAsset:'USDT', role:'Taker', pnl:0.08,  tp:null,     sl:null,    orderType:'MARKET', execId:null},
  {id:'F-9801', posId:'POS-003', time:'2026-04-03 13:10:00', orderNo:'9801ca', sym:'STOUSDT',    side:'Open SHORT',  price:0.508300, qty:257.5, fee:0.0131, feeAsset:'USDT', role:'Maker', pnl:null,  tp:0.007200, sl:0.540000, orderType:'LIMIT',  execId:'EX-0801'},
  {id:'F-9802', posId:'POS-003', time:'2026-04-03 13:15:05', orderNo:'9802cb', sym:'STOUSDT',    side:'Close SHORT', price:0.007200, qty:257.5, fee:0.0009, feeAsset:'USDT', role:'Taker', pnl:7.41,  tp:null,     sl:null,    orderType:'MARKET', execId:null},
  {id:'F-9821', posId:'POS-004', time:'2026-04-04 12:42:53', orderNo:'9821da', sym:'AIOTUSDT',   side:'Open LONG',   price:0.028700, qty:1719,  fee:0.0197, feeAsset:'USDT', role:'Maker', pnl:null,  tp:0.032500, sl:0.027000, orderType:'LIMIT',  execId:'EX-0821'},
  {id:'F-9822', posId:'POS-004', time:'2026-04-04 12:43:21', orderNo:'9822db', sym:'AIOTUSDT',   side:'Close LONG',  price:0.028800, qty:1719,  fee:0.0197, feeAsset:'USDT', role:'Taker', pnl:0.10,  tp:null,     sl:null,    orderType:'MARKET', execId:null},
  {id:'F-9891', posId:'POS-005', time:'2026-04-05 13:10:53', orderNo:'9891ea', sym:'PUFFERUSDT', side:'Open LONG',   price:0.039800, qty:32.7,  fee:0.0052, feeAsset:'USDT', role:'Taker', pnl:null,  tp:0.045000, sl:0.036000, orderType:'MARKET', execId:'EX-0891'},
  {id:'F-9892', posId:'POS-005', time:'2026-04-05 13:20:22', orderNo:'9892eb', sym:'PUFFERUSDT', side:'Close LONG',  price:0.039300, qty:32.7,  fee:0.0052, feeAsset:'USDT', role:'Taker', pnl:0.02,  tp:null,     sl:null,    orderType:'MARKET', execId:null},
  {id:'F-9836', posId:'POS-006', time:'2026-04-02 16:36:57', orderNo:'9836fa', sym:'STOUSDT',    side:'Open SHORT',  price:0.514200, qty:36.19, fee:0.0046, feeAsset:'USDT', role:'Maker', pnl:null,  tp:0.450000, sl:0.580000, orderType:'LIMIT',  execId:'EX-0836'},
  {id:'F-9837', posId:'POS-006', time:'2026-04-02 16:37:46', orderNo:'9837fb', sym:'STOUSDT',    side:'Close SHORT', price:0.561700, qty:36.19, fee:0.0051, feeAsset:'USDT', role:'Taker', pnl:-1.20, tp:null,     sl:null,    orderType:'MARKET', execId:null},
];

// ══ POSITIONS DATA — updated: exitReason + pnlPct ══════════════════════════
const POSITIONS_DATA = [
  {id:'POS-001', entry:'2026-04-04 15:13', exit:'2026-04-04 15:16', hold:'2m 10s', pair:'JCTUSDT',    dir:'LONG',  sizing:3334,  notional:10.67,  pnl:0.17,  fees:0.004, mfe:0.30,  mae:-0.10, mer:3.0,  tp:0.003500, sl:0.002900, pnlPct:1.59,  exitReason:'tp_hit',       notes:''},
  {id:'POS-002', entry:'2026-04-04 12:43', exit:'2026-04-04 12:45', hold:'1m 38s', pair:'BTCUSDT',    dir:'LONG',  sizing:0.009, notional:601.9,  pnl:0.08,  fees:0.241, mfe:0.08,  mae:0.00,  mer:null, tp:66950.00, sl:66780.00, pnlPct:0.01,  exitReason:'manual',       notes:''},
  {id:'POS-003', entry:'2026-04-03 13:10', exit:'2026-04-03 13:15', hold:'5m 05s', pair:'STOUSDT',    dir:'SHORT', sizing:257.5, notional:130.85, pnl:7.41,  fees:0.014, mfe:7.60,  mae:-3.58, mer:2.12, tp:0.007200, sl:0.540000, pnlPct:5.66,  exitReason:'tp_hit',       notes:'Big move on news'},
  {id:'POS-004', entry:'2026-04-04 12:42', exit:'2026-04-04 12:43', hold:'28s',    pair:'AIOTUSDT',   dir:'LONG',  sizing:1719,  notional:49.34,  pnl:0.10,  fees:0.039, mfe:0.31,  mae:-0.07, mer:4.43, tp:0.032500, sl:0.027000, pnlPct:0.20,  exitReason:'tp_hit',       notes:''},
  {id:'POS-005', entry:'2026-04-05 13:10', exit:'2026-04-05 13:20', hold:'9m 29s', pair:'PUFFERUSDT', dir:'LONG',  sizing:32.7,  notional:1.30,   pnl:0.02,  fees:0.010, mfe:0.04,  mae:-0.02, mer:null, tp:0.045000, sl:0.036000, pnlPct:1.54,  exitReason:'manual',       notes:''},
  {id:'POS-006', entry:'2026-04-02 16:36', exit:'2026-04-02 16:37', hold:'49s',    pair:'STOUSDT',    dir:'SHORT', sizing:36.19, notional:18.60,  pnl:-1.20, fees:0.010, mfe:2.56,  mae:-3.01, mer:0.85, tp:0.450000, sl:0.580000, pnlPct:-6.45, exitReason:'sl_hit',       notes:'Early exit'},
];

// ══ TRADE HISTORY — round-trip format (trade_history_table) ════════════════
const TRADE_HIST_DATA = [
  {id:'TH-001', exitTime:'2026-04-04 15:16', ticker:'JCTUSDT',    dir:'LONG',  entry:0.003201, exit:0.003232, realized:0.17,  realizedR:3.00, funding:0.000, fees:0.0042, slipExit:0.031, holdTime:'2m 10s', notes:''},
  {id:'TH-002', exitTime:'2026-04-04 12:45', ticker:'BTCUSDT',    dir:'LONG',  entry:66868.90, exit:66877.80, realized:0.08,  realizedR:null, funding:0.000, fees:0.2405, slipExit:0.012, holdTime:'1m 38s', notes:''},
  {id:'TH-003', exitTime:'2026-04-03 13:15', ticker:'STOUSDT',    dir:'SHORT', entry:0.508300, exit:0.007200, realized:7.41,  realizedR:2.12, funding:0.021, fees:0.0140, slipExit:0.018, holdTime:'5m 05s', notes:'Big move on news'},
  {id:'TH-004', exitTime:'2026-04-04 12:43', ticker:'AIOTUSDT',   dir:'LONG',  entry:0.028700, exit:0.028800, realized:0.10,  realizedR:4.43, funding:0.000, fees:0.0394, slipExit:0.041, holdTime:'28s',    notes:''},
  {id:'TH-005', exitTime:'2026-04-05 13:20', ticker:'PUFFERUSDT', dir:'LONG',  entry:0.039800, exit:0.039300, realized:0.02,  realizedR:null, funding:0.000, fees:0.0104, slipExit:0.025, holdTime:'9m 29s', notes:''},
  {id:'TH-006', exitTime:'2026-04-02 16:37', ticker:'STOUSDT',    dir:'SHORT', entry:0.514200, exit:0.561700, realized:-1.20, realizedR:0.85, funding:0.003, fees:0.0097, slipExit:0.021, holdTime:'49s',    notes:'Early exit'},
];

// ══ ORDER HISTORY ══════════════════════════════════════════════════════════════
const ORDER_HIST_DATA = [
  {time:'2026-04-04 15:16:03', sym:'JCTUSDT',    side:'SELL', type:'LIMIT',       qty:3334,  price:0.003232, stop:null,      tif:'GTC', status:'filled',           ordId:'9842ac', avgFill:0.003232},
  {time:'2026-04-04 15:13:52', sym:'JCTUSDT',    side:'BUY',  type:'LIMIT',       qty:3334,  price:0.003201, stop:null,      tif:'GTC', status:'filled',           ordId:'9841ab', avgFill:0.003201},
  {time:'2026-04-04 12:45:36', sym:'BTCUSDT',    side:'SELL', type:'MARKET',      qty:0.009, price:null,     stop:null,      tif:'GTC', status:'filled',           ordId:'9832bb', avgFill:66877.80},
  {time:'2026-04-04 12:44:58', sym:'BTCUSDT',    side:'BUY',  type:'LIMIT',       qty:0.009, price:66868.90, stop:null,      tif:'GTC', status:'filled',           ordId:'9831ba', avgFill:66868.90},
  {time:'2026-04-04 12:43:21', sym:'AIOTUSDT',   side:'SELL', type:'MARKET',      qty:1719,  price:null,     stop:null,      tif:'GTC', status:'filled',           ordId:'9822db', avgFill:0.028800},
  {time:'2026-04-04 12:42:53', sym:'AIOTUSDT',   side:'BUY',  type:'LIMIT',       qty:1719,  price:0.028700, stop:null,      tif:'GTC', status:'filled',           ordId:'9821da', avgFill:0.028700},
  {time:'2026-04-03 13:15:05', sym:'STOUSDT',    side:'BUY',  type:'MARKET',      qty:257.5, price:null,     stop:null,      tif:'GTC', status:'filled',           ordId:'9802cb', avgFill:0.007200},
  {time:'2026-04-03 13:10:00', sym:'STOUSDT',    side:'SELL', type:'LIMIT',       qty:257.5, price:0.508300, stop:null,      tif:'GTC', status:'filled',           ordId:'9801ca', avgFill:0.508300},
  {time:'2026-04-02 16:37:46', sym:'STOUSDT',    side:'BUY',  type:'STOP_MARKET', qty:36.19, price:null,     stop:0.580000,  tif:'GTC', status:'filled',           ordId:'9837fb', avgFill:0.561700},
  {time:'2026-04-02 16:36:57', sym:'STOUSDT',    side:'SELL', type:'LIMIT',       qty:36.19, price:0.514200, stop:null,      tif:'GTC', status:'filled',           ordId:'9836fa', avgFill:0.514200},
  {time:'2026-04-05 13:10:53', sym:'PUFFERUSDT', side:'BUY',  type:'MARKET',      qty:32.7,  price:null,     stop:null,      tif:'GTC', status:'filled',           ordId:'9891ea', avgFill:0.039800},
  {time:'2026-04-05 13:20:22', sym:'PUFFERUSDT', side:'SELL', type:'MARKET',      qty:32.7,  price:null,     stop:null,      tif:'GTC', status:'filled',           ordId:'9892eb', avgFill:0.039300},
  {time:'2026-04-05 09:44:12', sym:'SOLUSDT',    side:'BUY',  type:'LIMIT',       qty:4.0,   price:142.00,   stop:null,      tif:'GTC', status:'canceled',         ordId:'9845zz', avgFill:null},
  {time:'2026-04-05 09:44:12', sym:'SOLUSDT',    side:'SELL', type:'STOP_MARKET', qty:4.0,   price:null,     stop:138.50,    tif:'GTE', status:'expired',           ordId:'9845sl', avgFill:null},
];

// ══ LIVE TRADES ═══════════════════════════════════════════════════════════════
const LIVE_TRADES_DATA = [
  {ticker:'BTCUSDT',  dir:'LONG',  entryTime:'2026-05-16 08:32', maxProfit:1.24, maxLoss:-0.42, holdTime:'4h 12m', stopAdj:2},
  {ticker:'ETHUSDT',  dir:'SHORT', entryTime:'2026-05-16 06:18', maxProfit:0.31, maxLoss:-0.08, holdTime:'6h 26m', stopAdj:1},
];

// ══ OPEN POSITIONS + ORDERS (top panel) ════════════════════════════════════════
const OPEN_POS_DATA = [
  {ticker:'BTCUSDT', dir:'LONG',  entry:65800.0, mark:66150.0, size:0.012, notional:793.8, upnl:4.20,  fees:0.32, net:3.88,  mfe:5.10, mae:-0.80, tp:67000.0,  sl:65400.0, entryTs:'2026-05-16 08:32'},
  {ticker:'ETHUSDT', dir:'SHORT', entry:3312.50, mark:3290.40, size:0.25,  notional:822.6, upnl:5.53,  fees:0.16, net:5.37,  mfe:6.20, mae:-1.10, tp:3210.00,  sl:3380.00, entryTs:'2026-05-16 06:18'},
];
const OPEN_ORD_DATA = [
  {sym:'SOLUSDT',  side:'BUY',  type:'LIMIT',       qty:4.0,  filledQty:0,   price:142.00, stop:null,   tif:'GTC', posSide:'LONG',  comment:'entry-sol-01'},
  {sym:'SOLUSDT',  side:'SELL', type:'STOP_MARKET', qty:4.0,  filledQty:0,   price:null,   stop:138.50, tif:'GTE', posSide:'LONG',  comment:'sl-sol-01'},
];

// ══ PRE-TRADE — updated: model column, renamed fields ═════════════════════════
const H_PRE_ROWS = [
  {time:'2026-04-25T12:59:29', ticker:'BTCUSDT', side:'short', avg:77521.95, sl:78000.0, tp:77400.0, atrC:1.000, size:0.0017, notional:133.30, estR:0.08, eligible:false, model:'EMA Trend v2'},
  {time:'2026-04-25T12:14:43', ticker:'BTCUSDT', side:'short', avg:77638.55, sl:78000.0, tp:77400.0, atrC:1.000, size:0.0016, notional:123.60, estR:0.37, eligible:false, model:'EMA Trend v2'},
  {time:'2026-04-25T11:58:50', ticker:'BTCUSDT', side:'short', avg:77621.05, sl:78000.0, tp:77400.0, atrC:1.000, size:0.0022, notional:168.58, estR:0.51, eligible:false, model:'EMA Trend v2'},
];

// ══ HELPERS ════════════════════════════════════════════════════════════════════

function fmtP(v) {
  if (v == null) return '—';
  const a = Math.abs(v);
  return a >= 10000 ? v.toFixed(2) : a >= 1 ? v.toFixed(4) : v.toFixed(6);
}
function fmtQty(qty) {
  if (qty == null) return '—';
  if (qty >= 100) return qty % 1 === 0 ? qty.toLocaleString() : qty.toFixed(2);
  return qty >= 1 ? qty.toFixed(3) : qty.toFixed(4);
}
function pnlStr(v) { if (v == null) return '—'; return (v >= 0 ? '+' : '') + v.toFixed(2); }
function pnlColor(v) { if (v == null) return QEC.text; return v >= 0 ? QEC.green : QEC.red; }

function exitReasonBadge(r) {
  const M = {
    tp_hit:        { label:'TP',     bg:'#071a10', color:QEC.green  },
    sl_hit:        { label:'SL',     bg:'#200808', color:QEC.red    },
    trailing_stop: { label:'Trail',  bg:'#251500', color:QEC.amber  },
    manual:        { label:'Manual', bg:QEC.panel, color:QEC.muted  },
    liquidation:   { label:'Liq',    bg:'#200808', color:QEC.red    },
  };
  const s = M[r] || { label: r || '—', bg: QEC.panel, color: QEC.muted };
  return <span style={{ display:'inline-flex', alignItems:'center', padding:'2px 6px',
    borderRadius:'3px', fontSize:'0.6rem', fontWeight:700, background:s.bg, color:s.color }}>
    {s.label}
  </span>;
}

function orderStatusBadge(st) {
  const M = {
    filled:           { label:'filled',   bg:'#071a10', color:QEC.green },
    canceled:         { label:'canceled', bg:'#200808', color:QEC.red   },
    expired:          { label:'expired',  bg:QEC.panel, color:QEC.muted },
    rejected:         { label:'rejected', bg:'#200808', color:QEC.red   },
    new:              { label:'new',      bg:'#071828', color:QEC.cyan  },
    partially_filled: { label:'partial',  bg:'#251500', color:QEC.amber },
  };
  const s = M[st] || { label: st || '—', bg: QEC.panel, color: QEC.sub };
  return <span style={{ display:'inline-flex', alignItems:'center', padding:'2px 6px',
    borderRadius:'3px', fontSize:'0.6rem', fontWeight:700, background:s.bg, color:s.color }}>
    {s.label}
  </span>;
}

function getExecMatch(fill) {
  if (!fill.tp && !fill.sl) return null;
  const near = (a, b) => Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b)) * 0.0005;
  const isMarket = fill.orderType === 'MARKET';
  const score = (e) => {
    const em  = isMarket ? true : near(e.entryPrice, fill.price);
    const tm  = fill.tp ? near(e.tp, fill.tp)  : true;
    const sm  = fill.sl ? near(e.sl, fill.sl)  : true;
    const cnt = [em, tm, sm].filter(Boolean).length;
    return { exec:e, em, tm, sm, cnt, auto:cnt===3, isMarket };
  };
  if (fill.execId) {
    const e = EXEC_LOG_DATA.find(x => x.id === fill.execId);
    if (e) { const s = score(e); return { ...s, preConfirmed:s.auto }; }
  }
  const cands = EXEC_LOG_DATA.filter(e => e.ticker === fill.sym).map(score).sort((a,b) => b.cnt - a.cnt);
  return cands.length ? { ...cands[0], preConfirmed:false } : { exec:null, cnt:0, preConfirmed:false };
}

// ══ TABLE ATOMS ════════════════════════════════════════════════════════════════

const HTH = ({ children, style:st={} }) => (
  <th style={{ color:QEC.sub, fontSize:'0.6rem', fontWeight:700, letterSpacing:'0.07em',
    textTransform:'uppercase', padding:'5px 8px', borderBottom:`1px solid ${QEC.border}`,
    textAlign:'left', whiteSpace:'nowrap', ...st }}>{children}</th>
);
const HTD = ({ children, style:st={} }) => (
  <td style={{ padding:'5px 8px', borderBottom:`1px solid ${QEC.border}`,
    fontFamily:'JetBrains Mono,monospace', fontSize:'0.72rem', color:QEC.text,
    whiteSpace:'nowrap', ...st }}>{children}</td>
);
const DTH = ({ children, style:st={} }) => (
  <th style={{ color:QEC.muted, fontSize:'0.58rem', fontWeight:700, letterSpacing:'0.07em',
    textTransform:'uppercase', padding:'4px 8px', borderBottom:`1px solid ${QEC.border}`,
    textAlign:'left', whiteSpace:'nowrap', ...st }}>{children}</th>
);
const DTD = ({ children, style:st={} }) => (
  <td style={{ padding:'4px 8px', borderBottom:`1px solid ${QEC.border}`,
    fontFamily:'JetBrains Mono,monospace', fontSize:'0.68rem', color:QEC.text,
    whiteSpace:'nowrap', ...st }}>{children}</td>
);

// ══ EXEC LINK BADGE ═══════════════════════════════════════════════════════════

const ExecBadge = ({ match, onClick }) => {
  if (!match) return <span style={{ color:QEC.muted, fontSize:'0.6rem' }}>—</span>;
  if (!match.exec) return (
    <span onClick={onClick} style={{ display:'inline-flex', alignItems:'center', gap:'3px',
      padding:'2px 6px', borderRadius:'3px', fontSize:'0.58rem', fontWeight:700,
      background:'#200808', color:QEC.red, cursor:'pointer', letterSpacing:'0.04em' }}>✗ UNLINKED</span>
  );
  if (match.auto || match.preConfirmed) return (
    <span onClick={onClick} style={{ display:'inline-flex', alignItems:'center', gap:'3px',
      padding:'2px 6px', borderRadius:'3px', fontSize:'0.58rem', fontWeight:700,
      background:'#071a10', color:QEC.green, cursor:'pointer', letterSpacing:'0.04em' }}>● LINKED</span>
  );
  return (
    <span onClick={onClick} style={{ display:'inline-flex', alignItems:'center', gap:'3px',
      padding:'2px 6px', borderRadius:'3px', fontSize:'0.58rem', fontWeight:700,
      background:'#1e1100', color:QEC.amber, cursor:'pointer', letterSpacing:'0.04em' }}>⚠ {match.cnt}/3</span>
  );
};

// ══ EXEC LINK PANEL ════════════════════════════════════════════════════════════

const ExecLinkPanel = ({ fill, onClose }) => {
  const match = React.useMemo(() => getExecMatch(fill), [fill.id]);
  const [confirmed, setConfirmed] = React.useState(match ? match.preConfirmed : false);
  if (!match) return null;
  if (!match.exec) return (
    <div style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, borderRadius:'4px',
      padding:'10px 14px', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
      <span style={{ color:QEC.muted, fontSize:'0.7rem' }}>No execution log candidate for <span style={{ color:QEC.blue, fontFamily:'JetBrains Mono,monospace' }}>{fill.sym}</span></span>
      <button onClick={onClose} style={{ background:'none', border:'none', color:QEC.muted, cursor:'pointer', fontSize:'1rem' }}>×</button>
    </div>
  );
  const { exec, em, tm, sm, cnt, isMarket } = match;
  const resolved = cnt === 3 || confirmed;
  const criteria = [
    { label:'Entry Price', fillVal: isMarket ? 'MARKET ORDER' : fmtP(fill.price), execVal:fmtP(exec.entryPrice), ok:em, skip:isMarket },
    { label:'Take Profit', fillVal:fmtP(fill.tp),  execVal:fmtP(exec.tp),  ok:tm, skip:false },
    { label:'Stop Loss',   fillVal:fmtP(fill.sl),  execVal:fmtP(exec.sl),  ok:sm, skip:false },
  ];
  return (
    <div style={{ background:'#0a0f1a', border:`1px solid ${resolved ? QEC.green+'44' : QEC.amber+'44'}`, borderRadius:'4px', padding:'10px 14px' }}>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'10px' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
          <span style={{ fontSize:'0.58rem', fontWeight:700, letterSpacing:'0.1em', textTransform:'uppercase', color:QEC.muted }}>Execution Log Link</span>
          <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize:'0.68rem', color:QEC.sub }}>{exec.id}</span>
          <span style={{ fontSize:'0.62rem', color:QEC.muted }}>{exec.time}</span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
          <span style={{ padding:'2px 8px', borderRadius:'3px', fontSize:'0.58rem', fontWeight:700, letterSpacing:'0.05em',
            background: resolved ? '#071a10' : '#1e1100', color: resolved ? QEC.green : QEC.amber }}>
            {cnt===3 ? '● AUTO-LINKED' : confirmed ? '✓ CONFIRMED' : `⚠ ${cnt}/3 MATCH`}
          </span>
          <button onClick={onClose} style={{ background:'none', border:'none', color:QEC.muted, cursor:'pointer', fontSize:'1rem', padding:'0 2px' }}>×</button>
        </div>
      </div>
      <div style={{ overflowX:'auto', marginBottom:'10px' }}>
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead><tr>
            {['Criterion','Fill Trade','Exec Log',''].map(h => (
              <th key={h} style={{ color:QEC.muted, fontSize:'0.57rem', fontWeight:700, letterSpacing:'0.07em',
                textTransform:'uppercase', padding:'4px 10px', borderBottom:`1px solid ${QEC.border}`, textAlign:'left', whiteSpace:'nowrap' }}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {criteria.map(({ label, fillVal, execVal, ok, skip }) => (
              <tr key={label}>
                <td style={{ padding:'6px 10px', borderBottom:`1px solid ${QEC.border}`, fontSize:'0.68rem', color:QEC.sub }}>{label}</td>
                <td style={{ padding:'6px 10px', borderBottom:`1px solid ${QEC.border}`, fontFamily:'JetBrains Mono,monospace', fontSize:'0.7rem', color:skip?QEC.muted:QEC.text, fontStyle:skip?'italic':'normal' }}>{fillVal}</td>
                <td style={{ padding:'6px 10px', borderBottom:`1px solid ${QEC.border}`, fontFamily:'JetBrains Mono,monospace', fontSize:'0.7rem', color:skip?QEC.muted:ok?QEC.text:QEC.red, fontStyle:skip?'italic':'normal' }}>
                  {execVal}{!ok&&!skip&&<span style={{ marginLeft:'6px', fontSize:'0.62rem', fontWeight:700, color:QEC.red }}>≠</span>}
                </td>
                <td style={{ padding:'6px 10px', borderBottom:`1px solid ${QEC.border}`, textAlign:'center', width:'32px' }}>
                  {skip ? <span style={{ fontSize:'0.6rem', color:QEC.muted, fontStyle:'italic' }}>skip</span>
                        : ok  ? <span style={{ color:QEC.green, fontSize:'0.8rem' }}>✓</span>
                               : <span style={{ color:QEC.red,   fontSize:'0.8rem' }}>✗</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!resolved && (
        <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'10px' }}>
          <Btn variant="success" size="sm" onClick={() => setConfirmed(true)}>Confirm Link</Btn>
          <Btn variant="ghost" size="sm">Search Other</Btn>
          <span style={{ fontSize:'0.62rem', color:QEC.muted }}>{3-cnt} criterion{3-cnt!==1?'a':'ion'} differ{3-cnt===1?'s':''} — review before confirming</span>
        </div>
      )}
      {confirmed && cnt < 3 && (
        <div style={{ display:'flex', alignItems:'center', gap:'5px', marginBottom:'10px', fontSize:'0.65rem', color:QEC.green }}>
          <span>✓ Manually confirmed — {3-cnt} mismatch{3-cnt!==1?'es':''} acknowledged</span>
          <button onClick={() => setConfirmed(false)} style={{ marginLeft:'4px', background:'none', border:'none', color:QEC.muted, cursor:'pointer', fontSize:'0.65rem', textDecoration:'underline' }}>undo</button>
        </div>
      )}
      <div style={{ display:'flex', gap:'20px', flexWrap:'wrap', paddingTop:'8px', borderTop:`1px solid ${QEC.border}` }}>
        {[['Order Type',exec.type],['Size Filled',fmtQty(exec.sizeFilled)],['Slippage',(exec.slip*100).toFixed(3)+'%'],['Maker Fee',(exec.makerFee*100).toFixed(2)+'%'],['Latency',exec.latency+' ms']].map(([l,v]) => (
          <div key={l}>
            <div style={{ fontSize:'0.55rem', color:QEC.muted, fontWeight:700, textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:'1px' }}>{l}</div>
            <div style={{ fontFamily:'JetBrains Mono,monospace', fontSize:'0.68rem', color:QEC.sub }}>{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

// ══ FILL DRAWER ════════════════════════════════════════════════════════════════

const FillDrawer = ({ pos }) => {
  const [activeFill, setActiveFill] = React.useState(null);
  const fills = FILLS_DATA.filter(f => f.posId === pos.id);
  const toggle = (id) => setActiveFill(p => p === id ? null : id);
  return (
    <div style={{ background:'#050810', borderTop:`1px solid ${QEC.border}`, borderBottom:`2px solid ${QEC.blue}33`, padding:'8px 10px 10px 32px' }}>
      <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'8px' }}>
        <span style={{ fontSize:'0.58rem', fontWeight:700, textTransform:'uppercase', letterSpacing:'0.1em', color:QEC.blue }}>▾ Fill Trades</span>
        <span style={{ fontFamily:'JetBrains Mono,monospace', fontSize:'0.65rem', color:QEC.muted }}>{pos.id} · {fills.length} fills</span>
        <span style={{ fontSize:'0.6rem', color:QEC.muted, marginLeft:'auto' }}>Click <span style={{ color:QEC.amber }}>exec badge</span> on entry fills to inspect link</span>
      </div>
      <div style={{ overflowX:'auto' }}>
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead><tr>
            <DTH>Time</DTH><DTH>Order No.</DTH><DTH>Side</DTH><DTH>Price</DTH>
            <DTH>Qty</DTH><DTH>Fee</DTH><DTH>Role</DTH><DTH>PnL</DTH><DTH>Exec Link</DTH>
          </tr></thead>
          <tbody>
            {fills.map(fill => {
              const match   = getExecMatch(fill);
              const isEntry = !!fill.tp;
              const isOpen  = activeFill === fill.id;
              const sc      = fill.side.startsWith('Open') ? QEC.green : QEC.red;
              return (
                <React.Fragment key={fill.id}>
                  <tr style={{ background:isOpen?QEC.hover:'transparent' }}
                    onMouseOver={e => !isOpen && e.currentTarget.querySelectorAll('td').forEach(td => td.style.background='#0c1525')}
                    onMouseOut={e  => !isOpen && e.currentTarget.querySelectorAll('td').forEach(td => td.style.background='transparent')}>
                    <DTD style={{ color:QEC.sub }}>{fill.time.slice(11)}</DTD>
                    <DTD style={{ color:QEC.muted, fontSize:'0.62rem' }}>#{fill.orderNo}</DTD>
                    <DTD style={{ color:sc, fontWeight:700 }}>{fill.side}</DTD>
                    <DTD>{fmtP(fill.price)}</DTD>
                    <DTD>{fmtQty(fill.qty)}</DTD>
                    <DTD style={{ color:QEC.muted }}>{fill.fee.toFixed(4)} {fill.feeAsset}</DTD>
                    <DTD style={{ color:QEC.muted }}>{fill.role}</DTD>
                    <DTD style={{ color:pnlColor(fill.pnl), fontWeight:fill.pnl!=null?700:400 }}>{pnlStr(fill.pnl)}</DTD>
                    <td style={{ padding:'4px 8px', borderBottom:`1px solid ${QEC.border}` }}>
                      {isEntry ? (
                        <div style={{ display:'flex', alignItems:'center', gap:'5px' }}>
                          <ExecBadge match={match} onClick={() => toggle(fill.id)} />
                          <span style={{ color:QEC.muted, fontSize:'0.6rem', cursor:'pointer' }} onClick={() => toggle(fill.id)}>{isOpen?'▲':'▼'}</span>
                        </div>
                      ) : <span style={{ color:QEC.muted, fontSize:'0.6rem' }}>—</span>}
                    </td>
                  </tr>
                  {isOpen && isEntry && (
                    <tr><td colSpan={9} style={{ padding:'0 8px 8px 0', borderBottom:`1px solid ${QEC.border}` }}>
                      <ExecLinkPanel fill={fill} onClose={() => setActiveFill(null)} />
                    </td></tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ══ OPEN POSITIONS PANEL (top strip) ══════════════════════════════════════════

const OpenPositionsPanel = () => {
  const [sub, setSub] = React.useState('pos');
  return (
    <Card p="0">
      <div style={{ display:'flex', alignItems:'center', borderBottom:`1px solid ${QEC.border}`, padding:'0 10px' }}>
        {[['pos',`Positions(${OPEN_POS_DATA.length})`],['oo',`Open Orders(${OPEN_ORD_DATA.length})`]].map(([id,lbl]) => (
          <button key={id} onClick={() => setSub(id)} style={{
            padding:'6px 14px', border:'none', background:'none', cursor:'pointer',
            fontSize:'0.6rem', fontWeight:700, letterSpacing:'0.1em', textTransform:'uppercase',
            fontFamily:"'Space Grotesk',sans-serif",
            color: sub===id ? QEC.blue : QEC.muted,
            borderBottom: `2px solid ${sub===id ? QEC.blue : 'transparent'}`,
            marginBottom:'-1px',
          }}>{lbl}</button>
        ))}
        <span style={{ marginLeft:'auto', fontFamily:'JetBrains Mono,monospace', fontSize:'0.68rem', color:QEC.sub, padding:'0 10px' }}>
          {OPEN_POS_DATA.length}/{OPEN_POS_DATA.length + 3}
        </span>
      </div>
      <div style={{ padding:'8px 10px', overflowX:'auto' }}>
        {sub === 'pos' && (
          OPEN_POS_DATA.length ? (
            <table style={{ width:'100%', borderCollapse:'collapse' }}>
              <thead><tr>
                {['Symbol','Dir','Hold','Entry','Mark','Size','Notional','uPnL','Fees','Net','MFE','MAE','TP','SL'].map(h=><HTH key={h}>{h}</HTH>)}
              </tr></thead>
              <tbody>
                {OPEN_POS_DATA.map(p => {
                  const now = new Date(), entry = new Date(p.entryTs);
                  const diffMin = Math.floor((now - entry) / 60000);
                  const holdStr = diffMin < 60 ? `${diffMin}m` : `${Math.floor(diffMin/60)}h ${diffMin%60}m`;
                  return (
                    <tr key={p.ticker}
                      onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
                      onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
                      <HTD style={{ color:QEC.blue, fontWeight:700 }}>{p.ticker}</HTD>
                      <HTD style={{ color:p.dir==='LONG'?QEC.green:QEC.red, fontWeight:700 }}>{p.dir}</HTD>
                      <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{holdStr}</HTD>
                      <HTD>{fmtP(p.entry)}</HTD>
                      <HTD>{fmtP(p.mark)}</HTD>
                      <HTD>{fmtQty(p.size)}</HTD>
                      <HTD>{p.notional.toFixed(2)}</HTD>
                      <HTD style={{ color:pnlColor(p.upnl), fontWeight:700 }}>{pnlStr(p.upnl)}</HTD>
                      <HTD style={{ color:QEC.muted }}>{p.fees.toFixed(4)}</HTD>
                      <HTD style={{ color:pnlColor(p.net), fontWeight:700 }}>{pnlStr(p.net)}</HTD>
                      <HTD style={{ color:QEC.green }}>+{p.mfe.toFixed(2)}</HTD>
                      <HTD style={{ color:QEC.red }}>{p.mae.toFixed(2)}</HTD>
                      <HTD style={{ color:QEC.green, fontSize:'0.68rem' }}>{fmtP(p.tp)}</HTD>
                      <HTD style={{ color:QEC.red,   fontSize:'0.68rem' }}>{fmtP(p.sl)}</HTD>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : <div style={{ textAlign:'center', padding:'20px 0', color:QEC.muted, fontSize:'0.78rem' }}>No open positions.</div>
        )}
        {sub === 'oo' && (
          OPEN_ORD_DATA.length ? (
            <table style={{ width:'100%', borderCollapse:'collapse' }}>
              <thead><tr>
                {['Symbol','Side','Type','Qty','Filled','Remaining','Price','Trigger','TIF','Pos Side','Comment'].map(h=><HTH key={h}>{h}</HTH>)}
              </tr></thead>
              <tbody>
                {OPEN_ORD_DATA.map((o,i) => (
                  <tr key={i}
                    onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
                    onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
                    <HTD style={{ color:QEC.blue, fontWeight:700 }}>{o.sym}</HTD>
                    <HTD style={{ color:o.side==='BUY'?QEC.green:QEC.red, fontWeight:700 }}>{o.side}</HTD>
                    <HTD style={{ color:QEC.sub }}>{o.type}</HTD>
                    <HTD>{fmtQty(o.qty)}</HTD>
                    <HTD>{fmtQty(o.filledQty)}</HTD>
                    <HTD style={{ color:QEC.sub }}>{fmtQty(o.qty - o.filledQty)}</HTD>
                    <HTD>{o.price ? fmtP(o.price) : '—'}</HTD>
                    <HTD>{o.stop  ? fmtP(o.stop)  : '—'}</HTD>
                    <HTD style={{ color:QEC.sub }}>{o.tif}</HTD>
                    <HTD style={{ color:o.posSide==='LONG'?QEC.green:QEC.red }}>{o.posSide}</HTD>
                    <HTD style={{ color:QEC.muted, fontSize:'0.65rem' }}>{o.comment}</HTD>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div style={{ textAlign:'center', padding:'20px 0', color:QEC.muted, fontSize:'0.78rem' }}>No open orders.</div>
        )}
      </div>
    </Card>
  );
};

// ══ POSITION HISTORY TAB ══════════════════════════════════════════════════════

const HIST_PRESETS = ['Last 90 days','Last 30 days','Last 15 days','Last 7 days','Yesterday','Today'];

const PositionHistoryTab = () => {
  const [expanded, setExpanded] = React.useState(null);
  const [search,   setSearch]   = React.useState('');
  const [dir,      setDir]       = React.useState('');
  const [preset,   setPreset]   = React.useState('Last 30 days');

  const filtered = POSITIONS_DATA.filter(p =>
    (!search || p.pair.toLowerCase().includes(search.toLowerCase())) &&
    (!dir || p.dir === dir)
  );

  const posHasWarning = (pos) => FILLS_DATA.filter(f => f.posId === pos.id && f.tp).some(f => {
    const m = getExecMatch(f); return m && m.exec && !m.auto && !m.preConfirmed;
  });

  // cols: chevron(1) + Entry,Exit,Hold,Pair,Dir,Sizing,Notional,PnL,PnL%,Exit Reason,TP,SL,MFE,MAE,M·R,Notes(16) = 17
  const TOTAL_COLS = 17;

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'0' }}>
      <div style={{ display:'flex', flexDirection:'column', gap:'6px', paddingBottom:'8px', borderBottom:`1px solid ${QEC.border}`, marginBottom:'8px' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'6px', flexWrap:'wrap' }}>
          <Btn variant="primary" size="sm">Export to Excel</Btn>
          <Btn variant="secondary" size="sm">↺ Refresh</Btn>
          <span style={{ fontSize:'0.62rem', color:QEC.sub }}>Auto-refresh every 30s</span>
          <div style={{ marginLeft:'auto', display:'flex', gap:'4px' }}>
            <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search symbol…"
              style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px',
                padding:'3px 8px', fontSize:'0.7rem', height:'24px', width:'130px', outline:'none', fontFamily:'JetBrains Mono,monospace' }}/>
            <select value={dir} onChange={e=>setDir(e.target.value)}
              style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px', padding:'2px 6px', fontSize:'0.68rem', height:'24px' }}>
              <option value="">All Dirs</option><option>LONG</option><option>SHORT</option>
            </select>
          </div>
        </div>
        <div style={{ display:'flex', gap:'3px', marginTop:'6px', flexWrap:'wrap' }}>
          {HIST_PRESETS.map(p => (
            <button key={p} onClick={() => setPreset(p)} style={{
              padding:'2px 9px', borderRadius:'3px', cursor:'pointer', border:`1px solid ${QEC.border}`,
              background:preset===p?'#1a3060':QEC.panel, color:preset===p?'#93c5fd':QEC.sub, fontSize:'0.62rem', fontWeight:600,
            }}>{p}</button>
          ))}
        </div>
      </div>

      <div>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'8px', flexWrap:'wrap', gap:'6px' }}>
          <SecLabel style={{ marginBottom:0 }}>Position History ({filtered.length})</SecLabel>
          <span style={{ fontSize:'0.6rem', color:QEC.muted }}>▸ expand row for fills · click <span style={{ color:QEC.amber }}>⚠</span> to review exec link</span>
        </div>
        <div style={{ overflowX:'auto' }}>
          <table style={{ width:'100%', borderCollapse:'collapse' }}>
            <thead><tr>
              <th style={{ width:'18px', borderBottom:`1px solid ${QEC.border}` }}></th>
              {['Open','Close','Hold','Symbol','Dir','Qty','Notional','PnL','PnL %','Exit Reason','TP','SL','MFE','MAE','M·R','Notes'].map(h=><HTH key={h}>{h}</HTH>)}
            </tr></thead>
            <tbody>
              {filtered.map(pos => {
                const isOpen  = expanded === pos.id;
                const hasWarn = posHasWarning(pos);
                return (
                  <React.Fragment key={pos.id}>
                    <tr onClick={() => setExpanded(isOpen ? null : pos.id)}
                      style={{ cursor:'pointer', background:isOpen?'#0e1929':'transparent' }}
                      onMouseOver={e=>!isOpen&&e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
                      onMouseOut={e=>!isOpen&&e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
                      <td style={{ padding:'5px 6px', borderBottom:`1px solid ${QEC.border}`, color:isOpen?QEC.blue:QEC.muted, fontSize:'0.65rem', textAlign:'center', fontWeight:700 }}>
                        {isOpen?'▾':'▸'}
                      </td>
                      <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{pos.entry}</HTD>
                      <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{pos.exit}</HTD>
                      <HTD style={{ color:QEC.muted, fontSize:'0.65rem' }}>{pos.hold}</HTD>
                      <HTD style={{ color:QEC.blue, fontWeight:700 }}>
                        <span style={{ display:'flex', alignItems:'center', gap:'5px' }}>
                          {pos.pair}
                          {hasWarn && <span title="Execution link needs confirmation" style={{ color:QEC.amber, fontSize:'0.65rem' }}>⚠</span>}
                        </span>
                      </HTD>
                      <HTD style={{ color:pos.dir==='LONG'?QEC.green:QEC.red, fontWeight:700 }}>{pos.dir}</HTD>
                      <HTD>{fmtQty(pos.sizing)}</HTD>
                      <HTD>{pos.notional.toFixed(2)}</HTD>
                      <HTD style={{ color:pnlColor(pos.pnl), fontWeight:700 }}>{pnlStr(pos.pnl)}</HTD>
                      <HTD style={{ color:pnlColor(pos.pnlPct) }}>{pos.pnlPct >= 0 ? '+' : ''}{pos.pnlPct.toFixed(2)}%</HTD>
                      <td style={{ padding:'5px 8px', borderBottom:`1px solid ${QEC.border}` }}>{exitReasonBadge(pos.exitReason)}</td>
                      <HTD style={{ color:QEC.green, fontSize:'0.68rem' }}>{fmtP(pos.tp)}</HTD>
                      <HTD style={{ color:QEC.red,   fontSize:'0.68rem' }}>{fmtP(pos.sl)}</HTD>
                      <HTD style={{ color:QEC.green }}>{pos.mfe>=0?'+':''}{pos.mfe.toFixed(2)}</HTD>
                      <HTD style={{ color:QEC.red }}>{pos.mae.toFixed(2)}</HTD>
                      <HTD style={{ color:pos.mer!=null?QEC.text:QEC.muted }}>{pos.mer!=null?pos.mer.toFixed(2):'—'}</HTD>
                      <td onClick={e=>e.stopPropagation()} style={{ padding:'5px 8px', borderBottom:`1px solid ${QEC.border}`, fontFamily:'JetBrains Mono,monospace', fontSize:'0.7rem', maxWidth:'160px' }}>
                        {pos.notes
                          ? <span style={{ color:QEC.sub, display:'block', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }} title={pos.notes}>{pos.notes}</span>
                          : <span style={{ color:QEC.blue, fontSize:'0.62rem', cursor:'pointer' }}>+ Add note</span>}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr><td colSpan={TOTAL_COLS} style={{ padding:0 }}><FillDrawer pos={pos}/></td></tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginTop:'8px', flexWrap:'wrap', gap:'6px' }}>
          <span style={{ fontSize:'0.65rem', color:QEC.sub }}>Showing 1–{filtered.length} of {POSITIONS_DATA.length}</span>
          <div style={{ display:'flex', gap:'2px' }}>
            {['«','1','2','3','»'].map((p,i) => (
              <button key={i} style={{ padding:'2px 7px', border:`1px solid ${QEC.border}`, borderRadius:'3px', cursor:'pointer',
                background:p==='1'?QEC.blue:QEC.panel, color:p==='1'?'#fff':QEC.sub, fontSize:'0.65rem', fontWeight:600 }}>{p}</button>
            ))}
            <select style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px', padding:'2px 5px', fontSize:'0.65rem', height:'24px' }}>
              <option>20 / page</option><option>50 / page</option><option>100 / page</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  );
};

// ══ ORDER HISTORY TAB ══════════════════════════════════════════════════════════

const OrderHistoryTab = () => {
  const [search, setSearch] = React.useState('');
  const filtered = ORDER_HIST_DATA.filter(r => !search || r.sym.toLowerCase().includes(search.toLowerCase()));
  return (
    <div>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'8px', flexWrap:'wrap', gap:'6px' }}>
        <SecLabel style={{ marginBottom:0 }}>Order History ({filtered.length})</SecLabel>
        <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search symbol…"
          style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px',
            padding:'3px 8px', fontSize:'0.7rem', height:'24px', width:'140px', outline:'none' }}/>
      </div>
      <div style={{ overflowX:'auto' }}>
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead><tr>
            {['Time','Symbol','Side','Type','Qty','Price','Trigger','TIF','Status','Order ID','Avg Fill'].map(h=><HTH key={h}>{h}</HTH>)}
          </tr></thead>
          <tbody>
            {filtered.map((r,i) => (
              <tr key={i}
                onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
                onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
                <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{r.time.slice(5)}</HTD>
                <HTD style={{ color:QEC.blue, fontWeight:700 }}>{r.sym}</HTD>
                <HTD style={{ color:r.side==='BUY'?QEC.green:QEC.red, fontWeight:700 }}>{r.side}</HTD>
                <HTD style={{ color:QEC.sub }}>{r.type}</HTD>
                <HTD>{fmtQty(r.qty)}</HTD>
                <HTD>{r.price ? fmtP(r.price) : '—'}</HTD>
                <HTD>{r.stop  ? fmtP(r.stop)  : '—'}</HTD>
                <HTD style={{ color:QEC.sub }}>{r.tif}</HTD>
                <td style={{ padding:'5px 8px', borderBottom:`1px solid ${QEC.border}` }}>{orderStatusBadge(r.status)}</td>
                <HTD style={{ color:QEC.muted, fontSize:'0.65rem' }}>{r.ordId}</HTD>
                <HTD>{r.avgFill ? fmtP(r.avgFill) : '—'}</HTD>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ══ TRADE HISTORY TAB — round-trip format ══════════════════════════════════════

const TradeHistoryTab = () => {
  const [search, setSearch] = React.useState('');
  const [dir, setDir]       = React.useState('');
  const filtered = TRADE_HIST_DATA.filter(r =>
    (!search || r.ticker.toLowerCase().includes(search.toLowerCase())) && (!dir || r.dir === dir)
  );
  return (
    <div>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'8px', flexWrap:'wrap', gap:'6px' }}>
        <SecLabel style={{ marginBottom:0 }}>Trade History — Closed / Manual ({filtered.length} entries)</SecLabel>
        <div style={{ display:'flex', gap:'4px' }}>
          <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search ticker…"
            style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px',
              padding:'3px 8px', fontSize:'0.7rem', height:'24px', width:'130px', outline:'none' }}/>
          <select value={dir} onChange={e=>setDir(e.target.value)}
            style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px', padding:'2px 6px', fontSize:'0.68rem', height:'24px' }}>
            <option value="">All Dirs</option><option>LONG</option><option>SHORT</option>
          </select>
        </div>
      </div>
      <div style={{ overflowX:'auto' }}>
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead><tr>
            {['Exit Time','Ticker','Dir','Entry','Exit','Realized','R','Funding','Fees','Slip Exit','Hold Time','Notes'].map(h=><HTH key={h}>{h}</HTH>)}
          </tr></thead>
          <tbody>
            {filtered.map(r => (
              <tr key={r.id}
                onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
                onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
                <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{r.exitTime}</HTD>
                <HTD style={{ color:QEC.blue, fontWeight:700 }}>{r.ticker}</HTD>
                <HTD style={{ color:r.dir==='LONG'?QEC.green:QEC.red, fontWeight:700 }}>{r.dir}</HTD>
                <HTD>{fmtP(r.entry)}</HTD>
                <HTD>{fmtP(r.exit)}</HTD>
                <HTD style={{ color:pnlColor(r.realized), fontWeight:700 }}>{pnlStr(r.realized)}</HTD>
                <HTD style={{ color:QEC.sub }}>{r.realizedR != null ? r.realizedR.toFixed(2)+'R' : '—'}</HTD>
                <HTD style={{ color:QEC.sub }}>{r.funding.toFixed(4)}</HTD>
                <HTD style={{ color:QEC.sub }}>{r.fees.toFixed(4)}</HTD>
                <HTD style={{ color:QEC.sub }}>{(r.slipExit * 100).toFixed(3)}%</HTD>
                <HTD style={{ color:QEC.sub }}>{r.holdTime}</HTD>
                <HTD style={{ color:r.notes?QEC.sub:QEC.blue, fontSize:'0.62rem', cursor:'pointer' }}>
                  {r.notes || '+ Add note'}
                </HTD>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ══ EXECUTION LOG TAB ══════════════════════════════════════════════════════════

const ExecutionLogTab = () => (
  <div>
    <SecLabel style={{ marginBottom:'8px' }}>Execution Log ({EXEC_LOG_DATA.length} entries)</SecLabel>
    <div style={{ overflowX:'auto' }}>
      <table style={{ width:'100%', borderCollapse:'collapse' }}>
        <thead><tr>
          {['Entry Time','Exec ID','Ticker','Side','Actual Entry','Size Filled','Slippage','Order Type','Maker Fee','Latency ms','TP','SL'].map(h=><HTH key={h}>{h}</HTH>)}
        </tr></thead>
        <tbody>
          {EXEC_LOG_DATA.map(e => (
            <tr key={e.id}
              onMouseOver={ev=>ev.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
              onMouseOut={ev=>ev.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
              <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{e.time}</HTD>
              <HTD style={{ color:QEC.muted, fontSize:'0.65rem' }}>{e.id}</HTD>
              <HTD style={{ color:QEC.blue, fontWeight:700 }}>{e.ticker}</HTD>
              <HTD style={{ color:e.side==='BUY'?QEC.green:QEC.red, fontWeight:700 }}>{e.side}</HTD>
              <HTD>{fmtP(e.entryPrice)}</HTD>
              <HTD>{fmtQty(e.sizeFilled)}</HTD>
              <HTD style={{ color:QEC.sub }}>{(e.slip*100).toFixed(3)}%</HTD>
              <HTD style={{ color:QEC.sub }}>{e.type}</HTD>
              <HTD style={{ color:QEC.sub }}>{(e.makerFee*100).toFixed(2)}%</HTD>
              <HTD style={{ color:QEC.sub }}>{e.latency}</HTD>
              <HTD style={{ color:QEC.green, fontSize:'0.68rem' }}>{fmtP(e.tp)}</HTD>
              <HTD style={{ color:QEC.red,   fontSize:'0.68rem' }}>{fmtP(e.sl)}</HTD>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

// ══ LIVE TRADES TAB ════════════════════════════════════════════════════════════

const LiveTradesTab = () => (
  <div>
    <SecLabel style={{ marginBottom:'8px' }}>Live Trades ({LIVE_TRADES_DATA.length} entries)</SecLabel>
    <div style={{ overflowX:'auto' }}>
      <table style={{ width:'100%', borderCollapse:'collapse' }}>
        <thead><tr>
          {['Ticker','Dir','Entry Time','Max Profit','Max Loss','Hold Time','Stop Adj.'].map(h=><HTH key={h}>{h}</HTH>)}
        </tr></thead>
        <tbody>
          {LIVE_TRADES_DATA.map((r,i) => (
            <tr key={i}
              onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
              onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
              <HTD style={{ color:QEC.blue, fontWeight:700 }}>{r.ticker}</HTD>
              <HTD style={{ color:r.dir==='LONG'?QEC.green:QEC.red, fontWeight:700 }}>{r.dir}</HTD>
              <HTD style={{ color:QEC.sub, fontSize:'0.68rem' }}>{r.entryTime}</HTD>
              <HTD style={{ color:QEC.green }}>+{r.maxProfit.toFixed(2)}</HTD>
              <HTD style={{ color:QEC.red }}>{r.maxLoss.toFixed(2)}</HTD>
              <HTD style={{ color:QEC.sub }}>{r.holdTime}</HTD>
              <HTD style={{ color:QEC.sub }}>{r.stopAdj}</HTD>
            </tr>
          ))}
          {!LIVE_TRADES_DATA.length && (
            <tr><td colSpan={7} style={{ textAlign:'center', padding:'24px 0', color:QEC.muted, fontSize:'0.78rem' }}>No live trades logged yet.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  </div>
);

// ══ PRE-TRADE TAB — updated: model col, renamed fields ═════════════════════════

const PreTradeTab = () => (
  <div>
    <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'8px', flexWrap:'wrap', gap:'6px' }}>
      <SecLabel style={{ marginBottom:0 }}>Pre-Trade Log ({H_PRE_ROWS.length} entries)</SecLabel>
      <div style={{ display:'flex', gap:'4px' }}>
        <input placeholder="Search ticker…" style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px', padding:'3px 8px', fontSize:'0.7rem', height:'24px', width:'130px', outline:'none' }}/>
        <select style={{ background:QEC.panel, border:`1px solid ${QEC.border}`, color:QEC.text, borderRadius:'4px', padding:'2px 6px', fontSize:'0.68rem', height:'24px' }}>
          <option value="">All Sides</option><option>LONG</option><option>SHORT</option>
        </select>
      </div>
    </div>
    <div style={{ overflowX:'auto' }}>
      <table style={{ width:'100%', borderCollapse:'collapse' }}>
        <thead><tr>
          {['Time','Ticker','Side','Avg','SL','TP','ATR_c','Size','Notional','R:R','Eligible','Model','Notes'].map(h=><HTH key={h}>{h}</HTH>)}
        </tr></thead>
        <tbody>
          {H_PRE_ROWS.map((r,i) => (
            <tr key={i}
              onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
              onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
              <HTD style={{ color:QEC.sub, fontSize:'0.65rem' }}>{r.time.slice(11)}</HTD>
              <HTD style={{ color:QEC.blue, fontWeight:700 }}>{r.ticker}</HTD>
              <HTD style={{ color:r.side==='long'?QEC.green:QEC.red, fontWeight:700 }}>{r.side.toUpperCase()}</HTD>
              <HTD>{fmtP(r.avg)}</HTD>
              <HTD style={{ color:QEC.red }}>{fmtP(r.sl)}</HTD>
              <HTD style={{ color:QEC.green }}>{fmtP(r.tp)}</HTD>
              <HTD style={{ color:QEC.sub }}>{r.atrC != null ? r.atrC.toFixed(3) : '—'}</HTD>
              <HTD>{r.size.toFixed(4)}</HTD>
              <HTD>{r.notional.toFixed(2)}</HTD>
              <HTD style={{ color:QEC.amber }}>{r.estR.toFixed(2)}</HTD>
              <td style={{ padding:'5px 8px', borderBottom:`1px solid ${QEC.border}` }}>
                <span style={{ display:'inline-block', width:'8px', height:'8px', borderRadius:'50%', background:r.eligible?QEC.green:QEC.red }}/>
              </td>
              <HTD style={{ color:QEC.sub }}>{r.model || '—'}</HTD>
              <HTD style={{ color:QEC.blue, fontSize:'0.62rem', cursor:'pointer' }}>+ Add note</HTD>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);

// ══ HISTORY PAGE ═══════════════════════════════════════════════════════════════

const HIST_MAIN_TABS = [
  ['positions', 'Position History'],
  ['orders',    'Order History'],
  ['trades',    'Trade History'],
  ['live',      'Live Trades'],
];

const HIST_LOG_TABS = [
  ['pretrade',   'Pre-Trade Log'],
  ['executions', 'Execution Log'],
];

const HistoryPage = () => {
  const [mainTab, setMainTab] = React.useState('positions');
  const [logTab,  setLogTab]  = React.useState('pretrade');
  const [preset,  setPreset]  = React.useState('Last 30 days');

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'6px', padding:'8px' }}>

      {/* Card 1: Open Positions + Open Orders */}
      <OpenPositionsPanel />

      {/* Toolbar */}
      <Card p="7px 10px">
        <div style={{ display:'flex', alignItems:'center', gap:'6px', flexWrap:'wrap' }}>
          <Btn variant="primary" size="sm">Export All to Excel</Btn>
          <Btn variant="secondary" size="sm">↺ Refresh Now</Btn>
          <span style={{ fontSize:'0.62rem', color:QEC.sub }}>Auto-refreshes every 30s</span>
          <div style={{ marginLeft:'auto', display:'flex', alignItems:'center', gap:'4px', fontSize:'0.65rem', color:QEC.sub, fontFamily:'monospace' }}>
            <span>Close Time</span>
            <span style={{ color:QEC.text }}>2026-04-16</span>
            <span>→</span>
            <span style={{ color:QEC.text }}>2026-05-16</span>
            <Btn variant="ghost" size="sm">Reset</Btn>
          </div>
        </div>
        <div style={{ display:'flex', gap:'3px', marginTop:'6px', flexWrap:'wrap' }}>
          {HIST_PRESETS.map(p => (
            <button key={p} onClick={() => setPreset(p)} style={{
              padding:'2px 9px', borderRadius:'3px', cursor:'pointer', border:`1px solid ${QEC.border}`,
              background:preset===p?'#1a3060':QEC.panel, color:preset===p?'#93c5fd':QEC.sub, fontSize:'0.62rem', fontWeight:600,
            }}>{p}</button>
          ))}
        </div>
      </Card>

      {/* Card 2: Position History | Order History | Trade History | Live Trades */}
      <Card p="0">
        <div style={{ borderBottom:`1px solid ${QEC.border}`, padding:'0 8px' }}>          <TabBar tabs={HIST_MAIN_TABS} active={mainTab} onChange={setMainTab} variant="line" />
        </div>
        <div style={{ padding:'8px' }}>
          {mainTab === 'positions' && <PositionHistoryTab />}
          {mainTab === 'orders'    && <OrderHistoryTab />}
          {mainTab === 'trades'    && <TradeHistoryTab />}
          {mainTab === 'live'      && <LiveTradesTab />}
        </div>
      </Card>

      {/* Card 3: Pre-Trade Log | Execution Log */}
      <Card p="0">
        <div style={{ borderBottom:`1px solid ${QEC.border}`, padding:'0 8px' }}>
          <TabBar tabs={HIST_LOG_TABS} active={logTab} onChange={setLogTab} variant="line" />
        </div>
        <div style={{ padding:'8px' }}>
          {logTab === 'pretrade'   && <PreTradeTab />}
          {logTab === 'executions' && <ExecutionLogTab />}
        </div>
      </Card>

    </div>
  );
};

Object.assign(window, { HistoryPage });
