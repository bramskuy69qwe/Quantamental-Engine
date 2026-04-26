import React from 'react';
import { QEC, Card, Lbl, Mono, Stat, Badge, Btn, Inp, SecLabel } from './qe-shared.jsx';

const REGIMES = {
  risk_on_trending:   {label:'RISK ON TRENDING',  color:QEC.green,  bg:'#0a2018', mult:1.2},
  risk_on_choppy:     {label:'RISK ON CHOPPY',    color:QEC.cyan,   bg:'#082028', mult:1.0},
  neutral:            {label:'NEUTRAL',           color:QEC.sub,    bg:QEC.panel, mult:1.0},
  risk_off_defensive: {label:'RISK OFF DEFENSIVE',color:QEC.amber,  bg:'#251500', mult:0.7},
  risk_off_panic:     {label:'RISK OFF PANIC',    color:QEC.red,    bg:'#250808', mult:0.4},
};

const HISTORY = [
  {ts:'19:14', ticker:'BTCUSDT', side:'SHORT', entry:'77,638.55', tp:'77,400.00', sl:'78,000.00', regime:'RISK OFF DEFENSIVE', mult:0.7},
  {ts:'10:58', ticker:'BTCUSDT', side:'SHORT', entry:'77,621.05', tp:'77,400.00', sl:'78,000.00', regime:'NEUTRAL',            mult:1.0},
];

