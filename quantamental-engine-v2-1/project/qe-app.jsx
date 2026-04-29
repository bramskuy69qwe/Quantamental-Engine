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
  backtest:   {name:'Backtest',   sub:'Strategy simulation'},
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
const BacktestPage = () => (
  <div style={{padding:'8px'}}>
    <Card>
      <SecLabel>Backtest</SecLabel>
      <div style={{textAlign:'center',padding:'40px',color:QEC.sub,fontSize:'0.85rem'}}>
        Backtest module — configure strategies and run historical simulations.
      </div>
    </Card>
  </div>
);

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
  const [page, setPage]       = React.useState('dashboard');
  const [tweaks, setTweaks]   = React.useState(false);
  const [tabStyle, setTabStyle] = React.useState(TWEAK_DEFAULTS.tabStyle||'line');

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
      <TopNav page={page} setPage={setPage}/>
      <PageHeader page={page}/>
      <div style={{flex:1, overflowY:'auto'}}>
        {pages[page] || pages.dashboard}
      </div>
      <footer style={{textAlign:'center',color:QEC.muted,fontSize:'0.6rem',padding:'6px',fontFamily:'monospace'}}>
        Quantamental Risk Engine v2.1 — Binance USD-M Futures — UTC+7 — 2026-04-25 20:08:02
      </footer>
      {tweaks && <TweaksOverlay onClose={closeTweaks} initialTabStyle={tabStyle}/>}
    </div>
  );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App/>);
