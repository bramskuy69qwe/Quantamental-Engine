/* v3.0 — Shared nav + chrome components used across the app.
   P8 wave 1: the P0 MOCK dataset + QE_LIVE/QE_POS random walks are GONE.
   The chrome binds the shared QE_CHROME store (chrome-live.js — /api/state ·
   /api/dashboard/snapshot · /api/system · /accounts · QE_SSE status) and
   renders '—' when a source has no data (no fabrication, PaneFoot-v2
   doctrine). */

// DESIGN.md §8 regime label → RegimeBadge tone (chrome-local copy; the page
// modules load after this one and can't be referenced at eval time).
const NAV_REGIME_TONE = {
  risk_on_trending: 'trend', risk_on_choppy: 'chop', neutral: 'neut',
  risk_off_defensive: 'def', risk_off_panic: 'panic',
};

// SSE status → StatusDot tone (sse-adapter status values).
const NAV_SSE_TONE = { open: 'ok', connecting: 'warn', error: 'err', idle: 'off', disabled: 'off' };

/* shell-chrome-3 (2026-07-25 Meridian design-consistency audit) — EXCHANGE
 * MARKET-DATA feed health, read from `/api/state.exchange_ws` (QE_CHROME polls
 * /api/state every 10s, so this costs no extra request).
 *
 * INDEPENDENT of the SSE dot beside it: SSE is browser<->engine, this is
 * engine<->exchange. When the market feed drops, every price on screen freezes
 * while SSE keeps reporting "live" — so both dots must exist, and the audit's
 * finding was that only the SSE one did.
 *
 * The endpoint feeds this from the MARKET socket's own flags. It must never be
 * re-pointed at ws.connected / ws.last_update: those are the USER-DATA socket
 * (and last_update is floored by the 30s REST refresh), which is exactly the
 * mis-wiring the fix-review pass caught here before commit — it made this dot
 * lie in both directions.
 *
 * Supersedes this file's former justification for dropping the LAT cell, which
 * asserted the engine had no per-frame latency reading. It does — core/ws_manager
 * stamps one on every market frame, and the Jinja exchange_info fragment already
 * preferred it over the REST ping.
 *
 * STALE_S — the socket can claim connected while no frame has arrived for a
 * long time (silent half-open). Past this many seconds we degrade to warn and
 * show the age instead of the latency, because the age is the load-bearing
 * fact. Safe to keep tight now that the clock is market-frames-only: a live
 * feed stamps sub-second, so a healthy engine cannot drift across it.
 */
const NAV_FEED_STALE_S = 30;
const _navFeed = (ch) => {
  // A health indicator must not stay green when its own SOURCE is dead:
  // chrome-live keeps the last-good /api/state payload and only raises stateErr,
  // so without this branch the dot would show a stale 'ok' forever after the
  // engine goes away. Checked FIRST, before the last-good payload is read.
  if (ch && ch.stateErr) return { tone: 'off', value: '—',
    title: 'Exchange feed: reading unavailable — /api/state is not responding' };
  const w = (ch && ch.state && ch.state.exchange_ws) || null;
  if (!w) return { tone: 'off', value: '—',
    title: 'Exchange market-data feed: no reading yet (/api/state)' };
  if (!w.connected) return { tone: 'err', value: 'down',
    title: 'Exchange market-data websocket is DOWN — prices on screen are frozen' };
  if (w.stale_s != null && w.stale_s > NAV_FEED_STALE_S) return {
    tone: 'warn', value: Math.round(w.stale_s) + 's',
    title: `Exchange feed connected but no message for ${Math.round(w.stale_s)}s — prices may be stale`,
  };
  // On REST fallback the websocket is NOT delivering, so latency_ms is frozen at
  // whatever the last live frame measured. Showing it would present a stale
  // number as current — say REST instead.
  if (w.using_fallback) return { tone: 'warn', value: 'REST',
    title: 'Exchange market-data on REST FALLBACK — the websocket is not delivering; prices update on the poll interval' };
  return {
    tone: 'ok',
    value: w.latency_ms == null ? '—' : Math.round(w.latency_ms) + 'ms',
    title: 'Exchange market-data websocket live'
      + (w.latency_ms == null ? ' · latency not measured yet' : ` · ${Math.round(w.latency_ms)}ms per-frame latency`),
  };
};

