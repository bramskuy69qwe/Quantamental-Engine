// QE App root + Tweaks panel

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "density": "compact",
  "numSize": "medium",
  "theme": "navy",
  "tabStyle": "line"
}/*EDITMODE-END*/;

const DENSITY_PAD = {compact:'8px',normal:'12px',spacious:'18px'};
const NUM_SIZE    = {small:'0.82rem',medium:'0.92rem',large:'1.05rem'};

const THEME_VARS = {
  navy:    {bg:'#07080f',card:'#0c1118',panel:'#101826',border:'#18253a',blue:'#3c8ff5'},
  charcoal:{bg:'#080808',card:'#101010',panel:'#181818',border:'#282828',blue:'#4a9eff'},
  deep:    {bg:'#04060d',card:'#080e1a',panel:'#0c1424',border:'#122030',blue:'#2a7fff'},
};

const PAGE_META = {
  dashboard:  {name:'Dashboard',  sub:'Live overview · equity · risk · positions'},
  calculator: {name:'Calculator', sub:'Position sizing · TP/SL · order preview'},
  history:    {name:'History',    sub:'Trade log · pre-trade journal'},
  params:     {name:'Parameters', sub:'Risk limits · account management'},
  analytics:  {name:'Analytics',  sub:'Portfolio performance · equity curve · pairs'},
  backtest:   {name:'Backtest',   sub:'Strategy simulation · model management · QT import'},
  regime:     {name:'Regime',     sub:'Macro classifier · signals · timeline'},
};

const PageHeader = ({page}) => {
  const meta = PAGE_META[page] || {name: page, sub: ''};
  return (
    <div style={{
      background: QEC.card,
      borderBottom: `1px solid ${QEC.border}`,
      padding: '6px 10px',
      display: 'flex',
      alignItems: 'baseline',
      gap: '10px',
      position: 'sticky',
      top: '50px',
      zIndex: 190,
      flexShrink: 0,
    }}>
      <span style={{
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: '0.82rem',
        fontWeight: 700,
        color: QEC.text,
        letterSpacing: '0.02em',
      }}>{meta.name}</span>
      <span style={{
        fontSize: '0.62rem',
        color: QEC.muted,
        fontFamily: 'var(--font-ui)',
        letterSpacing: '0.02em',
      }}>{meta.sub}</span>
    </div>
  );
};
// ── Backtest Page ────────────────────────────────────────────────────────
const MOCK_SESSIONS = [
  {id:3, name:'EMA Trend 4H — Apr 2026', type:'native',   status:'completed', date_from:'2026-01-01', date_to:'2026-04-01', summary:{total_return_pct:0.142, max_drawdown:0.054, total_trades:87, r_stats:{win_rate:0.517, expectancy:0.31, profit_factor:1.48}}},
  {id:2, name:'QT Micro Import — Mar',   type:'microstructure', status:'completed', date_from:'2026-03-01', date_to:'2026-03-31', summary:{total_return_pct:-0.031, max_drawdown:0.089, total_trades:23, r_stats:{win_rate:0.391, expectancy:-0.18, profit_factor:0.72}}},
  {id:1, name:'EMA Backtest v1',         type:'native',   status:'failed',    date_from:'2025-12-01', date_to:'2026-01-01', summary:{}},
];

const BT_PANELS = [
  ['run','Run'],['fetch','Fetch Data'],['qt','QT Import'],['models','Models'],
];

