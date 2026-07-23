/* v3.0 P7 — Models library vocabulary: TypeBadge · KpiTile · KvMini ·
   ModelCard · ModelLibrary. Ported from the design reference
   (pages-models-lib.jsx) onto the REAL overview-feed rows
   (/api/models/overview: {…model, runs_count, latest_run, spark}).
   Loads after pages-models-data.jsx. */

const _MDLTYPE_TONE = { macro: 'info', micro: 'blue', both: 'mag' };
const TypeBadge = ({ type }) => (
  <Badge tone={_MDLTYPE_TONE[type] || 'mute'}>{mdlTypeLabel(type)}</Badge>
);

/* KPI tile — the reusable summary-stat card used across overview + report. */
const KpiTile = ({ label, value, sub, color }) => (
  <Card tight style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
    <div style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.5rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--qe-muted)' }}>{label}</div>
    <div className="qe-mono" style={{ fontSize: '0.92rem', fontWeight: 700, color: color || 'var(--qe-text)', lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    {sub && <div className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</div>}
  </Card>
);

const KvMini = ({ l, v, c }) => (
  <div style={{ minWidth: 0 }}>
    <div style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.5rem', fontWeight: 700, letterSpacing: '0.08em', color: 'var(--qe-muted)' }}>{l}</div>
    <div className="qe-mono" style={{ fontSize: '0.62rem', fontWeight: 700, color: c || 'var(--qe-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{v}</div>
  </div>
);

/* One library card — headline KPIs + sparkline from the model's latest
   completed imported run (the overview feed), or an honest "no runs" band. */
const ModelCard = ({ m, onOpen }) => {
  const k = mdlLatestKpis(m);
  const spark = m.spark || [];
  return (
    <div onClick={() => onOpen(m)} style={{ cursor: 'pointer', display: 'flex' }}>
      <Card ticks className="qe-model-card" style={{ display: 'flex', flexDirection: 'column', gap: 6, cursor: 'pointer', padding: '8px 10px', flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span style={{ fontFamily: 'var(--qe-ui)', fontWeight: 700, fontSize: '0.78rem', color: 'var(--qe-text)', letterSpacing: '0.01em' }}>{m.name}</span>
              <TypeBadge type={m.type} />
            </div>
            <div style={{ fontSize: '0.58rem', color: 'var(--qe-sub)', lineHeight: 1.4, marginTop: 3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{m.description}</div>
          </div>
        </div>

        {k ? (
          <React.Fragment>
            <div style={{ height: 26 }}>
              {spark.length > 1
                ? <Sparkline data={spark} height={26} color={k.net >= 0 ? 'var(--qe-green)' : 'var(--qe-red)'} />
                : <div style={{ height: 26 }} />}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 5 }}>
              <KvMini l="NET P/L" v={_mdlMoney(k.net, 0)} c={_mdlPl(k.net)} />
              <KvMini l="WIN %" v={k.winPct + '%'} />
              <KvMini l="PF" v={k.pf.toFixed(2)} c={k.pf >= 1.3 ? 'var(--qe-green)' : k.pf < 1 ? 'var(--qe-red)' : 'var(--qe-text)'} />
              <KvMini l="MAX DD" v={k.maxDDPct + '%'} c="var(--qe-red)" />
              <KvMini l="TRADES" v={k.nTrades} />
            </div>
          </React.Fragment>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '10px 4px', border: '1px dashed var(--qe-faint)' }}>
            <span style={{ color: 'var(--qe-amber)', fontSize: '0.7rem' }}>◇</span>
            <span style={{ fontSize: '0.58rem', color: 'var(--qe-muted)' }}>No backtests imported yet</span>
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 'auto', paddingTop: 4, borderTop: '1px solid var(--qe-faint)' }}>
          <span style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>updated {_mdlDate(m.updated_at || m.created_at)}</span>
          <span style={{ display: 'flex', gap: 4 }}>
            {(m.tags || []).slice(0, 2).map((t) => (
              <span key={t} style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', border: '1px solid var(--qe-faint)', padding: '0 3px' }}>{t}</span>
            ))}
          </span>
        </div>
      </Card>
    </div>
  );
};

/* Searchable / filterable card grid. `embedded` hides the + New button
   (the hosting Pane provides it). */
const ModelLibrary = ({ models, onOpen, onNew, embedded = false }) => {
  const [q, setQ] = React.useState('');
  const [type, setType] = React.useState('all');
  const [sort, setSort] = React.useState('updated');

  const filtered = (models || [])
    .filter((m) => type === 'all' || m.type === type)
    .filter((m) => {
      if (!q) return true;
      const needle = q.toLowerCase();
      return (m.name || '').toLowerCase().includes(needle)
        || (m.tags || []).some((t) => t.toLowerCase().includes(needle));
    })
    .sort((a, b) => {
      if (sort === 'updated') return String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || ''));
      if (sort === 'name') return String(a.name).localeCompare(String(b.name));
      const ka = mdlLatestKpis(a), kb = mdlLatestKpis(b);
      if (sort === 'net') return ((kb && kb.net) != null && kb ? kb.net : -1e9) - ((ka && ka.net) != null && ka ? ka.net : -1e9);
      if (sort === 'pf') return ((kb ? kb.pf : -1)) - ((ka ? ka.pf : -1));
      return 0;
    });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--qe-line)', flexShrink: 0, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', width: 200 }}>
          <input className="qe-input" placeholder="Search models…" value={q} onChange={(e) => setQ(e.target.value)} style={{ paddingLeft: 20 }} />
          <span style={{ position: 'absolute', left: 6, top: '50%', transform: 'translateY(-50%)', color: 'var(--qe-muted)', fontSize: '0.6rem', pointerEvents: 'none' }}>⌕</span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {[['all', 'All'], ...MDL_TYPES].map(([v, l]) => (
            <button key={v} className={`qe-btn qe-btn-sm ${type === v ? 'qe-btn-on' : ''}`} onClick={() => setType(v)}>{l}</button>
          ))}
        </div>
        <div className="qe-grow" />
        <span style={{ fontSize: '0.52rem', color: 'var(--qe-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Sort</span>
        <select className="qe-input qe-select" value={sort} onChange={(e) => setSort(e.target.value)} style={{ width: 120 }}>
          <option value="updated">Last updated</option>
          <option value="net">Net P/L</option>
          <option value="pf">Profit factor</option>
          <option value="name">Name</option>
        </select>
        {!embedded && <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onNew}>+ New Model</button>}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 10 }}>
        {filtered.length ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 10, alignItems: 'stretch' }}>
            {filtered.map((m) => <ModelCard key={m.id} m={m} onOpen={onOpen} />)}
          </div>
        ) : (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <EmptyState tone={(models || []).length ? 'neutral' : 'info'} glyph="◇"
              msg={(models || []).length ? 'No models match your filters' : 'No models yet'}
              hint={(models || []).length ? 'Clear the search or type filter.' : 'Create a reusable trading model, then import a backtest report to track its performance.'}
              cta={!(models || []).length && <button className="qe-btn qe-btn-sm qe-btn-primary" onClick={onNew}>+ New Model</button>} />
          </div>
        )}
      </div>
    </div>
  );
};

Object.assign(window, { TypeBadge, KpiTile, KvMini, ModelCard, ModelLibrary });