const _navCap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : '—');
const _navPct = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%');
const _navPctCol = (v) => (v == null ? 'var(--qe-muted)'
  : v > 0 ? 'var(--qe-green)' : v < 0 ? 'var(--qe-red)' : 'var(--qe-sub)');
const _navUptime = (s) => {
  if (s == null) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d > 0 ? `${d}d ${h}h` : h > 0 ? `${h}h ${m}m` : `${m}m`;
};

// ── TopNav — used in all variants except command-bar variant ─────────────
const NAV_ITEMS = ['Dashboard','Pre-Trade','Linkage','History','Analytics','Models','Regime','Primitives'];

// ── One clock for the whole app ──────────────────────────────────────
// P0: the frozen mock clock (anchored to 2026-04-25) is REMOVED (plan §4).
// Renders real wall-clock UTC now; true server/account-time sync (via the
// ws_status exchange clock offset) is a later refinement. QE_CLOCK_OFFSET is
// kept (=0) because notifications.jsx reads window.QE_CLOCK_OFFSET.
const QE_CLOCK_OFFSET = 0;
const qeClockFmt = (t) => { const s = new Date(t.getTime() + QE_CLOCK_OFFSET).toISOString(); return s.slice(0, 10) + ' ' + s.slice(11, 19) + ' UTC'; };

// Dashboard workspace presets — real layouts, keyed to the dashboard's tile
// order (EquityStats · EquityCurve · Risk · Positions · Signals · Monthly ·
// Params · Log). Applied by index via qeWorkspaceSetLayout.
const QE_DASH_PRESETS = {
  Risk: [
    { x: 0, y: 16, w: 8, h: 8 }, { x: 8, y: 9, w: 8, h: 7 }, { x: 0, y: 0, w: 8, h: 16 }, { x: 8, y: 0, w: 16, h: 9 },
    { x: 16, y: 9, w: 8, h: 7 }, { x: 8, y: 16, w: 8, h: 8 }, { x: 16, y: 16, w: 4, h: 8 }, { x: 20, y: 16, w: 4, h: 8 },
  ],
  Execution: [
    { x: 0, y: 10, w: 6, h: 7 }, { x: 16, y: 0, w: 8, h: 10 }, { x: 6, y: 10, w: 5, h: 7 }, { x: 0, y: 0, w: 16, h: 10 },
    { x: 11, y: 10, w: 5, h: 7 }, { x: 0, y: 17, w: 16, h: 7 }, { x: 16, y: 17, w: 8, h: 7 }, { x: 16, y: 10, w: 8, h: 7 },
  ],
  Macro: [
    { x: 0, y: 16, w: 6, h: 8 }, { x: 8, y: 0, w: 16, h: 8 }, { x: 6, y: 16, w: 6, h: 8 }, { x: 12, y: 16, w: 8, h: 8 },
    { x: 0, y: 0, w: 8, h: 16 }, { x: 16, y: 8, w: 8, h: 8 }, { x: 20, y: 16, w: 4, h: 8 }, { x: 8, y: 8, w: 8, h: 8 },
  ],
};

