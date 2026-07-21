/* QE v3.0 — Models tab (Model Library).
   Master-detail surface built entirely from v3.0 primitives:
   Pane · Card · DataList · Stat · Badge · EquityChart · Sparkline · EmptyState.

   Views (internal state machine, no router needed):
     library → detail → run    + create/edit + import overlays
   The engine never runs backtests — performance arrives only via import. */

const _MTYPE = { Macro: 'info', Micro: 'blue', Both: 'mag' };
const TypeBadge = ({type}) => <Badge tone={_MTYPE[type] || 'mute'}>{type}</Badge>;

const _money = (v, dp = 2) => (v >= 0 ? '+' : '−') + '$' + Math.abs(v).toLocaleString('en-US', {minimumFractionDigits: dp, maximumFractionDigits: dp});
const _plColor = (v) => v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)';

// Headline KPI for a model = its latest run (runs[0]), or null.
// (_latestRun itself comes from pages-models-data.jsx via window — single def.)

// ── KPI tile — the reusable summary-stat card used across detail + run ──────
const KpiTile = ({label, value, sub, color}) => (
  <Card tight style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
    <div style={{fontFamily:'var(--qe-ui)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.1em', textTransform:'uppercase', color:'var(--qe-muted)'}}>{label}</div>
    <div className="qe-mono" style={{fontSize:'0.92rem', fontWeight:700, color: color || 'var(--qe-text)', lineHeight:1.1, fontVariantNumeric:'tabular-nums'}}>{value}</div>
    {sub && <div className="qe-mono" style={{fontSize:'0.5rem', color:'var(--qe-muted)'}}>{sub}</div>}
  </Card>
);

// ═══════════════════════════════════════════════════════════════════════════
// A. LIBRARY
// ═══════════════════════════════════════════════════════════════════════════
const ModelCard = ({m, onOpen}) => {
  const run = _latestRun(m);
  const k = run && run.report ? runKpis(run.report) : null;
  const eq = run && run.report ? runEquity(run.report) : null;
  return (
    <div onClick={() => onOpen(m)} style={{cursor:'pointer', display:'flex'}}>
    <Card ticks className="qe-model-card" style={{display:'flex', flexDirection:'column', gap:6, cursor:'pointer', padding:'8px 10px', flex:1}}>
      <div style={{display:'flex', alignItems:'flex-start', gap:8}}>
        <div style={{minWidth:0, flex:1}}>
          <div style={{display:'flex', alignItems:'center', gap:7}}>
            <span style={{fontFamily:'var(--qe-ui)', fontWeight:700, fontSize:'0.78rem', color:'var(--qe-text)', letterSpacing:'0.01em'}}>{m.name}</span>
            <TypeBadge type={m.type}/>
          </div>
          <div style={{fontSize:'0.58rem', color:'var(--qe-sub)', lineHeight:1.4, marginTop:3,
                       display:'-webkit-box', WebkitLineClamp:2, WebkitBoxOrient:'vertical', overflow:'hidden'}}>{m.desc}</div>
        </div>
      </div>

      {run && k ? (
        <>
          <div style={{height:26}}>
            <Sparkline data={eq} height={26} color={k.net >= 0 ? 'var(--qe-green)' : 'var(--qe-red)'}/>
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(5, 1fr)', gap:5}}>
            <KvMini l="NET P/L" v={_money(k.net, 0)} c={_plColor(k.net)}/>
            <KvMini l="WIN %"   v={k.winPct + '%'}/>
            <KvMini l="PF"      v={k.pf.toFixed(2)} c={k.pf >= 1.3 ? 'var(--qe-green)' : k.pf < 1 ? 'var(--qe-red)' : 'var(--qe-text)'}/>
            <KvMini l="MAX DD"  v={k.maxDDPct + '%'} c="var(--qe-red)"/>
            <KvMini l="TRADES"  v={k.nTrades}/>
          </div>
        </>
      ) : (
        <div style={{display:'flex', alignItems:'center', gap:7, padding:'10px 4px', border:'1px dashed var(--qe-faint)'}}>
          <span style={{color:'var(--qe-amber)', fontSize:'0.7rem'}}>◇</span>
          <span style={{fontSize:'0.58rem', color:'var(--qe-muted)'}}>No backtests imported yet</span>
        </div>
      )}

      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginTop:'auto', paddingTop:4, borderTop:'1px solid var(--qe-faint)'}}>
        <span style={{fontSize:'0.5rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>updated {m.updated}</span>
        <span style={{display:'flex', gap:4}}>
          {m.tags.slice(0,2).map(t => <span key={t} style={{fontSize:'0.5rem', color:'var(--qe-muted)', letterSpacing:'0.06em', textTransform:'uppercase', border:'1px solid var(--qe-faint)', padding:'0 3px'}}>{t}</span>)}
        </span>
      </div>
    </Card>
    </div>
  );
};

