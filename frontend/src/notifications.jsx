// ════════════════════════════════════════════════════════════════════════
//  v3.0 — Notification System (ported from Meridian QE v2.5)
//  Context-driven: <NotificationProvider> wraps any page; the bell + halt
//  banner live in the real TopNavStd; the drawer / toasts / demo panel
//  overlay the page. App-global notification taxonomy (the REAL producer
//  set, G-O3): fills, risk/drawdown, calc-link, system/WS.
//  Single script scope — all helpers below are visible to each other; only
//  NotifCtx / NotifBell / NotifBanner / NotificationProvider are exported.
// ════════════════════════════════════════════════════════════════════════

const NotifCtx = React.createContext(null);

// ── taxonomy ─────────────────────────────────────────────────────────────
// P8 wave 1 (G-O3 UI wire): scoped to the FOUR channels the engine actually
// produces (core/notifications.py _TYPE_UI: LINK/RISK/FILLS + SYSTEM
// fallback). The design's REGIME/NEWS channels have no producer — their
// chips were fiction and are gone until real producers exist.
const N_CHANNELS = ['FILLS', 'RISK', 'LINK', 'SYSTEM'];
// per-channel primary action — [button label, target description]
const N_ACTIONS = {
  FILLS:  ['View order',  'order detail'],
  RISK:   ['Review risk', 'risk panel'],
  SYSTEM: ['Details',     'system log'],
  LINK:   ['Link trades', 'linkage queue'],
};
const nSev = (pri) => pri === 'halt' ? 'var(--qe-red)' : pri === 'risk' ? 'var(--qe-amber)' : 'var(--qe-line-2)';
const _rnd = (a) => a[Math.floor(Math.random() * a.length)];
const _px = (n, d = 1) => n.toFixed(d);

const N_SCENARIOS = {
  fill: () => { const side = _rnd(['BUY', 'SELL']); const s = _rnd([['BTC', 93580, 0.04], ['ETH', 3208, 0.18], ['SOL', 139, 12]]);
    const p = s[1] * (1 + (Math.random() - 0.5) * 0.004);
    return { ch: 'FILLS', pri: 'routine', head: `FILLED · ${side} ${_px(s[2] * (0.5 + Math.random()), 3)} ${s[0]}`,
      detail: `@ ${_px(p, 1)} · slippage +${_px(Math.random() * 0.9, 1)}bp · order #A${1900 + Math.floor(Math.random() * 99)}` }; },
  partial: () => { const s = _rnd([['ETH', 3208], ['SOL', 139], ['BTC', 93580]]);
    return { ch: 'FILLS', pri: 'routine', head: `Order #A${1880 + Math.floor(Math.random() * 40)} partially filled ${40 + Math.floor(Math.random() * 5) * 10}%`,
      detail: `SELL ${_px(Math.random(), 3)} / ${_px(1 + Math.random(), 3)} ${s[0]} @ ${_px(s[1], 1)}` }; },
  risk: () => _rnd([
    { ch: 'RISK', pri: 'risk', head: `Weekly loss ${78 + Math.floor(Math.random() * 12)}% of limit`, detail: `−$${(3.10 + Math.random() * 0.6).toFixed(2)} of −$4.11 · 1 more stop trips the cap` },
    { ch: 'RISK', pri: 'risk', head: `Daily drawdown ${_px(3.5 + Math.random(), 1)}% — approaching 5.0% cap`, detail: 'position sizing throttled to ×0.5' }]),
  halt: () => ({ ch: 'RISK', pri: 'halt', head: 'CALCULATOR BLOCKED — hard-stop breached', detail: 'Realized DD 5.04% > 5.00% cap · new entries gated · open positions unaffected' }),
  link: () => { const nl = (window.L_NEEDS_LINK || []).filter(o => o.status === 'NEEDS_MANUAL_REVIEW' || o.status === 'UNLINKED').length || 5;
    const nc = (window.L_CLOSES || []).filter(c => c.pending_reason).length || 3;
    return { ch: 'LINK', pri: 'risk', head: `Calc link window closes in 0${2 + Math.floor(Math.random() * 4)}:${10 + Math.floor(Math.random() * 49)}`, detail: `triage ${nl + nc} open · ${nl} orders below 6/6 · ${nc} closes to review` }; },
  ws: () => _rnd([
    { ch: 'SYSTEM', pri: 'routine', head: 'Market WS reconnected', detail: '2 streams · 108ms · gap 1.4s recovered' }]),
};
const N_STREAM = ['fill', 'partial', 'risk', 'link', 'ws'];

