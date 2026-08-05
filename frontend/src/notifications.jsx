// ════════════════════════════════════════════════════════════════════════
//  v3.0 — Notification System (ported from Meridian QE v2.5)
//  Context-driven: <NotificationProvider> wraps any page; the bell lives in
//  the real TopNavStd and the drawer / toasts overlay the page. App-global
//  notification taxonomy (the REAL producer set, G-O3): fills, risk/drawdown,
//  calc-link, system/WS. (The halt banner is SERVER state and lives in
//  nav-and-data's ChromeHaltBanner; the demo panel is gone — 2026-08-05.)
//  Single script scope — all helpers below are visible to each other; only
//  NotifCtx / NotifBell / NotifRow / NotificationProvider are exported.
// ════════════════════════════════════════════════════════════════════════

const NotifCtx = React.createContext(null);

// ── taxonomy ─────────────────────────────────────────────────────────────
// P8 wave 1 (G-O3 UI wire): scoped to the FOUR channels the engine actually
// produces (core/notifications.py _TYPE_UI: LINK/RISK/FILLS + SYSTEM
// fallback). The design's REGIME/NEWS channels have no producer — their
// chips were fiction and are gone until real producers exist.
const N_CHANNELS = ['FILLS', 'RISK', 'LINK', 'SYSTEM'];
// Per-channel primary action — [button label, DESTINATION PAGE].
// The second element used to be a prose "target description" that was only
// ever rendered into a confirmation toast; the button marked the row read,
// closed the drawer, claimed "→ Review risk / risk panel" and then went
// NOWHERE (2026-08-05 batch). Each entry is now a real QE_PAGES key routed
// through window.qeNav, and a channel with no honest destination gets NO
// button rather than one pointing approximately.
//   FILLS  → History   (the fills / order rows live there; "order detail" as
//                       a standalone page never existed — that was the
//                       ambiguity that made the original CTA unwireable)
//   RISK   → Dashboard (Risk Monitor: DD state, gauges, the override control)
//   LINK   → Linkage   (the triage board the alert is about)
//   SYSTEM → Dashboard (the Engine Log pane — a real live feed since
//                       3b9ef67; before that this channel had no destination)
const N_ACTIONS = {
  FILLS:  ['View in History', 'History'],
  RISK:   ['Review risk',     'Dashboard'],
  SYSTEM: ['Engine log',      'Dashboard'],
  LINK:   ['Link trades',     'Linkage'],
};
const nSev = (pri) => pri === 'halt' ? 'var(--qe-red)' : pri === 'risk' ? 'var(--qe-amber)' : 'var(--qe-line-2)';

/* N_SCENARIOS / N_STREAM / _rnd / _px DELETED 2026-08-05 with the demo panel:
   seven Math.random() event templates that fabricated fills, drawdowns and a
   hard-stop halt. They were the mock feed this provider used before the real
   one existed (GET /notifications/poll, P8 wave 1). Keeping fabricated RISK
   and HALT payloads in a shipped risk console is a liability even behind a
   flag — the halt template is exactly the string an operator would screenshot
   in a panic. */

// The real feed's cadence — one literal, read by both the setInterval and the
// read deadline derived from it (warm-hang sweep, 2026-08-01).
const N_POLL_MS = 5000;

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

/* ── THE CLIENT-SIDE HALT SUBSYSTEM IS GONE (2026-08-05, whole) ───────────
   Removed together, because they only ever fed each other: HALT_KEY /
   HALT_AT_KEY, readHaltUntil / readHaltAt (both `return 0` since P0),
   nextHaltRelease, the haltUntil / haltAt state, the auto-release effect,
   and — earlier the same day — NotifBanner with fmtHaltAt / fmtHaltLeft /
   HALT_GRASS.

   Why it was inert: P0 deleted the localStorage halt AUTHORITY as fiction
   (the reference persisted a "TRADING HALTED · positions frozen" banner with
   a client countdown, but this engine is advisory-only and never freezes
   positions). The readers were stubbed to 0, leaving the demo panel's halt
   scenario as the ONLY writer — so with the demo panel deleted, every last
   piece is unreachable.

   Halt is SERVER state now, and has been since P1/P3: `ChromeHaltBanner`
   (nav-and-data.jsx) renders chrome-wide off /api/state's `halted` /
   `blocked`, with dd_state over SSE. Nothing here should ever again decide
   whether trading is halted — a client that can persist its own halt can
   also disagree with the engine about one. */

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
            {/* No fallback label: a channel absent from N_ACTIONS has no
                destination, so it gets NO button. The old `||['View']` armed a
                button that could only ever go nowhere. */}
            {onAction && N_ACTIONS[ev.ch] && <button title={'Open ' + N_ACTIONS[ev.ch][1]} onClick={(e)=>{e.stopPropagation();onAction(ev);}} className="qe-notif-cta">{N_ACTIONS[ev.ch][0]}</button>}
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

