/* QE v3.0 — Models tab: create/edit + import overlays, ModelsPage orchestrator.
   Loaded after pages-models-data / -lib / -detail. */

// Shared overlay shell — a Pane, layered. Uses the Pane primitive's chrome
// (qe-pane-head title bar, card surface, grip, optional PaneFoot status line)
// so dialogs follow the same visual language as every tiled pane; the only
// addition is the modal layering (scrim + centering + z-index) and a close ✕.
const ModelDialog = ({title, onClose, width = 460, children, footer, foot = null, hot = true}) => (
  <div style={{position:'absolute', inset:0, zIndex:50, background:'rgba(0,0,0,0.66)', display:'flex', alignItems:'center', justifyContent:'center', padding:20}}
       onClick={onClose}>
    <div onClick={e => e.stopPropagation()} style={{width, maxWidth:'100%', maxHeight:'100%', display:'flex', flexDirection:'column', position:'relative',
         background:'var(--qe-card)', border:'1px solid var(--qe-line-2)', boxShadow:'0 24px 70px -16px var(--qe-bg)'}}>
      <PaneHead title={title} hot={hot}
        right={<button onClick={onClose} title="Close"
          style={{display:'inline-flex', alignItems:'center', justifyContent:'center', width:14, height:14,
            border:'1px solid var(--qe-faint)', background:'transparent', color:'var(--qe-muted)', cursor:'pointer',
            fontSize:'0.7rem', lineHeight:1, padding:0}}
          onMouseEnter={e=>{e.currentTarget.style.color='var(--qe-red)';e.currentTarget.style.borderColor='var(--qe-red)';}}
          onMouseLeave={e=>{e.currentTarget.style.color='var(--qe-muted)';e.currentTarget.style.borderColor='var(--qe-faint)';}}>✕</button>}/>
      <div style={{flex:1, minHeight:0, overflow:'auto', padding:10}}>{children}</div>
      {foot && <PaneFoot {...foot}/>}
      {footer && <div style={{display:'flex', alignItems:'center', justifyContent:'flex-end', gap:6, padding:'7px 9px', borderTop:'1px solid var(--qe-line)', background:'var(--qe-panel)', flexShrink:0}}>{footer}</div>}
      <span className="qe-grip" style={{pointerEvents:'none'}}/>
    </div>
  </div>
);

const _Field = ({label, children, hint, error}) => (
  <label style={{display:'flex', flexDirection:'column', gap:4, minWidth:0}}>
    <span style={{fontFamily:'var(--qe-ui)', fontSize:'0.52rem', fontWeight:700, letterSpacing:'0.09em', textTransform:'uppercase', color: error ? 'var(--qe-red)' : 'var(--qe-sub)'}}>{label}</span>
    {children}
    {error ? <span style={{fontSize:'0.5rem', color:'var(--qe-red)'}}>{error}</span>
           : hint && <span style={{fontSize:'0.5rem', color:'var(--qe-muted)'}}>{hint}</span>}
  </label>
);