export const CalculatorPage = () => {
  const [orderType, setOrderType]   = React.useState('market');
  const [tpslMode, setTpslMode]     = React.useState('price');
  const [regime]                    = React.useState('neutral');
  const [applyMult, setApplyMult]   = React.useState(true);
  const [sizeUnit, setSizeUnit]     = React.useState('notional');
  const [result, setResult]         = React.useState(null);
  const [loading, setLoading]       = React.useState(false);
  const [autoRefresh, setAutoRefresh] = React.useState(false);
  const [ticker, setTicker]         = React.useState('BTCUSDT');
  const [entry, setEntry]           = React.useState('77521.95');
  const [tp, setTp]                 = React.useState('77400');
  const [sl, setSl]                 = React.useState('78000');
  const [tpAmt, setTpAmt]           = React.useState('100');
  const [slAmt, setSlAmt]           = React.useState('100');
  const [modelName, setModelName]   = React.useState('');
  const [modelDesc, setModelDesc]   = React.useState('');

  const rg = REGIMES[regime];
  const entryF = parseFloat(entry);
  const tpF    = parseFloat(tp);
  const slF    = parseFloat(sl);
  const tpPct  = entryF > 0 && tpF > 0 ? Math.abs((tpF - entryF)/entryF*100).toFixed(2)+'%' : '—';
  const slPct  = entryF > 0 && slF > 0 ? Math.abs((slF - entryF)/entryF*100).toFixed(2)+'%' : '—';

  const fmt = (n, d=2) => n == null ? '—' :
    Number(n).toLocaleString(undefined, {minimumFractionDigits:d, maximumFractionDigits:d});
  const fmtExp = (v) => {
    if (v == null) return '—';
    const pct = v * 100;
    return pct >= 1000 ? (pct/1000).toFixed(2)+'k%' : pct.toFixed(2)+'%';
  };
  const mapResult = (d) => ({
    ticker:       d.ticker,
    side:         d.side?.toUpperCase(),
    orderType:    d.order_type?.toUpperCase(),
    avgEntry:     fmt(d.average, 4),
    riskUsdt:     fmt(d.risk_usdt),
    baseSize:     fmt(d.base_size),
    estFill:      fmt(d.est_fill_price, 4),
    depth:        fmt(d.one_percent_depth),
    bestBid:      fmt(d.best_bid, 4),
    bestAsk:      fmt(d.best_ask, 4),
    size:         fmt(d.size, 4),
    notional:     fmt(d.notional),
    tpProfit:     fmt(d.tp_usdt),
    slLoss:       fmt(d.sl_usdt),
    slippage:     (d.est_slippage * 100).toFixed(4) + '%',
    slippageUsdt: fmt(d.est_slippage_usdt),
    netProfit:    fmt(d.est_profit),
    netLoss:      fmt(d.est_loss),
    rr:           fmt(d.est_r, 3),
    exposure:     fmtExp(d.est_exposure),
    fee:          d.fee_rate != null ? (d.fee_rate * 100).toFixed(3) + '%' : '—',
    sector:       d.new_sector_exposure != null
                    ? `${d.ticker} sector: ${fmt(d.new_sector_exposure)} USDT`
                    : '—',
    eligible:     d.eligible,
    atrC:         d.atr_c,
    atrCategory:  d.atr_category,
    atr14:        d.atr14 != null ? fmt(d.atr14, 4) : '—',
    atr100:       d.atr100 != null ? fmt(d.atr100, 4) : '—',
    bids:         (d.bids || []).map(([p,s]) => [fmt(p,4), fmt(s,4)]),
    asks:         (d.asks || []).map(([p,s]) => [fmt(p,4), fmt(s,4)]),
  });

  const handleCalculate = async () => {
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append('ticker', ticker);
      fd.append('average', entry);
      fd.append('sl_price', sl);
      fd.append('tp_price', tp);
      fd.append('tp_amount_pct', tpAmt);
      fd.append('sl_amount_pct', slAmt);
      fd.append('model_name', modelName);
      fd.append('model_desc', modelDesc);
      fd.append('order_type', orderType);
      fd.append('apply_regime_multiplier', applyMult ? '1' : '0');
      const res = await fetch('/api/calculate', { method: 'POST', body: fd });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setResult(mapResult(data));
    } catch (err) {
      console.error('Calculate failed:', err);
    } finally {
      setLoading(false);
    }
  };

  const inpRow = {display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'};

  const OTypeBtn = ({id,label}) => (
    <Btn variant={orderType===id?'primary':'secondary'} size="sm" onClick={() => setOrderType(id)}
      style={{letterSpacing:'0.06em'}}>{label}</Btn>
  );
  const TFBtn = ({id,label}) => (
    <Btn variant={tpslMode===id?'primary':'secondary'} size="sm" onClick={() => setTpslMode(id)}>{label}</Btn>
  );

  const EMPTY_OB = [['—','—'],['—','—'],['—','—'],['—','—'],['—','—']];

  return (
    <div style={{display:'grid',gridTemplateColumns:'minmax(0,1fr) minmax(0,1fr)',gap:'6px',padding:'8px',alignItems:'start'}}>

      {/* ── LEFT: Form ── */}
      <div style={{display:'flex',flexDirection:'column',gap:'6px'}}>

        {/* Recent */}
        <Card p="8px 10px">
          <Lbl style={{marginBottom:'5px'}}>Recent</Lbl>
          <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
            {HISTORY.map((h,i) => (
              <div key={i} onClick={() => {setTicker(h.ticker);setEntry(h.entry.replace(/,/g,''));setTp(h.tp.replace(/,/g,''));setSl(h.sl.replace(/,/g,''));}} style={{
                background:QEC.panel,border:`1px solid ${QEC.border}`,borderRadius:'4px',
                padding:'5px 8px',cursor:'pointer',transition:'border-color 0.1s',
              }}
              onMouseOver={e => e.currentTarget.style.borderColor = QEC.borderFoc}
              onMouseOut={e => e.currentTarget.style.borderColor = QEC.border}>
                <div style={{display:'flex',gap:'6px',alignItems:'center',marginBottom:'2px'}}>
                  <span style={{fontFamily:'monospace',fontSize:'0.7rem',fontWeight:700,color:QEC.blue}}>{h.ticker}</span>
                  <Badge color={QEC.red} bg="#200808">{h.side}</Badge>
                  <span style={{fontSize:'0.62rem',color:QEC.sub,textTransform:'uppercase'}}>MARKET</span>
                  <span style={{marginLeft:'auto',fontSize:'0.62rem',color:QEC.sub,fontFamily:'monospace'}}>{h.ts}</span>
                </div>
                <div style={{fontFamily:'JetBrains Mono,monospace',fontSize:'0.65rem',color:QEC.sub}}>
                  Entry {h.entry} · TP {h.tp} · SL {h.sl}
                </div>
                <div style={{fontSize:'0.6rem',marginTop:'1px'}}>
                  <span style={{color:REGIMES[Object.keys(REGIMES).find(k=>REGIMES[k].label===h.regime)]?.color||QEC.sub}}>{h.regime}</span>
                  <span style={{color:QEC.sub}}> ×{h.mult} size</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Regime + Order */}
        <Card p="8px 10px">
          <div style={{display:'flex',alignItems:'center',gap:'6px',marginBottom:'8px',flexWrap:'wrap'}}>
            <Lbl style={{marginBottom:0}}>Regime:</Lbl>
            <Badge color={rg.color} bg={rg.bg}>{rg.label}</Badge>
            <span style={{fontFamily:'monospace',fontSize:'0.7rem',color:QEC.sub}}>×{rg.mult.toFixed(1)} size</span>
            <label style={{display:'flex',alignItems:'center',gap:'4px',cursor:'pointer',marginLeft:'auto'}}>
              <input type="checkbox" checked={applyMult} onChange={e=>setApplyMult(e.target.checked)} style={{accentColor:QEC.blue}}/>
              <span style={{fontSize:'0.65rem',color:QEC.sub}}>Apply multiplier</span>
            </label>
          </div>
          <div style={{display:'flex',alignItems:'center',gap:'4px',flexWrap:'wrap'}}>
            <Lbl style={{marginBottom:0}}>Order:</Lbl>
            <OTypeBtn id="market" label="MARKET"/>
            <OTypeBtn id="limit"  label="LIMIT"/>
            <OTypeBtn id="stop"   label="STOP"/>
            <Badge color={orderType==='limit' ? QEC.green : QEC.amber}
              bg={orderType==='limit' ? '#072018' : '#251500'}
              style={{marginLeft:'4px'}}>
              {orderType==='limit' ? 'MAKER FEE' : 'TAKER FEE'}
            </Badge>
          </div>
        </Card>

        {/* Ticker + Entry */}
        <Card p="8px 10px">
          <div style={inpRow}>
            <div>
              <Inp label="Ticker" value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())}/>
            </div>
            <div>
              <Lbl>Entry Price {orderType==='market' && <span style={{color:QEC.green,fontSize:'0.6rem',fontWeight:400}}>● LIVE</span>}</Lbl>
              <input readOnly={orderType==='market'} value={entry} onChange={e=>setEntry(e.target.value)}
                style={{background:QEC.panel,border:`1px solid ${orderType==='market'?'#0d3020':QEC.border}`,
                  color:orderType==='market'?QEC.green:QEC.text,borderRadius:'4px',padding:'5px 8px',
                  width:'100%',height:'30px',fontFamily:'JetBrains Mono,monospace',fontSize:'0.8rem',
                  outline:'none',boxSizing:'border-box'}}/>
            </div>
          </div>
        </Card>

        {/* TP/SL */}
        <Card p="8px 10px">
          <div style={{display:'flex',alignItems:'center',gap:'4px',marginBottom:'7px'}}>
            <Lbl style={{marginBottom:0}}>TP/SL:</Lbl>
            <TFBtn id="price" label="BY PRICE"/>
            <TFBtn id="pct"   label="BY %"/>
          </div>
          <div style={inpRow}>
            <Inp label="TP Price" value={tp} onChange={e=>setTp(e.target.value)} style={{color:QEC.green}}/>
            <Inp label="SL Price" value={sl} onChange={e=>setSl(e.target.value)} style={{color:QEC.red}}/>
          </div>
          <div style={{fontFamily:'monospace',fontSize:'0.65rem',color:QEC.sub,marginTop:'4px'}}>
            TP: <span style={{color:QEC.green}}>{tpPct}</span>
            &nbsp;|&nbsp;
            SL: <span style={{color:QEC.red}}>{slPct}</span>
          </div>
        </Card>

        {/* Amounts + Model */}
        <Card p="8px 10px">
          <div style={inpRow}>
            <Inp label="TP Amount (%)" value={tpAmt} onChange={e=>setTpAmt(e.target.value)} type="number"/>
            <Inp label="SL Amount (%)" value={slAmt} onChange={e=>setSlAmt(e.target.value)} type="number"/>
            <Inp label="Model Name (optional)" value={modelName} onChange={e=>setModelName(e.target.value)} placeholder="e.g. MA-Cross-V2"/>
            <Inp label="Model Description"     value={modelDesc} onChange={e=>setModelDesc(e.target.value)} placeholder="optional notes"/>
          </div>
          <div style={{display:'flex',gap:'6px',alignItems:'center',marginTop:'8px'}}>
            <Btn variant="primary" size="md" onClick={handleCalculate} disabled={loading}>
              {loading ? 'Calculating…' : 'Calculate'}
            </Btn>
            <Btn variant="secondary" size="md" onClick={() => {setResult(null);setTicker('');setEntry('');setTp('');setSl('');}}>Clear</Btn>
            <span style={{fontSize:'0.65rem',color:QEC.sub,marginLeft:'4px'}}>Risk/trade: <strong style={{color:QEC.text}}>1.00%</strong></span>
          </div>
        </Card>

        {/* Setup Summary */}
        <Card p="8px 10px">
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'7px',flexWrap:'wrap',gap:'4px'}}>
            <SecLabel style={{marginBottom:0}}>Setup Summary</SecLabel>
            <div style={{display:'flex',gap:'3px'}}>
              {['NOTIONAL','CONTRACTS','LOT'].map(u => (
                <Btn key={u} variant={sizeUnit===u.toLowerCase()?'primary':'secondary'} size="sm"
                  onClick={() => setSizeUnit(u.toLowerCase())} style={{fontSize:'0.6rem',letterSpacing:'0.05em'}}>{u}</Btn>
              ))}
            </div>
          </div>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'5px'}}>
            {[
              {lbl:'Symbol',     val: result?.ticker || ticker || '—'},
              {lbl:'Entry Price',val: result?.avgEntry || (entry ? parseFloat(entry).toLocaleString() : '—')},
              {lbl:'TP Price',   val: result?.tpProfit ? tp : (tp || '—'), color:QEC.green},
              {lbl:'SL Price',   val: result?.slLoss   ? sl : (sl || '—'), color:QEC.red},
            ].map(({lbl,val,color}) => (
              <div key={lbl}>
                <Lbl>{lbl}</Lbl>
                <input readOnly value={val} onClick={e=>e.target.select()}
                  style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:color||QEC.text,
                    borderRadius:'4px',padding:'4px 7px',width:'100%',height:'28px',
                    fontFamily:'JetBrains Mono,monospace',fontSize:'0.78rem',
                    cursor:'text',outline:'none',boxSizing:'border-box'}}/>
              </div>
            ))}
            <div style={{gridColumn:'1/-1'}}>
              <Lbl>Size ({sizeUnit.toUpperCase()})</Lbl>
              <input readOnly value={result ? (sizeUnit==='contracts'?result.size:result.notional) : '—'}
                onClick={e=>e.target.select()}
                style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.blue,
                  borderRadius:'4px',padding:'4px 7px',width:'100%',height:'28px',
                  fontFamily:'JetBrains Mono,monospace',fontSize:'0.78rem',
                  cursor:'text',outline:'none',boxSizing:'border-box',fontWeight:700}}/>
            </div>
          </div>
          <div style={{marginTop:'6px'}}>
            <Btn variant="ghost" size="sm">⇧ Copy All</Btn>
          </div>
        </Card>
      </div>

      {/* ── RIGHT: Results ── */}
      <div style={{display:'flex',flexDirection:'column',gap:'6px'}}>

        {result && (
          <Card p="6px 10px">
            <div style={{display:'flex',alignItems:'center',gap:'4px',flexWrap:'wrap'}}>
              <span style={{fontSize:'0.62rem',color:QEC.sub}}>AUTO-REFRESH:</span>
              {[1,5,10,30].map(s => (
                <Btn key={s} size="sm" variant={autoRefresh===s?'primary':'secondary'}
                  onClick={() => setAutoRefresh(autoRefresh===s?false:s)}
                  style={{fontSize:'0.6rem',minWidth:'28px'}}>{s}s</Btn>
              ))}
              <Btn size="sm" variant={autoRefresh===false?'secondary':'ghost'} style={{fontSize:'0.6rem'}}>⏸</Btn>
            </div>
          </Card>
        )}

        {/* Volatility + main metrics */}
        <Card p="8px 10px">
          <div style={{display:'flex',alignItems:'center',gap:'8px',marginBottom:'8px',flexWrap:'wrap'}}>
            <SecLabel style={{marginBottom:0}}>Volatility (ATR_C)</SecLabel>
            {result && (
              <>
                <Mono size="0.88rem">{result.atrC ?? '—'}</Mono>
                <Badge color={QEC.amber} bg="#251500">{result.atrCategory ?? 'UNKNOWN'}</Badge>
                <span style={{fontSize:'0.62rem',color:QEC.sub,fontFamily:'monospace'}}>ATR(100,4h): {result.atr100} / ATR(14,4h): {result.atr14}</span>
              </>
            )}
          </div>

          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px 12px'}}>
            {[
              {label:'Ticker',           value:result?.ticker || '—'},
              {label:'Side',             value:result?.side   || '—', color: result?.side==='LONG'?QEC.green:result?.side==='SHORT'?QEC.red:QEC.text},
              {label:'Order Type',       value:result?.orderType  || '—'},
              {label:'Avg Entry',        value:result?.avgEntry   || '—'},
              {label:'Risk USDT',        value:result?.riskUsdt   || '—'},
              {label:'Base Size (USDT)', value:result?.baseSize   || '—'},
              {label:'Est. Fill Price',  value:result?.estFill    || '—'},
              {label:'1% Depth (USDT)', value:result?.depth      || '—'},
            ].map(s => <Stat key={s.label} {...s}/>)}
            <div style={{gridColumn:'1/-1'}}>
              <Lbl>Best Bid / Ask</Lbl>
              <Mono size="0.88rem">
                {result ? <><span style={{color:QEC.green}}>{result.bestBid}</span> / <span style={{color:QEC.red}}>{result.bestAsk}</span></> : '—'}
              </Mono>
            </div>
          </div>
        </Card>

        {/* Calculated Position */}
        <Card p="8px 10px">
          <div style={{display:'flex',alignItems:'center',gap:'8px',marginBottom:'8px'}}>
            <SecLabel style={{marginBottom:0}}>Calculated Position</SecLabel>
            {result && <Badge color={result.eligible?QEC.green:QEC.amber} bg={result.eligible?'#072018':'#251500'}>{result.eligible?'ELIGIBLE':'INELIGIBLE'}</Badge>}
          </div>
          {result ? (
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px 12px'}}>
              <div><Lbl>_size (contracts)</Lbl><Mono size="1.4rem">{result.size}</Mono></div>
              <Stat label="Notional / est_size (USDT)" value={result.notional}/>
              <Stat label="TP → USDT profit" value={result.tpProfit} color={QEC.green}/>
              <Stat label="SL → USDT loss"   value={result.slLoss}   color={QEC.red}/>
            </div>
          ) : (
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px 12px'}}>
              {['_size (contracts)','Notional / est_size (USDT)','TP → USDT profit','SL → USDT loss'].map(l =>
                <Stat key={l} label={l} value="—"/>)}
            </div>
          )}
        </Card>

        {/* Estimations */}
        <Card p="8px 10px">
          <SecLabel>Estimations {result && <span style={{color:QEC.muted,textTransform:'none',letterSpacing:0,fontSize:'0.58rem'}}>— slippage estimates are indicative only.</span>}</SecLabel>
          <div style={{display:'grid',gridTemplateColumns:'repeat(3,1fr)',gap:'8px 12px'}}>
            {[
              {label:'Est. Slippage',       value:result?.slippage     || '—'},
              {label:'Est. Slippage USDT',  value:result?.slippageUsdt || '—'},
              {label:'Est. Net Profit',     value:result?.netProfit    || '—', color:result?QEC.green:null},
              {label:'Est. Net Loss',       value:result?.netLoss      || '—', color:result?QEC.red:null},
              {label:'Est. R:R',            value:result?.rr           || '—', color:result?QEC.amber:null},
              {label:'Est. Portfolio Exp.', value:result?.exposure     || '—'},
              {label:'Fee (2×)',            value:result?.fee          || '—'},
            ].map(s => <Stat key={s.label} {...s}/>)}
          </div>
        </Card>

        {/* Sector Exposure */}
        <Card p="8px 10px">
          <SecLabel>Correlated Sector Exposure</SecLabel>
          {result ? (
            <div style={{fontSize:'0.75rem',color:QEC.amber}}>{result.sector}</div>
          ) : (
            <div style={{fontSize:'0.72rem',color:QEC.sub}}>—</div>
          )}
        </Card>

        {/* Live Orderbook */}
        <Card p="8px 10px">
          <SecLabel>Live Orderbook {result && <span style={{color:QEC.sub,textTransform:'none',letterSpacing:0}}>— {result.ticker}</span>}</SecLabel>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8px'}}>
            <div>
              <div style={{fontSize:'0.65rem',fontWeight:700,color:QEC.green,marginBottom:'4px'}}>BIDS</div>
              {(result?.bids?.length ? result.bids : EMPTY_OB).map(([p,s],i) => (
                <div key={i} style={{display:'flex',justifyContent:'space-between',fontFamily:'JetBrains Mono,monospace',fontSize:'0.68rem',marginBottom:'2px'}}>
                  <span style={{color:result?.bids?.length?QEC.green:QEC.muted}}>{p}</span>
                  <span style={{color:result?.bids?.length?QEC.sub:QEC.muted}}>{s}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{fontSize:'0.65rem',fontWeight:700,color:QEC.red,marginBottom:'4px'}}>ASKS</div>
              {(result?.asks?.length ? result.asks : EMPTY_OB).map(([p,s],i) => (
                <div key={i} style={{display:'flex',justifyContent:'space-between',fontFamily:'JetBrains Mono,monospace',fontSize:'0.68rem',marginBottom:'2px'}}>
                  <span style={{color:result?.asks?.length?QEC.red:QEC.muted}}>{p}</span>
                  <span style={{color:result?.asks?.length?QEC.sub:QEC.muted}}>{s}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Log button spanning both cols */}
      <div style={{gridColumn:'1/-1'}}>
        <Btn variant="secondary" size="md">▼ Log Execution / Trade Close</Btn>
      </div>
    </div>
  );
};
