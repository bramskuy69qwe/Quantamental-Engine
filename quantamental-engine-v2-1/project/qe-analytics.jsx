// QE Analytics Page
const ANAL_TABS = [
  ['overview','Overview'],['equity','Equity Curve'],['calendar','Calendar PnL'],
  ['pairs','Traded Pairs'],['excursions','MFE / MAE'],['rmultiples','R-Multiples'],
  ['risk','Risk Metrics'],['live','Funding'],['beta','Beta Exposure'],
];

const EQ_CURVE = mockEquityData(60, 82.2, 6);

// ── Overview ──────────────────────────────────────────────────────────────
const AnalOverview = () => (
  <div style={{display:'flex',flexDirection:'column',gap:'6px'}}>
    <Card>
      <SecLabel>Volume &amp; Activity — April 2026</SecLabel>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(130px,1fr))',gap:'8px 16px'}}>
        <Stat label="Monthly Trading Volume" value="$2,168"/>
        <Stat label="Est. Broker Fee"        value="$2.54"/>
        <Stat label="No. of Longs"           value="19"/>
        <Stat label="No. of Shorts"          value="12"/>
        <div><Lbl>Most Traded Pairs</Lbl><Mono size="0.78rem">STOUSDT, JCTUSDT, AIOTUSDT, STRENUSDT, PUFFERUSDT</Mono></div>
      </div>
    </Card>

    <Card>
      <SecLabel>Equity &amp; PnL</SecLabel>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(120px,1fr))',gap:'8px 16px'}}>
        <Stat label="Initial Equity"    value="$93.38"/>
        <Stat label="Monthly Total PnL" value="-$11.18" color={QEC.red}/>
        <Stat label="Monthly PnL %"     value="-11.97%" color={QEC.red}/>
        <Stat label="Final Equity"      value="$82.20"/>
        <Stat label="Daily Avg PnL"     value="-$0.93"  color={QEC.red}/>
        <Stat label="Daily Avg PnL %"   value="-0.997%" color={QEC.red}/>
      </div>
    </Card>

    <Card>
      <SecLabel>Trade Statistics</SecLabel>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(120px,1fr))',gap:'8px 16px'}}>
        <Stat label="Total Trades"       value="31"/>
        <Stat label="Winning Trades"     value="12" color={QEC.green}/>
        <Stat label="Losing Trades"      value="19" color={QEC.red}/>
        <Stat label="Win Rate"           value="38.7%"/>
        <Stat label="Average Profit"     value="1.23"  color={QEC.green}/>
        <Stat label="Average Loss"       value="-1.02" color={QEC.red}/>
        <Stat label="Avg Risk:Reward"    value="1.20R"/>
        <Stat label="Biggest Profit"     value="7.41"  color={QEC.green}/>
        <Stat label="Biggest Loss"       value="-4.20" color={QEC.red}/>
        <Stat label="Maximum Drawdown"   value="12.24%" color={QEC.red}/>
      </div>
    </Card>

    <Card>
      <SecLabel>Cash &amp; Cumulative</SecLabel>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(120px,1fr))',gap:'8px 16px'}}>
        <Stat label="Deposit"         value="$0.00"/>
        <Stat label="Withdrawal"      value="$0.00"/>
        <Stat label="Cumulative PnL"  value="-$4.47" color={QEC.red}/>
        <Stat label="Cumulative PnL %" value="0.00%"/>
      </div>
    </Card>

    <Card>
      <SecLabel>Performance Ratios</SecLabel>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(120px,1fr))',gap:'8px 16px'}}>
        <Stat label="Sharpe"         value="—" color={QEC.sub}/>
        <Stat label="Sharpe (MFE)"   value="9.50"/>
        <Stat label="Sortino"        value="—" color={QEC.sub}/>
        <Stat label="Sortino (MAE)"  value="—" color={QEC.sub}/>
        <Stat label="Profit Factor"  value="—" color={QEC.sub}/>
        <Stat label="Expectancy ($)" value="—" color={QEC.sub}/>
      </div>
    </Card>
  </div>
);

