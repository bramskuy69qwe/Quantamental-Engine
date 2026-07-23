/* v3.0 P7 — Models page: create/edit + import overlays + orchestrator.
   All flows hit the REAL backend (see pages-models-data.jsx endpoint map);
   the design's simulated parse/upload lanes are replaced by real multipart
   uploads with a server-side dry-run preview (G-M5). Dialog foots follow the
   last-submit pattern (DESIGN.md §5 non-fetch panes); page panes bind the
   overview feed's qeFootState line. */

/* Shared overlay shell — a Pane, layered (scrim + centering + close ✕). */
const ModelDialog = ({ title, onClose, width = 460, children, footer, foot = null, hot = true }) => (
  <div style={{ position: 'absolute', inset: 0, zIndex: 50, background: 'rgba(0,0,0,0.66)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}
    onClick={onClose}>
    <div onClick={(e) => e.stopPropagation()} style={{ width, maxWidth: '100%', maxHeight: '100%', display: 'flex', flexDirection: 'column', position: 'relative',
      background: 'var(--qe-card)', border: '1px solid var(--qe-line-2)', boxShadow: '0 24px 70px -16px var(--qe-bg)' }}>
      <PaneHead title={title} hot={hot}
        right={<button onClick={onClose} title="Close"
          style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14,
            border: '1px solid var(--qe-faint)', background: 'transparent', color: 'var(--qe-muted)', cursor: 'pointer',
            fontSize: '0.7rem', lineHeight: 1, padding: 0 }}
          onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--qe-red)'; e.currentTarget.style.borderColor = 'var(--qe-red)'; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--qe-muted)'; e.currentTarget.style.borderColor = 'var(--qe-faint)'; }}>✕</button>} />
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 10 }}>{children}</div>
      {foot && <PaneFoot {...foot} />}
      {footer && <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6, padding: '7px 9px', borderTop: '1px solid var(--qe-line)', background: 'var(--qe-panel)', flexShrink: 0 }}>{footer}</div>}
      <span className="qe-grip" style={{ pointerEvents: 'none' }} />
    </div>
  </div>
);

const _MdlField = ({ label, children, hint, error }) => (
  <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
    <span style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.52rem', fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: error ? 'var(--qe-red)' : 'var(--qe-sub)' }}>{label}</span>
    {children}
    {error ? <span style={{ fontSize: '0.5rem', color: 'var(--qe-red)' }}>{error}</span>
      : hint && <span style={{ fontSize: '0.5rem', color: 'var(--qe-muted)' }}>{hint}</span>}
  </label>
);