const BacktestPage = () => {
  const [panel, setPanel]   = React.useState('run');
  const [sessions]          = React.useState(MOCK_SESSIONS);
  const [selSession, setSel] = React.useState(null);

  const statusColor = {completed:QEC.green, running:QEC.amber, failed:QEC.red, pending:QEC.sub};

  return (
    <div style={{display:'grid',gridTemplateColumns:'minmax(270px,1fr) 2fr',gap:'6px',padding:'8px',alignItems:'start'}}>

      {/* Left: config panels */}
      <div style={{display:'flex',flexDirection:'column',gap:'6px'}}>
        {/* Tab switcher */}
        <div style={{display:'flex',borderBottom:`1px solid ${QEC.border}`,marginBottom:0}}>
          {BT_PANELS.map(([id,lbl]) => (
            <button key={id} onClick={()=>setPanel(id)} style={{
              padding:'6px 12px',border:'none',cursor:'pointer',background:'transparent',
              color: panel===id ? QEC.text : QEC.muted,
              fontWeight: panel===id ? 700 : 500,
              fontSize:'0.7rem',fontFamily:"'Space Grotesk',sans-serif",
              borderBottom: panel===id ? `2px solid ${QEC.blue}` : '2px solid transparent',
              marginBottom:'-1px',
            }}>{lbl}</button>
          ))}
        </div>

        {/* Run panel */}
        {panel==='run' && (
          <Card p="8px 10px">
            <SecLabel>Strategy Config</SecLabel>
            <div style={{display:'flex',flexDirection:'column',gap:'7px'}}>
              <Inp label="Name" defaultValue="Backtest 2026-05-04"/>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Inp label="Date From" type="date" defaultValue="2026-02-01"/>
                <Inp label="Date To"   type="date" defaultValue="2026-05-04"/>
              </div>
              <Inp label="Symbols" defaultValue="BTCUSDT,ETHUSDT"/>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Sel label="Timeframe"><option>1h</option><option selected>4h</option><option>1d</option></Sel>
                <Inp label="Initial Equity ($)" type="number" defaultValue="10000"/>
              </div>
              <div style={{height:'1px',background:QEC.border}}/>
              <span style={{fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',color:QEC.sub}}>Entry Signals</span>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Inp label="EMA Fast" type="number" defaultValue="20"/>
                <Inp label="EMA Slow" type="number" defaultValue="50"/>
                <Inp label="ATR SL Mult" type="number" defaultValue="1.5"/>
                <Inp label="ATR TP Mult" type="number" defaultValue="3.0"/>
                <Inp label="Min ATR-C" type="number" defaultValue="0.2"/>
                <Sel label="Direction"><option>Both</option><option>Long only</option><option>Short only</option></Sel>
              </div>
              <div style={{height:'1px',background:QEC.border}}/>
              <span style={{fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.08em',textTransform:'uppercase',color:QEC.sub}}>Risk</span>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Inp label="Risk / Trade (%)" type="number" defaultValue="1.0"/>
                <Inp label="Max Positions"    type="number" defaultValue="5"/>
              </div>
              <Btn variant="primary" size="md" style={{width:'100%',marginTop:'4px'}}>▶ Run Backtest</Btn>
            </div>
          </Card>
        )}

        {/* Fetch panel */}
        {panel==='fetch' && (
          <Card p="8px 10px">
            <SecLabel>Fetch Historical Data</SecLabel>
            <div style={{display:'flex',flexDirection:'column',gap:'7px'}}>
              <Inp label="Symbols" defaultValue="BTCUSDT,ETHUSDT,SOLUSDT"/>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Sel label="Timeframe"><option>1h</option><option selected>4h</option><option>1d</option></Sel>
                <Inp label="Days Back" type="number" defaultValue="730"/>
              </div>
              <Btn variant="primary" size="md" style={{width:'100%'}}>Start Fetch</Btn>
              <div style={{fontSize:'0.65rem',color:QEC.muted,textAlign:'center'}}>No recent fetch jobs.</div>
            </div>
          </Card>
        )}

        {/* QT Import */}
        {panel==='qt' && (
          <Card p="8px 10px">
            <SecLabel>Import Quantower Results</SecLabel>
            <div style={{display:'flex',flexDirection:'column',gap:'7px'}}>
              <div style={{fontSize:'0.7rem',color:QEC.sub,lineHeight:1.5}}>Paste the JSON export from Quantower Strategy Manager, or use the <span style={{color:QEC.blue,fontFamily:'JetBrains Mono,monospace'}}>BacktestUploader</span> plugin.</div>
              <Inp label="Session Name" defaultValue="Quantower Import"/>
              <div>
                <Lbl>JSON Payload</Lbl>
                <textarea placeholder='{"trades":[...]}'  style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.text,borderRadius:'4px',padding:'6px 8px',fontSize:'0.72rem',fontFamily:'JetBrains Mono,monospace',resize:'vertical',width:'100%',height:'120px',marginTop:'3px'}}/>
              </div>
              <Btn variant="primary" size="md" style={{width:'100%'}}>Import</Btn>
            </div>
          </Card>
        )}

        {/* Models */}
        {panel==='models' && (
          <Card p="8px 10px">
            <SecLabel>Add / Edit Model</SecLabel>
            <div style={{display:'flex',flexDirection:'column',gap:'7px'}}>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Inp label="Model Name" placeholder="e.g. EMA Trend v2"/>
                <Sel label="Type"><option>Both</option><option>Macro</option><option>Micro</option></Sel>
              </div>
              <div>
                <Lbl>Description</Lbl>
                <textarea placeholder="Brief description…" style={{background:QEC.panel,border:`1px solid ${QEC.border}`,color:QEC.text,borderRadius:'4px',padding:'5px 8px',fontSize:'0.72rem',resize:'vertical',width:'100%',height:'56px',marginTop:'3px'}}/>
              </div>
              <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'6px'}}>
                <Inp label="EMA Fast" type="number" defaultValue="20"/>
                <Inp label="EMA Slow" type="number" defaultValue="50"/>
                <Inp label="ATR SL Mult" type="number" defaultValue="1.5"/>
                <Inp label="ATR TP Mult" type="number" defaultValue="3.0"/>
                <Inp label="Risk / Trade (%)" type="number" defaultValue="1.0"/>
                <Inp label="Max Positions" type="number" defaultValue="5"/>
              </div>
              <div style={{display:'flex',gap:'6px'}}>
                <Btn variant="primary" size="md" style={{flex:1}}>Save Model</Btn>
                <Btn variant="secondary" size="md" style={{flex:1}}>Clear</Btn>
              </div>
            </div>
          </Card>
        )}
      </div>

      {/* Right: sessions + results */}
      <div style={{display:'flex',flexDirection:'column',gap:'6px'}}>
        <Card p="8px 10px">
          <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'8px'}}>
            <SecLabel style={{marginBottom:0}}>Sessions ({sessions.length})</SecLabel>
            <Btn variant="ghost" size="sm">↺ Refresh</Btn>
          </div>
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%',borderCollapse:'collapse'}}>
              <thead><tr>
                {['#','Name','Type','Range','Status','Trades','Return',''].map(h => (
                  <th key={h} style={{color:QEC.sub,fontSize:'0.6rem',fontWeight:700,letterSpacing:'0.07em',textTransform:'uppercase',padding:'5px 8px',borderBottom:`1px solid ${QEC.border}`,textAlign:'left',whiteSpace:'nowrap'}}>{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {sessions.map(s => {
                  const sum = s.summary||{}, ret = sum.total_return_pct!=null ? ((sum.total_return_pct*100).toFixed(2)+'%') : '—';
                  const retColor = parseFloat(ret)>=0 ? QEC.green : QEC.red;
                  const sc = statusColor[s.status]||QEC.sub;
                  return (
                    <tr key={s.id}
                      onClick={()=>setSel(selSession===s.id?null:s.id)}
                      style={{cursor:'pointer',background:selSession===s.id?QEC.hover:'transparent'}}
                      onMouseOver={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=QEC.hover)}
                      onMouseOut={e=>e.currentTarget.querySelectorAll('td').forEach(td=>td.style.background=selSession===s.id?QEC.hover:'transparent')}>
                      <td style={{padding:'5px 8px',fontSize:'0.7rem',color:QEC.muted,fontFamily:'monospace',borderBottom:`1px solid ${QEC.border}`}}>{s.id}</td>
                      <td style={{padding:'5px 8px',fontSize:'0.72rem',fontWeight:600,color:QEC.text,borderBottom:`1px solid ${QEC.border}`,whiteSpace:'nowrap'}}>{s.name}</td>
                      <td style={{padding:'5px 8px',fontSize:'0.65rem',color:QEC.sub,borderBottom:`1px solid ${QEC.border}`}}>{s.type}</td>
                      <td style={{padding:'5px 8px',fontSize:'0.65rem',color:QEC.sub,borderBottom:`1px solid ${QEC.border}`,whiteSpace:'nowrap'}}>{s.date_from} → {s.date_to}</td>
                      <td style={{padding:'5px 8px',fontSize:'0.7rem',fontWeight:700,color:sc,borderBottom:`1px solid ${QEC.border}`}}>{s.status}</td>
                      <td style={{padding:'5px 8px',fontSize:'0.72rem',fontFamily:'monospace',borderBottom:`1px solid ${QEC.border}`}}>{sum.total_trades||'—'}</td>
                      <td style={{padding:'5px 8px',fontSize:'0.72rem',fontWeight:700,color:retColor,fontFamily:'monospace',borderBottom:`1px solid ${QEC.border}`}}>{ret}</td>
                      <td style={{padding:'5px 8px',borderBottom:`1px solid ${QEC.border}`}}>
                        <Btn variant="danger" size="sm" onClick={e=>{e.stopPropagation();}}>✕</Btn>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Results panel */}
        {selSession && (() => {
          const s = sessions.find(x=>x.id===selSession);
          if(!s||!s.summary?.total_return_pct) return (
            <Card p="8px 10px">
              <div style={{textAlign:'center',color:QEC.muted,padding:'20px',fontSize:'0.78rem'}}>No results data for this session.</div>
            </Card>
          );
          const sum=s.summary, r=sum.r_stats||{};
          const statItems=[
            {label:'Return',        val:((sum.total_return_pct*100).toFixed(2))+'%', good:sum.total_return_pct>=0},
            {label:'Max DD',        val:((sum.max_drawdown*100).toFixed(2))+'%',     good:false},
            {label:'Trades',        val:sum.total_trades,                             good:true},
            {label:'Win Rate',      val:((r.win_rate*100).toFixed(1))+'%',           good:r.win_rate>=0.5},
            {label:'Expectancy',    val:r.expectancy.toFixed(3)+'R',                 good:r.expectancy>=0},
            {label:'Profit Factor', val:r.profit_factor.toFixed(2),                  good:r.profit_factor>=1},
          ];
          return (
            <Card p="8px 10px">
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'8px'}}>
                <SecLabel style={{marginBottom:0}}>Results — {s.name}</SecLabel>
                <Btn variant="ghost" size="sm" onClick={()=>setSel(null)}>✕</Btn>
              </div>
              <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(100px,1fr))',gap:'6px',marginBottom:'10px'}}>
                {statItems.map(({label,val,good}) => (
                  <Card key={label} p="7px 8px">
                    <Lbl>{label}</Lbl>
                    <div style={{fontFamily:'JetBrains Mono,monospace',fontSize:'0.88rem',fontWeight:700,color:good?QEC.green:QEC.red}}>{val}</div>
                  </Card>
                ))}
              </div>
              {s.type==='microstructure' && (
                <Badge color={QEC.cyan} bg="#071828" style={{marginBottom:'8px'}}>Quantower microstructure import</Badge>
              )}
              <div style={{height:'80px',background:QEC.panel,borderRadius:'4px',display:'flex',alignItems:'center',justifyContent:'center'}}>
                <span style={{fontSize:'0.65rem',color:QEC.muted}}>Equity curve chart</span>
              </div>
            </Card>
          );
        })()}
      </div>
    </div>
  );
};

// ── Tweaks Panel ──────────────────────────────────────────────────────────
const TweaksOverlay = ({onClose, initialTabStyle='line'}) => {
  const [vals, setVals] = React.useState({...TWEAK_DEFAULTS, tabStyle: initialTabStyle});
  const set = (k,v) => {
    const next = {...vals, [k]:v};
    setVals(next);
    window.parent.postMessage({type:'__edit_mode_set_keys', edits: next}, '*');
    if (k === 'theme') {
      const t = THEME_VARS[v] || THEME_VARS.navy;
      Object.assign(QEC, {bg:t.bg,card:t.card,panel:t.panel,border:t.border,blue:t.blue});
    }
    if (k === 'tabStyle') {
      window.__QE_TAB_STYLE = v;
      setTabStyle(v);
    }
  };

  const OptionRow = ({label, options, field}) => (
    <div style={{marginBottom:'12px'}}>
      <div style={{fontSize:'0.65rem',fontWeight:700,color:QEC.sub,letterSpacing:'0.08em',textTransform:'uppercase',marginBottom:'5px'}}>{label}</div>
      <div style={{display:'flex',gap:'4px'}}>
        {options.map(([id,lbl]) => (
          <button key={id} onClick={()=>set(field,id)} style={{
            padding:'4px 10px',border:`1px solid ${vals[field]===id?QEC.blue:QEC.border}`,
            borderRadius:'4px',cursor:'pointer',
            background:vals[field]===id?'#1a3060':'transparent',
            color:vals[field]===id?'#93c5fd':QEC.sub,
            fontSize:'0.68rem',fontWeight:vals[field]===id?700:500,
          }}>{lbl}</button>
        ))}
      </div>
    </div>
  );

  return (
    <div style={{
      position:'fixed',bottom:'12px',right:'12px',zIndex:1000,
      background:QEC.card,border:`1px solid ${QEC.borderFoc}`,
      borderRadius:'6px',padding:'14px 16px',width:'240px',
      boxShadow:'0 12px 40px rgba(0,0,0,0.7)',
    }}>
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:'12px'}}>
        <span style={{fontSize:'0.72rem',fontWeight:700,color:QEC.text,letterSpacing:'0.04em'}}>Tweaks</span>
        <button onClick={onClose} style={{background:'none',border:'none',color:QEC.sub,cursor:'pointer',fontSize:'1rem',lineHeight:1}}>×</button>
      </div>
      <OptionRow label="Tab Style"   field="tabStyle" options={[['line','Line'],['filled','Filled'],['pill','Pill'],['bracket','[ ]']]}/>
      <OptionRow label="Density"     field="density" options={[['compact','Compact'],['normal','Normal'],['spacious','Roomy']]}/>
      <OptionRow label="Number Size" field="numSize"  options={[['small','S'],['medium','M'],['large','L']]}/>
      <OptionRow label="Color Theme" field="theme"    options={[['navy','Navy'],['charcoal','Slate'],['deep','Deep']]}/>
      <div style={{marginTop:'8px',paddingTop:'8px',borderTop:`1px solid ${QEC.border}`,fontSize:'0.62rem',color:QEC.muted,lineHeight:1.5}}>
        Changes apply live. Theme choice persists across reloads.
      </div>
    </div>
  );
};

