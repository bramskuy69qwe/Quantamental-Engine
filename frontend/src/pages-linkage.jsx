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

const _lkForm = async (url, fields, method = 'POST') => {
  const body = new URLSearchParams();
  Object.entries(fields || {}).forEach(([k, v]) => { if (v != null) body.append(k, v); });
  const r = await fetch(url, {
    method, headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  // the link/cancel endpoints answer 200 for EVERY outcome with a
  // status-discriminated alert body — the alert-error/-warning class is the
  // real failure signal, not the HTTP status [P4 audit #2]
  const raw = await r.text();
  return {
    ok: r.ok && !/alert-(error|warning)/.test(raw),
    text: _ptStrip(raw),
  };
};

/* link resolver — candidate list + per-criterion diff */
const LkLinkResolver = ({ item, onDone }) => {
  const cands = item.candidates || [];
  const [selCand, setSelCand] = React.useState(cands[0] && cands[0].calc_id);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState(null);
  const cand = cands.find((c) => c.calc_id === selCand) || cands[0];

  const act = async (kind) => {
    const label = kind === 'link' ? `Link order #${item.id} to ${cand.calc_id}?`
      : `Mark order #${item.id} UNPLANNED?`;
    if (!window.confirm(label)) return;
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.symbol}</span>
        <Badge tone={(item.side || '').toUpperCase() === 'BUY' || (item.side || '').toUpperCase() === 'LONG' ? 'ok' : 'err'}>{(item.side || '').toUpperCase()}</Badge>
        <LinkBadge status={item.link_status} />
        <div className="qe-grow" />
        <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-muted)' }}><PtAge ts={item.created_at_ms} /></span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)', marginBottom: 8 }}>
        <KV l="Order" v={'#' + (item.exchange_order_id || item.id)} />
        <KV l="Type" v={(item.order_type || '').toUpperCase()} />
        <KV l="Price" v={lpPx(item.price)} color="var(--qe-cyan)" />
        <KV l="TP" v={lpPx(item.tp_trigger_price)} color="var(--qe-green)" />
        <KV l="SL" v={lpPx(item.sl_trigger_price)} color="var(--qe-red)" />
        <KV l="Status" v={item.link_status} />
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
            {cands.map((c) => {
              const on = c.calc_id === selCand;
              return (
                <button key={c.calc_id} onClick={() => setSelCand(c.calc_id)} style={{
                  display: 'flex', alignItems: 'center', gap: 5, padding: '3px 8px', cursor: 'pointer',
                  background: on ? 'var(--qe-active)' : 'var(--qe-panel)', border: `1px solid ${on ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
                }}>
                  <span className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>{String(c.calc_id).slice(-6)}</span>
                  <Badge tone="warn">{lpScore(c)} / 6</Badge>
                  {c.status === 'released' ? <Badge tone="mag">REPLACEMENT</Badge> : null}
                </button>
              );
            })}
          </div>
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
      const r = await _lkForm(`/history/close_reason/${item.id}`, { exit_reason: pick, close_note: note }, 'PUT');
      setMsg({ text: r.ok ? 'reason saved' : (r.text || 'save failed'), ok: r.ok });
      if (r.ok) onDone(`${item.symbol} close → ${(LP_EXIT_REASONS[pick] || {}).label || pick}`);
    } catch (e) { setMsg({ text: 'save failed — engine unreachable?', ok: false }); }
    setBusy(false);
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        <span className="qe-mono" style={{ color: 'var(--qe-cyan)', fontWeight: 700, fontSize: '0.72rem' }}>{item.symbol}</span>
        <Badge tone={item.direction === 'LONG' ? 'ok' : 'err'}>{item.direction}</Badge>
        <span className="qe-mono" style={{ fontWeight: 700, color: lpSgn(item.net_pnl) }}>{lpUsd(item.net_pnl)}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '5px 10px', padding: '6px 8px', border: '1px solid var(--qe-line)', marginBottom: 8 }}>
        <KV l="Entry" v={lpPx(item.entry_price)} />
        <KV l="Exit" v={lpPx(item.exit_price)} />
        <KV l="Funding" v={lpUsd(item.funding_fees, 3)} color={lpSgn(item.funding_fees)} />
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

  const load = React.useCallback((which) => {
    const get = (url, fn, pick) => _ptJson(url).then((d) => fn(pick ? d[pick] : d)).catch(() => {});
    if (!which || which === 'fast') {
      get('/orders/needs_review', setNeeds, 'orders');
      get('/api/linkage/positions', setPositions, 'positions');
      get('/api/linkage/calcs', setCalcs, 'calcs');
    }
    if (!which || which === 'slow') {
      get('/api/linkage/funding', setFunding);
      get('/api/linkage/closes', setCloses, 'closes');
    }
  }, []);
  React.useEffect(() => {
    load();
    const t1 = setInterval(() => load('fast'), 5000);
    const t2 = setInterval(() => load('slow'), 30000);
    return () => { clearInterval(t1); clearInterval(t2); };
  }, [load]);

  /* live uPnL deltas: SSE position_update refreshes upnl by symbol (P1 pattern) */
  React.useEffect(() => {
    if (typeof window.QE_SSE === 'undefined') return;
    return window.QE_SSE.onChannel('position_update', (p) => {
      const list = Array.isArray(p.positions) ? p.positions : [];
      setPositions((prev) => {
        if (!prev) return prev;
        const by = {}; list.forEach((x) => { by[x.symbol] = x; });
        return prev.map((r) => {
          const u = by[r.symbol];
          return u && u.upnl != null ? { ...r, upnl: u.upnl } : r;
        });
      });
    });
  }, []);

  const flash = (m) => { setToast(m); setTimeout(() => setToast(null), 2600); };

  /* unified inbox: link items + pending-reason closes */
  const inbox = [
    ...((needs || []).map((o) => ({ ...o, kind: 'link', key: 'L' + o.id }))),
    ...((closes || []).filter((c) => c.pending_reason).map((c) => ({ ...c, kind: 'close', key: 'C' + c.id }))),
  ];
  const active = inbox.find((i) => i.key === sel) || inbox[0];
  const resolveDone = (m) => { flash(m); setSel(null); load(); };

  const posCols = [
    { key: 'symbol', label: 'Sym', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.symbol || '').replace('USDT', '')}</span> },
    { key: 'direction', label: 'Side', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{(r.direction || ' ')[0]}</Badge> },
    { key: 'size', label: 'Size', align: 'right' },
    { key: 'entry', label: 'Entry', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.entry)}</span> },
    { key: 'mark', label: 'Mark', align: 'right', render: (r) => lpPx(r.mark) },
    { key: 'upnl', label: 'uPnL', align: 'right', render: (r) => <span style={{ color: lpSgn(r.upnl), fontWeight: 700 }}>{lpUsd(r.upnl)}</span> },
    { key: 'tpsl', label: 'TP / SL', align: 'right', sort: false, render: (r) => <span style={{ fontSize: '0.56rem' }}><span className="qe-up">{r.tp_live ? lpPx(r.tp_live) : '—'}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span className="qe-dn">{r.sl_live ? lpPx(r.sl_live) : '—'}</span></span> },
    { key: 'link_status', label: 'Link', render: (r) => <LinkBadge status={r.link_status} /> },
    { key: 'dev', label: 'Plan deviation', sort: false, render: (r) => <DevBadge pos={r} /> },
  ];
  const calcCols = [
    { key: 'ticker', label: 'Sym', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.ticker || '').replace('USDT', '')}</span> },
    { key: 'side', label: 'Side', render: (r) => <Badge tone={(r.side || '').toLowerCase() === 'long' ? 'ok' : 'err'}>{(r.side || ' ')[0].toUpperCase()}</Badge> },
    { key: 'average', label: 'Entry', align: 'right', render: (r) => lpPx(r.average) },
    { key: 'tp_price', label: 'TP', align: 'right', render: (r) => <span className="qe-up">{lpPx(r.tp_price)}</span> },
    { key: 'sl_price', label: 'SL', align: 'right', render: (r) => <span className="qe-dn">{lpPx(r.sl_price)}</span> },
    { key: 'cd', label: 'Link window', align: 'right', sort: false, render: (r) => <CalcCountdown expiry={r.expiry_ms} window={r.window_seconds} /> },
    { key: 'act', label: '', align: 'right', sort: false, render: (r) => (
        <button className="qe-btn qe-btn-sm qe-btn-ghost" title="Cancel this calc"
          onClick={async (e) => {
            e.stopPropagation();
            if (!window.confirm(`Cancel calc ${String(r.calc_id).slice(-8)}?`)) return;
            try { const res = await _lkForm(`/calculator/cancel/${r.calc_id}`, {}); flash(res.text || 'cancel sent'); load('fast'); }
            catch (err) { flash('cancel failed'); }
          }}>✕</button>
      ) },
  ];
  const fundCols = [
    { key: 'symbol', label: 'Sym', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.symbol || '').replace('USDT', '')}</span> },
    { key: 'direction', label: 'Side', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{(r.direction || ' ')[0]}</Badge> },
    { key: 'rate', label: 'Rate', align: 'right', render: (r) => r.rate == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: r.rate >= 0 ? 'var(--qe-amber)' : 'var(--qe-green)' }}>{(r.rate * 100).toFixed(4)}%</span> },
    { key: 'pays', label: 'Flow', render: (r) => r.rate == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <FundingWho pays={r.pays} /> },
    { key: 'est_next', label: 'Est', align: 'right', render: (r) => r.rate == null ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: lpSgn(r.est_next), fontSize: '0.56rem' }}>{lpUsd(r.est_next, 4)}</span> },
    { key: 'cum', label: 'Cum', align: 'right', render: (r) => <span style={{ color: lpSgn(r.cum) }}>{lpUsd(r.cum, 3)}</span> },
  ];
  const closeCols = [
    { key: 'symbol', label: 'Sym', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{(r.symbol || '').replace('USDT', '')}</span> },
    { key: 'direction', label: 'Side', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{(r.direction || ' ')[0]}</Badge> },
    { key: 'entry_price', label: 'Entry', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.entry_price)}</span> },
    { key: 'exit_price', label: 'Exit', align: 'right', render: (r) => lpPx(r.exit_price) },
    { key: 'net_pnl', label: 'PnL', align: 'right', render: (r) => <span style={{ color: lpSgn(r.net_pnl), fontWeight: 700 }}>{lpUsd(r.net_pnl)}</span> },
    { key: 'exit_reason', label: 'Exit reason', render: (r) => <ExitBadge reason={r.exit_reason} note={r.close_note} pending={r.pending_reason} /> },
    { key: 'funding_fees', label: 'Fund', align: 'right', render: (r) => <span style={{ color: lpSgn(r.funding_fees), fontSize: '0.56rem' }}>{lpUsd(r.funding_fees, 3)}</span> },
  ];

  return (
    <div className="qe-scope" data-screen-label="03 Linkage" style={{ width: '100%', height: '100%', background: 'var(--qe-bg)', display: 'flex', flexDirection: 'column', position: 'relative' }}>
      <TopNavStd page="Linkage" variant="line" dense />
      <PageHeader title="Linkage" subtitle="calc-linkage workspace · manual link · close reasons · positions · funding">
        <StatusDot tone={inbox.length ? 'warn' : 'ok'} label="QUEUE" value={`${inbox.length} open`} />
      </PageHeader>

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <GridWorkspace persistId="linkage">
          <GridItem x={0} y={0} w={9} h={24} minW={6} minH={10}>
            <Pane title="MANUAL LINK — NEEDS REVIEW"
              right={<Badge tone={inbox.length ? 'warn' : 'ok'}>{inbox.length}</Badge>}
              bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
              {needs == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               !inbox.length ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 10 }}>
                  <EmptyState tone="info" glyph="✓" msg="Inbox clear" hint="Every order is linked and every close is categorized." />
                </div>
              ) : (
                <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '162px 1fr' }}>
                  <div style={{ overflow: 'auto', borderRight: '1px solid var(--qe-line)' }}>
                    {inbox.map((item) => {
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
                            <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>{(item.symbol || '').replace('USDT', '')}</span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                            {item.kind === 'link'
                              ? <LinkBadge status={item.link_status} variant={3} />
                              : <span className="qe-mono" style={{ fontSize: '0.52rem', color: 'var(--qe-magenta)' }}>set reason</span>}
                            <span className="qe-mono" style={{ fontSize: '0.5rem', marginLeft: 'auto', color: item.kind === 'link' ? 'var(--qe-muted)' : lpSgn(item.net_pnl) }}>
                              {item.kind === 'link' ? `#${item.id}` : lpUsd(item.net_pnl)}
                            </span>
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
              onRefresh={() => load('fast')} bodyStyle={{ padding: 0 }}>
              {positions == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={posCols} rows={positions} selKey="position_id" tools={false} emptyMsg="no open positions" />}
            </Pane>
          </GridItem>

          <GridItem x={9} y={9} w={8} h={8} minW={4} minH={5}>
            <Pane title="Active Calcs" count={calcs ? calcs.length : null} bodyStyle={{ padding: 0 }}>
              {calcs == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={calcCols} rows={calcs} selKey="calc_id" tools={false} emptyMsg="no active calcs" />}
            </Pane>
          </GridItem>
          <GridItem x={17} y={9} w={7} h={8} minW={4} minH={5}>
            <Pane title="Funding" tag="LIVE" bodyStyle={{ padding: 0 }} onRefresh={() => load('slow')}>
              {funding == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={fundCols} rows={funding.rows || []} selKey="position_id" tools={false}
                 emptyMsg="no open positions"
                 summary={<><span>net next {funding.countdown_s != null ? lpClock(funding.countdown_s) : '—'}</span><span style={{ color: lpSgn(funding.net_next) }}>{lpUsd(funding.net_next, 3)}</span></>} />}
            </Pane>
          </GridItem>

          <GridItem x={9} y={17} w={15} h={7} minW={6} minH={5}>
            <Pane title="Recent Closes" count={closes ? closes.length : null} bodyStyle={{ padding: 0 }}>
              {closes == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
               <DataList columns={closeCols} rows={closes} selKey="id" tools={false} emptyMsg="no recent closes" />}
            </Pane>
          </GridItem>
        </GridWorkspace>
      </div>

      {toast && (
        <div style={{ position: 'absolute', bottom: 14, left: '50%', transform: 'translateX(-50%)', zIndex: 80, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'var(--qe-bg)', border: '1px solid var(--qe-green)' }}>
          <span style={{ color: 'var(--qe-green)' }}>✓</span>
          <span className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-text)' }}>{toast}</span>
        </div>
      )}
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { LinkagePage });
