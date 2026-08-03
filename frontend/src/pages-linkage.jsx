/* v3.0 — Linkage triage board (P4). Ported from the Meridian reference
   (linkage.jsx DashLinkA) and WIRED to real data:
     · inbox      ← GET /orders/needs_review (per-candidate 3-leg diff) +
                    /api/linkage/closes pending_reason rows
     · monitors   ← /api/linkage/positions (5s) · /api/linkage/calcs (5s) ·
                    /api/linkage/funding (30s) · /api/linkage/closes (30s)
     · live uPnL  ← SSE position_update deltas merged onto the polled rows
                    (NOT the design's random-walk useQePosMark)
     · actions    → the EXISTING choke-pointed endpoints: POST
                    /orders/{id}/manual_link (form calc_id) · POST
                    /orders/{id}/mark_unplanned · PUT /history/close_reason/{id}
                    (form exit_reason + close_note) · POST
                    /calculator/cancel/{calc_id}. HTML 200 responses stripped
                    to text (the P2 convention); confirms before each.
   Named deviations: the 6-row crit array renders the loose finder's 3 legs +
   3 computed-true rows (strict 6/6 audit is /context territory); candidate
   model/r/tags chips are dropped (not in the needs_review payload);
   funding rows treat null/0 sentinels as "no data" [P4 audit L1]. */

/* The two lane cadences. One literal each, feeding both the scheduler and the
   read deadline derived from it (warm-hang sweep, 2026-08-01). */
const LK_FAST_MS = 5000;
const LK_SLOW_MS = 30000;

const _lkForm = async (url, fields, method = 'POST', opts = {}) => {
  const body = new URLSearchParams();
  Object.entries(fields || {}).forEach(([k, v]) => { if (v != null) body.append(k, v); });
  const r = await fetch(url, {
    method, headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  const raw = await r.text();
  // `jsonOk`: the endpoint answers with REAL status codes and a JSON body, so
  // the HTTP status is the whole truth. Required for any door that ECHOES
  // operator text (notes, close_note) — body-sniffing would read a note
  // containing "alert-error" as a failed save (2026-07-30).
  if (opts.jsonOk) {
    let data = {};
    // `|| {}`: JSON.parse('null') succeeds and yields null, which would make
    // the `data.error` read below throw.
    try { data = JSON.parse(raw) || {}; } catch (e) { /* non-JSON error page */ }
    return { ok: r.ok, data, text: data.error || _ptStrip(raw) };
  }
  // the link/cancel endpoints answer 200 for EVERY outcome with a
  // status-discriminated alert body — the alert-error/-warning class is the
  // real failure signal, not the HTTP status [P4 audit #2]
  return {
    ok: r.ok && !/alert-(error|warning)/.test(raw),
    text: _ptStrip(raw),
  };
};

/* link resolver — candidate list + per-criterion diff */
// operator-bug #5: candidate-calc meta formatters. `timestamp` is the calc's
// ISO creation time; `age_hours` its float age from the loose finder.
const _lkCreated = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d) ? '—' : d.toLocaleTimeString([], { hour12: false });
};
const _lkAgeH = (h) => {
  if (h == null || isNaN(h)) return '';
  if (h < 1) return `${Math.round(h * 60)}m`;
  const hh = Math.floor(h);
  return `${hh}h ${Math.round((h - hh) * 60)}m`;
};
// design-parity #2: hold-duration (ms → "6m 18s") + wall-clock HH:MM from ms.
const _lkDur = (ms) => {
  if (ms == null || isNaN(ms) || ms < 0) return '—';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  const h = Math.floor(s / 3600);
  return `${h}h ${Math.floor((s % 3600) / 60)}m`;
};
const _lkHM = (ms) => {
  if (!ms) return '—';
  const d = new Date(ms);
  return isNaN(d) ? '—' : d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' });
};
/* linkage-2 — absolute next-settlement wall clock. Prefer the endpoint's
   next_funding_time_ms; fall back to the countdown so the label degrades to a
   derived time rather than to nothing. */
const _lkSettleAt = (f) => {
  if (!f) return '—';
  const ms = f.next_funding_time_ms != null ? f.next_funding_time_ms
    : (f.countdown_s != null ? Date.now() + f.countdown_s * 1000 : null);
  if (!ms) return '—';
  const d = new Date(ms);
  return isNaN(d) ? '—' : d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' });
};

const _lkHMS = (ms) => {
  if (!ms) return '—';
  const d = new Date(ms);
  return isNaN(d) ? '—' : d.toLocaleTimeString([], { hour12: false });
};

