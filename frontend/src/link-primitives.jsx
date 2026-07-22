/* v3.0 — linkage vocabulary (P4). Ported from the Meridian reference
   (link-primitives.jsx). Deviations: the per-symbol DEC price map is replaced
   by the magnitude-adaptive rule (mirrors core/formatters.format_price — no
   symbol table to rot); canonical variants only (LinkBadge v1/v3, DevBadge v2). */

const lpPx = (v) => {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(+v);
  const d = a >= 1000 ? 2 : a >= 1 ? 4 : 6;
  return (+v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
};
const lpUsd = (v, d = 2) => (v == null || isNaN(v)) ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d);
const lpPct = (v, d = 2) => (v == null || isNaN(v)) ? '—' : (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d) + '%';
const lpSgn = (v) => v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)';
const lpClock = (s) => {
  if (s == null) return '—';
  if (s <= 0) return 'expired';
  const m = Math.floor(s / 60), ss = Math.floor(s % 60);
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}:${String(ss).padStart(2, '0')}`;
};

/* self-ticking countdown over an epoch-ms expiry */
const useLpCountdown = (expiryMs) => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => { const i = setInterval(force, 1000); return () => clearInterval(i); }, []);
  return expiryMs != null ? Math.round((expiryMs - Date.now()) / 1000) : null;
};

const CalcCountdown = ({ expiry, window: win = 300 }) => {
  const s = useLpCountdown(expiry);
  if (s == null) return <span className="qe-mono" style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>—</span>;
  const tone = s <= 0 ? 'var(--qe-red)' : s <= 60 ? 'var(--qe-amber)' : 'var(--qe-green)';
  const pct = Math.max(0, Math.min(100, (s / (win || 300)) * 100));
  const r = 4, sw = 3, c = 2 * Math.PI * r, off = c * (1 - pct / 100);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', gap: 5, verticalAlign: 'middle' }} title={`window ${win}s`}>
      <svg width="11" height="11" viewBox="0 0 11 11" style={{ transform: 'rotate(-90deg)', flexShrink: 0, display: 'block' }}>
        <circle cx="5.5" cy="5.5" r={r} fill="none" stroke="var(--qe-faint)" strokeWidth={sw} />
        <circle cx="5.5" cy="5.5" r={r} fill="none" stroke={tone} strokeWidth={sw}
          strokeDasharray={c} strokeDashoffset={off} style={{ transition: 'stroke-dashoffset 1s linear' }} />
      </svg>
      <span className="qe-mono" style={{ color: tone, fontWeight: 700, fontSize: '0.6rem', lineHeight: '11px' }}>{lpClock(s)}</span>
    </span>
  );
};

const LP_LINK_META = {
  LINKED:              { v1: 'LINKED',       v3: 'LINKED',   tone: 'ok',   col: 'var(--qe-green)' },
  NEEDS_MANUAL_REVIEW: { v1: 'NEEDS REVIEW', v3: 'REVIEW',   tone: 'warn', col: 'var(--qe-amber)' },
  UNLINKED:            { v1: 'UNLINKED',     v3: 'UNLINKED', tone: 'err',  col: 'var(--qe-red)' },
  UNPLANNED:           { v1: 'UNPLANNED',    v3: 'UNPLAN',   tone: 'blue', col: 'var(--qe-blue)' },
};
const LinkBadge = ({ status, variant = 1 }) => {
  const m = LP_LINK_META[status]; if (!m) return null;
  if (variant === 3) {
    return (
      <span className="qe-mono" style={{ fontSize: '0.56rem', fontWeight: 700, color: m.col, letterSpacing: '0.08em' }}>
        <span style={{ color: 'var(--qe-muted)' }}>[</span>{m.v3}<span style={{ color: 'var(--qe-muted)' }}>]</span>
      </span>
    );
  }
  return <Badge tone={m.tone}>{m.v1}</Badge>;
};

const LP_DEV_META = {
  green:  { label: 'ON-PLAN',  col: 'var(--qe-green)' },
  yellow: { label: 'AMENDED',  col: 'var(--qe-amber)' },
  red:    { label: 'OFF-PLAN', col: 'var(--qe-red)' },
};
/* badge + latest numeric drift (±0.1% deadband mirrors the engine's boolean
   tolerance — a 0.04% drift must not read as amended next to a green badge
   [P4 backend audit L2]) */
const DevBadge = ({ pos }) => {
  const m = LP_DEV_META[pos.deviation_badge]; if (!m) return <span style={{ color: 'var(--qe-muted)' }}>—</span>;
  const drift = Math.abs(pos.tp_drift_pct || 0) >= 0.1 ? `tp ${lpPct(pos.tp_drift_pct)}`
    : Math.abs(pos.sl_drift_pct || 0) >= 0.1 ? `sl ${lpPct(pos.sl_drift_pct)}` : null;
  const desc = pos.deviation_badge === 'red' && !pos.calc_id ? 'no calc' : drift;
  const title = `size Δ ${lpPct(pos.size_delta_pct)} · ${pos.amendment_count || 0} amendment${(pos.amendment_count || 0) === 1 ? '' : 's'}${pos.tpsl_amended ? ' · TP/SL amended' : ''}`;
  return (
    <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}>
      <span className="qe-badge" style={{ color: m.col, borderColor: m.col, background: 'transparent', padding: '1px 5px', fontSize: '0.52rem' }}>{m.label}</span>
      {desc && <span className="qe-mono" style={{ fontSize: '0.55rem', color: m.col, fontWeight: 600 }}>{desc}</span>}
      {(pos.amendment_count || 0) > 0 && <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>✎{pos.amendment_count}</span>}
    </span>
  );
};

const LP_EXIT_REASONS = {
  TP_PLANNED:              { label: 'TP · plan',    tone: 'ok' },
  TP_AMENDED:              { label: 'TP · amended', tone: 'warn' },
  SL_PLANNED:              { label: 'SL · plan',    tone: 'err' },
  SL_AMENDED:              { label: 'SL · amended', tone: 'warn' },
  TP_LADDER_COMPLETE:      { label: 'TP ladder',    tone: 'ok' },
  MIXED:                   { label: 'Mixed',        tone: 'warn' },
  MANUAL_INTERVENTION:     { label: 'Intervention', tone: 'mag' },
  MANUAL_DISCIPLINE_BREAK: { label: 'Discipline',   tone: 'err' },
  MANUAL_NEW_OPPORTUNITY:  { label: 'New opp',      tone: 'blue' },
  MANUAL_OTHER:            { label: 'Manual',       tone: 'mute' },
  LIQUIDATION:             { label: 'Liquidation',  tone: 'err' },
  ADL:                     { label: 'ADL',          tone: 'err' },
  EXPIRED:                 { label: 'Expired',      tone: 'mute' },
};
const LP_MANUAL_REASONS = [
  { key: 'MANUAL_INTERVENTION',      label: 'Intervention',     hint: 'Judgement call — exited against the plan deliberately' },
  { key: 'MANUAL_DISCIPLINE_BREAK',  label: 'Discipline break', hint: 'Fear / impatience — broke the plan, logging it honestly' },
  { key: 'MANUAL_NEW_OPPORTUNITY',   label: 'New opportunity',  hint: 'Freed capital for a better setup' },
  { key: 'MANUAL_OTHER',             label: 'Other',            hint: 'Free-text rationale below' },
];
const ExitBadge = ({ reason, note, pending }) => {
  if (!reason || pending) return <Badge tone="warn">SET REASON</Badge>;
  const m = LP_EXIT_REASONS[reason] || { label: reason, tone: 'mute' };
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
      <Badge tone={m.tone}>{m.label}</Badge>
      {note && <span title={note} style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>✎</span>}
    </span>
  );
};

/* Per-criterion diff. Real backend = the LOOSE finder's 3 legs (entry/tp/sl
   drift + match); ticker/direction/window are computed-true by construction
   (the finder filters on them) — rendered as passing rows, a named deviation
   from the design's strict-matcher 6-row array. */
const lpCritRows = (order, cand) => ([
  { k: 'Ticker',      calc: cand.ticker, order: order.symbol, ok: true },
  { k: 'Direction',   calc: (cand.side || '').toUpperCase(), order: (order.side || '').toUpperCase(), ok: true },
  { k: 'In-window',   calc: cand.age_hours != null ? `${(+cand.age_hours).toFixed(1)}h ago` : '—', order: 'loose 168h', ok: true },
  { k: 'Entry',       calc: lpPx(cand.effective_entry), order: lpPx(order.price),
    ok: !!cand.entry_match, diff: cand.entry_drift_pct != null ? lpPct(cand.entry_drift_pct * 100) : '' },
  { k: 'Take-profit', calc: lpPx(cand.tp_price), order: lpPx(order.tp_trigger_price),
    ok: !!cand.tp_match, diff: cand.tp_drift_pct != null ? lpPct(cand.tp_drift_pct * 100) : '' },
  { k: 'Stop-loss',   calc: lpPx(cand.sl_price), order: lpPx(order.sl_trigger_price),
    ok: !!cand.sl_match, diff: cand.sl_drift_pct != null ? lpPct(cand.sl_drift_pct * 100) : '' },
]);
const lpScore = (cand) => 3 + (cand.entry_match ? 1 : 0) + (cand.tp_match ? 1 : 0) + (cand.sl_match ? 1 : 0);
const MatchDiff = ({ order, candidate }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
    {lpCritRows(order, candidate).map((c) => (
      <div key={c.k} style={{
        display: 'grid', gridTemplateColumns: '76px 1fr 1fr 52px 18px',
        alignItems: 'center', gap: 6, padding: '2px 6px',
        background: c.ok ? 'transparent' : 'var(--qe-bg-red)',
        borderLeft: `2px solid ${c.ok ? 'var(--qe-green)' : 'var(--qe-red)'}`,
        fontFamily: 'var(--qe-mono)', fontSize: '0.58rem',
      }}>
        <span style={{ color: 'var(--qe-sub)' }}>{c.k}</span>
        <span style={{ color: 'var(--qe-text)' }}>{c.calc}</span>
        <span style={{ color: c.ok ? 'var(--qe-text)' : 'var(--qe-red)' }}>{c.order}</span>
        <span style={{ color: 'var(--qe-muted)', fontSize: '0.52rem' }}>{c.diff || ''}</span>
        <span style={{ color: c.ok ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700, textAlign: 'right', fontSize: '0.78rem', lineHeight: 1 }}>{c.ok ? '●' : '○'}</span>
      </div>
    ))}
  </div>
);

const FundingWho = ({ pays }) => pays === 'you'
  ? <span className="qe-mono" style={{ color: 'var(--qe-red)', fontSize: '0.58rem', fontWeight: 700 }}>PAY</span>
  : <span className="qe-mono" style={{ color: 'var(--qe-green)', fontSize: '0.58rem', fontWeight: 700 }}>EARN</span>;

Object.assign(window, {
  lpPx, lpUsd, lpPct, lpSgn, lpClock, useLpCountdown,
  CalcCountdown, LinkBadge, DevBadge, ExitBadge, MatchDiff, FundingWho,
  LP_EXIT_REASONS, LP_MANUAL_REASONS, LP_LINK_META, LP_DEV_META, lpCritRows, lpScore,
});