const _MdlSec = ({ title, sub, children }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.54rem', fontWeight: 700, letterSpacing: '0.16em', textTransform: 'uppercase', color: 'var(--qe-sub)', whiteSpace: 'nowrap' }}>{title}</span>
      {sub && <span style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', whiteSpace: 'nowrap' }}>{sub}</span>}
      <span style={{ flex: 1, height: 1, background: 'var(--qe-line)' }}></span>
    </div>
    {children}
  </div>
);

/* Hidden-input file picker button. */
const _MdlFileBtn = ({ label, onFile, className = 'qe-btn qe-btn-sm qe-btn-on', accept = '.xlsx,.xml' }) => {
  const ref = React.useRef(null);
  return (
    <React.Fragment>
      <input ref={ref} type="file" accept={accept} style={{ display: 'none' }}
        onChange={(e) => { const f = e.target.files && e.target.files[0]; if (f) onFile(f); e.target.value = ''; }} />
      <button className={className} onClick={() => ref.current && ref.current.click()}>{label}</button>
    </React.Fragment>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════
   CREATE / EDIT MODEL FORM — blank path or real from-report path (G-M5)
   ═══════════════════════════════════════════════════════════════════════════ */
const MDL_SOURCE_APPS = ['MultiCharts', 'TradeStation', 'NinjaTrader', 'Generic CSV'];

const ModelFormModal = ({ model, onClose, onSave }) => {
  const editing = !!model;
  const blank = {
    name: '', type: 'macro', desc: '', tags: '',
    app: 'MultiCharts', symbol: '', resolution: '', pointValue: '', currency: 'USD',
    initialCapital: '', commission: '', slippage: '',
    riskPct: '1.0', matchWindow: '90', tp: '', sl: '', regimeMult: false,
    entry: '', exit: '', notes: '', universe: '',
  };
  const fromModel = (m) => {
    const r = m.risk_preset || {}, s = m.strategy || {}, src = m.source || {};
    return {
      name: m.name || '', type: m.type || 'both', desc: m.description || '',
      tags: (m.tags || []).join(', '),
      app: src.app || 'MultiCharts', symbol: src.symbol || '', resolution: src.resolution || '',
      pointValue: src.point_value != null ? String(src.point_value) : '', currency: src.currency || 'USD',
      initialCapital: src.initial_capital != null ? String(src.initial_capital) : '',
      commission: src.commission || '', slippage: src.slippage || '',
      riskPct: r.risk_pct != null ? String(r.risk_pct) : '', matchWindow: r.window_seconds != null ? String(r.window_seconds) : '',
      tp: r.tp_methodology || '', sl: r.sl_methodology || '', regimeMult: !!r.apply_regime_multiplier,
      entry: s.entry_logic || '', exit: s.exit_logic || '', notes: s.notes || '', universe: s.target_universe || '',
    };
  };

  const [mode, setMode] = React.useState('blank');      // blank | import  (new only)
  const [f, setF] = React.useState(() => (editing ? fromModel(model) : blank));
  const [parsed, setParsed] = React.useState(null);     // {file(File), preview}
  const [busy, setBusy] = React.useState(false);
  const [subErr, setSubErr] = React.useState(null);
  const [touched, setTouched] = React.useState(false);
  const set = (k, v) => setF((p) => ({ ...p, [k]: v }));

  /* Real dry-run parse (server-side) → autofill from the report's Settings. */
  const doParse = async (file) => {
    setBusy(true); setSubErr(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('app_id', 'multicharts');
      const pv = await _mdlUpload('/api/models/import?dry_run=1', fd);
      setParsed({ file, preview: pv });
      const sug = pv.source_suggestion || {};
      const inputs = pv.settings || {};
      const rp = parseFloat(inputs.RiskPctOfEquity);
      setF((p) => ({
        ...p,
        name: p.name || [sug.symbol, sug.resolution].filter(Boolean).join(' ').trim(),
        symbol: sug.symbol || p.symbol, resolution: sug.resolution || p.resolution,
        pointValue: sug.point_value != null ? String(sug.point_value) : p.pointValue,
        currency: sug.currency || p.currency,
        initialCapital: sug.initial_capital != null ? String(sug.initial_capital) : p.initialCapital,
        commission: sug.commission || p.commission, slippage: sug.slippage || p.slippage,
        riskPct: Number.isFinite(rp) ? String(rp) : p.riskPct,
        universe: p.universe || sug.symbol || '',
      }));
    } catch (e) {
      setSubErr(e);
    }
    setBusy(false);
  };

  const errors = {
    name: !f.name.trim() ? 'Name is required' : null,
    riskPct: f.riskPct.trim() && !(parseFloat(f.riskPct) > 0 && parseFloat(f.riskPct) <= 100) ? 'Risk must be in (0, 100]' : null,
  };
  const valid = !errors.name && !errors.riskPct;

  const buildBody = () => {
    const risk = { ...((model && model.risk_preset) || {}), apply_regime_multiplier: f.regimeMult };
    if (f.riskPct.trim()) risk.risk_pct = parseFloat(f.riskPct); else delete risk.risk_pct;
    if (f.matchWindow.trim()) risk.window_seconds = parseInt(f.matchWindow, 10); else delete risk.window_seconds;
    if (f.tp.trim()) risk.tp_methodology = f.tp.trim(); else delete risk.tp_methodology;
    if (f.sl.trim()) risk.sl_methodology = f.sl.trim(); else delete risk.sl_methodology;
    const strategy = {
      ...((model && model.strategy) || {}),
      entry_logic: f.entry.trim(), exit_logic: f.exit.trim(),
      target_universe: f.universe.trim(), notes: f.notes.trim(),
    };
    const source = {};
    if (f.app.trim()) source.app = f.app.trim();
    if (f.symbol.trim()) source.symbol = f.symbol.trim();
    if (f.resolution.trim()) source.resolution = f.resolution.trim();
    if (f.pointValue.trim() && Number.isFinite(parseFloat(f.pointValue))) source.point_value = parseFloat(f.pointValue);
    if (f.currency.trim()) source.currency = f.currency.trim();
    if (f.initialCapital.trim() && Number.isFinite(parseFloat(f.initialCapital))) source.initial_capital = parseFloat(f.initialCapital);
    if (f.commission.trim()) source.commission = f.commission.trim();
    if (f.slippage.trim()) source.slippage = f.slippage.trim();
    return {
      name: f.name.trim(), type: f.type, description: f.desc.trim(),
      risk_preset: risk, strategy,
      source: Object.keys(source).length > 1 || source.symbol ? source : (editing ? (model.source || {}) : {}),
      tags: f.tags.split(',').map((t) => t.trim()).filter(Boolean),
    };
  };

  const submit = async () => {
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true); setSubErr(null);
    const body = buildBody();
    try {
      if (editing) {
        await _mdlSend('/api/models/' + model.id, 'PUT', body);
        onSave({ kind: 'updated', modelId: model.id });
      } else if (parsed) {
        const fd = new FormData();
        fd.append('file', parsed.file);
        fd.append('app_id', 'multicharts');
        fd.append('payload', JSON.stringify(body));
        const res = await _mdlUpload('/api/models/import', fd);
        onSave({ kind: 'created+imported', modelId: res.model_id, runId: res.run_id });
      } else {
        const res = await _mdlSend('/api/models', 'POST', body);
        onSave({ kind: 'created', modelId: res.model_id });
      }
    } catch (e) {
      setSubErr(e);
      setBusy(false);
    }
  };

  const seg = (val, label) => (
    <button key={val} onClick={() => { setMode(val); if (val === 'blank') setParsed(null); }}
      style={{ flex: 1, padding: '7px 0', fontFamily: 'var(--qe-ui)', fontSize: '0.58rem', fontWeight: 700, letterSpacing: '0.04em',
        cursor: 'pointer', border: '1px solid ' + (mode === val ? 'var(--qe-cyan)' : 'var(--qe-line)'),
        background: mode === val ? 'var(--qe-bg-cyan)' : 'transparent', color: mode === val ? 'var(--qe-cyan)' : 'var(--qe-sub)' }}>{label}</button>
  );

  /* last-submit foot (non-fetch pane, DESIGN.md §5) */
  const foot = busy ? { tone: 'sub', busy: true, msg: parsed && !editing ? 'uploading…' : 'saving…' }
    : subErr ? { tone: 'err', msg: qeFootCause(subErr) + ' — ' + String(subErr.message || '').slice(0, 60) }
    : parsed ? { tone: 'ok', msg: `parsed ${parsed.file.name} · fields auto-filled` }
    : { tone: 'sub', msg: 'ok · local — nothing submitted yet' };

  const pvk = parsed ? mdlRunKpis(parsed.preview.summary) : null;

  return (
    <ModelDialog title={editing ? `Edit Model · ${model.name}` : 'New Model'} width={640} onClose={onClose}
      foot={foot}
      footer={<React.Fragment>
        <button className="qe-btn qe-btn-sm" onClick={onClose}>Cancel</button>
        <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={!valid || busy}
          onClick={submit} style={!valid || busy ? { opacity: 0.5, cursor: 'not-allowed' } : {}}>
          {editing ? 'Save changes' : parsed ? 'Create model + import run' : 'Create model'}</button>
      </React.Fragment>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20, padding: '4px 6px' }}>

        {!editing && (
          <div style={{ display: 'flex', gap: 6 }}>
            {seg('blank', '+ Blank model')}
            {seg('import', '⤓ From backtest report')}
          </div>
        )}

        {!editing && mode === 'import' && (
          <_MdlSec title="Import Backtest Report" sub="MultiCharts .xlsx / .xml">
            {!parsed ? (
              <div style={{ border: '1px dashed var(--qe-line-2)', padding: '22px 16px', textAlign: 'center', background: 'var(--qe-panel)' }}>
                <div style={{ fontSize: '1.3rem', color: 'var(--qe-muted)', lineHeight: 1 }}>⤓</div>
                <div style={{ fontSize: '0.62rem', color: 'var(--qe-sub)', marginTop: 8 }}>Pick a report to auto-fill the model</div>
                <div style={{ fontSize: '0.52rem', color: 'var(--qe-muted)', marginTop: 4 }}>parses the Settings sheet — symbol, point value, resolution, risk inputs</div>
                <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginTop: 14 }}>
                  {busy ? <Spinner label="parsing" /> : <_MdlFileBtn label="Choose file…" onFile={doParse} />}
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Badge tone="ok">PARSED</Badge>
                  <span className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-text)' }}>{parsed.file.name}</span>
                  <div className="qe-grow"></div>
                  <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setParsed(null)}>Clear</button>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
                  <KpiTile label="Net P/L" value={_mdlMoney(pvk.net, 0)} color={_mdlPl(pvk.net)} />
                  <KpiTile label="Profit Factor" value={pvk.pf.toFixed(2)} color={pvk.pf >= 1 ? 'var(--qe-green)' : 'var(--qe-red)'} />
                  <KpiTile label="Win %" value={pvk.winPct + '%'} />
                  <KpiTile label="Trades" value={pvk.nTrades} />
                </div>
                {(parsed.preview.warnings || []).map((w, i) => (
                  <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.54rem', color: 'var(--qe-amber)' }}>
                    <span>!</span><span>{w}</span>
                  </div>
                ))}
                <div style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>Fields below were auto-filled from the report — edit anything before creating. Nothing is saved until you confirm.</div>
              </div>
            )}
          </_MdlSec>
        )}

        <_MdlSec title="Identity">
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '14px 12px' }}>
            <_MdlField label="Name" error={touched && errors.name}>
              <input className="qe-input" value={f.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. BTC Macro Trend" />
            </_MdlField>
            <_MdlField label="Type">
              <select className="qe-input qe-select" value={f.type} onChange={(e) => set('type', e.target.value)}>
                {MDL_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </_MdlField>
            <_MdlField label="Description" hint="One or two lines — shown on the library card.">
              <textarea className="qe-input" rows={2} value={f.desc} onChange={(e) => set('desc', e.target.value)} style={{ resize: 'vertical', lineHeight: 1.4 }} />
            </_MdlField>
            <_MdlField label="Tags" hint="comma-separated">
              <input className="qe-input" value={f.tags} onChange={(e) => set('tags', e.target.value)} placeholder="trend, core" />
            </_MdlField>
          </div>
        </_MdlSec>

        <_MdlSec title="Source Binding" sub="where the model was backtested (§3 — the model owns it)">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '14px 12px' }}>
            <_MdlField label="Source app">
              <select className="qe-input qe-select" value={f.app} onChange={(e) => set('app', e.target.value)}>
                {MDL_SOURCE_APPS.concat(MDL_SOURCE_APPS.indexOf(f.app) < 0 && f.app ? [f.app] : []).map((a) => <option key={a}>{a}</option>)}
              </select>
            </_MdlField>
            <_MdlField label="Symbol">
              <input className="qe-input" value={f.symbol} onChange={(e) => set('symbol', e.target.value)} placeholder="@ES" />
            </_MdlField>
            <_MdlField label="Resolution">
              <input className="qe-input" value={f.resolution} onChange={(e) => set('resolution', e.target.value)} placeholder="1 Minute" />
            </_MdlField>
            <_MdlField label="Point value">
              <input className="qe-input" type="number" step="1" value={f.pointValue} onChange={(e) => set('pointValue', e.target.value)} placeholder="50" />
            </_MdlField>
            <_MdlField label="Currency">
              <input className="qe-input" value={f.currency} onChange={(e) => set('currency', e.target.value)} placeholder="USD" />
            </_MdlField>
            <_MdlField label="Initial capital">
              <input className="qe-input" type="number" step="1000" value={f.initialCapital} onChange={(e) => set('initialCapital', e.target.value)} />
            </_MdlField>
            <_MdlField label="Commission">
              <input className="qe-input" value={f.commission} onChange={(e) => set('commission', e.target.value)} />
            </_MdlField>
            <_MdlField label="Slippage">
              <input className="qe-input" value={f.slippage} onChange={(e) => set('slippage', e.target.value)} />
            </_MdlField>
          </div>
        </_MdlSec>

        <_MdlSec title="Risk & Sizing Preset">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 12px' }}>
            <_MdlField label="Risk / trade (%)" error={touched && errors.riskPct}>
              <input className="qe-input" type="number" step="0.05" value={f.riskPct} onChange={(e) => set('riskPct', e.target.value)} />
            </_MdlField>
            <_MdlField label="Match window (s)">
              <input className="qe-input" type="number" step="5" value={f.matchWindow} onChange={(e) => set('matchWindow', e.target.value)} />
            </_MdlField>
            <_MdlField label="TP methodology">
              <input className="qe-input" value={f.tp} onChange={(e) => set('tp', e.target.value)} placeholder="ATR × 2.5" />
            </_MdlField>
            <_MdlField label="SL methodology">
              <input className="qe-input" value={f.sl} onChange={(e) => set('sl', e.target.value)} placeholder="ATR × 1.2" />
            </_MdlField>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
            <Switch checked={f.regimeMult} onChange={() => set('regimeMult', !f.regimeMult)} accent="var(--qe-cyan)" />
            <span style={{ fontSize: '0.6rem', color: 'var(--qe-sub)' }}>Apply regime multiplier</span>
          </div>
        </_MdlSec>

        <_MdlSec title="Strategy">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px 12px' }}>
              <_MdlField label="Entry logic">
                <input className="qe-input" value={f.entry} onChange={(e) => set('entry', e.target.value)} />
              </_MdlField>
              <_MdlField label="Exit logic">
                <input className="qe-input" value={f.exit} onChange={(e) => set('exit', e.target.value)} />
              </_MdlField>
            </div>
            <_MdlField label="Target universe">
              <input className="qe-input" value={f.universe} onChange={(e) => set('universe', e.target.value)} placeholder="e.g. BTCUSDT perp" />
            </_MdlField>
            <_MdlField label="Notes" hint="Freeform strategy definition.">
              <textarea className="qe-input" rows={3} value={f.notes} onChange={(e) => set('notes', e.target.value)} style={{ resize: 'vertical', lineHeight: 1.5 }} />
            </_MdlField>
          </div>
        </_MdlSec>
      </div>
    </ModelDialog>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════
   IMPORT BACKTEST FLOW (existing model) — real dry-run preview → confirm
   ═══════════════════════════════════════════════════════════════════════════ */