// Lightweight section header — label + rule, no panel box. Matches the app's
// SecLbl rhythm so the form reads as part of the system, not a stack of cards.
const _Sec = ({title, sub, children}) => (
  <div style={{display:'flex', flexDirection:'column', gap:12}}>
    <div style={{display:'flex', alignItems:'center', gap:8}}>
      <span style={{fontFamily:'var(--qe-ui)', fontSize:'0.54rem', fontWeight:700, letterSpacing:'0.16em', textTransform:'uppercase', color:'var(--qe-sub)', whiteSpace:'nowrap'}}>{title}</span>
      {sub && <span style={{fontSize:'0.5rem', color:'var(--qe-muted)', whiteSpace:'nowrap'}}>{sub}</span>}
      <span style={{flex:1, height:1, background:'var(--qe-line)'}}></span>
    </div>
    {children}
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// D. CREATE / EDIT MODEL FORM — polished, sectioned, with optional import path
// ═══════════════════════════════════════════════════════════════════════════
const SOURCE_APPS = ['MultiCharts', 'TradeStation', 'NinjaTrader', 'Generic CSV'];

const ModelFormModal = ({model, onClose, onSave}) => {
  const editing = !!model;
  const blank = {
    name: '', type: 'Macro', desc: '',
    app: 'MultiCharts', symbol: '', resolution: '1 Minute', pointValue: '', currency: 'USD',
    initialCapital: 100000, commission: 'No Commission', slippage: '0$ per Trade',
    riskPct: 1.0, matchWindow: 90, tp: 'ATR × 2.5', sl: 'ATR × 1.2', regimeMult: true,
    notes: '', universe: '',
  };
  const fromModel = (m) => ({
    name: m.name, type: m.type, desc: m.desc,
    app: (m.source && m.source.app) || 'MultiCharts', symbol: (m.source && m.source.symbol) || '',
    resolution: (m.source && m.source.resolution) || '1 Minute', pointValue: (m.source && m.source.pointValue) || '',
    currency: (m.source && m.source.currency) || 'USD', initialCapital: (m.source && m.source.initialCapital) || 100000,
    commission: (m.source && m.source.commission) || 'No Commission', slippage: (m.source && m.source.slippage) || '0$ per Trade',
    riskPct: m.risk.riskPct, matchWindow: m.risk.matchWindow, tp: m.risk.tp, sl: m.risk.sl, regimeMult: m.risk.regimeMult,
    notes: m.strategy.notes, universe: m.strategy.universe,
  });

  const [mode, setMode] = React.useState('blank');      // blank | import  (new only)
  const [f, setF] = React.useState(() => editing ? fromModel(model) : blank);
  const [parsed, setParsed] = React.useState(null);     // {report, file, kpis}
  const [touched, setTouched] = React.useState(false);
  const set = (k, v) => setF(p => ({...p, [k]: v}));

  // Simulate parsing a dropped MultiCharts report → autofill from its Settings.
  const doParse = (which) => {
    const report = (which === 'es' && typeof MC_ES_REPORT !== 'undefined')
      ? MC_ES_REPORT
      : _synthReport(Math.floor(Math.random()*9e4)+1e4, { nTrades: 96, winRate: 0.55, avgWin: 320, avgLoss: -260, startEq: 50000, symbol: 'NQ', point: 20, sigLong: 'BRK_L', sigShort: 'BRK_S', exitTP: 'TP', exitSL: 'SL', compression: '5 Minutes', inputs:[{k:'RiskPctOfEquity',v:1.0},{k:'RewardRiskMult',v:2.0}] });
    const meta = parseReportMeta(report);
    const file = which === 'es' ? '@ES - 1 Minute.xlsx' : 'NQ_breakout_5m.xlsx';
    setParsed({ report, file, kpis: runKpis(report), meta });
    setF(p => ({ ...p,
      name: p.name || meta.name, type: 'Micro', symbol: meta.symbol, resolution: meta.resolution,
      pointValue: meta.pointValue, currency: meta.currency, initialCapital: meta.initialCapital,
      commission: meta.commission, slippage: meta.slippage, riskPct: meta.riskPct, tp: meta.tp,
      universe: p.universe || meta.universe,
    }));
  };
  const clearParse = () => setParsed(null);

  const errors = {
    name: !f.name.trim() ? 'Name is required' : null,
    riskPct: (f.riskPct <= 0 || f.riskPct > 10) ? 'Risk must be 0–10%' : null,
  };
  const valid = !errors.name && !errors.riskPct;
  const submit = () => { setTouched(true); if (valid) onSave({ ...f, _importReport: parsed ? parsed.report : null, _importFile: parsed ? parsed.file : null }); };

  const seg = (val, label) => (
    <button onClick={() => { setMode(val); if (val==='blank') setParsed(null); }}
      style={{flex:1, padding:'7px 0', fontFamily:'var(--qe-ui)', fontSize:'0.58rem', fontWeight:700, letterSpacing:'0.04em',
        cursor:'pointer', border:'1px solid '+(mode===val?'var(--qe-cyan)':'var(--qe-line)'),
        background: mode===val?'var(--qe-bg-cyan)':'transparent', color: mode===val?'var(--qe-cyan)':'var(--qe-sub)'}}>{label}</button>
  );

  return (
    <ModelDialog title={editing ? `Edit Model · ${model.name}` : 'New Model'} width={640} onClose={onClose}
      foot={{tone: parsed ? 'ok' : 'info', id: 5300, msg: parsed ? `parsed ${parsed.file} — fields auto-filled from report` : (editing ? 'editing model definition' : 'define a reusable model'), ms: 0}}
      footer={<>
        <button className="qe-btn qe-btn-sm" onClick={onClose}>Cancel</button>
        <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={!valid}
          onClick={submit} style={!valid ? {opacity:0.5, cursor:'not-allowed'} : {}}>
          {editing ? 'Save changes' : parsed ? 'Create model + import run' : 'Create model'}</button>
      </>}>
      <div style={{display:'flex', flexDirection:'column', gap:20, padding:'4px 6px'}}>

        {/* create-path chooser (new model only) */}
        {!editing && (
          <div style={{display:'flex', gap:6}}>
            {seg('blank', '+ Blank model')}
            {seg('import', '⤓ From backtest report')}
          </div>
        )}

        {/* import drop / parsed banner */}
        {!editing && mode === 'import' && (
          <_Sec title="Import Backtest Report" sub="MultiCharts .xlsx / .xml">
            {!parsed ? (
              <div style={{border:'1px dashed var(--qe-line-2)', padding:'22px 16px', textAlign:'center', background:'var(--qe-panel)'}}>
                <div style={{fontSize:'1.3rem', color:'var(--qe-muted)', lineHeight:1}}>⤓</div>
                <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginTop:8}}>Drop a report to auto-fill the model</div>
                <div style={{fontSize:'0.52rem', color:'var(--qe-muted)', marginTop:4}}>parses the Settings sheet — symbol, point value, resolution, risk inputs</div>
                <div style={{display:'flex', gap:6, justifyContent:'center', marginTop:14}}>
                  <button className="qe-btn qe-btn-sm qe-btn-on" onClick={() => doParse('es')}>Use @ES sample</button>
                  <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => doParse('other')}>Choose file…</button>
                </div>
              </div>
            ) : (
              <div style={{display:'flex', flexDirection:'column', gap:10}}>
                <div style={{display:'flex', alignItems:'center', gap:8}}>
                  <Badge tone="ok">PARSED</Badge>
                  <span className="qe-mono" style={{fontSize:'0.6rem', color:'var(--qe-text)'}}>{parsed.file}</span>
                  <div className="qe-grow"></div>
                  <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={clearParse}>Clear</button>
                </div>
                <div style={{display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:6}}>
                  <KpiTile label="Net P/L" value={_money(parsed.kpis.net,0)} color={_plColor(parsed.kpis.net)}/>
                  <KpiTile label="Profit Factor" value={parsed.kpis.pf.toFixed(2)} color={parsed.kpis.pf>=1?'var(--qe-green)':'var(--qe-red)'}/>
                  <KpiTile label="Win %" value={parsed.kpis.winPct + '%'}/>
                  <KpiTile label="Trades" value={parsed.kpis.nTrades}/>
                </div>
                <div style={{fontSize:'0.52rem', color:'var(--qe-muted)'}}>Fields below were auto-filled from the report — edit anything before creating.</div>
              </div>
            )}
          </_Sec>
        )}

        {/* identity */}
        <_Sec title="Identity">
          <div style={{display:'grid', gridTemplateColumns:'2fr 1fr', gap:'14px 12px'}}>
            <_Field label="Name" error={touched && errors.name}>
              <input className="qe-input" value={f.name} onChange={e => set('name', e.target.value)} placeholder="e.g. BTC Macro Trend"/>
            </_Field>
            <_Field label="Type">
              <select className="qe-input qe-select" value={f.type} onChange={e => set('type', e.target.value)}>
                <option>Macro</option><option>Micro</option><option>Both</option>
              </select>
            </_Field>
            <_Field label="Description" hint="One or two lines — shown on the library card.">
              <textarea className="qe-input" rows={2} value={f.desc} onChange={e => set('desc', e.target.value)} style={{resize:'vertical', lineHeight:1.4, gridColumn:'1 / -1'}}/>
            </_Field>
          </div>
        </_Sec>

        {/* source binding */}
        <_Sec title="Source Binding" sub="ties the model to its 3rd-party backtest source">
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'14px 12px'}}>
            <_Field label="Source app">
              <select className="qe-input qe-select" value={f.app} onChange={e => set('app', e.target.value)}>
                {SOURCE_APPS.map(a => <option key={a}>{a}</option>)}
              </select>
            </_Field>
            <_Field label="Symbol">
              <input className="qe-input" value={f.symbol} onChange={e => set('symbol', e.target.value)} placeholder="@ES"/>
            </_Field>
            <_Field label="Resolution">
              <input className="qe-input" value={f.resolution} onChange={e => set('resolution', e.target.value)} placeholder="1 Minute"/>
            </_Field>
            <_Field label="Point value">
              <input className="qe-input" type="number" step="1" value={f.pointValue} onChange={e => set('pointValue', e.target.value)} placeholder="50"/>
            </_Field>
            <_Field label="Currency">
              <input className="qe-input" value={f.currency} onChange={e => set('currency', e.target.value)} placeholder="USD"/>
            </_Field>
            <_Field label="Initial capital">
              <input className="qe-input" type="number" step="1000" value={f.initialCapital} onChange={e => set('initialCapital', parseFloat(e.target.value)||0)}/>
            </_Field>
            <_Field label="Commission">
              <input className="qe-input" value={f.commission} onChange={e => set('commission', e.target.value)}/>
            </_Field>
            <_Field label="Slippage">
              <input className="qe-input" value={f.slippage} onChange={e => set('slippage', e.target.value)}/>
            </_Field>
          </div>
        </_Sec>

        {/* risk & sizing */}
        <_Sec title="Risk & Sizing Preset">
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'14px 12px'}}>
            <_Field label="Risk / trade (%)" error={touched && errors.riskPct}>
              <input className="qe-input" type="number" step="0.05" value={f.riskPct} onChange={e => set('riskPct', parseFloat(e.target.value)||0)}/>
            </_Field>
            <_Field label="Match window (s)">
              <input className="qe-input" type="number" step="5" value={f.matchWindow} onChange={e => set('matchWindow', parseInt(e.target.value)||0)}/>
            </_Field>
            <_Field label="TP methodology">
              <input className="qe-input" value={f.tp} onChange={e => set('tp', e.target.value)}/>
            </_Field>
            <_Field label="SL methodology">
              <input className="qe-input" value={f.sl} onChange={e => set('sl', e.target.value)}/>
            </_Field>
          </div>
          <div style={{display:'flex', alignItems:'center', gap:8, marginTop:2}}>
            <Switch checked={f.regimeMult} onChange={() => set('regimeMult', !f.regimeMult)} accent="var(--qe-cyan)"/>
            <span style={{fontSize:'0.6rem', color:'var(--qe-sub)'}}>Apply regime multiplier</span>
          </div>
        </_Sec>

        {/* strategy */}
        <_Sec title="Strategy">
          <div style={{display:'flex', flexDirection:'column', gap:14}}>
            <_Field label="Target universe">
              <input className="qe-input" value={f.universe} onChange={e => set('universe', e.target.value)} placeholder="e.g. BTCUSDT perp"/>
            </_Field>
            <_Field label="Notes" hint="Freeform strategy definition.">
              <textarea className="qe-input" rows={3} value={f.notes} onChange={e => set('notes', e.target.value)} style={{resize:'vertical', lineHeight:1.5}}/>
            </_Field>
          </div>
        </_Sec>
      </div>
    </ModelDialog>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// E. IMPORT BACKTEST FLOW