const NotifSwitch = ({ label, on, onToggle, title, disabled = false }) =>
  <Switch label={label} checked={on} onChange={onToggle} title={title} disabled={disabled} />;

// ── toast (thin wrapper over the <Toast> primitive) ──────────────────────
const NotifToast = ({ ev, onClick, onClose }) =>
  <Toast tone={ev.pri==='halt'?'err':ev.pri==='risk'?'warn':'mute'} tag={ev.ch} time={nAbs(ev.ts)}
    title={ev.head} detail={ev.detail} onClose={onClose} onClick={onClick} />;

/* NotifDemo (the "DEMO · FIRE EVENTS" panel) DELETED 2026-08-05, with its
   `demo` prop, the ◆ DEMO chip, `demoOpen`, `autostream` + its interval,
   `pushEvent`, `fire` and `reset`.

   It was already UNREACHABLE: `demo` defaulted false and the app's sole mount
   (app-shell.jsx) passes no props — so it could not be opened without editing
   code, which means nothing was lost as a debugging affordance. Deleting it
   is what let the client-side halt subsystem go whole (see the note above):
   the panel's halt scenario was that subsystem's last writer. */

// ── provider — owns state, exposes ctx, overlays the page ────────────────
// Wired to the REAL feed — GET /notifications/poll (backend shipped in P1,
// G-O3) — and seeds EMPTY; the first poll (since=-1) primes the cursor
// without backlog replay. The WebAudio beep is the one reference "mock
// device" still here, and it is real feedback on real events.
function NotificationProvider({ children }) {
  const [events, setEvents] = React.useState([]);
  const [open, setOpen] = React.useState(false);
  const [filter, setFilter] = React.useState('All');
  const [priority, setPriority] = React.useState('All');
  const [muted, setMuted] = React.useState({});
  const [sound, setSound] = React.useState(true);
  const [dnd, setDnd] = React.useState(false);
  const [toasts, setToasts] = React.useState([]);
  const [now, setNow] = React.useState(Date.now());
  /* `idRef` (the client-side id minter) went with them too — its only three
     consumers were pushEvent, actionToast and the halt auto-release event.
     The real feed mints ids server-side (`id: 'n' + n.id` in poll()). It
     survived my first stranded-state sweep and was caught by the audit. */

  React.useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  /* Gone with the demo panel + halt subsystem (2026-08-05): the `banner` flag,
     haltUntil / haltAt and the auto-release effect that cleared them, plus
     `demoOpen` / `autostream`. Also `desktop` + `toggleDesktop`: the ONLY
     dispatch site was inside the demo's pushEvent, so once that went the state
     had no reader — the real feed's toast path below never consulted it. The
     drawer's Desktop switch stays exactly as the 2026-07-25 operator decision
     left it (rendered, disabled, honestly titled); to SHIP the capability,
     request permission when that switch is enabled and dispatch a
     `new Notification(...)` in poll() beside the nBeep call, respecting
     muted/dnd. That instruction is the documentation — a dead toggleDesktop
     standing in for it was itself the pattern this batch removes. */
  const flags = React.useRef({}); flags.current = { muted, sound, dnd, open };
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
      // DEADLINE (2026-08-01, warm-hang sweep). This latch is released in the
      // `finally` below — which a promise that never settles never reaches.
      // One hung poll therefore killed the alert feed for the rest of the
      // session, silently: no error, no retry, a quiet bell on a risk console.
      // The deadline turns the hang into a rejection, so the finally runs.
      const url = '/notifications/poll?since=' + sinceRef.current;
      let deadline = null;   // cleared in the finally, so the BODY read is
                             // covered too (headers-then-stalled-stream hangs
                             // exactly like a dead socket)
      try {
        const got = await _ptFetch(url,
          { headers: { Accept: 'application/json' } }, qePollDeadline(N_POLL_MS));
        deadline = got.t;
        if (!got.r.ok) return;
        const d = await got.r.json();
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
      finally { clearTimeout(deadline); inFlight = false; }
    };
    poll();
    const t = setInterval(poll, N_POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const markRead = (id) => setEvents(l => l.map(e => e.id === id ? { ...e, unread: false } : e));
  const dismiss = (id) => setEvents(l => l.filter(e => e.id !== id));
  /* Primary notification action: resolve (mark read), close the drawer, and
     ACTUALLY NAVIGATE. The `actionToast` that used to stand in for the
     navigation is deleted — it rendered "→ Review risk / risk panel", which
     reads as confirmation that the jump happened. On a risk console a control
     that reports success it did not achieve is worse than one that visibly
     does nothing: it trains the operator to believe the alert was actioned.
     Arriving on the page is its own feedback, so nothing replaces it; if
     qeNav is somehow absent the row still marks read and the drawer still
     closes, and NOTHING claims a jump occurred. */
  const handleAction = (ev) => {
    const entry = N_ACTIONS[ev.ch];
    if (!entry) return;               // no destination → the row renders no button
    markRead(ev.id); setOpen(false);
    if (window.qeNav) window.qeNav(entry[1]);
  };
  const markAll = () => setEvents(l => l.map(e => ({ ...e, unread: false })));
  const clearAll = () => setEvents([]);
  const toggleMute = (ch) => setMuted(m => ({ ...m, [ch]: !m[ch] }));
  /* Desktop notifications stay DEFERRED (plan §7 explicit defer list) — the
     drawer's switch is rendered disabled with an honest title, per the
     2026-07-25 operator decision. See the state block above for how to ship
     it; `desktop`/`toggleDesktop` are gone because the demo's pushEvent was
     their only reader. `reset` went with the demo panel that called it. */

  const unread = events.filter(e => e.unread && !muted[e.ch]).length;
  const counts = N_CHANNELS.reduce((a, ch) => (a[ch] = events.filter(e => e.ch === ch).length, a), {});
  const priPass = (e) => priority === 'All' ? true : priority === 'Risk+' ? (e.pri==='risk'||e.pri==='halt') : e.pri==='halt';
  const visible = events.filter(e => (filter === 'All' || e.ch === filter) && priPass(e));
  const justNow = visible.filter(e => now - e.ts < 120000);
  const earlier = visible.filter(e => now - e.ts >= 120000);

  // haltUntil/haltAt left the context with NotifBanner, their only reader
  // (batch audit #6) — the state itself stays for the demo-gated halt lane.
  const ctx = { unread, open, toggleOpen: () => setOpen(o => !o) };
  // height of the nav chrome (dense nav 32 + workspace bar 22, + halt banner 30)
  // so the center / scrim sit BELOW the title bar and never cover or dim it.
  // 54 = dense nav 32 + workspace bar 22. Each under-nav Banner is 30px + 1px
  // border. qeChromeBannerCount (nav-and-data) is the single source of truth so
  // the offset and the banners can never disagree.
  const navH = 54 + 31 * (typeof qeChromeBannerCount === 'function' ? qeChromeBannerCount() : 0);

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
              {/* shell-chrome-2 (2026-07-25 Meridian audit): rendered DISABLED, not
                  live. Desktop notifications are on plan §7's explicit defer list
                  and no dispatch exists on the real feed path, so a live-looking
                  switch promised out-of-focus reachability it could not deliver —
                  worse than either wiring it or showing it off. Operator decision
                  2026-07-25: keep the deferral, make the control honest. To ship
                  it later: request permission when this switch is enabled and
                  dispatch from poll() beside the nBeep call, respecting
                  muted/dnd. */}
              <NotifSwitch label="Desktop" on={false} disabled
                title="Desktop notifications are deferred (plan §7) — not yet implemented" />
              <NotifSwitch label="DND" on={dnd} onToggle={()=>setDnd(v=>!v)} title="Do not disturb" />
            </div>
          </div>
        )}
        {/* toasts — persist through open/close; slide left of the drawer when
            open. Offset is navH + 8, NOT a hardcoded 62/92 pair keyed on the
            dead `banner` flag: `banner` derived from haltUntil, which
            readHaltUntil() pins at 0 forever (P0 removed the localStorage halt
            authority as fiction), so the 92 arm was unreachable and toasts sat
            at 62 while the drawer/scrim above followed the LIVE
            qeChromeBannerCount. One real under-nav banner put navH at 85 and
            the toast overlapped it by ~23px; two banners, 54px. Same navH
            source as the scrim, so they cannot disagree. (The counter itself
            was missing its operator-seat arm — fixed in nav-and-data.jsx in
            the same commit; this comment claimed coverage the counter did not
            have, which is the exact failure this batch elsewhere repairs.) */}
        {toasts.length > 0 && (
          <div style={{ position:'absolute', top: navH + 8, right: open ? 370 : 8, zIndex:60, display:'flex', flexDirection:'column', gap:5, transition:'right .18s ease' }}>
            {toasts.map(t => <NotifToast key={t.id} ev={t} onClick={() => { setOpen(true); markRead(t.id); removeToast(t.id); }} onClose={() => removeToast(t.id)} />)}
          </div>
        )}
      </div>
    </NotifCtx.Provider>
  );
}

Object.assign(window, { NotifCtx, NotifBell, NotifRow, NotificationProvider });