// ── App Root ──────────────────────────────────────────────────────────────
const App = () => {
  const [page, setPage]           = React.useState('dashboard');
  const [tweaks, setTweaks]       = React.useState(false);
  const [tabStyle, setTabStyle]   = React.useState(TWEAK_DEFAULTS.tabStyle||'line');
  const [platform, setPlatform]   = React.useState('standalone');
  const [pluginConnected]         = React.useState(false); // mock: always offline in prototype

  const showBanner = platform === 'standalone' || (platform === 'quantower' && !pluginConnected);
  const bannerMsg  = platform === 'standalone'
    ? 'Standalone mode — P&L and positions are estimated from Binance WS, not broker truth.'
    : 'Quantower plugin not connected — showing last-known positions. P&L may be stale.';

  // Tweaks protocol
  React.useEffect(() => {
    const handler = (e) => {
      if (e.data?.type === '__activate_edit_mode')   setTweaks(true);
      if (e.data?.type === '__deactivate_edit_mode') setTweaks(false);
    };
    window.addEventListener('message', handler);
    window.parent.postMessage({type:'__edit_mode_available'}, '*');
    return () => window.removeEventListener('message', handler);
  }, []);

  const closeTweaks = () => {
    setTweaks(false);
    window.parent.postMessage({type:'__edit_mode_dismissed'}, '*');
  };

  const pages = {
    dashboard:  <DashboardPage/>,
    calculator: <CalculatorPage/>,
    history:    <HistoryPage/>,
    params:     <ParamsPage/>,
    analytics:  <AnalyticsPage tabStyle={tabStyle}/>,
    backtest:   <BacktestPage/>,
    regime:     <RegimePage tabStyle={tabStyle}/>,
  };

  return (
    <div style={{
      background:QEC.bg, color:QEC.text,
      minHeight:'100vh', display:'flex', flexDirection:'column',
      fontFamily:"'Space Grotesk', sans-serif",
    }}>
      <TopNav page={page} setPage={setPage} platform={platform} setPlatform={setPlatform} pluginConnected={pluginConnected}/>
      <PageHeader page={page}/>

      {/* Standalone / disconnected banner */}
      {showBanner && (
        <div style={{
          display:'flex', alignItems:'center', gap:'8px',
          background:'#1e0f00', borderBottom:`1px solid #6b3a00`,
          padding:'5px 12px', fontSize:'0.7rem', color:QEC.amber, flexShrink:0,
        }}>
          <svg xmlns="http://www.w3.org/2000/svg" style={{width:'13px',height:'13px',flexShrink:0}} viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd"/>
          </svg>
          {bannerMsg}
        </div>
      )}

      <div style={{flex:1, overflowY:'auto'}}>
        {pages[page] || pages.dashboard}
      </div>
      <footer style={{textAlign:'center',color:QEC.muted,fontSize:'0.6rem',padding:'6px',fontFamily:'monospace'}}>
        Quantamental Risk Engine v2.1 — Binance USD-M Futures — UTC+7 — 2026-05-04 20:08:02
      </footer>
      {tweaks && <TweaksOverlay onClose={closeTweaks} initialTabStyle={tabStyle}/>}
    </div>
  );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App/>);
