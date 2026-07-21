/* ─────────────────────────────────────────────────────────────────────────
   linkage.jsx — Linkage · "Triage Board"
   Calm secondary monitor. The left MANUAL LINK pane unifies needs-link orders +
   manual-close nudges into ONE queue, resolved with the side-by-side pattern
   (queue strip → candidate list + per-criterion diff, or reason picker). The
   right is a tiling wall of monitors — every pane is the standard Pane +
   DataList primitive. Lays out in a GridWorkspace (drag / resize).
   ───────────────────────────────────────────────────────────────────────── */

// compact key/value cell used across both resolvers
// KV (key/value cell) is now a shared primitive (primitives.jsx) — used here via the global.

// inbox detail — link order: candidate list + per-criterion diff

// ── ticking ages — seed age + elapsed session time, so "41s ago" stays true
const L_T0 = Date.now();
const useTickAge = (seed) => {
  const [, f] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => { const t = setInterval(f, 1000); return () => clearInterval(t); }, []);
  return seed + Math.round((Date.now() - L_T0) / 1000);
};
const fmtAgeS = (s) => s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s/60)}m ${String(s%60).padStart(2,'0')}s` : `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`;
const TickAge = ({seed, suffix=' ago'}) => { const a = useTickAge(seed); return <React.Fragment>{fmtAgeS(a)}{suffix}</React.Fragment>; };

// ── live mark/uPnL cells — read the SAME shared per-symbol walk as the
// Dashboard book (window.useQePosMark), so the two pages can never disagree.
const _dashRow = sym => (window.MOCK?.positionsOpen || []).find(p => p.sym === sym);
const LMarkLive = ({r, d}) => { const {mark} = window.useQePosMark(d); return <React.Fragment>{fmtPx(r.sym, mark)}</React.Fragment>; };
const LMark = ({r}) => { const d = _dashRow(r.sym); return d ? <LMarkLive r={r} d={d}/> : <React.Fragment>{fmtPx(r.sym, r.mark)}</React.Fragment>; };
const LUpnlLive = ({r, d}) => { const {mark} = window.useQePosMark(d);
  const v = r.upnl + (mark - r.mark) * r.size * (r.dir === 'LONG' ? 1 : -1);
  return <span style={{ color: sgn(v), fontWeight: 700 }}>{fmtUsd(v)}</span>; };
const LUpnl = ({r}) => { const d = _dashRow(r.sym); return d ? <LUpnlLive r={r} d={d}/> : <span style={{ color: sgn(r.upnl), fontWeight: 700 }}>{fmtUsd(r.upnl)}</span>; };

const LinkResolver = ({ item, onResolve }) => {
  const [selCand, setSelCand] = React.useState(item.candidates[0]?.calc_id);
  const cand = item.candidates.find(c => c.calc_id === selCand) || item.candidates[0];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.sym}</span>
        <Badge tone={item.dir === 'LONG' ? 'ok' : 'err'}>{item.dir}</Badge>
        <LinkBadge status={item.status} variant={1} />
        <div className="qe-grow" />
        <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>{item.ts} · <TickAge seed={item.age_s}/></span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)', marginBottom: 8 }}>
        <KV l="Order" v={`#${item.order_id}`} />
        <KV l="Type" v={item.type} />
        <KV l="Price" v={fmtPx(item.sym, item.price)} color="var(--qe-cyan)" />
        <KV l="Size" v={item.size} />
        <KV l="Notional" v={`${item.notional} U`} />
        <KV l="Operator" v={item.operator} />
        <KV l="Client order id" v={item.client_oid} span />
      </div>
      {item.candidates.length === 0 ? (
        <EmptyState tone="warn" glyph="∅" msg="No candidate calcs in window" hint="Window expired — mark unplanned or wait for a fresh calc." />
      ) : (
        <>
          <div className="qe-lbl" style={{ margin: '2px 0 5px' }}>Candidate calcs · {item.candidates.length}</div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 6 }}>
            {item.candidates.map(c => {
              const on = c.calc_id === selCand;
              return (
                <button key={c.calc_id} onClick={() => setSelCand(c.calc_id)} style={{
                  display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', cursor: 'pointer',
                  background: on ? 'var(--qe-active)' : 'var(--qe-panel)', border: `1px solid ${on ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
                }}>
                  <span className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>{c.calc_id.replace('CALC-', '')}</span>
                  <Badge tone={c.best ? 'warn' : 'mute'}>{c.score}</Badge>
                  {c.best && <span style={{ fontSize: '0.5rem', color: 'var(--qe-amber)', letterSpacing: '0.08em' }}>BEST</span>}
                </button>
              );
            })}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', padding: '0 2px 6px', fontFamily: 'var(--qe-mono)', fontSize: '0.52rem', color: 'var(--qe-muted)' }}>
            <span style={{ color: 'var(--qe-sub)' }}>{cand.model}</span>
            <span>created {cand.created} (<TickAge seed={cand.age_s} suffix=""/>)</span>
            <span>R {cand.r}</span>
            {cand.tags && cand.tags.map(t => <span key={t} style={{ color: 'var(--qe-purple)' }}>#{t}</span>)}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '70px 1fr 1fr 46px', gap: 6, padding: '0 6px 2px', fontFamily: 'var(--qe-mono)', fontSize: '0.5rem', color: 'var(--qe-muted)', letterSpacing: '0.06em' }}>
            <span>CRITERION</span><span>CALC {cand.calc_id.replace('CALC-', '')}</span><span>ORDER #{item.order_id}</span><span style={{ textAlign: 'right' }}>MATCH</span>
          </div>
          <MatchDiff candidate={cand} compact />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingTop: 8 }}>
            <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>{cand.score} — {cand.score === '6 / 6' ? 'eligible' : 'below 6/6 threshold'}</span>
            <div className="qe-grow" />
            <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => onResolve(item, 'unplanned')}>UNPLANNED</button>
            <button className="qe-btn qe-btn-sm qe-btn-success" title={`Link ${cand.calc_id}`} onClick={() => onResolve(item, 'link', cand.calc_id)}>Link</button>
          </div>
        </>
      )}
    </div>
  );
};

// inbox detail — manual close: reason picker
const ReasonResolver = ({ item, onResolve }) => {
  const [pick, setPick] = React.useState(null);
  const [note, setNote] = React.useState('');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.sym}</span>
        <Badge tone={item.dir === 'LONG' ? 'ok' : 'err'}>{item.dir}</Badge>
        <span className="qe-mono" style={{ fontWeight: 700, color: sgn(item.pnl) }}>{fmtUsd(item.pnl)} ({fmtPct(item.pct)})</span>
        <div className="qe-grow" />
        <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>closed {item.ts}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)', marginBottom: 8 }}>
        <KV l="Entry" v={fmtPx(item.sym, item.entry)} />
        <KV l="Exit" v={fmtPx(item.sym, item.exit)} />
        <KV l="Hold" v={item.hold} />
        <KV l="Funding" v={fmtUsd(item.funding, 3)} color={sgn(item.funding)} />
        <KV l="Closed at" v={item.ts} />
        <KV l="Detected" v="opposite-side mkt" />
      </div>
      <div className="qe-mono" style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', marginBottom: 7 }}>No calc matched this close — categorize it (optional, never blocks).</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, marginBottom: 8 }}>
        {window.L_MANUAL_REASONS.map(r => (
          <button key={r.key} onClick={() => setPick(r.key)} style={{
            textAlign: 'left', padding: '6px 8px', cursor: 'pointer',
            background: pick === r.key ? 'var(--qe-active)' : 'var(--qe-panel)',
            border: `1px solid ${pick === r.key ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
          }}>
            <div className="qe-mono" style={{ fontSize: '0.6rem', fontWeight: 700, color: pick === r.key ? 'var(--qe-cyan)' : 'var(--qe-text)' }}>{r.label}</div>
            <div style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', marginTop: 2, lineHeight: 1.3 }}>{r.hint}</div>
          </button>
        ))}
      </div>
      <input className="qe-input" placeholder="optional note…" value={note} onChange={e => setNote(e.target.value)} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
        <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => onResolve(item, 'later')}>Later</button>
        <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={!pick} style={{ opacity: pick ? 1 : 0.45 }} onClick={() => onResolve(item, 'reason', pick)}>Save</button>
      </div>
    </div>
  );
};