// ═══════════════════════════════════════════════════════════════════════════
const ImportModal = ({model, onClose, onConfirm}) => {
  const [step, setStep] = React.useState('source');   // source | upload | preview | error
  const [source, setSource] = React.useState('MultiCharts');
  const pv = MOCK_IMPORT_PREVIEW;

  const fakeUpload = (bad) => setStep(bad ? 'error' : 'preview');

  return (
    <ModelDialog title={`Import Report → ${model.name}`} width={480} onClose={onClose}
      footer={
        step === 'preview' ? <>
          <button className="qe-btn qe-btn-sm" onClick={() => setStep('upload')}>Back</button>
          <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={() => onConfirm(pv)}>Confirm import</button>
        </> :
        step === 'error' ? <>
          <button className="qe-btn qe-btn-sm" onClick={() => setStep('upload')}>Try another file</button>
        </> :
        step === 'upload' ? <button className="qe-btn qe-btn-sm" onClick={() => setStep('source')}>Back</button>
        : null
      }>
      {/* step rail */}
      <div style={{display:'flex', gap:6, marginBottom:14}}>
        {['source','upload','preview'].map((s, i) => {
          const active = step === s;
          const done = ['source','upload','preview'].indexOf(step) > i || step === 'error' && i < 2;
          return (
            <div key={s} style={{flex:1, display:'flex', alignItems:'center', gap:5}}>
              <span style={{width:16, height:16, display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0,
                border:`1px solid ${active?'var(--qe-cyan)':done?'var(--qe-green)':'var(--qe-faint)'}`,
                color: active?'var(--qe-cyan)':done?'var(--qe-green)':'var(--qe-muted)', fontSize:'0.5rem', fontFamily:'var(--qe-mono)', fontWeight:700}}>{done?'✓':i+1}</span>
              <span style={{fontSize:'0.5rem', textTransform:'uppercase', letterSpacing:'0.08em', color: active?'var(--qe-cyan)':'var(--qe-muted)'}}>{s}</span>
            </div>
          );
        })}
      </div>

      {step === 'source' && (
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          <_Field label="Source application" hint="More backtesting apps will be supported over time.">
            <select className="qe-input qe-select" value={source} onChange={e => setSource(e.target.value)}>
              <option>MultiCharts</option>
              <option disabled>VectorBT Pro (soon)</option>
              <option disabled>NautilusTrader (soon)</option>
            </select>
          </_Field>
          <div style={{display:'flex', justifyContent:'flex-end'}}>
            <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={() => setStep('upload')}>Next →</button>
          </div>
        </div>
      )}

      {step === 'upload' && (
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          <div style={{border:'1px dashed var(--qe-line-2)', padding:'26px 16px', textAlign:'center', background:'var(--qe-panel)'}}>
            <div style={{fontSize:'1.4rem', color:'var(--qe-muted)', lineHeight:1}}>⤓</div>
            <div style={{fontSize:'0.62rem', color:'var(--qe-sub)', marginTop:8}}>Drop a {source} report here</div>
            <div style={{fontSize:'0.5rem', color:'var(--qe-muted)', marginTop:3}}>.xlsx or .xml — performance summary + trade list</div>
            <div style={{display:'flex', gap:6, justifyContent:'center', marginTop:12}}>
              <button className="qe-btn qe-btn-sm qe-btn-on" onClick={() => fakeUpload(false)}>Choose file…</button>
              <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => fakeUpload(true)}>Simulate bad file</button>
            </div>
          </div>
        </div>
      )}

      {step === 'preview' && (
        <div style={{display:'flex', flexDirection:'column', gap:10}}>
          <div style={{display:'flex', alignItems:'center', gap:7}}>
            <Badge tone="ok">PARSED</Badge>
            <span className="qe-mono" style={{fontSize:'0.6rem', color:'var(--qe-text)'}}>{pv.file}</span>
          </div>
          <div style={{display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:7}}>
            <KpiTile label="Net Profit" value={_money(pv.net,0)} color={_plColor(pv.net)}/>
            <KpiTile label="Profit Factor" value={pv.pf.toFixed(2)} color={pv.pf>=1.3?'var(--qe-green)':'var(--qe-text)'}/>
            <KpiTile label="Win %" value={pv.winPct + '%'}/>
            <KpiTile label="Max DD" value={pv.maxDDPct + '%'} color="var(--qe-red)"/>
            <KpiTile label="Sharpe" value={pv.sharpe.toFixed(2)}/>
            <KpiTile label="Trades" value={pv.nTrades}/>
          </div>
          <div style={{fontSize:'0.54rem', color:'var(--qe-muted)', fontFamily:'var(--qe-mono)'}}>
            {pv.symbol} · {pv.window}
          </div>
          {pv.warnings.map((w, i) => (
            <div key={i} style={{display:'flex', gap:6, alignItems:'center', fontSize:'0.54rem', color:'var(--qe-amber)'}}>
              <span>!</span><span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {step === 'error' && (
        <EmptyState tone="err" glyph="✗" msg="Unrecognized file format"
          hint="This doesn't look like a MultiCharts performance report. Expected an .xlsx or .xml export containing a summary sheet and a trade-by-trade list."/>
      )}
    </ModelDialog>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ORCHESTRATOR
// ═══════════════════════════════════════════════════════════════════════════
// Sub-tab strip: a fixed "Overview" tab + one permanent tab per existing model
// (adding/deleting a model adds/removes its tab) + a trailing "+" to create one.
const ModelTabStrip = ({models, active, onSelect, onNew}) => (
  <TabStrip value={active} onChange={onSelect}
    tabs={[['overview','Overview'], ...models.map(m => [m.id, m.name])]}
    right={<button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={onNew} title="New model"
      style={{alignSelf:'center', marginLeft:6, fontSize:'0.9rem', lineHeight:1, padding:'0 8px'}}>+</button>}/>
);

const ModelsPage = () => {
  const [models, setModels] = React.useState(MOCK_MODELS);
  const [active, setActive] = React.useState('overview'); // 'overview' | modelId
  const [modal, setModal] = React.useState(null);         // null | 'new' | 'edit' | 'import'
  const [toast, setToast] = React.useState(null);
  const [confirmDel, setConfirmDel] = React.useState(false); // two-step Delete

  React.useEffect(() => { setConfirmDel(false); }, [active]);
  React.useEffect(() => {
    if (!confirmDel) return;
    const t = setTimeout(() => setConfirmDel(false), 4000); // auto-revert
    return () => clearTimeout(t);
  }, [confirmDel]);

  const model = active !== 'overview' ? models.find(m => m.id === active) || null : null;

  const flash = (msg) => { setToast(msg); setTimeout(() => setToast(null), 2600); };

  const openModel = (m) => setActive(m.id);

  const loadCalc = () => { flash('Risk preset → Pre-Trade'); setTimeout(() => window.qeNav && window.qeNav('Pre-Trade'), 700); };

  const saveModel = (f) => {
    const source = { app: f.app, symbol: f.symbol, resolution: f.resolution, pointValue: parseFloat(f.pointValue) || 0,
      currency: f.currency, initialCapital: f.initialCapital, commission: f.commission, slippage: f.slippage };
    if (modal === 'edit' && model) {
      setModels(ms => ms.map(m => m.id === model.id ? {...m,
        name: f.name, type: f.type, desc: f.desc, updated: '2026-04-25',
        source: {...(m.source||{}), ...source},
        risk: {...m.risk, riskPct: f.riskPct, matchWindow: f.matchWindow, tp: f.tp, sl: f.sl, regimeMult: f.regimeMult},
        strategy: {...m.strategy, notes: f.notes, universe: f.universe},
      } : m));
      flash('Model updated');
    } else {
      const id = 'mdl_' + (f.name||'model').toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 24) + '_' + Math.floor(Math.random()*900+100);
      const runs = f._importReport ? [{
        id: 'run_' + id + '_1', source: f.app, file: f._importFile || 'import.xlsx',
        window: 'imported', imported: '2026-04-25 12:00', report: f._importReport,
      }] : [];
      setModels(ms => [{
        id, name: f.name, type: f.type, desc: f.desc, updated: '2026-04-25', tags: f._importReport ? ['new','imported'] : ['new'],
        source,
        risk: {riskPct: f.riskPct, sizing: 'Fixed fractional', matchWindow: f.matchWindow, tp: f.tp, sl: f.sl, regimeMult: f.regimeMult, sizeOverride: null},
        strategy: {notes: f.notes, entry: '—', exit: '—', universe: f.universe || '—', regimeCfg: f.regimeMult ? 'multiplier on' : 'multiplier off'},
        runs, usage: [],
      }, ...ms]);
      setActive(id);
      flash(f._importReport ? 'Model created + run imported' : 'Model created');
    }
    setModal(null);
  };

  const deleteModel = () => {
    if (!model) return;
    const id = model.id;
    setConfirmDel(false);
    setModels(ms => ms.filter(m => m.id !== id));
    setActive('overview');
    flash('Model deleted');
  };

  const confirmImport = () => { flash('Backtest report imported'); setModal(null); };

  const subtitle = model
    ? `${model.name} · ${model.type} model`
    : 'reusable, exchange-agnostic trading models · performance via import';

  const headerActions = model ? (
    <>
      <button className="qe-btn qe-btn-sm" onClick={() => setModal('edit')}>Edit</button>
      <button className="qe-btn qe-btn-sm qe-btn-on" onClick={loadCalc}>↪ Load into Pre-Trade</button>
      {confirmDel ? (
        <span style={{display:'inline-flex', gap:4, alignItems:'center'}}>
          <span style={{fontSize:'0.56rem', color:'var(--qe-red)', fontFamily:'var(--qe-mono)', fontWeight:700, letterSpacing:'0.04em'}}>DELETE “{model.name}”?</span>
          <button className="qe-btn qe-btn-sm qe-btn-danger" onClick={deleteModel}>Confirm</button>
          <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setConfirmDel(false)}>Cancel</button>
        </span>
      ) : (
        <button className="qe-btn qe-btn-sm qe-btn-danger" onClick={() => setConfirmDel(true)}>Delete</button>
      )}
    </>
  ) : (
    <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={() => setModal('new')}>+ New Model</button>
  );

  return (
    <div className="qe-scope" data-screen-label="06 Models" style={{width:'100%', height:'100%', background:'var(--qe-bg)', display:'flex', flexDirection:'column', overflow:'hidden', position:'relative'}}>
      <TopNavStd page="Models" variant="line" dense/>
      <PageHeader title="Models" subtitle={subtitle}>
        {headerActions}
      </PageHeader>

      <ModelTabStrip models={models} active={active}
        onSelect={setActive} onNew={() => setModal('new')}/>

      {active === 'overview' && <ModelOverview models={models} onOpen={openModel} onNew={() => setModal('new')}/>}
      {model && (
        <ModelView m={model} onImport={() => setModal('import')} onLoadCalc={loadCalc}/>
      )}

      {modal === 'new' && <ModelFormModal onClose={() => setModal(null)} onSave={saveModel}/>}
      {modal === 'edit' && model && <ModelFormModal model={model} onClose={() => setModal(null)} onSave={saveModel}/>}
      {modal === 'import' && model && <ImportModal model={model} onClose={() => setModal(null)} onConfirm={confirmImport}/>}

      {toast && (
        <div style={{position:'absolute', bottom:16, left:'50%', transform:'translateX(-50%)', zIndex:60,
          display:'flex', alignItems:'center', gap:8, padding:'7px 14px', background:'var(--qe-card)',
          border:'1px solid var(--qe-green)', boxShadow:'0 8px 30px var(--qe-bg)'}}>
          <span style={{width:7, height:7, borderRadius:'50%', background:'var(--qe-green)'}}/>
          <span className="qe-mono" style={{fontSize:'0.6rem', color:'var(--qe-text)'}}>{toast}</span>
        </div>
      )}
    </div>
  );
};

Object.assign(window, { ModelsPage, ModelTabStrip, ModelFormModal, ImportModal, ModelDialog });