const LkLinkResolver = ({ item, onDone }) => {
  const cands = item.candidates || [];
  const [selCand, setSelCand] = React.useState(cands[0] && cands[0].calc_id);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const cand = cands.find((c) => c.calc_id === selCand) || cands[0];

  // E2E-P6-003 (operator, 2026-07-29): link / unplanned used a NATIVE
  // window.confirm while the sibling calc-cancel flow uses the ModelDialog
  // primitive — inconsistent with the shipped dialog standard, unstyleable,
  // and un-drivable (a browser-automated page intercepts native dialogs, so the
  // confirm vanished before the operator could accept it). Same primitive,
  // same "basic pane with a close button" pattern as the cancel-calc dialog.
  const [confirmKind, setConfirmKind] = React.useState(null); // 'link' | 'unplanned'

  const runAct = async (kind) => {
    setConfirmKind(null);
    setBusy(true); setMsg(null);
    try {
      const r = kind === 'link'
        ? await _lkForm(`/orders/${item.id}/manual_link`, { calc_id: cand.calc_id })
        : await _lkForm(`/orders/${item.id}/mark_unplanned`, {});
      setMsg({ text: r.text || (r.ok ? 'done' : 'failed'), ok: r.ok });
      if (r.ok) onDone(r.text || (kind === 'link' ? `#${item.id} linked to ${cand.calc_id}` : `#${item.id} marked UNPLANNED`));
    } catch (e) { setMsg({ text: 'action failed — engine unreachable?', ok: false }); }
    setBusy(false);
  };

  const act = (kind) => setConfirmKind(kind);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.symbol}</span>
        <Badge tone={(item.side || '').toUpperCase() === 'BUY' || (item.side || '').toUpperCase() === 'LONG' ? 'ok' : 'err'}>{(item.side || '').toUpperCase()}</Badge>
        <LinkBadge status={item.link_status} />
        <div className="qe-grow" />
        {/* design-parity #2: absolute placed-at time + relative age (was age only). */}
        <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>{_lkHM(item.created_at_ms)} · <PtAge ts={item.created_at_ms} /></span>
      </div>
      {/* operator-bug #5: order-detail block matches the Meridian design —
          Size / Notional / Operator / Client-order-id (backend now selects
          quantity / operator_id / client_order_id on /orders/needs_review).
          TP/SL moved out of here; they already appear in the criterion diff
          below (and Status is the LinkBadge in the header). */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)', marginBottom: 8 }}>
        <KV l="Order" v={'#' + (item.exchange_order_id || item.id)} />
        <KV l="Type" v={(item.order_type || '').toUpperCase()} />
        {/* E2E-P6-002 (display half): a MARKET order's `price` is 0 — the real
            executed entry is avg_fill_price, which the review-queue payload now
            carries. Rendering price alone showed "MARKET @ 0.000000" and a 0
            notional for every market entry. */}
        <KV l="Price" v={lpPx(_lkEntryPx(item))} color="var(--qe-cyan)" />
        <KV l="Size" v={item.quantity != null ? (+item.quantity).toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'} />
        <KV l="Notional" v={(_lkEntryPx(item) && item.quantity != null) ? `${(_lkEntryPx(item) * item.quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })} U` : '—'} />
        <KV l="Operator" v={item.operator_id || '—'} />
        <KV l="Client order id" v={item.client_order_id || '—'} span />
      </div>
      {!cands.length ? (
        <React.Fragment>
          <EmptyState tone="warn" glyph="∅" msg="No candidate calcs in window" hint="Mark unplanned or wait for a fresh calc." />
          <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 8 }}>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy} onClick={() => act('unplanned')}>UNPLANNED</button>
          </div>
        </React.Fragment>
      ) : (
        <React.Fragment>
          <div className="qe-lbl" style={{ margin: '2px 0 5px' }}>Candidate calcs · {cands.length}</div>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginBottom: 6 }}>
            {cands.map((c, ci) => {
              const on = c.calc_id === selCand;
              // operator-bug #5: candidates arrive sorted best-first (backend:
              // matching-legs DESC), so index 0 is the BEST match — mark it
              // (design's amber BEST tag). Score badge follows the design:
              // warn on best, mute on the rest.
              const best = ci === 0;
              return (
                <button key={c.calc_id} onClick={() => setSelCand(c.calc_id)} style={{
                  display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', cursor: 'pointer',
                  background: on ? 'var(--qe-active)' : 'var(--qe-panel)', border: `1px solid ${on ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
                }}>
                  <span className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>{String(c.calc_id).slice(-6)}</span>
                  <Badge tone={best ? 'warn' : 'mute'}>{lpScore(c)} / 6</Badge>
                  {best ? <span style={{ fontSize: '0.5rem', color: 'var(--qe-amber)', letterSpacing: '0.08em', fontWeight: 700 }}>BEST</span> : null}
                  {c.status === 'released' ? <Badge tone="mag">REPLACEMENT</Badge> : null}
                </button>
              );
            })}
          </div>
          {/* operator-bug #5: model · created · R · tags meta for the selected
              candidate. Backend enriches from pre_trade_log (model_name / est_r
              real; tags DORMANT — pre_trade_log.tags is unwritten today, so the
              chips only render if it is ever populated). model is omitted when
              the operator ran the calc without a model name (empty on live). */}
          {cand ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', padding: '0 2px 6px', fontFamily: 'var(--qe-mono)', fontSize: '0.52rem', color: 'var(--qe-muted)' }}>
              {cand.model ? <span style={{ color: 'var(--qe-sub)', fontWeight: 700 }}>{cand.model}</span> : null}
              <span>created {_lkCreated(cand.timestamp)}{cand.age_hours != null ? ` (${_lkAgeH(cand.age_hours)})` : ''}</span>
              {cand.r != null ? <span>R {(+cand.r).toFixed(2)}</span> : null}
              {(cand.tags || []).map((t) => <span key={t} style={{ color: 'var(--qe-purple)' }}>#{t}</span>)}
            </div>
          ) : null}
          <div style={{ display: 'grid', gridTemplateColumns: '76px 1fr 1fr 52px 18px', gap: 6, padding: '0 6px 2px', fontFamily: 'var(--qe-mono)', fontSize: '0.5rem', color: 'var(--qe-muted)', letterSpacing: '0.06em' }}>
            <span>CRITERION</span><span>CALC {String(cand.calc_id).slice(-6)}</span><span>ORDER #{item.id}</span><span>DIFF</span><span style={{ textAlign: 'right' }}>OK</span>
          </div>
          <MatchDiff order={item} candidate={cand} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingTop: 8 }}>
            <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>{lpScore(cand)} / 6 — {lpScore(cand) === 6 ? 'eligible' : 'below 6/6 threshold'}</span>
            <div className="qe-grow" />
            <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy} onClick={() => act('unplanned')}>UNPLANNED</button>
            <button className="qe-btn qe-btn-sm qe-btn-success" disabled={busy} title={`Link ${cand.calc_id}`} onClick={() => act('link')}>
              {busy ? <Spinner size="0.62rem" /> : 'Link'}
            </button>
          </div>
        </React.Fragment>
      )}
      {msg ? <div className="qe-mono" style={{ fontSize: '0.58rem', marginTop: 6, color: msg.ok ? 'var(--qe-green)' : 'var(--qe-red)' }}>{msg.text}</div> : null}

      {/* E2E-P6-003: the link / unplanned confirm, on the SAME ModelDialog
          primitive as the calc-cancel dialog (scrim-click + ✕ + the ghost
          button all dismiss). Replaces window.confirm — which was off-standard,
          unstyleable, and disappeared instantly under browser automation. */}
      {confirmKind && (
        <ModelDialog
          title={confirmKind === 'link'
            ? `Link order · #${item.exchange_order_id || item.id}`
            : `Mark unplanned · #${item.exchange_order_id || item.id}`}
          width={420}
          onClose={() => { if (!busy) setConfirmKind(null); }}
          footer={<React.Fragment>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy}
              onClick={() => setConfirmKind(null)}>Keep as is</button>
            <button
              className={`qe-btn qe-btn-sm ${confirmKind === 'link' ? 'qe-btn-success' : 'qe-btn-danger'}`}
              disabled={busy} onClick={() => runAct(confirmKind)}>
              {busy ? <Spinner size="0.62rem" />
                : (confirmKind === 'link' ? 'Link calc' : 'Mark UNPLANNED')}
            </button>
          </React.Fragment>}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.symbol}</span>
              <Badge tone={(item.side || '').toUpperCase() === 'BUY' || (item.side || '').toUpperCase() === 'LONG' ? 'ok' : 'err'}>{(item.side || '').toUpperCase()}</Badge>
              <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)' }}>{(item.order_type || '').toUpperCase()} @ {lpPx(_lkEntryPx(item))}</span>
            </div>
            {confirmKind === 'link' && cand ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)' }}>
                <KV l="Calc" v={String(cand.calc_id).slice(-8)} color="var(--qe-cyan)" />
                <KV l="Score" v={`${lpScore(cand)} / 6`} />
                <KV l="Entry" v={lpPx(cand.effective_entry != null ? cand.effective_entry : cand.average)} />
              </div>
            ) : null}
            <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', lineHeight: 1.4 }}>
              {confirmKind === 'link'
                ? 'Links this order to the selected calc and stamps its fills. The calc moves to MATCHED and leaves Active Calcs.'
                : 'Marks this order as an unplanned entry. It leaves the review queue and will not be linked to any calc.'}
            </div>
          </div>
        </ModelDialog>
      )}
    </div>
  );
};