const KvMini = ({l, v, c}) => (
  <div style={{minWidth:0}}>
    <div style={{fontFamily:'var(--qe-ui)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.08em', color:'var(--qe-muted)'}}>{l}</div>
    <div className="qe-mono" style={{fontSize:'0.62rem', fontWeight:700, color: c || 'var(--qe-text)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</div>
  </div>
);

const ModelLibrary = ({models, onOpen, onNew, embedded=false}) => {
  const [q, setQ] = React.useState('');
  const [type, setType] = React.useState('All');
  const [sort, setSort] = React.useState('updated');

  const filtered = models
    .filter(m => type === 'All' || m.type === type)
    .filter(m => !q || m.name.toLowerCase().includes(q.toLowerCase()) || m.tags.some(t => t.includes(q.toLowerCase())))
    .sort((a, b) => {
      if (sort === 'updated') return b.updated.localeCompare(a.updated);
      if (sort === 'name') return a.name.localeCompare(b.name);
      const ka = _latestRun(a) && _latestRun(a).report ? runKpis(_latestRun(a).report) : null;
      const kb = _latestRun(b) && _latestRun(b).report ? runKpis(_latestRun(b).report) : null;
      if (sort === 'net') return (kb?.net ?? -1e9) - (ka?.net ?? -1e9);
      if (sort === 'pf')  return (kb?.pf ?? -1) - (ka?.pf ?? -1);
      return 0;
    });

  return (
    <div style={{display:'flex', flexDirection:'column', height:'100%', minHeight:0}}>
      {/* toolbar */}
      <div style={{display:'flex', alignItems:'center', gap:8, padding:'8px 10px', borderBottom:'1px solid var(--qe-line)', flexShrink:0, flexWrap:'wrap'}}>
        <div style={{position:'relative', width:200}}>
          <input className="qe-input" placeholder="Search models…" value={q} onChange={e => setQ(e.target.value)} style={{paddingLeft:20}}/>
          <span style={{position:'absolute', left:6, top:'50%', transform:'translateY(-50%)', color:'var(--qe-muted)', fontSize:'0.6rem', pointerEvents:'none'}}>⌕</span>
        </div>
        <div style={{display:'flex', gap:4}}>
          {['All','Macro','Micro','Both'].map(t => (
            <button key={t} className={`qe-btn qe-btn-sm ${type===t?'qe-btn-on':''}`} onClick={() => setType(t)}>{t}</button>
          ))}
        </div>
        <div className="qe-grow"/>
        <span style={{fontSize:'0.52rem', color:'var(--qe-muted)', textTransform:'uppercase', letterSpacing:'0.08em'}}>Sort</span>
        <select className="qe-input qe-select" value={sort} onChange={e => setSort(e.target.value)} style={{width:120}}>
          <option value="updated">Last updated</option>
          <option value="net">Net P/L</option>
          <option value="pf">Profit factor</option>
          <option value="name">Name</option>
        </select>
        {!embedded && <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onNew}>+ New Model</button>}
      </div>

      {/* grid */}
      <div style={{flex:1, minHeight:0, overflow:'auto', padding:10}}>
        {filtered.length ? (
          <div style={{display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(290px, 1fr))', gap:10, alignItems:'stretch'}}>
            {filtered.map(m => <ModelCard key={m.id} m={m} onOpen={onOpen}/>)}
          </div>
        ) : (
          <div style={{height:'100%', display:'flex', alignItems:'center', justifyContent:'center'}}>
            <EmptyState tone={models.length ? 'neutral' : 'info'} glyph="◇"
              msg={models.length ? 'No models match your filters' : 'No models yet'}
              hint={models.length ? 'Clear the search or type filter.' : 'Create a reusable trading model, then import a backtest report to track its performance.'}
              cta={!models.length && <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onNew}>+ New Model</button>}/>
          </div>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { TypeBadge, KpiTile, KvMini, ModelCard, ModelLibrary, _money, _plColor });