// Funding settlement countdown — ticks down from L_FUNDING.countdown_s (anchored at load).
const SettleCountdown = () => {
  const [s, setS] = React.useState(window.L_FUNDING.countdown_s);
  React.useEffect(() => {
    const t0 = Date.now(), base = window.L_FUNDING.countdown_s;
    const iv = setInterval(() => setS(Math.max(0, base - Math.round((Date.now() - t0) / 1000))), 1000);
    return () => clearInterval(iv);
  }, []);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return <>next settle {window.L_FUNDING.next_settlement} · in {h}h {String(m).padStart(2, '0')}m {String(sec).padStart(2, '0')}s</>;
};

const DashLinkA = () => {
  const [resolved, setResolved] = React.useState({});
  const [toast, setToast] = React.useState(null);
  const [sync, setSync] = React.useState({ n: 0, ms: 42 });
  const flash = (m, ms = 2200) => { setToast(m); setTimeout(() => setToast(null), ms); };
  const refreshPositions = () => {
    const ms = 28 + Math.floor(Math.random() * 44);
    setSync(s => ({ n: s.n + 1, ms }));
    flash(`Open positions re-synced · ${window.L_POSITIONS.length} live · ${ms}ms`);
  };

  // Active calcs are state, not static data: when a link window expires the
  // calc leaves the Active list and a fresh mock calc takes its place (stands
  // in for new calcs arriving from Pre-Trade — keeps countdown + list honest).
  const [calcs, setCalcs] = React.useState(() => window.L_CALCS.map(c => ({ ...c })));
  React.useEffect(() => {
    const iv = setInterval(() => {
      setCalcs(cs => {
        const now = Date.now();
        let changed = false;
        const next = cs.map(c => {
          if (c.status !== 'active' || c.expiry > now) return c;
          changed = true;
          const id = 'CALC-' + Math.floor(Math.random() * 0xffff).toString(16).padStart(4, '0');
          // stagger the fresh window (30–100% remaining) so countdowns never tick in lockstep
          return { ...c, id, expiry: now + Math.round((0.3 + Math.random() * 0.7) * c.window) * 1000 };
        });
        return changed ? next : cs;
      });
    }, 2000);
    return () => clearInterval(iv);
  }, []);
  const activeCalcs = calcs.filter(c => c.status === 'active');

  const inbox = [
    ...window.L_NEEDS_LINK.filter(o => o.status === 'NEEDS_MANUAL_REVIEW' || o.status === 'UNLINKED').map(o => ({ ...o, kind: 'link', key: 'L' + o.order_id })),
    ...window.L_CLOSES.filter(c => c.pending_reason).map(c => ({ ...c, kind: 'close', key: 'C' + c.id })),
  ].filter(x => !resolved[x.key]);

  const [sel, setSel] = React.useState(inbox[0]?.key);
  const active = inbox.find(i => i.key === sel) || inbox[0];

  const resolve = (item, action, val) => {
    setResolved(r => ({ ...r, [item.key]: { action, val } }));
    const rest = inbox.filter(i => i.key !== item.key);
    setSel(rest[0]?.key);
    const msg = action === 'link' ? `Order #${item.order_id} linked to ${val}`
      : action === 'unplanned' ? `Order #${item.order_id} marked UNPLANNED`
      : action === 'reason' ? `${item.sym} close → ${(window.L_EXIT_REASONS['MANUAL_' + val] || {}).label || val}`
      : `${item.sym} left uncategorized — set later from History`;
    setToast(msg); setTimeout(() => setToast(null), 2600);
  };

  // ── standardized DataList column schemas (one row height everywhere) ──────
  const posCols = [
    { key: 'sym', label: 'Sym', render: r => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.sym.replace('USDT', '')}</span> },
    { key: 'dir', label: 'Side', render: r => <Badge tone={r.dir === 'LONG' ? 'ok' : 'err'}>{r.dir[0]}</Badge> },
    { key: 'size', label: 'Size', align: 'right', render: r => r.size },
    { key: 'entry', label: 'Entry', align: 'right', render: r => <span style={{ color: 'var(--qe-sub)' }}>{fmtPx(r.sym, r.entry)}</span> },
    { key: 'mark', label: 'Mark', align: 'right', render: r => <LMark r={r}/> },
    { key: 'upnl', label: 'uPnL', align: 'right', render: r => <LUpnl r={r}/> },
    { key: 'tpsl', label: 'TP / SL', align: 'right', render: r => <span style={{ fontSize: '0.56rem' }}><span className="qe-up">{r.tp_live ? fmtPx(r.sym, r.tp_live) : '—'}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span className="qe-dn">{r.sl_live ? fmtPx(r.sym, r.sl_live) : '—'}</span></span> },
    { key: 'link', label: 'Link', render: r => <LinkBadge status={r.link} variant={1} /> },
    { key: 'dev', label: 'Plan deviation', render: r => <DevBadge pos={r} variant={2} /> },
  ];
  const calcCols = [
    { key: 'sym', label: 'Sym', render: r => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.sym.replace('USDT', '')}</span> },
    { key: 'dir', label: 'Side', render: r => <Badge tone={r.dir === 'LONG' ? 'ok' : 'err'}>{r.dir[0]}</Badge> },
    { key: 'entry', label: 'Entry', align: 'right', render: r => fmtPx(r.sym, r.entry) },
    { key: 'tp', label: 'TP', align: 'right', render: r => <span className="qe-up">{fmtPx(r.sym, r.tp)}</span> },
    { key: 'sl', label: 'SL', align: 'right', render: r => <span className="qe-dn">{fmtPx(r.sym, r.sl)}</span> },
    { key: 'r', label: 'R', align: 'right', render: r => <span style={{ color: 'var(--qe-cyan)' }}>{r.r}</span> },
    { key: 'cd', label: 'Link window', align: 'right', render: r => <CalcCountdown expiry={r.expiry} window={r.window} variant="ring" /> },
  ];
  const fundCols = [
    { key: 'sym', label: 'Sym', render: r => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.sym.replace('USDT', '')}</span> },
    { key: 'dir', label: 'Side', render: r => <Badge tone={r.dir === 'LONG' ? 'ok' : 'err'}>{r.dir[0]}</Badge> },
    { key: 'rate', label: 'Rate', align: 'right', render: r => <span style={{ color: r.rate >= 0 ? 'var(--qe-amber)' : 'var(--qe-green)' }}>{(r.rate * 100).toFixed(4)}%</span> },
    { key: 'pays', label: 'Flow', render: r => <FundingWho pays={r.pays} /> },
    { key: 'est', label: 'Est', align: 'right', render: r => <span style={{ color: sgn(r.est_next), fontSize: '0.56rem' }}>{fmtUsd(r.est_next, 4)}</span> },
    { key: 'cum', label: 'Cum', align: 'right', render: r => <span style={{ color: sgn(r.cum) }}>{fmtUsd(r.cum, 3)}</span> },
  ];
  const closeCols = [
    { key: 'sym', label: 'Sym', render: r => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.sym.replace('USDT', '')}</span> },
    { key: 'dir', label: 'Side', render: r => <Badge tone={r.dir === 'LONG' ? 'ok' : 'err'}>{r.dir[0]}</Badge> },
    { key: 'ts', label: 'Time', render: r => <span style={{ color: 'var(--qe-muted)', fontSize: '0.56rem' }}>{r.ts}</span> },
    { key: 'entry', label: 'Entry', align: 'right', render: r => <span style={{ color: 'var(--qe-sub)' }}>{fmtPx(r.sym, r.entry)}</span> },
    { key: 'exit', label: 'Exit', align: 'right', render: r => fmtPx(r.sym, r.exit) },
    { key: 'pnl', label: 'PnL', align: 'right', render: r => <span style={{ color: sgn(r.pnl), fontWeight: 700 }}>{fmtUsd(r.pnl)} <span style={{ opacity: 0.7, fontSize: '0.54rem' }}>{fmtPct(r.pct)}</span></span> },
    { key: 'hold', label: 'Hold', render: r => <span style={{ color: 'var(--qe-muted)', fontSize: '0.56rem' }}>{r.hold}</span> },
    { key: 'exit_reason', label: 'Exit reason', render: r => { const rr = resolved['C' + r.id]; return <ExitBadge reason={rr && rr.action === 'reason' ? 'MANUAL_' + rr.val : r.exit_reason} note={r.note} />; } },
    { key: 'funding', label: 'Fund', align: 'right', render: r => <span style={{ color: sgn(r.funding), fontSize: '0.56rem' }}>{fmtUsd(r.funding, 3)}</span> },
  ];

  return (
    <div className="qe-scope" data-screen-label="03 Linkage" style={{ width: '100%', height: '100%', background: 'var(--qe-bg)', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <TopNavStd page="Linkage" variant="line" dense />
      <PageHeader title="Linkage" subtitle="calc-linkage workspace · manual link · close reasons · positions · funding">
        <StatusDot tone="info" label="LINK" value="5m window" />
        <StatusDot tone="warn" label="QUEUE" value={`${inbox.length} open`} />
      </PageHeader>

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <GridWorkspace persistId="linkage">
        {/* ── ACTION INBOX — uses the Pane primitive ───────────────── */}
        <GridItem x={0} y={0} w={9} h={24} minW={6} minH={10}>
        <Pane title="MANUAL LINK — NEEDS REVIEW"
          right={<span className="qe-badge qe-badge-warn" style={{ padding: '0 4px', fontSize: '0.5rem', lineHeight: '11px' }}>{inbox.length}</span>}
          foot={{ tone: inbox.length ? 'warn' : 'ok', id: 1851, msg: inbox.length ? `${inbox.filter(i => i.kind === 'link').length} orders below 6/6 · ${inbox.filter(i => i.kind === 'close').length} closes uncategorized` : 'queue clear · all linked & categorized', ms: 3 }}
          bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          {inbox.length === 0 ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 10 }}>
              <EmptyState tone="info" glyph="✓" msg="Inbox clear" hint="Every order is linked and every close is categorized." />
            </div>
          ) : (
            <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '162px 1fr' }}>
              {/* LEFT · trades needing a link — scrolls independently */}
              <div style={{ overflow: 'auto', borderRight: '1px solid var(--qe-line)' }}>
                {inbox.map(item => {
                  const on = active && item.key === active.key;
                  const accent = item.kind === 'link' ? 'var(--qe-amber)' : 'var(--qe-magenta)';
                  return (
                    <div key={item.key} onClick={() => setSel(item.key)} style={{
                      display: 'flex', flexDirection: 'column', gap: 3, padding: '7px 8px', cursor: 'pointer',
                      borderBottom: '1px solid var(--qe-faint)', borderLeft: `3px solid ${on ? 'var(--qe-cyan)' : 'transparent'}`,
                      background: on ? 'var(--qe-active)' : 'transparent',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        <span className="qe-mono" style={{ fontSize: '0.5rem', color: accent, fontWeight: 700, letterSpacing: '0.08em' }}>{item.kind === 'link' ? 'LINK' : 'REASON'}</span>
                        <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>{item.sym.replace('USDT', '')}</span>
                        <Badge tone={item.dir === 'LONG' ? 'ok' : 'err'}>{item.dir[0]}</Badge>
                        <span className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', marginLeft: 'auto' }}>{item.ts}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                        {item.kind === 'link'
                          ? <LinkBadge status={item.status} variant={3} />
                          : <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-magenta)' }}>set reason</span>}
                        <span className="qe-mono" style={{ fontSize: '0.5rem', marginLeft: 'auto', color: item.kind === 'link' ? 'var(--qe-muted)' : sgn(item.pnl) }}>{item.kind === 'link' ? <React.Fragment>#{item.order_id} · <TickAge seed={item.age_s} suffix=""/></React.Fragment> : fmtUsd(item.pnl)}</span>
                      </div>
                      <div className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.kind === 'link' ? `${item.type} @ ${fmtPx(item.sym, item.price)} · ${item.notional}U` : `${item.hold} · ${fmtPx(item.sym, item.entry)}→${fmtPx(item.sym, item.exit)}`}
                      </div>
                    </div>
                  );
                })}
              </div>
              {/* RIGHT · details — scrolls independently */}
              <div style={{ overflow: 'auto', padding: 8 }}>
                {active && (active.kind === 'link'
                  ? <LinkResolver key={active.key} item={active} onResolve={resolve} />
                  : <ReasonResolver key={active.key} item={active} onResolve={resolve} />)}
              </div>
            </div>
          )}
        </Pane>
        </GridItem>

        {/* ── MONITOR WALL — draggable / resizable tiles ───────────── */}
        <GridItem x={9} y={0} w={15} h={9} minW={6} minH={5}>
          <Pane title="Open Positions" count={window.L_POSITIONS.length}
            onRefresh={refreshPositions}
            foot={{ tone: 'info', id: 1844, msg: sync.n ? `re-synced ×${sync.n} · ${window.L_POSITIONS.length} positions · 4 working orders` : `reconciler synced · ${window.L_POSITIONS.length} positions · 4 working orders`, ms: sync.ms }}
            bodyStyle={{ padding: 0 }}>
            <DataList columns={posCols} rows={window.L_POSITIONS} selKey="id" />
          </Pane>
        </GridItem>

        <GridItem x={9} y={9} w={8} h={8} minW={4} minH={5}>
            <Pane title="Active Calcs" count={activeCalcs.length}
              foot={{ tone: 'info', id: 1845, msg: 'link windows tick down live · 300s each · expired slots recycle · matcher armed', ms: 2 }}
              bodyStyle={{ padding: 0 }}>
              <DataList columns={calcCols} rows={activeCalcs} selKey="id" />
            </Pane>
        </GridItem>
        <GridItem x={17} y={9} w={7} h={8} minW={4} minH={5}>
            <Pane title="Funding" tag="LIVE" foot={{ tone: 'sub', id: 1847, msg: <SettleCountdown/>, ms: 1 }}
              bodyStyle={{ padding: 0 }}>
              <DataList columns={fundCols} rows={window.L_FUNDING.rows} selKey="pos"
                summary={<><span>net at {window.L_FUNDING.next_settlement}</span><span style={{ color: sgn(window.L_FUNDING.net_cum) }}>cum {fmtUsd(window.L_FUNDING.net_cum, 3)}</span></>} />
            </Pane>
        </GridItem>

        <GridItem x={9} y={17} w={15} h={7} minW={6} minH={5}>
          <Pane title="Recent Closes" count={window.L_CLOSES.length}
            foot={{ tone: 'sub', id: 1849, msg: `last close ${window.L_CLOSES[0].ts} · ${window.L_CLOSES.length} closed today`, ms: 1 }}
            bodyStyle={{ padding: 0 }}>
            <DataList columns={closeCols} rows={window.L_CLOSES} selKey="id" />
          </Pane>
        </GridItem>
        </GridWorkspace>
      </div>

      {toast && (
        <div style={{ position: 'absolute', bottom: 14, left: '50%', transform: 'translateX(-50%)', zIndex: 80, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'var(--qe-bg)', border: '1px solid var(--qe-green)', boxShadow: '0 8px 30px var(--qe-bg)' }}>
          <span style={{ color: 'var(--qe-green)' }}>✓</span>
          <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-text)' }}>{toast}</span>
        </div>
      )}
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { DashLinkA });