// ─────────────────────────────────────────────────────────────────────────
// WorkspaceBar — the workspace + exchange-info strip shown under the top nav on
// EVERY page (so workspace presets and live exchange info are always visible).
// Workspace controls (presets · save · load · create) are only usable on the
// Dashboard; elsewhere they render disabled. ⊞ Pane / ⤢ Pop are planned stubs
// (always disabled). The exchange Strip stays live everywhere.
// ─────────────────────────────────────────────────────────────────────────
const WorkspaceBar = ({ interactive = false, persistId = 'dashboard' }) => {
  const ch = useQeChrome();
  const [preset, setPreset] = React.useState('Default');
  const [flash, setFlash] = React.useState(null);          // transient status text
  const flashTimer = React.useRef(null);
  const say = (msg) => {
    setFlash(msg);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 1800);
  };
  React.useEffect(() => () => clearTimeout(flashTimer.current), []);

  const presets = ['Default', 'Risk', 'Execution', 'Macro'];
  const onSave = () => say(window.qeWorkspaceSave(persistId) ? '✓ Saved' : 'Save failed');
  const onLoad = () => say(window.qeWorkspaceHasSaved(persistId)
    ? (window.qeWorkspaceLoad(persistId) ? '✓ Loaded' : 'Load failed')
    : 'No saved layout');
  const onCreate = () => { window.qeWorkspaceReset(persistId); say('New workspace'); };
  const onPreset = (p) => {
    setPreset(p);
    // Default restores the baseline layout; the named presets are real layout
    // maps (dashboard tile order) applied through the workspace registry.
    if (p === 'Default') { window.qeWorkspaceReset(persistId); say('Default layout'); }
    else if (QE_DASH_PRESETS[p] && window.qeWorkspaceSetLayout(persistId, QE_DASH_PRESETS[p])) say(p + ' layout');
    else say('Preset unavailable');
  };

  const dim = interactive ? 1 : 0.4;
  const guard = (fn) => interactive ? fn : undefined;

  return (
    <div className="qe-hscroll" style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '2px 6px', borderBottom: '1px solid var(--qe-line)',
      background: 'var(--qe-page)', height: 22, flexShrink: 0,
    }}>
      <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', letterSpacing: '0.1em' }}>WORKSPACE</span>

      <div className="qe-period" style={{ opacity: dim, pointerEvents: interactive ? 'auto' : 'none' }}>
        {presets.map(p => (
          <button key={p} className={preset === p ? 'on' : ''} onClick={guard(() => onPreset(p))}>{p}</button>
        ))}
      </div>

      {/* Save · Load · Create — workspace layout actions (Dashboard only) */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, opacity: dim, pointerEvents: interactive ? 'auto' : 'none' }}>
        <button className="qe-btn qe-btn-sm" onClick={guard(onSave)}   title="Save current layout">⤓ Save</button>
        <button className="qe-btn qe-btn-sm" onClick={guard(onLoad)}   title="Load saved layout">⤒ Load</button>
        <button className="qe-btn qe-btn-sm" onClick={guard(onCreate)} title="New workspace from default" style={{ width: 22, padding: 0, justifyContent: 'center' }}>+</button>
        {flash && <span className="qe-mono" style={{ fontSize: '0.54rem', color: flash[0] === '✓' ? 'var(--qe-green)' : 'var(--qe-amber)' }}>{flash}</span>}
      </div>

      {!interactive && (
        <span className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-faint)', letterSpacing: '0.06em' }}>· dashboard only</span>
      )}

      <div className="qe-grow" />

      {/* P8 wave 1: real chrome strip — /api/state (10s) + snapshot (30s);
          '—' when a source has no data yet (never fabricate).
          shell-chrome-3 (Meridian audit) RESTORED the design's LAT cell. The
          justification that used to sit here — that the engine had no
          per-market-frame latency reading — was simply untrue: core/ws_manager
          stamps one on every market frame, and it now rides
          /api/state.exchange_ws. LAT is the EXCHANGE FEED's latency; the SSE dot
          in the top nav is a different pipe entirely. */}
      <Strip dense items={(() => {
        const st = ch.state, eq = ch.snap && ch.snap.equity, rk = ch.snap && ch.snap.risk;
        const jr = ch.snap && ch.snap.journal, rg = ch.snap && ch.snap.regime;
        const active = (ch.accounts || []).find((a) => a.is_active);
        const dPct = eq ? eq.daily_pnl_pct : null;
        const wPct = eq ? eq.weekly_pnl_pct : null;
        const mPct = jr ? jr.monthly_pnl_pct : null;
        const feed = _navFeed(ch);
        return [
          { label: 'EXCH',   value: active ? _navCap(active.exchange) : '—' },
          { label: 'LAT',    value: <span title={feed.title} style={{
              color: feed.tone === 'err' ? 'var(--qe-red)'
                : feed.tone === 'warn' ? 'var(--qe-amber)'
                : feed.tone === 'off' ? 'var(--qe-muted)' : 'var(--qe-sub)',
            }}>{feed.value}</span> },
          { label: 'REGIME', value: rg && rg.label && NAV_REGIME_TONE[rg.label]
              ? <RegimeBadge tone={NAV_REGIME_TONE[rg.label]} />
              : <span style={{ color: 'var(--qe-muted)' }}>—</span> },
          { label: 'P&L·D',  value: <LiveValue id="ws.pnl.d" value={dPct == null ? '—' : dPct} format={() => _navPct(dPct)} style={{ color: _navPctCol(dPct), fontWeight: 700 }} /> },
          { label: 'P&L·W',  value: <LiveValue id="ws.pnl.w" value={wPct == null ? '—' : wPct} format={() => _navPct(wPct)} style={{ color: _navPctCol(wPct), fontWeight: 700 }} /> },
          { label: 'P&L·M',  value: <LiveValue id="ws.pnl.m" value={mPct == null ? '—' : mPct} format={() => _navPct(mPct)} style={{ color: _navPctCol(mPct), fontWeight: 700 }} /> },
          { label: 'OPEN',   value: st ? `${st.position_count}${rk && rk.positions_max != null ? '/' + rk.positions_max : ''}` : '—', color: 'var(--qe-cyan)' },
          { label: 'EXP',    value: <LiveValue id="ws.exp" value={st ? st.total_exposure : '—'} format={(x) => (st ? (+x).toFixed(2) + '×' : '—')} /> },
          { label: 'DD',     value: <LiveValue id="ws.dd" value={st ? st.drawdown * 100 : '—'} format={(x) => (st ? (+x).toFixed(2) + '%' : '—')} style={st && st.dd_state !== 'ok' ? { color: st.dd_state === 'limit' ? 'var(--qe-red)' : 'var(--qe-amber)', fontWeight: 700 } : undefined} /> },
        ];
      })()} />

      <button className="qe-btn qe-btn-sm" disabled title="Add pane — planned, not wired in this build" style={{ opacity: 0.4, cursor: 'default' }}>⊞ Pane</button>
      <button className="qe-btn qe-btn-sm" disabled title="Pop out — planned, not wired in this build" style={{ opacity: 0.4, cursor: 'default' }}>⤢ Pop</button>
    </div>
  );
};