/* P8 wave 1: N_SEED (7 fabricated events, 3 "unread" at boot) is GONE — the
   provider seeds empty and fills from the REAL feed (GET /notifications/poll,
   the G-O3 backend that shipped in P1). */

function nRel(ts, now) { const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 5) return 'now'; if (s < 60) return s + 's'; if (s < 3600) return Math.floor(s / 60) + 'm'; return Math.floor(s / 3600) + 'h'; }
function nAbs(ts) { const d = new Date(ts + (window.QE_CLOCK_OFFSET || 0)); const p = n => String(n).padStart(2, '0');
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`; }

// nBeep: the notification sound. Demo-ORIGINATED but production-consumed —
// real poll events ride the same toast/beep/DND rules as demo ones (the
// `sound` switch in the drawer gates it; audit NIT-1 wording fix).
let _nac = null;
function nBeep(pri) { try {
  _nac = _nac || new (window.AudioContext || window.webkitAudioContext)();
  if (_nac.state === 'suspended') _nac.resume();
  const seq = pri === 'halt' ? [[330, 0], [220, 0.13]] : pri === 'risk' ? [[520, 0]] : [[760, 0]];
  seq.forEach(([f, t]) => { const o = _nac.createOscillator(), g = _nac.createGain();
    o.type = pri === 'routine' ? 'sine' : 'triangle'; o.frequency.value = f;
    const t0 = _nac.currentTime + t; g.gain.setValueAtTime(0.0001, t0);
    g.gain.exponentialRampToValueAtTime(pri === 'routine' ? 0.06 : 0.12, t0 + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.18);
    o.connect(g); g.connect(_nac.destination); o.start(t0); o.stop(t0 + 0.2); });
} catch (e) {} }

// ── nav bell (consumes context; static when no provider) ─────────────────
const NotifBell = () => {
  const ctx = React.useContext(NotifCtx);
  const count = ctx ? ctx.unread : 0;
  const active = ctx ? ctx.open : false;
  return (
    <div onClick={ctx ? ctx.toggleOpen : undefined} title="Notifications"
      style={{ position:'relative', display:'inline-flex', alignItems:'center', justifyContent:'center', width:22, height:22,
        cursor: ctx ? 'pointer' : 'default', border:`1px solid ${active ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
        background: active ? 'var(--qe-bg-cyan)' : 'transparent', color: active ? 'var(--qe-cyan)' : 'var(--qe-sub)' }}>
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3">
        <path d="M8 1.6c-2.2 0-3.7 1.7-3.7 3.9 0 3.4-1 4.4-1.4 4.8h10.2c-.4-.4-1.4-1.4-1.4-4.8 0-2.2-1.5-3.9-3.7-3.9Z"/>
        <path d="M6.5 12.6a1.5 1.5 0 0 0 3 0"/>
      </svg>
      {count > 0 && (
        <span style={{ position:'absolute', top:-6, right:-6, minWidth:14, height:14, padding:'0 3px', background:'var(--qe-red)',
          color:'var(--qe-text)', fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:800, display:'flex', alignItems:'center',
          justifyContent:'center', lineHeight:1, border:'1px solid var(--qe-bg)' }}>{count}</span>
      )}
    </div>
  );
};