/* reason resolver — the manual-close reason picker */
const LkReasonResolver = ({ item, onDone }) => {
  const [pick, setPick] = React.useState(null);
  const [note, setNote] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await _lkForm(`/history/close_reason/${item.id}`, { exit_reason: pick, close_note: note }, 'PUT', { jsonOk: true });
      setMsg({ text: r.ok ? 'reason saved' : (r.text || 'save failed'), ok: r.ok });
      if (r.ok) onDone(`${item.symbol} close → ${(LP_EXIT_REASONS[pick] || {}).label || pick}`);
    } catch (e) { setMsg({ text: 'save failed — engine unreachable?', ok: false }); }
    setBusy(false);
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      {/* design-parity #2: header carries P&L% + the closed-at time; the grid
          fills in Hold / Closed at / Detected (all from the close row) — these
          were the fields missing vs the Meridian ReasonResolver. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.symbol}</span>
        <Badge tone={item.direction === 'LONG' ? 'ok' : 'err'}>{item.direction}</Badge>
        <span className="qe-mono" style={{ fontWeight: 700, color: lpSgn(item.net_pnl) }}>
          {lpUsd(item.net_pnl)}{(item.entry_price && item.quantity)
            ? ` (${lpPct(item.net_pnl / (item.entry_price * item.quantity) * 100)})` : ''}
        </span>
        <div className="qe-grow" />
        <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}>closed {_lkHM(item.exit_time_ms)}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)', marginBottom: 8 }}>
        <KV l="Entry" v={lpPx(item.entry_price)} />
        <KV l="Exit" v={lpPx(item.exit_price)} />
        <KV l="Hold" v={_lkDur(item.hold_time_ms)} />
        <KV l="Funding" v={lpUsd(item.funding_fees, 3)} color={lpSgn(item.funding_fees)} />
        <KV l="Closed at" v={_lkHM(item.exit_time_ms)} />
        <KV l="Detected" v={(LP_EXIT_REASONS[item.exit_reason] || {}).label || item.exit_reason || '—'} />
      </div>
      <div className="qe-mono" style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', marginBottom: 7 }}>No calc matched this close — categorize it (optional, never blocks).</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, marginBottom: 8 }}>
        {LP_MANUAL_REASONS.map((r) => (
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
      <input className="qe-input" placeholder="optional note…" value={note} onChange={(e) => setNote(e.target.value)} />
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6, marginTop: 8 }}>
        {/* design-parity #2: "Later" defers the close — it stays pending in the
            queue (nothing written), just dismisses the active detail. */}
        <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy}
          onClick={() => onDone(`${item.symbol} — left for later`)}>Later</button>
        <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={!pick || busy} style={{ opacity: pick ? 1 : 0.45 }} onClick={save}>
          {busy ? <Spinner size="0.62rem" /> : 'Save'}
        </button>
      </div>
      {msg ? <div className="qe-mono" style={{ fontSize: '0.58rem', marginTop: 6, color: msg.ok ? 'var(--qe-green)' : 'var(--qe-red)' }}>{msg.text}</div> : null}
    </div>
  );
};

