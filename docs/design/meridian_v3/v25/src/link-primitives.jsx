/* ─────────────────────────────────────────────────────────────────────────
   link-primitives.jsx — linkage vocabulary shared by all 3 directions.
   Built on the v25 primitives (Badge, Pane, DataList…). Where the spec asks
   for an operator pick (link-status badge, deviation badge) each ships as
   numbered VARIANTS; the cockpits use the chosen canonical (V1 link, V2 dev)
   and the picker artboard shows all of them.
   ───────────────────────────────────────────────────────────────────────── */

// ── formatting ─────────────────────────────────────────────────────────────
const DEC = { BTCUSDT: 1, ETHUSDT: 2, SOLUSDT: 2, AVAXUSDT: 2, LINKUSDT: 2, MKRUSDT: 1, INJUSDT: 2, LABUSDT: 3 };
const fmtPx = (sym, v) => v == null ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: DEC[sym] ?? 2, maximumFractionDigits: DEC[sym] ?? 2 });
const fmtUsd = (v, d = 2) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d);
const fmtPct = (v, d = 2) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d) + '%';
const sgn = (v) => v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)';

// ── live countdown hook (ticks once a second over an expiry epoch) ─────────
const useCountdown = (expiryMs) => {
  const [, force] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => { const i = setInterval(force, 1000); return () => clearInterval(i); }, []);
  const s = Math.round((expiryMs - Date.now()) / 1000);
  return s;
};
const fmtClock = (s) => {
  if (s <= 0) return 'expired';
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${String(ss).padStart(2, '0')}`;
};

// ── CalcCountdown — the link-window timer on an active calc ─────────────────
// variant 'chip' (boxed, used in lists) | 'bar' (with depleting track) | 'ring'
const CalcCountdown = ({ expiry, window = 300, variant = 'chip', showLabel = true }) => {
  const s = useCountdown(expiry);
  const tone = s <= 0 ? 'err' : s <= 60 ? 'warn' : 'ok';
  const col = `var(--qe-${tone === 'ok' ? 'green' : tone === 'warn' ? 'amber' : 'red'})`;
  const pct = Math.max(0, Math.min(100, (s / window) * 100));
  if (variant === 'bar') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 84 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--qe-mono)', fontSize: '0.56rem' }}>
          {showLabel && <span style={{ color: 'var(--qe-muted)', letterSpacing: '0.1em' }}>LINK</span>}
          <span style={{ color: col, fontWeight: 700 }}>{fmtClock(s)}</span>
        </div>
        <div style={{ height: 3, background: 'var(--qe-faint)' }}>
          <div style={{ height: '100%', width: pct + '%', background: col, transition: 'width 1s linear' }} />
        </div>
      </div>
    );
  }
  if (variant === 'ring') {
    // small Ø to sit inside a DataList row; stroke width unchanged so the
    // ring keeps its weight.
    const r = 4, sw = 3, c = 2 * Math.PI * r, off = c * (1 - pct / 100);
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'flex-end', gap: 5, verticalAlign: 'middle' }} title={`window ${window}s`}>
        <svg width="11" height="11" viewBox="0 0 11 11" style={{ transform: 'rotate(-90deg)', flexShrink: 0, display: 'block' }}>
          <circle cx="5.5" cy="5.5" r={r} fill="none" stroke="var(--qe-faint)" strokeWidth={sw} />
          <circle cx="5.5" cy="5.5" r={r} fill="none" stroke={col} strokeWidth={sw}
            strokeDasharray={c} strokeDashoffset={off} style={{ transition: 'stroke-dashoffset 1s linear' }} />
        </svg>
        <span className="qe-mono" style={{ color: col, fontWeight: 700, fontSize: '0.6rem', lineHeight: '11px' }}>{fmtClock(s)}</span>
      </span>
    );
  }
  // chip
  return (
    <span className="qe-mono" style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '1px 6px',
      border: `1px solid ${col}`, color: col, fontWeight: 700, fontSize: '0.6rem',
      background: tone === 'err' ? 'var(--qe-bg-red)' : 'transparent',
    }}>
      {showLabel && <span style={{ width: 5, height: 5, background: col, borderRadius: tone === 'ok' ? '50%' : 0 }} />}
      {fmtClock(s)}
    </span>
  );
};

// ── Link-status badge — 3 variants (operator picks) ────────────────────────
const LINK_META = {
  LINKED:              { v1: 'LINKED',       v3: 'LINKED',  tone: 'ok',   col: 'var(--qe-green)', glyph: '⛓' },
  NEEDS_MANUAL_REVIEW: { v1: 'NEEDS REVIEW', v3: 'REVIEW',  tone: 'warn', col: 'var(--qe-amber)', glyph: '?' },
  UNLINKED:            { v1: 'UNLINKED',     v3: 'UNLINKED',tone: 'err',  col: 'var(--qe-red)',   glyph: '⚡' },
  UNPLANNED:           { v1: 'UNPLANNED',    v3: 'UNPLAN',  tone: 'blue', col: 'var(--qe-blue)',  glyph: '○' },
};
const LinkBadge = ({ status, variant = 1 }) => {
  const m = LINK_META[status]; if (!m) return null;
  if (variant === 2) {  // solid dot + label, low chrome
    return (
      <span className="qe-mono" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '0.58rem', fontWeight: 700, color: m.col, letterSpacing: '0.06em' }}>
        <span style={{ width: 6, height: 6, background: m.col, borderRadius: '50%', flexShrink: 0 }} />{m.v1}
      </span>
    );
  }
  if (variant === 3) {  // bracketed terminal tag
    return (
      <span className="qe-mono" style={{ fontSize: '0.56rem', fontWeight: 700, color: m.col, letterSpacing: '0.08em' }}>
        <span style={{ color: 'var(--qe-muted)' }}>[</span>{m.v3}<span style={{ color: 'var(--qe-muted)' }}>]</span>
      </span>
    );
  }
  return <Badge tone={m.tone}>{m.v1}</Badge>;  // v1 — outline pill (canonical)
};

// ── Deviation badge — 3 variants; numeric TP/SL drift is the picked default ─
const DEV_META = {
  green:  { label: 'ON-PLAN', tone: 'ok',   col: 'var(--qe-green)' },
  yellow: { label: 'AMENDED', tone: 'warn', col: 'var(--qe-amber)' },
  red:    { label: 'OFF-PLAN',tone: 'err',  col: 'var(--qe-red)' },
};
// amendments are a timeline of events; the badge surfaces ONLY the latest
// state in one line. The whole timeline rides on the tooltip (title).
const latestAmend = (p) => {
  if (p.amends && p.amends.length) {
    const a = p.amends[p.amends.length - 1];
    return `${a.field} ${fmtPct(a.pct, 2)}`;
  }
  if (p.amendments > 0) {
    if (p.tp_drift_pct != null && Math.abs(p.tp_drift_pct) >= 0.005) return `tp ${fmtPct(p.tp_drift_pct, 2)}`;
    if (p.sl_drift_pct != null && Math.abs(p.sl_drift_pct) >= 0.005) return `sl ${fmtPct(p.sl_drift_pct, 2)}`;
  }
  return null;
};
const amendTimeline = (p) => (p.amends && p.amends.length)
  ? p.amends.map(a => `${a.ts} · ${a.field} ${a.old}→${a.neo} (${fmtPct(a.pct, 2)})`).join('   ·   ')
  : `${p.amendments} amendment${p.amendments === 1 ? '' : 's'}`;
const DevBadge = ({ pos, variant = 2 }) => {
  const m = DEV_META[pos.dev]; if (!m) return null;
  const latest = latestAmend(pos);
  const title = amendTimeline(pos);
  if (variant === 1) {  // pure color dot + word
    return <span className="qe-mono" title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.56rem', fontWeight: 700, color: m.col }}>
      <span style={{ width: 6, height: 6, background: m.col }} />{m.label}
    </span>;
  }
  if (variant === 3) {  // segmented severity meter + latest one-liner
    const lvl = pos.dev === 'green' ? 1 : pos.dev === 'yellow' ? 2 : 3;
    return (
      <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <span style={{ display: 'inline-flex', gap: 1 }}>
          {[1, 2, 3].map(i => <span key={i} style={{ width: 7, height: 7, background: i <= lvl ? m.col : 'var(--qe-faint)' }} />)}
        </span>
        {latest && <span className="qe-mono" style={{ fontSize: '0.54rem', color: m.col }}>{latest}</span>}
      </span>
    );
  }
  // v2 — badge + the LATEST amendment state, one line (full timeline on hover)
  const desc = pos.dev === 'red' ? 'no calc' : latest;
  return (
    <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}>
      <span className="qe-badge" style={{ color: m.col, borderColor: m.col, background: 'transparent', padding: '1px 5px', fontSize: '0.52rem' }}>{m.label}</span>
      {desc && <span className="qe-mono" style={{ fontSize: '0.55rem', color: m.col, fontWeight: 600 }}>{desc}</span>}
      {pos.amendments > 0 && <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>✎{pos.amendments}</span>}
    </span>
  );
};

// ── Exit-reason badge ───────────────────────────────────────────────────────
const ExitBadge = ({ reason, note }) => {
  if (!reason) return <Badge tone="warn" style={{ borderStyle: 'dashed' }}>SET REASON</Badge>;
  const m = window.L_EXIT_REASONS[reason] || { label: reason, tone: 'mute' };
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
    <Badge tone={m.tone}>{m.label}</Badge>{note && <span title={note} style={{ color: 'var(--qe-muted)', fontSize: '0.6rem' }}>✎</span>}
  </span>;
};

// ── Per-criterion match diff (Needs-Link core) ─────────────────────────────
const CRIT_LABEL = { ticker: 'Ticker', direction: 'Direction', window: 'In-window', entry: 'Entry', tp: 'Take-profit', sl: 'Stop-loss' };
const MatchDiff = ({ candidate, compact = false }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
    {candidate.crit.map(c => (
      <div key={c.k} style={{
        display: 'grid', gridTemplateColumns: compact ? '70px 1fr 1fr 46px' : '88px 1fr 1fr 64px 18px',
        alignItems: 'center', gap: 6, padding: '2px 6px',
        background: c.ok ? 'transparent' : 'var(--qe-bg-red)',
        borderLeft: `2px solid ${c.ok ? 'var(--qe-green)' : 'var(--qe-red)'}`,
        fontFamily: 'var(--qe-mono)', fontSize: '0.58rem',
      }}>
        <span style={{ color: 'var(--qe-sub)' }}>{CRIT_LABEL[c.k]}</span>
        <span style={{ color: 'var(--qe-text)' }}>{c.calc}</span>
        <span style={{ color: c.ok ? 'var(--qe-text)' : 'var(--qe-red)' }}>{c.order}</span>
        {!compact && <span style={{ color: 'var(--qe-muted)', fontSize: '0.52rem' }}>{c.tol}</span>}
        <span style={{ color: c.ok ? 'var(--qe-green)' : 'var(--qe-red)', fontWeight: 700, textAlign: 'right', fontSize: '0.78rem', lineHeight: 1 }}>
          {c.ok ? '●' : '○'}
        </span>
      </div>
    ))}
  </div>
);

// ── Funding direction helper ───────────────────────────────────────────────
const FundingWho = ({ pays }) => pays === 'you'
  ? <span className="qe-mono" style={{ color: 'var(--qe-red)', fontSize: '0.58rem', fontWeight: 700 }}>PAY</span>
  : <span className="qe-mono" style={{ color: 'var(--qe-green)', fontSize: '0.58rem', fontWeight: 700 }}>EARN</span>;

Object.assign(window, {
  fmtPx, fmtUsd, fmtPct, sgn, useCountdown, fmtClock,
  CalcCountdown, LinkBadge, DevBadge, ExitBadge, MatchDiff, FundingWho,
  LINK_META, DEV_META, CRIT_LABEL,
});