const ImportModal = ({ model, onClose, onDone }) => {
  const [step, setStep] = React.useState('source');   // source | upload | preview | error
  const [file, setFile] = React.useState(null);
  const [preview, setPreview] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);

  const doPreview = async (f) => {
    setBusy(true); setErr(null); setFile(f);
    try {
      const fd = new FormData();
      fd.append('file', f);
      fd.append('app_id', 'multicharts');
      const pv = await _mdlUpload(`/models/${model.id}/backtest-upload?format=json&dry_run=1`, fd);
      setPreview(pv); setStep('preview');
    } catch (e) { setErr(e); setStep('error'); }
    setBusy(false);
  };

  const doConfirm = async () => {
    if (!file || busy) return;
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('app_id', 'multicharts');
      const res = await _mdlUpload(`/models/${model.id}/backtest-upload?format=json`, fd);
      onDone(res);
    } catch (e) { setErr(e); setStep('error'); setBusy(false); }
  };

  const foot = busy ? { tone: 'sub', busy: true, msg: step === 'preview' ? 'importing…' : 'parsing…' }
    : err ? { tone: 'err', msg: qeFootCause(err) + ' — ' + String(err.message || '').slice(0, 60) }
    : preview ? { tone: 'ok', msg: `parsed ${preview.file} · nothing saved yet` }
    : { tone: 'sub', msg: 'ok · local — nothing uploaded yet' };

  const pvk = preview ? mdlRunKpis(preview.summary) : null;

  return (
    <ModelDialog title={`Import Report → ${model.name}`} width={480} onClose={onClose} foot={foot}
      footer={
        step === 'preview' ? <React.Fragment>
          <button className="qe-btn qe-btn-sm" onClick={() => setStep('upload')}>Back</button>
          <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={busy} onClick={doConfirm}>Confirm import</button>
        </React.Fragment> :
        step === 'error' ? <button className="qe-btn qe-btn-sm" onClick={() => { setErr(null); setStep('upload'); }}>Try another file</button> :
        step === 'upload' ? <button className="qe-btn qe-btn-sm" onClick={() => setStep('source')}>Back</button>
        : null
      }>
      <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
        {['source', 'upload', 'preview'].map((s, i) => {
          const active = step === s;
          const done = ['source', 'upload', 'preview'].indexOf(step) > i || (step === 'error' && i < 2);
          return (
            <div key={s} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 16, height: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                border: `1px solid ${active ? 'var(--qe-cyan)' : done ? 'var(--qe-green)' : 'var(--qe-faint)'}`,
                color: active ? 'var(--qe-cyan)' : done ? 'var(--qe-green)' : 'var(--qe-muted)', fontSize: '0.5rem', fontFamily: 'var(--qe-mono)', fontWeight: 700 }}>{done ? '✓' : i + 1}</span>
              <span style={{ fontSize: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: active ? 'var(--qe-cyan)' : 'var(--qe-muted)' }}>{s}</span>
            </div>
          );
        })}
      </div>

      {step === 'source' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <_MdlField label="Source application" hint="More backtesting apps will be supported over time.">
            <select className="qe-input qe-select" defaultValue="MultiCharts">
              <option>MultiCharts</option>
            </select>
          </_MdlField>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={() => setStep('upload')}>Next →</button>
          </div>
        </div>
      )}

      {step === 'upload' && (
        <div style={{ border: '1px dashed var(--qe-line-2)', padding: '26px 16px', textAlign: 'center', background: 'var(--qe-panel)' }}>
          <div style={{ fontSize: '1.4rem', color: 'var(--qe-muted)', lineHeight: 1 }}>⤓</div>
          <div style={{ fontSize: '0.62rem', color: 'var(--qe-sub)', marginTop: 8 }}>Pick a MultiCharts report</div>
          <div style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', marginTop: 3 }}>.xlsx or .xml — performance summary + trade list</div>
          <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginTop: 12 }}>
            {busy ? <Spinner label="parsing" /> : <_MdlFileBtn label="Choose file…" onFile={doPreview} />}
          </div>
        </div>
      )}

      {step === 'preview' && preview && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <Badge tone="ok">PARSED</Badge>
            <span className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-text)' }}>{preview.file}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 7 }}>
            <KpiTile label="Net Profit" value={_mdlMoney(pvk.net, 0)} color={_mdlPl(pvk.net)} />
            <KpiTile label="Profit Factor" value={pvk.pf.toFixed(2)} color={pvk.pf >= 1.3 ? 'var(--qe-green)' : 'var(--qe-text)'} />
            <KpiTile label="Win %" value={pvk.winPct + '%'} />
            <KpiTile label="Max DD" value={pvk.maxDDPct + '%'} color="var(--qe-red)" />
            <KpiTile label="Sharpe" value={pvk.sharpe.toFixed(2)} />
            <KpiTile label="Trades" value={pvk.nTrades} />
          </div>
          <div style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>
            {preview.session_name} · {preview.trades_count} trades · {(preview.sheets || []).length} sheets captured
          </div>
          {(preview.warnings || []).map((w, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: '0.54rem', color: 'var(--qe-amber)' }}>
              <span>!</span><span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {step === 'error' && (
        <EmptyState tone="err" glyph="✗" msg="Import failed"
          hint={err ? String(err.message || qeFootCause(err)) : 'Unrecognized file format.'} />
      )}
    </ModelDialog>
  );
};