// ── OS-clock-drift banner (operator clock-drift bug) ────────────────────────
// Renders in the SAME shared under-nav slot as the halt banner (NotifBanner),
// stacked ABOVE it (system alert takes priority), on EVERY page — a drifted OS
// clock breaks every SIGNED exchange read (Binance -1021, >1000ms ahead), not
// one page. Reads the shared QE_CHROME store (/api/state clock_severity ·
// offset = exchange − local, so local drift = −offset; positive ⇒ AHEAD, the
// -1021 direction). Null (0-height) when the clock is ok.
const ClockDriftBanner = () => {
  const ch = useQeChrome();
  const state = (ch && ch.state) || {};
  const sev = state.clock_severity;
  if (!sev || sev === 'ok') return null;
  const drift = -Math.round(state.clock_offset_ms || 0);
  const driftStr = (drift >= 0 ? '+' : '') + drift + 'ms';
  const failed = sev === 'failed';
  return (
    <Banner
      tone={sev === 'warn' ? 'warn' : 'err'}
      tag="CLOCK"
      title={failed ? 'CLOCK SYNC FAILED — exchange server time unreachable'
                    : 'OS CLOCK DRIFT — exchange requests may be rejected'}
      detail={failed
        ? 'Could not reach exchange server time; if account/funding reads keep failing, sync the OS clock.'
        : `local clock ${driftStr} vs exchange · Binance rejects signed reads >1000ms ahead (-1021) · sync the OS clock`}
    />
  );
};