const LinkagePage = () => {
  const [needs, setNeeds]     = React.useState(null);   // needs_review orders
  const [positions, setPositions] = React.useState(null);
  const [calcs, setCalcs]     = React.useState(null);
  const [funding, setFunding] = React.useState(null);
  const [closes, setCloses]   = React.useState(null);
  const [sel, setSel]         = React.useState(null);
  const [toast, setToast]     = React.useState(null);
  // operator-bug #6: calc-cancel confirm dialog (ModelDialog primitive) —
  // replaces the browser window.confirm. Holds the calc row pending confirm.
  const [cancelCalc, setCancelCalc]     = React.useState(null);
  const [cancelReason, setCancelReason] = React.useState('');
  const [cancelBusy, setCancelBusy]     = React.useState(false);

  // Per-SOURCE pipe state (audit MED-1: the lanes span different routers —
  // the /orders/… router vs the /api/linkage/… one — so a lane-representative
  // foot would misattribute partial failures in both directions).
  // (Those two paths were once written as globs. A slash-star sequence inside
  // a line comment opens a PHANTOM block comment for tests/_srcpin.py's
  // stripper, which ate lines 344-389 of this file — every source pin over
  // `nets`, `load` and `lkFoot` was passing vacuously. Same trap as C1's
  // service worker. Never put a block-comment opener in a line comment;
  // pinned app-wide by tests/test_net_deadline.py::TestTheCommentStripperTrap,
  // whose first draft of THIS very comment tripped its own detector.)
  const [nets, setNets] = React.useState({});
  const load = React.useCallback((which) => {
    // `everyMs` is the lane's own cadence — the read deadline derives from it
    // (warm-hang sweep, 2026-08-01), so retuning a lane retunes both.
    const get = (url, fn, pick, key, everyMs) => {
      const t0 = performance.now();
      return _ptJson(url, qePollDeadline(everyMs))
        .then((d) => {
          fn(pick ? d[pick] : d);
          setNets((m) => ({ ...m, [key]: { err: null, ms: performance.now() - t0 } }));
        })
        .catch((err) => { setNets((m) => ({ ...m, [key]: { ...m[key], err } })); });
    };
    if (!which || which === 'fast') {
      get('/orders/needs_review', setNeeds, 'orders', 'needs', LK_FAST_MS);
      get('/api/linkage/positions', setPositions, 'positions', 'positions', LK_FAST_MS);
      get('/api/linkage/calcs', setCalcs, 'calcs', 'calcs', LK_FAST_MS);
    }
    if (!which || which === 'slow') {
      get('/api/linkage/funding', setFunding, null, 'funding', LK_SLOW_MS);
      get('/api/linkage/closes', setCloses, 'closes', 'closes', LK_SLOW_MS);
    }
  }, []);
  const lkFoot = (key, hasData) => {
    const n = nets[key] || {};
    return qeFootState({ loading: n.ms == null && !n.err, err: n.err, hasData, ms: n.ms, retrying: true });
  };
  React.useEffect(() => {
    load();
    const t1 = setInterval(() => load('fast'), LK_FAST_MS);
    const t2 = setInterval(() => load('slow'), LK_SLOW_MS);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [load]);

  /* P8 doc wave (audit L3-F4) — named trims vs the design reference, each
   individually defensible, collectively recorded here: the inbox strip
   omits the direction badge / timestamp / context third line; the reason
   resolver omits Hold + Closed-at KVs and the "Later" (defer) button; the
   funding settlement countdown renders the polled value (≤30s stale) rather
   than ticking locally.
   CLOSED 2026-07-25 (Meridian audit LOW tail): Recent Closes has Time / Hold /
   PnL-% again (linkage-1), Active Calcs has R (linkage-3), the funding summary
   states cum + the absolute settle time (linkage-2), and the PageHeader carries
   the LINK · window dot (linkage-4). */

/* live uPnL deltas: SSE position_update refreshes upnl — keyed by
     symbol|side, NEVER symbol alone (P8 audit L3-F1: in HEDGE mode a symbol
     holds a LONG and a SHORT leg; the symbol-keyed merge stamped one leg's
     uPnL onto both). SSE carries `side`, rows carry `direction`. */
  React.useEffect(() => {
    if (typeof window.QE_SSE === 'undefined') return;
    const sideKey = (s) => ((s || '').toLowerCase().startsWith('l') ? 'L' : 'S');
    return window.QE_SSE.onChannel('position_update', (p) => {
      const list = Array.isArray(p.positions) ? p.positions : [];
      setPositions((prev) => {
        if (!prev) return prev;
        const by = {}; list.forEach((x) => { by[x.symbol + '|' + sideKey(x.side)] = x; });
        return prev.map((r) => {
          const u = by[r.symbol + '|' + sideKey(r.direction)];
          return u && u.upnl != null ? { ...r, upnl: u.upnl } : r;
        });
      });
    });
  }, []);

  /* M10 (wiring inventory, fixed 2026-08-03): the toast carries a TONE. It
     used to be a bare string rendered under a hardcoded green ✓ — so an
     engine REFUSAL ("Calc is no longer cancellable…"), and even this page's
     own "cancel failed — engine unreachable?", flashed as success. The
     cancel door answers 200 for every outcome with the truth in the alert
     class (_lkForm body-sniffs it into `ok`), so painting green
     unconditionally threw that signal away at the last hop. Err toasts
     dwell longer: refusal text is a sentence, 2.6 s was sized for "done". */
  const flash = (m, tone = 'ok') => {
    setToast({ text: m, tone });
    setTimeout(() => setToast(null), tone === 'ok' ? 2600 : 5200);
  };

  /* unified inbox: link items + pending-reason closes */
  const inbox = [
    ...((needs || []).map((o) => ({ ...o, kind: 'link', key: 'L' + o.id }))),
    ...((closes || []).filter((c) => c.pending_reason).map((c) => ({ ...c, kind: 'close', key: 'C' + c.id }))),
  ];
  const active = inbox.find((i) => i.key === sel) || inbox[0];
  const resolveDone = (m) => { flash(m); setSel(null); load(); };

  const posCols = [
    { key: 'symbol', label: 'Sym', filter: true,
      filterVal: (r) => (r.symbol || '').replace('USDT', ''),
      sortVal:   (r) => (r.symbol || '').replace('USDT', ''),
      render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.symbol || '').replace('USDT', '')}</span> },
    { key: 'direction', label: 'Side', filter: { label: 'SIDE' },
      filterVal: (r) => (r.direction || '').toUpperCase() || '—',
      render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{(r.direction || ' ')[0]}</Badge> },
    { key: 'size', label: 'Size', align: 'right' },
    { key: 'entry', label: 'Entry', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.entry)}</span> },
    { key: 'mark', label: 'Mark', align: 'right', render: (r) => lpPx(r.mark) },
    { key: 'upnl', label: 'uPnL', align: 'right', render: (r) => <span style={{ color: lpSgn(r.upnl), fontWeight: 700 }}>{lpUsd(r.upnl)}</span> },
    // TP/SL keeps sort:false — two independent prices, no single defensible key.
    // It DOES gain a protection facet: "which positions are unprotected" is a
    // real triage question and the raw fields answer it categorically.
    { key: 'tpsl', label: 'TP / SL', align: 'right', sort: false,
      filter: { label: 'TP/SL' },
      filterVal: (r) => (r.tp_live ? 'TP' : '') + (r.tp_live && r.sl_live ? '+' : '') + (r.sl_live ? 'SL' : '') || 'NONE',
      render: (r) => <span style={{ fontSize: '0.56rem' }}><span className="qe-up">{r.tp_live ? lpPx(r.tp_live) : '—'}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span className="qe-dn">{r.sl_live ? lpPx(r.sl_live) : '—'}</span></span> },
    { key: 'link_status', label: 'Link', filter: { label: 'LINK' }, render: (r) => <LinkBadge status={r.link_status} /> },
    // `dev` is not a row field — the badge reads deviation_badge. That made the
    // column invisible to BOTH sort and facet derivation (defined===0), which is
    // why it had opted out of sort entirely. sortVal/filterVal are the primitive's
    // escape hatch for exactly this. Ascending = worst-first: this is a triage
    // pane, so "off-plan at the top" is the useful direction.
    { key: 'dev', label: 'Plan deviation',
      sortVal: (r) => ({ red: 0, yellow: 1, green: 2 })[r.deviation_badge] != null
        ? ({ red: 0, yellow: 1, green: 2 })[r.deviation_badge] : 3,
      filter: { label: 'PLAN' },
      filterVal: (r) => ((LP_DEV_META || {})[r.deviation_badge] || {}).label || '—',
      render: (r) => <DevBadge pos={r} /> },
  ];
  const calcCols = [
    { key: 'ticker', label: 'Sym', filter: true,
      filterVal: (r) => (r.ticker || '').replace('USDT', ''),
      sortVal:   (r) => (r.ticker || '').replace('USDT', ''),
      render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.ticker || '').replace('USDT', '')}</span> },
    { key: 'side', label: 'Side', filter: { label: 'SIDE' },
      filterVal: (r) => (r.side || '').toUpperCase() || '—',
      render: (r) => <Badge tone={(r.side || '').toLowerCase() === 'long' ? 'ok' : 'err'}>{(r.side || ' ')[0].toUpperCase()}</Badge> },
    { key: 'average', label: 'Entry', align: 'right', render: (r) => lpPx(r.average) },
    { key: 'tp_price', label: 'TP', align: 'right', render: (r) => <span className="qe-up">{lpPx(r.tp_price)}</span> },
    { key: 'sl_price', label: 'SL', align: 'right', render: (r) => <span className="qe-dn">{lpPx(r.sl_price)}</span> },
    // linkage-3: est_r is already on every row (SELECT * on pre_trade_log); the
    // resolver renders the same value for candidates.
    { key: 'est_r', label: 'R', align: 'right',
      render: (r) => r.est_r == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span>
        : <span style={{ color: 'var(--qe-cyan)' }}>{(+r.est_r).toFixed(2)}</span> },
    // Same shape as posCols.dev: 'cd' is not a row field, so the column was
    // invisible to sort and facets. It renders a countdown off the REAL numeric
    // expiry_ms, and "which calc expires first" is the ordering this pane exists
    // for. The STATE facet hangs here because no column declares `status`, so the
    // facet engine could never see it.
    { key: 'cd', label: 'Link window', align: 'right',
      sortVal: (r) => r.expiry_ms,
      filter: { label: 'STATE' },
      filterVal: (r) => (r.status || '').toUpperCase() || '—',
      render: (r) => <CalcCountdown expiry={r.expiry_ms} window={r.window_seconds} /> },
    // 'act' stays sort:false + filter:false — it is a button, not data.
    { key: 'act', label: '', align: 'right', sort: false, filter: false, search: false, render: (r) => (
        // operator-bug #6: open the ModelDialog confirm instead of window.confirm.
        <button className="qe-btn qe-btn-sm qe-btn-ghost" title="Cancel this calc"
          onClick={(e) => { e.stopPropagation(); setCancelReason(''); setCancelCalc(r); }}>✕</button>
      ) },
  ];
  const fundCols = [
    { key: 'symbol', label: 'Sym', filter: true,
      filterVal: (r) => (r.symbol || '').replace('USDT', ''),
      sortVal:   (r) => (r.symbol || '').replace('USDT', ''),
      render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.symbol || '').replace('USDT', '')}</span> },
    { key: 'direction', label: 'Side', filter: { label: 'SIDE' },
      filterVal: (r) => (r.direction || '').toUpperCase() || '—',
      render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{(r.direction || ' ')[0]}</Badge> },
    { key: 'rate', label: 'Rate', align: 'right', render: (r) => r.rate == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: r.rate >= 0 ? 'var(--qe-amber)' : 'var(--qe-green)' }}>{(r.rate * 100).toFixed(4)}%</span> },
    // Flow is this pane's categorical axis. filterVal/searchVal must mirror the
    // CELL, not the raw field: routes_cockpit assigns `pays` unconditionally, so
    // a rate==null row still carries pays='venue' and would facet as EARN while
    // rendering '—'. Returning '' for those rows drops them from the facet
    // (raw==='' is skipped) instead of filing them under a flow they don't have.
    { key: 'pays', label: 'Flow',
      filter: { label: 'FLOW' },
      filterVal: (r) => (r.rate == null ? '' : r.pays === 'you' ? 'PAY' : 'EARN'),
      searchVal: (r) => (r.rate == null ? '' : r.pays === 'you' ? 'PAY' : 'EARN'),
      render: (r) => r.rate == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <FundingWho pays={r.pays} /> },
    { key: 'est_next', label: 'Est', align: 'right', render: (r) => r.rate == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: lpSgn(r.est_next), fontSize: '0.56rem' }}>{lpUsd(r.est_next, 4)}</span> },
    { key: 'cum', label: 'Cum', align: 'right', render: (r) => <span style={{ color: lpSgn(r.cum) }}>{lpUsd(r.cum, 3)}</span> },
  ];
  const closeCols = [
    // linkage-1: recency and hold were only implied by server sort order; on a
    // triage board the operator correlates closes against what else happened at
    // that moment, and neither is derivable from another cell.
    { key: 'exit_time_ms', label: 'Time', sortVal: (r) => r.exit_time_ms || 0,
      render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{_lkHM(r.exit_time_ms)}</span> },
    { key: 'symbol', label: 'Sym', filter: true,
      filterVal: (r) => (r.symbol || '').replace('USDT', ''),
      sortVal:   (r) => (r.symbol || '').replace('USDT', ''),
      render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.symbol || '').replace('USDT', '')}</span> },
    { key: 'direction', label: 'Side', filter: { label: 'SIDE' },
      filterVal: (r) => (r.direction || '').toUpperCase() || '—',
      render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{(r.direction || ' ')[0]}</Badge> },
    { key: 'entry_price', label: 'Entry', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.entry_price)}</span> },
    { key: 'exit_price', label: 'Exit', align: 'right', render: (r) => lpPx(r.exit_price) },
    // Bucket the continuous PnL into the sign trichotomy — the raw float is
    // never offered as options (that would be one option per row).
    { key: 'net_pnl', label: 'PnL', align: 'right',
      filter: { label: 'RESULT' },
      filterVal: (r) => ((r.net_pnl || 0) > 0 ? 'WIN' : (r.net_pnl || 0) < 0 ? 'LOSS' : 'FLAT'),
      // linkage-1: absolute AND percent — a -0.62 on a 12m scalp reads very
      // differently from a +1.93 on a 3h hold.
      render: (r) => {
        const den = (r.entry_price || 0) * (r.quantity || 0);
        const pct = den ? (r.net_pnl / den) * 100 : null;
        return (<span style={{ whiteSpace: 'nowrap' }}>
          <span style={{ color: lpSgn(r.net_pnl), fontWeight: 700 }}>{lpUsd(r.net_pnl)}</span>
          {pct == null ? null : <span style={{ color: 'var(--qe-muted)', fontSize: '0.56rem', marginLeft: 4 }}>{lpPct(pct)}</span>}
        </span>);
      } },
    { key: 'hold_time_ms', label: 'Hold', align: 'right', sortVal: (r) => r.hold_time_ms || 0,
      render: (r) => <span style={{ color: 'var(--qe-muted)', fontSize: '0.56rem' }}>{_lkDur(r.hold_time_ms)}</span> },
    // Facet/sort/search all follow the RENDERED badge (pending → "SET REASON",
    // otherwise the LP_EXIT_REASONS label), so the column can no longer sort or
    // filter on a value the operator never sees. NB the facet stays invisible
    // while every close shares one reason — that bail is data-gated and resolves
    // itself as soon as reasons are categorised through this page's resolver.
    { key: 'exit_reason', label: 'Exit reason',
      filter: { label: 'REASON' },
      filterVal: (r) => r.pending_reason ? 'SET REASON' : (((LP_EXIT_REASONS || {})[r.exit_reason] || {}).label || r.exit_reason || '—'),
      sortVal:   (r) => r.pending_reason ? 'SET REASON' : (((LP_EXIT_REASONS || {})[r.exit_reason] || {}).label || r.exit_reason || ''),
      searchVal: (r) => r.pending_reason ? 'SET REASON pending' : `${((LP_EXIT_REASONS || {})[r.exit_reason] || {}).label || ''} ${r.exit_reason || ''} ${r.close_note || ''}`,
      render: (r) => <ExitBadge reason={r.exit_reason} note={r.close_note} pending={r.pending_reason} /> },
    { key: 'funding_fees', label: 'Fund', align: 'right', render: (r) => <span style={{ color: lpSgn(r.funding_fees), fontSize: '0.56rem' }}>{lpUsd(r.funding_fees, 3)}</span> },
  ];

  return (
    <div className="qe-scope" data-screen-label="03 Linkage" style={{ width: '100%', height: '100%', background: 'var(--qe-bg)', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <TopNavStd page="Linkage" variant="line" dense />
      <PageHeader title="Linkage" subtitle="calc-linkage workspace · manual link · close reasons · positions · funding">
        {/* linkage-4: the configured link window is what explains most of this
            page's queue — an order that missed it lands in NEEDS REVIEW. Taken
            off the calc rows already in hand (window_seconds), so no new fetch. */}
        {(() => {
          const w = (calcs || []).map((c) => c.window_seconds).find((v) => v != null);
          return <StatusDot tone="info" label="LINK"
            value={w == null ? '—' : (w >= 60 ? Math.round(w / 60) + 'm window' : w + 's window')} />;
        })()}
        <StatusDot tone={inbox.length ? 'warn' : 'ok'} label="QUEUE" value={`${inbox.length} open`} />
      </PageHeader>

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <GridWorkspace persistId="linkage">
          <GridItem x={0} y={0} w={9} h={24} minW={6} minH={10}>
            <Pane title="MANUAL LINK — NEEDS REVIEW"
              right={<Badge tone={inbox.length ? 'warn' : 'ok'}>{inbox.length}</Badge>}
              bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}
              foot={lkFoot('needs', needs != null)}>
              {needs == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               !inbox.length ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 10 }}>
                  <EmptyState fill tone="info" glyph="✓" msg="Inbox clear" hint="Every order is linked and every close is categorized." />
                </div>
              ) : (
                <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '162px 1fr' }}>
                  <div style={{ overflow: 'auto', borderRight: '1px solid var(--qe-line)' }}>
                    {inbox.map((item) => {
                      const on = active && item.key === active.key;
                      const accent = item.kind === 'link' ? 'var(--qe-amber)' : 'var(--qe-magenta)';
                      // design-parity #4: the inbox strip carries side + placed/closed
                      // time (row 1), status + #order/age or pnl (row 2), and a
                      // context line (row 3) — all previously trimmed (P8 note).
                      const sideRaw = (item.kind === 'link' ? item.side : item.direction) || '';
                      const isLong = sideRaw.toUpperCase() === 'BUY' || sideRaw.toUpperCase() === 'LONG';
                      const ts = item.kind === 'link' ? item.created_at_ms : item.exit_time_ms;
                      // E2E-P6-002: market orders carry price 0 — use the fill.
                      const _px = _lkEntryPx(item);
                      const notional = (_px && item.quantity) ? (_px * item.quantity).toFixed(2) : null;
                      return (
                        <div key={item.key} onClick={() => setSel(item.key)} style={{
                          display: 'flex', flexDirection: 'column', gap: 3, padding: '7px 8px', cursor: 'pointer',
                          borderBottom: '1px solid var(--qe-faint)', borderLeft: `3px solid ${on ? 'var(--qe-cyan)' : 'transparent'}`,
                          background: on ? 'var(--qe-active)' : 'transparent',
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            <span className="qe-mono" style={{ fontSize: '0.5rem', color: accent, fontWeight: 700, letterSpacing: '0.08em' }}>{item.kind === 'link' ? 'LINK' : 'REASON'}</span>
                            <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>{(item.symbol || '').replace('USDT', '')}</span>
                            {sideRaw ? <Badge tone={isLong ? 'ok' : 'err'}>{isLong ? 'L' : 'S'}</Badge> : null}
                            <span className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', marginLeft: 'auto' }}>{_lkHMS(ts)}</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            {item.kind === 'link'
                              ? <LinkBadge status={item.link_status} variant={3} />
                              : <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-magenta)' }}>set reason</span>}
                            <span className="qe-mono" style={{ fontSize: '0.5rem', marginLeft: 'auto', color: item.kind === 'link' ? 'var(--qe-muted)' : lpSgn(item.net_pnl) }}>
                              {item.kind === 'link'
                                ? <React.Fragment>#{item.id} · <PtAge ts={item.created_at_ms} /></React.Fragment>
                                : lpUsd(item.net_pnl)}
                            </span>
                          </div>
                          <div className="qe-mono" style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {item.kind === 'link'
                              ? `${(item.order_type || '').toUpperCase()} @ ${lpPx(_px)}${notional ? ` · ${notional}U` : ''}`
                              : `${_lkDur(item.hold_time_ms)} · ${lpPx(item.entry_price)}→${lpPx(item.exit_price)}`}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ overflow: 'auto', padding: 8 }}>
                    {active && (active.kind === 'link'
                      ? <LkLinkResolver key={active.key} item={active} onDone={resolveDone} />
                      : <LkReasonResolver key={active.key} item={active} onDone={resolveDone} />)}
                  </div>
                </div>
              )}
            </Pane>
          </GridItem>

          <GridItem x={9} y={0} w={15} h={9} minW={6} minH={5}>
            <Pane title="Open Positions" count={positions ? positions.length : null}
              onRefresh={() => load('fast')} bodyStyle={{ padding: 0 }}
              foot={lkFoot('positions', positions != null)}>
              {positions == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={posCols} rows={positions} selKey="position_id" emptyMsg="no open positions" />}
            </Pane>
          </GridItem>

          <GridItem x={9} y={9} w={8} h={8} minW={4} minH={5}>
            <Pane title="Active Calcs" count={calcs ? calcs.length : null} bodyStyle={{ padding: 0 }}
              foot={lkFoot('calcs', calcs != null)}>
              {calcs == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={calcCols} rows={calcs} selKey="calc_id" emptyMsg="no active calcs" />}
            </Pane>
          </GridItem>
          <GridItem x={17} y={9} w={7} h={8} minW={4} minH={5}>
            <Pane title="Funding" tag="LIVE" bodyStyle={{ padding: 0 }} onRefresh={() => load('slow')}
              foot={lkFoot('funding', funding != null)}>
              {funding == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={fundCols} rows={funding.rows || []} selKey="position_id"                 emptyMsg="no open positions"
                 summary={<>
                   <span>net at {_lkSettleAt(funding)}</span>
                   <span>next {funding.countdown_s != null ? lpClock(funding.countdown_s) : '—'}</span>
                   <span style={{ color: lpSgn(funding.net_next) }}>{lpUsd(funding.net_next, 3)}</span>
                   <span style={{ color: 'var(--qe-muted)' }}>cum</span>
                   <span style={{ color: lpSgn(funding.net_cum) }}>{lpUsd(funding.net_cum, 3)}</span>
                 </>} />}
            </Pane>
          </GridItem>

          <GridItem x={9} y={17} w={15} h={7} minW={6} minH={5}>
            <Pane title="Recent Closes" count={closes ? closes.length : null} bodyStyle={{ padding: 0 }}
              foot={lkFoot('closes', closes != null)}>
              {closes == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={closeCols} rows={closes} selKey="id" emptyMsg="no recent closes" />}
            </Pane>
          </GridItem>
        </GridWorkspace>
      </div>

      {/* operator-bug #6: calc-cancel confirm — ModelDialog primitive (hoisted
          to primitives.jsx), the "basic pane with a close button" pattern.
          Scrim-click + ✕ + Keep all dismiss; Cancel calc POSTs the existing
          /calculator/cancel/{id} endpoint (optional reason). */}
      {cancelCalc && (
        <ModelDialog
          title={`Cancel calc · ${String(cancelCalc.calc_id).slice(-8)}`}
          width={420}
          onClose={() => { if (!cancelBusy) { setCancelCalc(null); setCancelReason(''); } }}
          footer={<React.Fragment>
            <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={cancelBusy}
              onClick={() => { setCancelCalc(null); setCancelReason(''); }}>Keep calc</button>
            <button className="qe-btn qe-btn-sm qe-btn-danger" disabled={cancelBusy}
              onClick={async () => {
                setCancelBusy(true);
                try {
                  const res = await _lkForm(`/calculator/cancel/${cancelCalc.calc_id}`,
                    cancelReason.trim() ? { reason: cancelReason.trim() } : {});
                  // M10: `res.ok` is _lkForm's body-sniffed truth (the door
                  // answers 200 for every outcome) — it used to be discarded
                  // here, so refusals flashed under the green ✓. The dialog
                  // still closes on refusal (not_found / not_cancellable /
                  // race_lost are all terminal for it) and the reload
                  // refreshes the list either way.
                  flash(res.text || (res.ok ? 'cancel sent' : 'cancel failed'),
                        res.ok ? 'ok' : 'err');
                  setCancelCalc(null); setCancelReason(''); load('fast');
                } catch (err) { flash('cancel failed — engine unreachable?', 'err'); }
                setCancelBusy(false);
              }}>{cancelBusy ? <Spinner size="0.62rem" /> : 'Cancel calc'}</button>
          </React.Fragment>}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{cancelCalc.ticker}</span>
              <Badge tone={(cancelCalc.side || '').toLowerCase() === 'long' ? 'ok' : 'err'}>{(cancelCalc.side || '').toUpperCase()}</Badge>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)' }}>
              <KV l="Entry" v={lpPx(cancelCalc.average)} />
              <KV l="TP" v={lpPx(cancelCalc.tp_price)} color="var(--qe-green)" />
              <KV l="SL" v={lpPx(cancelCalc.sl_price)} color="var(--qe-red)" />
            </div>
            <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', lineHeight: 1.4 }}>
              Cancelling releases this calc's link window. A fill after this lands
              UNPLANNED unless a fresh calc is run for the ticker.
            </div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.52rem', fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: 'var(--qe-sub)' }}>Reason (optional)</span>
              <input className="qe-input" value={cancelReason} placeholder="why…"
                onChange={(e) => setCancelReason(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Escape' && !cancelBusy) { setCancelCalc(null); setCancelReason(''); } }}
                style={{ height: 22, boxSizing: 'border-box' }} />
            </label>
          </div>
        </ModelDialog>
      )}

      {toast && (
        <div style={{ position: 'absolute', bottom: 14, left: '50%', transform: 'translateX(-50%)', zIndex: 80, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'var(--qe-bg)', border: `1px solid ${toast.tone === 'ok' ? 'var(--qe-green)' : 'var(--qe-red)'}` }}>
          <span style={{ color: toast.tone === 'ok' ? 'var(--qe-green)' : 'var(--qe-red)' }}>{toast.tone === 'ok' ? '✓' : '✗'}</span>
          <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-text)' }}>{toast.text}</span>
        </div>
      )}
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { LinkagePage });