/* ═══════════════════════════════════════════════════════════════════════════
   ORCHESTRATOR
   ═══════════════════════════════════════════════════════════════════════════ */
const ModelTabStrip = ({ models, active, onSelect, onNew }) => (
  <TabStrip value={active} onChange={onSelect}
    tabs={[['overview', 'Overview'], ...(models || []).map((m) => [m.id, m.name])]}
    right={<button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={onNew} title="New model"
      style={{ alignSelf: 'center', marginLeft: 6, fontSize: '0.9rem', lineHeight: 1, padding: '0 8px' }}>+</button>} />
);

const ModelsPage = () => {
  const { data, err, foot: ovFoot, reload } = useAnaJson('/api/models/overview');
  const models = (data && data.models) || [];

  const [active, setActive] = React.useState('overview'); // 'overview' | model id
  const [modal, setModal] = React.useState(null);         // null | 'new' | 'edit' | 'import'
  const importDoneRef = React.useRef(null);               // ImportModal → refresh runs/usage
  const [toast, setToast] = React.useState(null);
  const [confirmDel, setConfirmDel] = React.useState(false);

  React.useEffect(() => { setConfirmDel(false); }, [active]);
  React.useEffect(() => {
    if (!confirmDel) return undefined;
    const t = setTimeout(() => setConfirmDel(false), 4000);
    return () => clearTimeout(t);
  }, [confirmDel]);

  const model = active !== 'overview' ? models.find((m) => m.id === active) || null : null;
  // A deleted / vanished model falls back to Overview once the feed refreshes.
  React.useEffect(() => {
    if (active !== 'overview' && data && !models.some((m) => m.id === active)) setActive('overview');
  }, [data, active]);

  const toastTimer = React.useRef(null);
  // tone: 'ok' (default) | 'err' — failures must not wear success chrome
  // (P8 audit L6-LOW-1: "Delete failed" rendered in the green toast).
  const flash = (msg, tone = 'ok') => {
    setToast({ msg, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  };
  React.useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  const loadCalc = (id) => {
    try { history.replaceState(null, '', '?model_id=' + id + window.location.hash); } catch (e) {}
    flash('Risk preset → Pre-Trade');
    setTimeout(() => window.qeNav && window.qeNav('Pre-Trade'), 400);
  };

  const onFormSave = async (res) => {
    setModal(null);
    // MED-1 fold: activate the new tab only AFTER the feed carries the
    // new id — the vanish-guard effect would otherwise bounce straight
    // back to Overview (reload() resolves post-setData).
    await reload();
    if (res.kind === 'updated') flash('Model updated');
    else if (res.kind === 'created+imported') { flash('Model created + run imported'); setActive(res.modelId); }
    else { flash('Model created'); setActive(res.modelId); }
  };

  const deleteModel = async () => {
    if (!model) return;
    setConfirmDel(false);
    try {
      await _mdlSend('/api/models/' + model.id, 'DELETE');
      setActive('overview');
      reload();
      flash('Model deleted');
    } catch (e) { flash('Delete failed: ' + qeFootCause(e), 'err'); }
  };

  const onImportDone = (res) => {
    setModal(null);
    reload();
    if (importDoneRef.current) { try { importDoneRef.current(); } catch (e) {} importDoneRef.current = null; }
    flash(`Backtest report imported (run #${res.run_id})`);
  };

  const subtitle = model
    ? `${model.name} · ${mdlTypeLabel(model.type)} model`
    : 'reusable, exchange-agnostic trading models · performance via import';

  const headerActions = model ? (
    <React.Fragment>
      <button className="qe-btn qe-btn-sm" onClick={() => setModal('edit')}>Edit</button>
      <button className="qe-btn qe-btn-sm qe-btn-on" onClick={() => loadCalc(model.id)}>↪ Load into Pre-Trade</button>
      {confirmDel ? (
        <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: '0.56rem', color: 'var(--qe-red)', fontFamily: 'var(--qe-mono)', fontWeight: 700, letterSpacing: '0.04em' }}>DELETE “{model.name}” + its runs?</span>
          <button className="qe-btn qe-btn-sm qe-btn-danger" onClick={deleteModel}>Confirm</button>
          <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setConfirmDel(false)}>Cancel</button>
        </span>
      ) : (
        <button className="qe-btn qe-btn-sm qe-btn-danger" onClick={() => setConfirmDel(true)}>Delete</button>
      )}
    </React.Fragment>
  ) : (
    <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={() => setModal('new')}>+ New Model</button>
  );

  return (
    <div className="qe-scope" data-screen-label="06 Models" style={{ width: '100%', height: '100%', background: 'var(--qe-bg)', display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
      <TopNavStd page="Models" variant="line" dense />
      <PageHeader title="Models" subtitle={subtitle}>
        {headerActions}
      </PageHeader>

      <ModelTabStrip models={models} active={active}
        onSelect={setActive} onNew={() => setModal('new')} />

      {active === 'overview' && (
        err && !data ? (
          <div style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <EmptyState tone="err" glyph="✗" msg="models feed unavailable" hint={qeFootCause(err)}
              cta={<button className="qe-btn qe-btn-sm" onClick={reload}>Retry</button>} />
          </div>
        ) : (
          <ModelOverview models={models} foot={ovFoot} onOpen={(m) => setActive(m.id)} onNew={() => setModal('new')} />
        )
      )}
      {model && (
        // key: a model switch remounts the whole view — no cross-model
        // stale frame / phantom report fetch (P7 audit LOW-2).
        <ModelView key={model.id} m={model} ovFoot={ovFoot}
          onImport={(refresh) => { importDoneRef.current = refresh || null; setModal('import'); }}
          onLoadCalc={() => loadCalc(model.id)} />
      )}

      {modal === 'new' && <ModelFormModal onClose={() => setModal(null)} onSave={onFormSave} />}
      {modal === 'edit' && model && <ModelFormModal model={model} onClose={() => setModal(null)} onSave={onFormSave} />}
      {modal === 'import' && model && <ImportModal model={model} onClose={() => { importDoneRef.current = null; setModal(null); }} onDone={onImportDone} />}

      {toast && (
        <div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)', zIndex: 60,
          display: 'flex', alignItems: 'center', gap: 8, padding: '7px 14px', background: 'var(--qe-card)',
          border: `1px solid ${toast.tone === 'err' ? 'var(--qe-red)' : 'var(--qe-green)'}`, boxShadow: '0 8px 30px var(--qe-bg)' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: toast.tone === 'err' ? 'var(--qe-red)' : 'var(--qe-green)' }} />
          <span className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-text)' }}>{toast.msg}</span>
        </div>
      )}
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { ModelsPage, ModelTabStrip, ModelFormModal, ImportModal, ModelDialog });