const TopNavStd = ({page='Dashboard', onChange, variant='line', dense=false}) => {
  const [locked, toggleLock] = useWorkspaceLock();
  const ch = useQeChrome();
  const [switching, setSwitching] = React.useState(false);
  const [switchErr, setSwitchErr] = React.useState(false);
  // When a page doesn't pass onChange, delegate to the global app router (app-shell.jsx).
  const nav = onChange || ((p) => { if (window.qeNav) window.qeNav(p); });
  const accounts = ch.accounts || [];
  const active = accounts.find((a) => a.is_active);
  // Real account switch — the pages-config activate idiom; full reload after
  // (the SSE stream + every page pipe is per-account). A failed switch is
  // SURFACED (audit LOW-2), not swallowed — a rollback is a real event.
  const onAccount = async (id) => {
    if (!id || switching || (active && String(active.id) === String(id))) return;
    setSwitching(true); setSwitchErr(false);
    try {
      const r = await fetch('/accounts/' + id + '/activate', { method: 'POST' });
      if (r.ok) { window.location.reload(); return; }
    } catch (e) { /* engine unreachable — fall through to the error surface */ }
    setSwitching(false);
    setSwitchErr(true);
    setTimeout(() => setSwitchErr(false), 4000);
  };
  const sseTone = NAV_SSE_TONE[ch.sse] || 'off';
  const feed = _navFeed(ch);
  return (
  <React.Fragment>
  <div className="qe-hscroll" style={{
    display:'flex', alignItems:'center', gap:0,
    background:'var(--qe-bg)', borderBottom:'1px solid var(--qe-line)',
    fontFamily:'var(--qe-ui)', height: dense ? 32 : 38, flexShrink:0,
  }}>
    <div style={{padding:'0 14px', display:'flex', alignItems:'baseline', gap:8, borderRight:'1px solid var(--qe-line)', alignSelf:'stretch', alignItems:'center'}}>
      <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:700, color:'var(--qe-cyan)', letterSpacing:'0.08em'}}>{(window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName) || 'QRE'}</span>
      <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-sub)', letterSpacing:'0.06em'}}>{(window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion) || 'v3'}</span>
    </div>
    <div style={{display:'flex', alignSelf:'stretch'}}>
      {NAV_ITEMS.map(it => {
        const on = page === it;
        if (variant==='line') return (
          <React.Fragment key={it}>
            {it==='Primitives' && <div style={{width:1, alignSelf:'center', height:16, background:'var(--qe-line)', margin:'0 6px'}}/>}
            <button onClick={()=>nav(it)} style={{
              background:'transparent', border:'none', cursor:'pointer',
              padding:'0 12px', height:'100%', display:'inline-flex', alignItems:'center', gap:5,
              fontFamily:'var(--qe-ui)', fontSize:'0.72rem', fontWeight:on?700:500,
              color: on ? (it==='Primitives'?'var(--qe-amber)':'var(--qe-cyan)') : 'var(--qe-sub)',
              borderBottom: on ? `2px solid ${it==='Primitives'?'var(--qe-amber)':'var(--qe-cyan)'}` : '2px solid transparent',
              marginBottom: '-1px', letterSpacing:'0.04em',
            }}>
              {it}
              {it==='Primitives' && <span style={{fontFamily:'var(--qe-mono)', fontSize:'0.5rem', fontWeight:700, letterSpacing:'0.08em', color: on?'var(--qe-bg)':'var(--qe-amber)', background: on?'var(--qe-amber)':'transparent', border:'1px solid var(--qe-amber)', padding:'0 3px', lineHeight:1.4}}>DEV</span>}
            </button>
          </React.Fragment>
        );
        if (variant==='solid') return (
          <button key={it} onClick={()=>nav(it)} style={{
            background: on ? 'var(--qe-cyan)' : 'transparent',
            color: on ? 'var(--qe-bg)' : 'var(--qe-sub)',
            border:'none', cursor:'pointer', padding:'0 14px', height:'100%',
            fontFamily:'var(--qe-ui)', fontSize:'0.72rem', fontWeight:on?700:500,
            letterSpacing:'0.04em',
          }}>{it}</button>
        );
        // bracket
        return (
          <button key={it} onClick={()=>nav(it)} style={{
            background:'transparent', border:'none', cursor:'pointer',
            padding:'0 10px', height:'100%',
            fontFamily:'var(--qe-mono)', fontSize:'0.7rem', fontWeight:on?700:500,
            color: on ? 'var(--qe-cyan)' : 'var(--qe-sub)',
          }}>
            {on ? <>[<span style={{padding:'0 2px'}}>{it}</span>]</> : it}
          </button>
        );
      })}
    </div>
    <div className="qe-grow"/>
    <div style={{display:'flex', alignItems:'center', gap:8, padding:'0 12px', alignSelf:'stretch'}}>
      <span style={{display:'inline-flex', alignItems:'center', gap:5, alignSelf:'center'}}>
        <LockButton locked={locked} onToggle={toggleLock} compact
          style={{height:22, width:22, padding:0, justifyContent:'center'}}/>
        {accounts.length ? (
          <select className="qe-input qe-select" style={{height:22, fontSize:'0.62rem', width:175}}
            value={active ? String(active.id) : ''} disabled={switching}
            onChange={(e)=>onAccount(e.target.value)} title="Switch active account (reloads)">
            {accounts.map((a)=>(
              <option key={a.id} value={String(a.id)}>{a.name} ({_navCap(a.exchange)}){a.is_active ? '' : ' — inactive'}</option>
            ))}
          </select>
        ) : (
          <select className="qe-input qe-select" style={{height:22, fontSize:'0.62rem', width:175}} disabled value="">
            <option value="">— no accounts —</option>
          </select>
        )}
        {switchErr && <span className="qe-mono" style={{fontSize:'0.54rem', color:'var(--qe-red)'}}>switch failed</span>}
      </span>
      <StatusDot tone={sseTone} label="SSE" value={ch.sse === 'open' ? 'live' : ch.sse}/>
      {/* shell-chrome-3: exchange feed health sits BESIDE the SSE dot because the
          two are independent pipes — see _navFeed. */}
      <span title={feed.title} style={{display:'inline-flex'}}>
        <StatusDot tone={feed.tone} label="FEED" value={feed.value}/>
      </span>
      <span style={{
        fontFamily:'var(--qe-mono)', fontSize:'0.56rem', color:'var(--qe-muted)',
        letterSpacing:'0.04em',
      }}><LiveClock id="nav.clock" format={qeClockFmt}/></span>
      <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
        <button onClick={()=>nav('Config')} title="Configuration" style={{
          display:'inline-flex', alignItems:'center', justifyContent:'center', width:22, height:22, padding:0,
          background: page==='Config' ? 'var(--qe-bg-cyan)' : 'transparent', cursor:'pointer',
          border:`1px solid ${page==='Config' ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
          color: page==='Config' ? 'var(--qe-cyan)' : 'var(--qe-sub)', fontSize:'0.85rem', lineHeight:1, transition:'all 0.12s',
        }}
          onMouseOver={e => { e.currentTarget.style.color='var(--qe-cyan)'; e.currentTarget.style.borderColor='var(--qe-line-2)'; }}
          onMouseOut={e => { e.currentTarget.style.color = page==='Config'?'var(--qe-cyan)':'var(--qe-sub)'; e.currentTarget.style.borderColor = page==='Config'?'var(--qe-cyan)':'var(--qe-line)'; }}>⚙</button>
        <NotifBell/>
      </span>
    </div>
  </div>
  {/* operator clock-drift bug: OS-drift banner stacks ABOVE the halt banner in
      the shared under-nav slot (system alert first, like a notification stack). */}
  <ClockDriftBanner/>
  <NotifBanner/>
  <WorkspaceBar interactive={page === 'Dashboard'} />
  </React.Fragment>
  );
};

// ── StatusFooter — the bottom status bar shown on EVERY page (no news). ──
// P8 wave 1: real footer — identity from QE_BOOTSTRAP, uptime from
// /api/system (G-O9), engine + SSE dots from the chrome store's real pipe
// health. The design's tasks-queue/events/bus/db ornaments had no engine
// source and are DROPPED (fail-loud beats fabrication; G-O9 "or drop the
// ornaments" option).
const StatusFooter = () => {
  const ch = useQeChrome();
  const engineTone = ch.stateErr ? 'var(--qe-red)' : ch.state ? 'var(--qe-green)' : 'var(--qe-muted)';
  const sseTone = ch.sse === 'open' ? 'var(--qe-green)'
    : ch.sse === 'connecting' ? 'var(--qe-amber)'
    : ch.sse === 'error' ? 'var(--qe-red)' : 'var(--qe-muted)';
  const feed = _navFeed(ch);
  return (
    <div style={{
      display:'flex', alignItems:'center', gap:10,
      background:'var(--qe-bg)', borderTop:'1px solid var(--qe-line)',
      padding:'1px 8px', height:18, flexShrink:0,
      fontFamily:'var(--qe-mono)', fontSize:'0.54rem', color:'var(--qe-muted)',
    }}>
      <span style={{color:'var(--qe-sub)'}}>{((window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectShortName) || 'QRE') + ' ' + ((window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.projectVersion) || 'v3')}</span>
      <span>·</span>
      <span>uptime <LiveValue id="sb.uptime" value={ch.sys ? ch.sys.uptime_s : '—'} format={() => _navUptime(ch.sys ? ch.sys.uptime_s : null)}/></span>
      <div className="qe-grow"/>
      <span style={{color:engineTone}}>● engine</span>
      <span style={{color:sseTone}}>● sse</span>
      {/* shell-chrome-3: the design's third footer dot was the EXCHANGE feed. */}
      <span title={feed.title} style={{color:
        feed.tone === 'ok' ? 'var(--qe-green)'
        : feed.tone === 'warn' ? 'var(--qe-amber)'
        : feed.tone === 'err' ? 'var(--qe-red)' : 'var(--qe-muted)'
      }}>● feed</span>
      <LiveClock id="sb.clock" format={qeClockFmt} style={{color:'var(--qe-muted)'}}/>
    </div>
  );
};

Object.assign(window, {
  NAV_ITEMS, TopNavStd, WorkspaceBar, StatusFooter,
  QE_CLOCK_OFFSET, qeClockFmt,
});