// ── pinned halt banner (rendered under the nav by TopNavStd) ─────────────
// Circuit-breaker banner: shows a live countdown until the halt releases and
// stays up no matter what — across reloads / app startup — until the cooldown
// elapses. No acknowledge: you cannot dismiss a hard-stop, only wait it out.
const HALT_KEY = 'qe.haltUntil';
const HALT_AT_KEY = 'qe.haltAt';
// P0: the localStorage halt AUTHORITY is removed (plan §4 + §1.3, HIGH). The
// reference persisted a "TRADING HALTED · positions frozen" banner in
// localStorage with a client countdown — but the engine is advisory-only and
// never freezes positions, so that banner is fiction. These readers return 0 so
// the banner never shows from stale/persisted state; the real driver (dd_state /
// weekly_pnl SSE + a `halted` flag on /api/state — G-O2) is wired in P1/P3.
function readHaltUntil() { return 0; }
function readHaltAt() { return 0; }
const fmtHaltAt = (ts) => { try { return new Date(ts + (window.QE_CLOCK_OFFSET || 0)).toISOString().slice(11, 19); } catch (e) { return ''; } };
// daily hard-stop releases at the next UTC day boundary (00:00 UTC)
function nextHaltRelease() { const d = new Date(); d.setUTCHours(24, 0, 0, 0); return d.getTime(); }
function fmtHaltLeft(ms) { if (ms < 0) ms = 0;
  const dd = Math.floor(ms / 86400000), hh = Math.floor(ms % 86400000 / 3600000), mm = Math.floor(ms % 3600000 / 60000), ss = Math.floor(ms % 60000 / 1000);
  return `${dd}d ${String(hh).padStart(2,'0')}h ${String(mm).padStart(2,'0')}m ${String(ss).padStart(2,'0')}s`; }
const HALT_GRASS = [
  'step away — go touch some grass.',
  'markets will survive without you. go outside.',
  'breathe, hydrate, go touch some grass.',
  'the highest-EV trade right now is a walk.',
];

const NotifBanner = () => {
  const ctx = React.useContext(NotifCtx);
  if (!ctx || !ctx.haltUntil) return null;
  const rem = ctx.haltUntil - Date.now();
  if (rem <= 0) return null;
  const grass = HALT_GRASS[Math.floor(ctx.haltUntil / 60000) % HALT_GRASS.length];
  // rendered with the Banner primitive (one banner implementation app-wide)
  return (
    <Banner tone="err" tag="HALT"
      time={ctx.haltAt > 0 ? fmtHaltAt(ctx.haltAt) : null}
      title="CALCULATOR BLOCKED"
      detail={<React.Fragment>hard-stop breached · new entries gated · open positions unaffected · <span style={{ color:'var(--qe-sub)' }}>{grass}</span></React.Fragment>}
      releaseIn={fmtHaltLeft(rem)}/>
  );
};