// ── Equity Curve ──────────────────────────────────────────────────────────
const AnalEquity = () => {
  const [tf, setTf] = React.useState('1M');
  const tfs = ['1W','2W','1M','3M','6M','1Y','All'];
  return (
    <Card>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'8px',flexWrap:'wrap',gap:'4px'}}>
        <div>
          <SecLabel style={{marginBottom:'2px'}}>Equity Curve — Last 1M</SecLabel>
          <div style={{fontFamily:'JetBrains Mono,monospace',fontSize:'0.65rem',color:QEC.sub,display:'flex',gap:'8px',flexWrap:'wrap'}}>
            <span>O <span style={{color:QEC.text}}>$82.20</span></span>
            <span>H <span style={{color:QEC.green}}>$82.20</span></span>
            <span>L <span style={{color:QEC.red}}>$82.20</span></span>
            <span>C <span style={{color:QEC.text}}>$82.20</span></span>
            <span>Chg <span style={{color:QEC.text}}>+$0.00 (+0.00%)</span></span>
          </div>
        </div>
        <div style={{display:'flex',gap:'3px',alignItems:'center'}}>
          {tfs.map(t => (
            <button key={t} onClick={()=>setTf(t)} style={{
              padding:'2px 8px',border:'none',cursor:'pointer',borderRadius:'3px',
              background:tf===t?QEC.blue:QEC.panel,
              color:tf===t?'#fff':QEC.sub,fontSize:'0.62rem',fontWeight:700,
            }}>{t}</button>
          ))}
        </div>
      </div>
      <Sparkline data={EQ_CURVE} color={QEC.green} height={120}/>
      <div style={{display:'flex',justifyContent:'space-between',fontSize:'0.6rem',color:QEC.muted,marginTop:'4px',fontFamily:'monospace'}}>
        <span>Mar 28</span><span>Apr 2</span><span>Apr 7</span><span>Apr 12</span><span>Apr 18</span><span>Apr 25</span>
      </div>
    </Card>
  );
};

// ── Calendar PnL ──────────────────────────────────────────────────────────
const DAY_DATA = {3:-10.93,1:-0.17,2:0.68,4:-0.87,25:0.00};
const AnalCalendar = () => {
  const days = ['MON','TUE','WED','THU','FRI','SAT','SUN'];
  // April 2026: starts on Wednesday (index 2)
  const daysInMonth = 30;
  const startOffset = 2;
  const cells = [];
  for (let i = 0; i < startOffset; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const getColor = (d) => {
    if (!d || !DAY_DATA[d]) return {bg:QEC.muted+'50', text:QEC.sub};
    const v = DAY_DATA[d];
    if (v > 0) return {bg:`${QEC.green}30`, text:QEC.green};
    if (v < 0) {
      const intensity = Math.min(1, Math.abs(v) / 12);
      return {bg:`rgba(232,53,53,${0.15 + intensity * 0.35})`, text:QEC.red};
    }
    return {bg:QEC.muted+'50', text:QEC.text};
  };

  return (
    <Card>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'12px'}}>
        <Btn variant="ghost" size="sm">‹ Prev</Btn>
        <Mono size="0.9rem">April 2026</Mono>
        <Btn variant="ghost" size="sm">Next ›</Btn>
      </div>

      <div style={{display:'grid',gridTemplateColumns:'repeat(7,1fr)',gap:'3px',marginBottom:'3px'}}>
        {days.map(d => (
          <div key={d} style={{textAlign:'center',fontSize:'0.6rem',color:QEC.sub,fontWeight:700,letterSpacing:'0.05em',padding:'2px 0'}}>{d}</div>
        ))}
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(7,1fr)',gap:'3px'}}>
        {cells.map((d,i) => {
          const {bg, text} = getColor(d);
          const v = d ? DAY_DATA[d] : null;
          return (
            <div key={i} style={{
              background: d ? bg : 'transparent',
              borderRadius:'4px',
              padding:'6px 5px',
              minHeight:'52px',
              position:'relative',
            }}>
              {d && <>
                <div style={{fontSize:'0.6rem',color:text,fontWeight:700}}>{d}</div>
                <div style={{fontSize:'0.65rem',color:text,fontFamily:'JetBrains Mono,monospace',marginTop:'2px'}}>
                  {v != null ? `$${v.toFixed(2)}` : ''}
                </div>
              </>}
            </div>
          );
        })}
      </div>

      <Divider/>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(110px,1fr))',gap:'8px'}}>
        <Stat label="Trading Days" value="12"/>
        <Stat label="Avg Daily PnL" value="-$0.93" color={QEC.red}/>
        <Stat label="Best Day"      value="-$0.00" color={QEC.sub}/>
        <Stat label="Worst Day"     value="-$10.93" color={QEC.red}/>
      </div>
    </Card>
  );
};