// ── row ──────────────────────────────────────────────────────────────────
const NotifRow = ({ ev, now, muted, onRead, onDismiss, onAction }) => {
  const sev = nSev(ev.pri); const colored = ev.pri !== 'routine';
  return (
    <div className="qe-notif-row" onClick={() => ev.unread && onRead(ev.id)}
      style={{ position:'relative', display:'flex', gap:9, padding:'5px 11px 6px 12px', cursor: ev.unread ? 'pointer' : 'default',
        borderBottom:'1px solid var(--qe-faint)', background: ev.unread ? 'color-mix(in srgb, var(--qe-text) 2%, transparent)' : 'transparent', opacity: muted ? 0.5 : 1 }}>
      {ev.unread && <span style={{ position:'absolute', left:0, top:0, bottom:0, width:2, background:sev }} />}
      <div style={{ minWidth:0, flex:1, display:'flex', flexDirection:'column', gap:1 }}>
        <div style={{ display:'flex', alignItems:'center', gap:7 }}>
          <span style={{ fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.14em', color:'var(--qe-muted)' }}>{ev.ch}</span>
          <span style={{ fontFamily:'var(--qe-mono)', fontSize:'0.5rem', letterSpacing:'0.02em', color:'var(--qe-muted)' }}>· {nAbs(ev.ts)}</span>
          {colored && <span style={{ fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.1em', color:sev }}>{ev.pri === 'halt' ? 'HALT' : 'RISK'}</span>}
          {muted && <span style={{ fontFamily:'var(--qe-mono)', fontSize:'0.5rem', letterSpacing:'0.08em', color:'var(--qe-muted)' }}>MUTED</span>}
          <span className="qe-grow" />
          <div className="qe-notif-actions" style={{ display:'flex', gap:4, alignItems:'center' }}>
            {onAction && <button title="Open" onClick={(e)=>{e.stopPropagation();onAction(ev);}} className="qe-notif-cta">{(N_ACTIONS[ev.ch]||['View'])[0]}</button>}
            {ev.unread && <button title="Mark read" onClick={(e)=>{e.stopPropagation();onRead(ev.id);}} className="qe-notif-ib">✓</button>}
            <button title="Dismiss" onClick={(e)=>{e.stopPropagation();onDismiss(ev.id);}} className="qe-notif-ib">×</button>
          </div>
          <span className="qe-notif-time" style={{ fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)' }}>{nRel(ev.ts, now)}</span>
          {ev.unread && <span style={{ width:5, height:5, borderRadius:'50%', background:sev, flexShrink:0 }} />}
        </div>
        <div style={{ fontFamily:'var(--qe-ui)', fontSize:'0.72rem', lineHeight:1.2, fontWeight: ev.unread ? 600 : 500, color: ev.unread ? 'var(--qe-text)' : 'var(--qe-sub)' }}>{ev.head}</div>
        <div style={{ fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)', lineHeight:1.28 }}>{ev.detail}</div>
      </div>
    </div>
  );
};

const NotifChip = ({ label, count, active, muted, onFilter, onMute }) =>
  <Chip label={label} count={count} active={active} muted={muted} onClick={onFilter} onMute={onMute} />;

const NotifSeg = ({ options, active, onPick }) => (
  <div style={{ display:'inline-flex', border:'1px solid var(--qe-line)' }}>
    {options.map((o,i) => (
      <button key={o} onClick={()=>onPick(o)} style={{ border:'none', borderRight: i<options.length-1 ? '1px solid var(--qe-line)' : 'none',
        cursor:'pointer', padding:'2px 9px', fontFamily:'var(--qe-mono)', fontSize:'0.56rem', fontWeight:600, letterSpacing:'0.04em',
        background: o===active ? 'var(--qe-active)' : 'transparent', color: o===active ? 'var(--qe-text)' : 'var(--qe-muted)' }}>{o}</button>
    ))}
  </div>
);

const NotifSwitch = ({ label, on, onToggle, title }) =>
  <Switch label={label} checked={on} onChange={onToggle} title={title} />;

// ── toast (thin wrapper over the <Toast> primitive) ──────────────────────
const NotifToast = ({ ev, onClick, onClose }) =>
  <Toast tone={ev.pri==='halt'?'err':ev.pri==='risk'?'warn':'mute'} tag={ev.ch} time={nAbs(ev.ts)}
    title={ev.head} detail={ev.detail} onClose={onClose} onClick={onClick} />;

// ── demo panel (fire scenarios) ──────────────────────────────────────────
const NotifDemo = ({ fire, autostream, onAuto, onReset, onHide }) => {
  const Btn = ({ label, k, danger }) => (
    <button onClick={()=>fire(k)} className={'qe-btn qe-btn-sm' + (danger ? ' qe-btn-danger' : '')} style={{ justifyContent:'center' }}>{label}</button>
  );
  return (
    <div style={{ position:'absolute', left:10, bottom:50, zIndex:70, width:198, background:'var(--qe-card)', border:'1px solid var(--qe-line-2)', boxShadow:'0 10px 30px rgba(0,0,0,0.6)' }}>
      <div style={{ display:'flex', alignItems:'center', gap:6, padding:'5px 9px', borderBottom:'1px solid var(--qe-line)', background:'var(--qe-panel)' }}>
        <span style={{ width:6, height:6, background:'var(--qe-cyan)' }} />
        <span style={{ fontFamily:'var(--qe-ui)', fontSize:'0.54rem', fontWeight:800, letterSpacing:'0.14em', color:'var(--qe-sub)' }}>DEMO · FIRE EVENTS</span>
        <span className="qe-grow" />
        <button onClick={onHide} title="Collapse demo panel" className="qe-btn qe-btn-ghost qe-btn-sm" style={{ height:16, padding:'0 5px' }}>–</button>
      </div>
      <div style={{ padding:8, display:'grid', gridTemplateColumns:'1fr 1fr', gap:5 }}>
        <Btn label="Fill" k="fill" /><Btn label="Partial" k="partial" /><Btn label="Risk" k="risk" />
        <Btn label="Link" k="link" /><Btn label="WS recon" k="ws" /><Btn label="Burst ×5" k="burst" />
        <button onClick={()=>fire('halt')} className="qe-btn qe-btn-sm qe-btn-danger" style={{ gridColumn:'1 / -1', justifyContent:'center' }}>⛔ HARD-STOP HALT</button>
      </div>
      <div style={{ display:'flex', alignItems:'center', gap:8, padding:'6px 9px', borderTop:'1px solid var(--qe-line)' }}>
        <NotifSwitch label="Auto-stream" on={autostream} onToggle={onAuto} />
        <span className="qe-grow" />
        <button onClick={onReset} className="qe-btn qe-btn-ghost qe-btn-sm">RESET</button>
      </div>
    </div>
  );
};

// ── provider — owns state, exposes ctx, overlays the page ────────────────
// `demo` defaults FALSE — the DEMO fire-events panel, autostream, WebAudio
// beep and desktop-notification dispatch are the reference's mock devices
// (plan §4) and must not ship. P8 wave 1: the provider is wired to the REAL
// feed — GET /notifications/poll (backend shipped in P1, G-O3) — and seeds
// EMPTY; the first poll (since=-1) primes the cursor without backlog replay.
function NotificationProvider({ children, demo = false }) {
  const [events, setEvents] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState('All');
  const [priority, setPriority] = React.useState('All');
  const [muted, setMuted] = React.useState({});
  const [sound, setSound] = React.useState(true);
  const [demoOpen, setDemoOpen] = React.useState(false); // demo panel starts collapsed — chip re-opens it
  const [desktop, setDesktop] = React.useState(false);
  const [dnd, setDnd] = React.useState(false);
  const [haltUntil, setHaltUntil] = React.useState(readHaltUntil);
  const [haltAt, setHaltAt] = React.useState(readHaltAt);
  const [toasts, setToasts] = React.useState([]);
  const [autostream, setAutostream] = React.useState(false);
  const [now, setNow] = React.useState(Date.now());
  const idRef = React.useRef(1);

  React.useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  // halt banner is up whenever the cooldown is still in the future
  const banner = haltUntil > now;
  // auto-release once the cooldown elapses (survives reload via localStorage)
  React.useEffect(() => {
    if (haltUntil && Date.now() >= haltUntil) {
      setHaltUntil(0); try { localStorage.removeItem(HALT_KEY); } catch (e) {}
      setHaltAt(0); try { localStorage.removeItem(HALT_AT_KEY); } catch (e) {}
      setEvents(list => [{ id:'e'+(idRef.current++), ch:'SYSTEM', pri:'routine', head:'Trading halt released', detail:'Daily hard-stop window elapsed · trading re-enabled', ts: Date.now(), unread:true }, ...list]);
    }
  }, [now, haltUntil]);
  const flags = React.useRef({}); flags.current = { muted, sound, desktop, dnd, open };
  const removeToast = (id) => setToasts(ts => ts.filter(t => t.id !== id));

  // ── G-O3 UI wire: the real notification feed (P8 wave 1) ────────────────
  // Poll /notifications/poll every 5s. The endpoint serves the v3 UI shape
  // {ch, pri, head, detail, ts} alongside the legacy {id, ...}; since=-1
  // primes the cursor (server returns latest_id + no backlog). Real events
  // ride the same toast/beep/DND rules as demo ones. A failed poll keeps
  // the bell quiet — no fabricated fallback.
  const sinceRef = React.useRef(-1);
  React.useEffect(() => {
    let alive = true;
    let inFlight = false;  // audit LOW-1: overlapping polls would re-read the
                           // same cursor and double-process events
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const r = await fetch('/notifications/poll?since=' + sinceRef.current,
          { headers: { Accept: 'application/json' } });
        if (!r.ok) return;
        const d = await r.json();
        if (!alive || !d || typeof d.latest_id !== 'number') return;
        const priming = sinceRef.current < 0;
        sinceRef.current = d.latest_id;
        if (priming) return;
        (d.notifications || []).forEach((n) => {
          const ev = {
            id: 'n' + n.id,
            ch: N_CHANNELS.indexOf(n.ch) >= 0 ? n.ch : 'SYSTEM',
            pri: n.pri || 'routine',
            head: n.head || n.message || '',
            detail: n.detail || '',
            ts: n.ts || n.ts_ms || Date.now(),
            unread: true,
          };
          setEvents((list) => [ev, ...list].slice(0, 200));
          const f = flags.current;
          if (!(f.dnd || f.muted[ev.ch])) {
            if (f.sound) nBeep(ev.pri);
            setToasts((ts) => [ev, ...ts].slice(0, 4));
            setTimeout(() => removeToast(ev.id), 5200);
          }
        });
      } catch (e) { /* engine unreachable — nothing to show */ }
      finally { inFlight = false; }
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const pushEvent = React.useCallback((key) => {
    const tpl = N_SCENARIOS[key](); if (!tpl) return;
    const ev = { ...tpl, id: 'e' + (idRef.current++), ts: Date.now(), unread: true };
    setEvents(list => [ev, ...list]);
    if (ev.pri === 'halt') { const until = nextHaltRelease(); setHaltUntil(until); try { localStorage.setItem(HALT_KEY, String(until)); } catch (e) {} const at = Date.now(); setHaltAt(at); try { localStorage.setItem(HALT_AT_KEY, String(at)); } catch (e) {} }
    const f = flags.current; const suppressed = f.dnd || f.muted[ev.ch];
    if (!suppressed) {
      if (f.sound) nBeep(ev.pri);
      setToasts(ts => [ev, ...ts].slice(0, 4));
      setTimeout(() => removeToast(ev.id), 5200);
      if (f.desktop && 'Notification' in window && Notification.permission === 'granted') {
        try { new Notification(ev.ch + ' · ' + ev.head, { body: ev.detail }); } catch (e) {}
      }
    }
  }, []);

  const fire = (key) => { if (key === 'burst') { ['fill','link','risk','ws','partial'].forEach((k,i)=>setTimeout(()=>pushEvent(k), i*420)); return; } pushEvent(key); };

  React.useEffect(() => { if (!autostream) return;
    const t = setInterval(() => pushEvent(N_STREAM[Math.floor(Math.random()*N_STREAM.length)]), 4500); return () => clearInterval(t); }, [autostream, pushEvent]);

  const markRead = (id) => setEvents(l => l.map(e => e.id === id ? { ...e, unread: false } : e));
  const dismiss = (id) => setEvents(l => l.filter(e => e.id !== id));
  // transient confirmation toast (not added to history)
  const actionToast = (label, target) => { const ev = { id:'act'+(idRef.current++), ch:'', pri:'routine', head:'→ ' + label, detail: target, ts: Date.now() };
    setToasts(ts => [ev, ...ts].slice(0, 4)); setTimeout(() => removeToast(ev.id), 3200); };
  // primary notification action: resolve (mark read), close the center, route
  const handleAction = (ev) => { const [label, target] = N_ACTIONS[ev.ch] || ['View', 'detail'];
    markRead(ev.id); setOpen(false); actionToast(label, target); };
  const markAll = () => setEvents(l => l.map(e => ({ ...e, unread: false })));
  const clearAll = () => setEvents([]);
  const toggleMute = (ch) => setMuted(m => ({ ...m, [ch]: !m[ch] }));
  // P0: no browser Notification.requestPermission() prompt (plan §4). The toggle
  // just flips the flag; desktop dispatch stays gated behind pushEvent (demo-only)
  // so nothing fires. Real desktop-notification support is deferred.
  const toggleDesktop = () => setDesktop(v => !v);
  const reset = () => { setEvents([]); setHaltUntil(0); try { localStorage.removeItem(HALT_KEY); } catch (e) {} setHaltAt(0); try { localStorage.removeItem(HALT_AT_KEY); } catch (e) {} setToasts([]); setFilter('All'); setPriority('All'); setMuted({}); };

  const unread = events.filter(e => e.unread && !muted[e.ch]).length;
  const counts = N_CHANNELS.reduce((a, ch) => (a[ch] = events.filter(e => e.ch === ch).length, a), {});
  const priPass = (e) => priority === 'All' ? true : priority === 'Risk+' ? (e.pri==='risk'||e.pri==='halt') : e.pri==='halt';
  const visible = events.filter(e => (filter === 'All' || e.ch === filter) && priPass(e));
  const justNow = visible.filter(e => now - e.ts < 120000);
  const earlier = visible.filter(e => now - e.ts >= 120000);

  const ctx = { unread, open, banner, haltUntil, haltAt, toggleOpen: () => setOpen(o => !o) };
  // height of the nav chrome (dense nav 32 + workspace bar 22, + halt banner 30)
  // so the center / scrim sit BELOW the title bar and never cover or dim it.
  const navH = banner ? 84 : 54;

  const Group = ({ title, rows }) => rows.length === 0 ? null : (
    <React.Fragment>
      <div style={{ padding:'4px 11px 3px', fontFamily:'var(--qe-ui)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.16em', color:'var(--qe-muted)', textTransform:'uppercase' }}>{title}</div>
      {rows.map(ev => <NotifRow key={ev.id} ev={ev} now={now} muted={!!muted[ev.ch]} onRead={markRead} onDismiss={dismiss} onAction={handleAction} />)}
    </React.Fragment>
  );

  return (
    <NotifCtx.Provider value={ctx}>
      <div style={{ position:'relative', height:'100%', width:'100%', overflow:'hidden' }}>
        {children}
        {/* scrim — below the title bar so the nav stays bright + interactive */}
        {open && <div onClick={() => setOpen(false)} style={{ position:'absolute', top:navH, left:0, right:0, bottom:0, background:'rgba(0,0,0,0.4)', zIndex:55 }} />}
        {/* drawer — starts below the title bar */}
        {open && (
          <div style={{ position:'absolute', top:navH, right:0, bottom:0, width:362, zIndex:58, background:'var(--qe-card)', borderLeft:'1px solid var(--qe-line-2)', borderTop:'1px solid var(--qe-line-2)', boxShadow:'-14px 0 40px rgba(0,0,0,0.6)', display:'flex', flexDirection:'column' }}>
            <div style={{ flexShrink:0, padding:'8px 11px', borderBottom:'1px solid var(--qe-line)', display:'flex', flexDirection:'column', gap:7 }}>
              <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                <span style={{ fontFamily:'var(--qe-ui)', fontWeight:700, fontSize:'0.72rem', letterSpacing:'0.12em', color:'var(--qe-text)' }}>NOTIFICATIONS</span>
                <span style={{ fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color: unread ? 'var(--qe-sub)' : 'var(--qe-muted)' }}>{unread} unread</span>
                {dnd && <span style={{ fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.1em', color:'var(--qe-amber)', border:'1px solid var(--qe-amber)', padding:'0 4px' }}>DND</span>}
                <span className="qe-grow" />
                <button onClick={markAll} className="qe-btn qe-btn-ghost qe-btn-sm" style={{ opacity: unread?1:0.4 }}>MARK ALL READ</button>
                <button onClick={clearAll} className="qe-btn qe-btn-ghost qe-btn-sm" style={{ opacity: events.length?1:0.4 }}>CLEAR</button>
                <span onClick={() => setOpen(false)} title="Close" style={{ color:'var(--qe-muted)', fontSize:'0.95rem', cursor:'pointer', paddingLeft:2 }}>×</span>
              </div>
              <div style={{ display:'flex', flexWrap:'wrap', gap:4 }}>
                <NotifChip label="All" count={events.length} active={filter==='All'} onFilter={()=>setFilter('All')} />
                {N_CHANNELS.map(ch => <NotifChip key={ch} label={ch} count={counts[ch]} active={filter===ch} muted={!!muted[ch]} onFilter={()=>setFilter(ch)} onMute={()=>toggleMute(ch)} />)}
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                <span style={{ fontFamily:'var(--qe-ui)', fontSize:'0.52rem', fontWeight:700, letterSpacing:'0.12em', color:'var(--qe-muted)', textTransform:'uppercase' }}>PRIORITY</span>
                <NotifSeg options={['All','Risk+','Halt']} active={priority} onPick={setPriority} />
              </div>
            </div>
            <div style={{ flex:1, minHeight:0, overflowY:'auto' }}>
              {visible.length === 0 ? (
                <div className="qe-empty" style={{ margin:12 }}>
                  <div className="qe-empty-glyph">— — —</div>
                  <div className="qe-empty-msg">{events.length ? 'Nothing matches this filter' : 'No notifications'}</div>
                  {events.length>0 && <button onClick={()=>{setFilter('All');setPriority('All');}} className="qe-btn qe-btn-sm qe-empty-cta">Clear filters</button>}
                </div>
              ) : (
                <React.Fragment><Group title="Just now" rows={justNow} /><Group title="Earlier today" rows={earlier} /></React.Fragment>
              )}
            </div>
            <div style={{ flexShrink:0, padding:'7px 11px', borderTop:'1px solid var(--qe-line)', background:'var(--qe-panel)', display:'flex', alignItems:'center', gap:14 }}>
              <NotifSwitch label="Sound" on={sound} onToggle={()=>setSound(v=>!v)} title="Play a cue on incoming" />
              <NotifSwitch label="Desktop" on={desktop} onToggle={toggleDesktop} title="Browser push notifications" />
              <NotifSwitch label="DND" on={dnd} onToggle={()=>setDnd(v=>!v)} title="Do not disturb" />
            </div>
          </div>
        )}
        {/* toasts — persist through open/close; slide left of the drawer when open */}
        {toasts.length > 0 && (
          <div style={{ position:'absolute', top: banner ? 92 : 62, right: open ? 370 : 8, zIndex:60, display:'flex', flexDirection:'column', gap:5, transition:'right .18s ease' }}>
            {toasts.map(t => <NotifToast key={t.id} ev={t} onClick={() => { setOpen(true); markRead(t.id); removeToast(t.id); }} onClose={() => removeToast(t.id)} />)}
          </div>
        )}
        {demo && (demoOpen
          ? <NotifDemo fire={fire} autostream={autostream} onAuto={()=>setAutostream(v=>!v)} onReset={reset} onHide={()=>setDemoOpen(false)} />
          : <button onClick={()=>setDemoOpen(true)} title="Open the notification demo panel" className="qe-btn qe-btn-sm" style={{ position:'absolute', left:10, bottom:50, zIndex:70, opacity:0.8 }}>◆ DEMO</button>)}
      </div>
    </NotifCtx.Provider>
  );
}

Object.assign(window, { NotifCtx, NotifBell, NotifBanner, NotifRow, NotificationProvider });