// ── Traded Pairs ──────────────────────────────────────────────────────────
const PAIRS = [
  {sym:'STOUSDT', trades:22,longs:10,shorts:12,pnlL:-6.63,pnlS:1.66,pnlT:-4.98,wr:'31.8%',avgW:2.04,avgL:-1.28,fees:1.76,vol:1357},
  {sym:'JCTUSDT', trades:4, longs:4, shorts:0, pnlL:0.11, pnlS:null,pnlT:0.11, wr:'50.0%',avgW:0.09,avgL:-0.04,fees:0.05,vol:30},
  {sym:'AIOTUSDT',trades:2, longs:2, shorts:0, pnlL:0.21, pnlS:null,pnlT:0.21, wr:'100%', avgW:0.11,avgL:null,  fees:0.06,vol:70},
  {sym:'STRENUSDT',trades:1,longs:1, shorts:0, pnlL:-0.11,pnlS:null,pnlT:-0.11,wr:'0.0%', avgW:null, avgL:-0.11,fees:0.06,vol:92},
  {sym:'PUFFERUSDT',trades:1,longs:1,shorts:0, pnlL:-0.02,pnlS:null,pnlT:-0.02,wr:'0.0%', avgW:null, avgL:-0.02,fees:0.08,vol:1},
  {sym:'BTCUSDT',  trades:1,longs:1, shorts:0, pnlL:0.08, pnlS:null,pnlT:0.08, wr:'100%', avgW:0.08,avgL:null,  fees:0.60,vol:602},
];
const TH2 = ({c}) => <th style={{color:QEC.sub,fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.07em',textTransform:'uppercase',padding:'5px 8px',borderBottom:`1px solid ${QEC.border}`,textAlign:'left',whiteSpace:'nowrap'}}>{c}</th>;
const TD2 = ({v,color,style={}}) => <td style={{padding:'5px 8px',borderBottom:`1px solid ${QEC.border}`,fontFamily:'JetBrains Mono,monospace',fontSize:'0.72rem',color:color||QEC.text,whiteSpace:'nowrap',...style}}>{v}</td>;

const AnalPairs = () => (
  <Card>
    <SecLabel>Traded Pairs — April 2026 (6 symbols)</SecLabel>
    <div style={{overflowX:'auto'}}>
      <table style={{width:'100%',borderCollapse:'collapse'}}>
        <thead><tr>
          {['Symbol','Trades','Longs','Shorts','PnL (Long)','PnL (Short)','PnL Total','Win Rate','Avg Win','Avg Loss','Fees','Volume'].map(h =>
            <TH2 key={h} c={h}/>
          )}
        </tr></thead>
        <tbody>
          {PAIRS.map((r,i) => (
            <tr key={i}
              onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
              onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background='transparent')}>
              <TD2 v={r.sym} color={QEC.blue} style={{fontWeight:700}}/>
              <TD2 v={r.trades}/>
              <TD2 v={r.longs}  color={QEC.green}/>
              <TD2 v={r.shorts} color={r.shorts>0?QEC.red:QEC.sub}/>
              <TD2 v={r.pnlL!=null?(r.pnlL>=0?'+':'')+r.pnlL.toFixed(2):'—'} color={r.pnlL!=null?(r.pnlL>=0?QEC.green:QEC.red):QEC.sub}/>
              <TD2 v={r.pnlS!=null?(r.pnlS>=0?'+':'')+r.pnlS.toFixed(2):'—'} color={r.pnlS!=null?(r.pnlS>=0?QEC.green:QEC.red):QEC.sub}/>
              <TD2 v={(r.pnlT>=0?'+':'')+r.pnlT.toFixed(2)} color={r.pnlT>=0?QEC.green:QEC.red} style={{fontWeight:700}}/>
              <TD2 v={r.wr} color={parseFloat(r.wr)>=50?QEC.green:QEC.red}/>
              <TD2 v={r.avgW!=null?r.avgW.toFixed(2):'—'} color={QEC.green}/>
              <TD2 v={r.avgL!=null?r.avgL.toFixed(2):'—'} color={r.avgL!=null?QEC.red:QEC.sub}/>
              <TD2 v={r.fees.toFixed(2)} color={QEC.sub}/>
              <TD2 v={r.vol.toLocaleString()}/>
            </tr>
          ))}
          <tr style={{background:QEC.panel}}>
            <TD2 v="TOTAL" style={{fontWeight:700}}/>
            <TD2 v="31"/>
            {['','','','',''].map((_,i)=><TD2 key={i} v=""/>)}
            <TD2 v="-4.70" color={QEC.red} style={{fontWeight:700}}/>
            {['',''].map((_,i)=><TD2 key={i} v=""/>)}
            <TD2 v="2.54" color={QEC.sub}/>
            <TD2 v="2,168"/>
          </tr>
        </tbody>
      </table>
    </div>
  </Card>
);

// ── MFE/MAE ───────────────────────────────────────────────────────────────
const MFE_DATA = [
  {mfe:0.20,mae:-0.18,pnl:0.17,profitable:true},{mfe:0.02,mae:-0.03,pnl:-0.02,profitable:false},
  {mfe:0.04,mae:-0.09,pnl:-0.06,profitable:false},{mfe:0.03,mae:0.00,pnl:0.01,profitable:true},
  {mfe:0.00,mae:-0.02,pnl:-0.02,profitable:false},{mfe:0.08,mae:0.00,pnl:0.08,profitable:true},
  {mfe:0.15,mae:-0.05,pnl:0.11,profitable:true},{mfe:0.31,mae:-0.07,pnl:0.10,profitable:true},
  {mfe:7.60,mae:-3.58,pnl:7.41,profitable:true},{mfe:2.56,mae:-3.01,pnl:2.20,profitable:true},
  {mfe:2.88,mae:-5.61,pnl:-4.20,profitable:false},{mfe:1.12,mae:-1.46,pnl:-0.92,profitable:false},
  {mfe:3.14,mae:-1.17,pnl:-0.56,profitable:false},{mfe:2.04,mae:-1.05,pnl:-0.68,profitable:true},
];
const AnalMFEMAE = () => {
  const W=600, H=160;
  const mfeVals = MFE_DATA.map(d=>d.mfe), maeVals = MFE_DATA.map(d=>Math.abs(d.mae));
  const maxMFE = Math.max(...mfeVals,1), maxMAE = Math.max(...maeVals,1);
  return (
    <Card>
      <SecLabel>MFE / MAE Excursions — April 2026</SecLabel>
      <svg viewBox={`0 0 ${W} ${H}`} style={{width:'100%',height:`${H}px`,background:QEC.panel,borderRadius:'4px',marginBottom:'8px'}}>
        {/* Grid */}
        {[0,0.25,0.5,0.75,1].map(t => {
          const y = t * H;
          return <line key={t} x1="0" y1={y} x2={W} y2={y} stroke={QEC.border} strokeWidth="0.5"/>;
        })}
        {/* X axis */}
        <line x1="0" y1={H/2} x2={W} y2={H/2} stroke={QEC.border} strokeWidth="1"/>
        {/* Dots */}
        {MFE_DATA.map((d,i) => {
          const x = (d.mfe / maxMFE) * (W - 40) + 20;
          const y = H/2 - (Math.abs(d.mae) / maxMAE) * (H/2 - 10) * Math.sign(-d.mae || -1);
          return (
            <circle key={i} cx={x} cy={Math.max(8, Math.min(H-8, y))} r="5"
              fill={d.profitable ? QEC.green : QEC.red} opacity="0.8"/>
          );
        })}
        <text x="10" y={H-4} fill={QEC.sub} fontSize="9">MFE ($)</text>
        <text x="4"  y="12"  fill={QEC.sub} fontSize="9" writingMode="vertical-rl">MAE</text>
        <text x={W-50} y={H-4} fill={QEC.sub} fontSize="9">$15</text>
      </svg>
      <div style={{display:'flex',gap:'16px',marginBottom:'8px',fontSize:'0.65rem'}}>
        <span><span style={{display:'inline-block',width:'8px',height:'8px',borderRadius:'50%',background:QEC.green,marginRight:'4px'}}></span>Profitable</span>
        <span><span style={{display:'inline-block',width:'8px',height:'8px',borderRadius:'50%',background:QEC.red,marginRight:'4px'}}></span>Loss</span>
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(120px,1fr))',gap:'8px',marginBottom:'8px'}}>
        <Stat label="Avg MFE"      value="$2.52" color={QEC.green}/>
        <Stat label="Avg |MAE|"    value="$1.68" color={QEC.red}/>
        <Stat label="Avg MF-Ratio" value="2.03"/>
        <Stat label="MFE > 2× MAE" value="29.0%"/>
      </div>
    </Card>
  );
};

// ── Empty state for sparse tabs ───────────────────────────────────────────
const EmptyTab = ({msg}) => (
  <Card>
    <div style={{textAlign:'center',padding:'32px',color:QEC.sub,fontSize:'0.8rem'}}>{msg}</div>
  </Card>
);

// ── Main Analytics component ──────────────────────────────────────────────
const AnalyticsPage = ({tabStyle='line'}) => {
  const [tab, setTab]     = React.useState('overview');
  const [month, setMonth] = React.useState('2026-04');
  const [allTime, setAllTime] = React.useState(false);

  const shiftMonth = d => {
    const [y,m] = month.split('-').map(Number);
    const dt = new Date(y, m-1+d, 1);
    setMonth(dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0'));
    setAllTime(false);
  };

  const content = {
    overview:   <AnalOverview/>,
    equity:     <AnalEquity/>,
    calendar:   <AnalCalendar/>,
    pairs:      <AnalPairs/>,
    excursions: <AnalMFEMAE/>,
    rmultiples: <EmptyTab msg="No R multiple data for this period. R multiples come from the manual Trade History log (individual_realized_r field)."/>,
    risk:       <EmptyTab msg="Insufficient data (need ≥ 20 trading days). Currently have 11 days."/>,
    live:       <EmptyTab msg="No open positions — no funding exposure."/>,
    beta:       <EmptyTab msg="No open positions."/>,
  }[tab] || null;

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'6px',padding:'8px'}}>
      {/* Header */}
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:'6px'}}>
    
        <div style={{display:'flex',alignItems:'center',gap:'4px'}}>
          <Btn variant="ghost" size="sm" onClick={()=>shiftMonth(-1)}>‹</Btn>
          <Mono size="0.85rem" style={{minWidth:'70px',textAlign:'center'}}>{allTime?'All Time':month}</Mono>
          <Btn variant="ghost" size="sm" onClick={()=>shiftMonth(1)}>›</Btn>
          {['This Month','Last Month','All Time'].map((l,i) => (
            <button key={l} onClick={()=>{if(i===2){setAllTime(true);}else{setAllTime(false);const now=new Date();const d=new Date(now.getFullYear(),now.getMonth()+(-i),1);setMonth(d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0'));}}} style={{
              padding:'3px 8px',border:`1px solid ${QEC.border}`,borderRadius:'3px',cursor:'pointer',
              background:QEC.panel,color:QEC.sub,fontSize:'0.65rem',fontWeight:600,
            }}>{l}</button>
          ))}
        </div>
      </div>

      {/* Tab bar */}
      <TabBar tabs={ANAL_TABS} active={tab} onChange={setTab}
        variant={tabStyle}
        style={{marginBottom:'6px'}}/>

      {content}
    </div>
  );
};

Object.assign(window, {AnalyticsPage});
