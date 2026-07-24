/* v3.0 — History page (P4). Ported from the Meridian reference (HistoryPage)
   and WIRED to the ?format=json doors:
     · Closed Positions ← /fragments/history/closed_positions?format=json
       (rows carry the route-stamped deviation_badge)
     · Orders   ← /fragments/history/order_history?format=json
     · Fills    ← /fragments/history/fills?format=json
     · Pre-Trade Log ← /fragments/history/pre_trade?format=json (model_display)
     · Trade Events  ← /fragments/history/trade_events?format=json
     · detail drilldown ← /fragments/history/position_fills?format=json
       (per-fill exec-link badges) — amendments/events ride /context/position/{id}
     · close reason ← PUT /history/close_reason/{id} (LP_MANUAL_REASONS picker)
   Server-side paging + symbol search + date range (presets → date_from/to ISO);
   30s auto-refresh per the Jinja cadence. Named deviations: column-click server
   sort is NOT wired (each table uses its default sort; DataList tools are off —
   the server owns search/paging); the summary strip + CSV export cover the
   LOADED page of rows, not the full dataset; pnl %, M·R and the MFE/MAE heat
   cell are computed client-side from the row's own fields (P8 wave 2 —
   restored per audit L3-F2; the pre-wave header FALSELY claimed M·R was
   already rendered); Open-time/TP/SL columns stay drilldown-only (width);
   the drilldown renders ctx.amendments only; the Trade-Events payload
   expand-grid is NOT ported (the SUMMARY one-liner is — L3-F3); ctx.events +
   the Jinja Export-Audit button are NOT ported — P8 candidates. */

const _hFmtTs = (ms) => {
  if (!ms) return '—';
  const d = new Date(+ms);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const _hDur = (ms) => {
  if (ms == null) return '—';
  const s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return (d ? d + 'd ' : '') + (d || h ? h + 'h ' : '') + m + 'm';
};
const _hIso = (dt, end) => {
  const p = (n) => String(n).padStart(2, '0');
  return `${dt.getFullYear()}-${p(dt.getMonth() + 1)}-${p(dt.getDate())}T${end ? '23:59:59' : '00:00:00'}`;
};
const _hRange = (preset) => {
  if (preset === 'all') return { date_from: '', date_to: '' };
  const now = new Date();
  const from = new Date(now);
  if (preset === 'ytd') { from.setMonth(0, 1); }
  else from.setDate(now.getDate() - ({ '7d': 7, '15d': 15, '30d': 30, '90d': 90 }[preset] || 30));
  return { date_from: _hIso(from, false), date_to: _hIso(now, true) };
};

/* MAE ◂ heat ▸ MFE excursion cell (the design's HistHeat, P8 wave 2 L3-F2):
   two half-bars scaled to the row's own magnitudes — visual only, the
   numbers live in the drilldown. Named deviation: the design's third
   channel (center ENTRY rule + exit-PnL tick) is NOT ported — exit PnL
   already has its own NET column; a zero-magnitude side renders 0-width. */
const HistHeat = ({ mfe, mae }) => {
  if (mfe == null && mae == null) return <span style={{ color: 'var(--qe-muted)' }}>—</span>;
  const f = Math.max(0, +mfe || 0), a = Math.abs(+mae || 0);
  const span = Math.max(f, a) || 1;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 2, width: 74 }} title={`MFE +${f.toFixed(2)} / MAE -${a.toFixed(2)}`}>
      <span style={{ flex: 1, height: 7, display: 'flex', justifyContent: 'flex-end', background: 'var(--qe-panel)' }}>
        <span style={{ width: `${(a / span) * 100}%`, background: 'var(--qe-red)', opacity: 0.75 }} />
      </span>
      <span style={{ flex: 1, height: 7, display: 'flex', background: 'var(--qe-panel)' }}>
        <span style={{ width: `${(f / span) * 100}%`, background: 'var(--qe-green)', opacity: 0.75 }} />
      </span>
    </span>
  );
};

/* Trade-Events SUMMARY one-liner — the Jinja per-type branches ported
   verbatim (P8 wave 2 L3-F3; the payload expand-grid stays unported). */
const _hEvtSummary = (r) => {
  const p = r._payload || {};
  const f = (v, d = 4) => (v == null || isNaN(v) ? '—' : (+v).toFixed(d));
  if (r.event_type === 'position_amended' && p.old != null) return `${p.field || ''}: ${f(p.old)} → ${f(p.new)}`;
  if ((r.event_type === 'tp_modified' || r.event_type === 'sl_modified') && p.from_price != null) return `${f(p.from_price)} → ${f(p.to_price)}`;
  if (r.event_type === 'order_filled' && p.price != null) return `Price: ${f(p.price)} · Qty: ${f(p.quantity != null ? p.quantity : p.fill_qty)}`;
  if (r.event_type === 'position_closed' && p.pnl != null) return `PnL: ${f(p.pnl, 2)}`;
  if (r.event_type === 'order_placed' && p.side) return `${p.side} ${p.order_type || ''}`;
  const raw = r.payload_json || '';
  return raw.length > 60 ? raw.slice(0, 60) + '…' : raw;
};

const H_TABS = [
  ['positions', 'Closed Positions', '/fragments/history/closed_positions'],
  ['orders',    'Orders',           '/fragments/history/order_history'],
  ['fills',     'Fills',            '/fragments/history/fills'],
  ['events',    'Trade Events',     '/fragments/history/trade_events'],
  ['pretrade',  'Pre-Trade Log',    '/fragments/history/pre_trade'],
];

/* reason-picker modal body (shared LP_MANUAL_REASONS) */
const HReasonModal = ({ row, onClose, onSaved }) => {
  const [pick, setPick] = React.useState(null);
  const [note, setNote] = React.useState(row.close_note || '');
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const r = await _lkForm(`/history/close_reason/${row.id}`, { exit_reason: pick, close_note: note }, 'PUT');
      if (r.ok) { onSaved(); onClose(); } else setErr(r.text || 'save failed');
    } catch (e) { setErr('save failed — engine unreachable?'); }
    setBusy(false);
  };
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 90, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div style={{ background: 'var(--qe-card)', border: '1px solid var(--qe-line)', padding: 14, width: 380 }} onClick={(e) => e.stopPropagation()}>
        <SecLbl rule right={<button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={onClose}>✕</button>}>
          {row.symbol} · close reason
        </SecLbl>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, margin: '8px 0' }}>
          {LP_MANUAL_REASONS.map((r) => (
            <button key={r.key} onClick={() => setPick(r.key)} style={{
              textAlign: 'left', padding: '6px 8px', cursor: 'pointer',
              background: pick === r.key ? 'var(--qe-active)' : 'var(--qe-panel)',
              border: `1px solid ${pick === r.key ? 'var(--qe-cyan)' : 'var(--qe-line)'}`,
            }}>
              <div className="qe-mono" style={{ fontSize: '0.6rem', fontWeight: 700, color: pick === r.key ? 'var(--qe-cyan)' : 'var(--qe-text)' }}>{r.label}</div>
              <div style={{ fontSize: '0.5rem', color: 'var(--qe-muted)', marginTop: 2 }}>{r.hint}</div>
            </button>
          ))}
        </div>
        <input className="qe-input" placeholder="optional note…" value={note} onChange={(e) => setNote(e.target.value)} />
        {err ? <div className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-red)', marginTop: 6 }}>{err}</div> : null}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={!pick || busy} onClick={save}>{busy ? <Spinner size="0.62rem" /> : 'Save'}</button>
        </div>
      </div>
    </div>
  );
};

const HistoryPage = () => {
  const [tab, setTab]       = React.useState('positions');
  const [period, setPeriod] = React.useState('30d');
  const [q, setQ]           = React.useState('');
  const [page, setPage]     = React.useState(1);
  const [perPage, setPerPage] = React.useState(75);   // operator-bug #2: 20 -> 75 default
  const [data, setData]     = React.useState(null);   // {rows, total, ...}
  const [loading, setLoading] = React.useState(false);
  const [sel, setSel]       = React.useState(null);   // selected closed row
  const [drill, setDrill]   = React.useState(null);   // {fills, ctx}
  const [modal, setModal]   = React.useState(null);
  const seqRef = React.useRef(0);
  const [net, setNet] = React.useState({});         // table-fetch pipe (qeFootState)
  const [netDrill, setNetDrill] = React.useState({}); // drilldown pipe

  const load = React.useCallback(async () => {
    const ep = H_TABS.find(([k]) => k === tab)[2];
    const { date_from, date_to } = _hRange(period);
    const params = new URLSearchParams({
      format: 'json', page: String(page), per_page: String(perPage),
      search: q.trim(), date_from, date_to,
    });
    const seq = ++seqRef.current;
    setLoading(true);
    const t0 = performance.now();
    try {
      const d = await _ptJson(ep + '?' + params.toString());
      if (seq === seqRef.current) { setData(d); setNet({ err: null, ms: performance.now() - t0 }); }
    } catch (err) {
      // keep last-good on a poll hiccup [P4 audit #5]
      if (seq === seqRef.current) { setData((prev) => prev || { rows: [], total: 0 }); setNet((n) => ({ ...n, err })); }
    }
    if (seq === seqRef.current) setLoading(false);
  }, [tab, period, q, page, perPage]);

  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => { const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);
  React.useEffect(() => { setPage(1); setSel(null); setDrill(null); }, [tab, period, q]);

  /* drilldown for a selected closed position */
  const drillSeq = React.useRef(0);
  const openDrill = async (row) => {
    if (sel && sel.id === row.id) { setSel(null); setDrill(null); return; }
    const seq = ++drillSeq.current;          // stale-response guard [P4 audit #3]
    setSel(row); setDrill(null); setNetDrill({});
    const t0 = performance.now();
    // the inner catches make Promise.all unrejectable — capture the first
    // leg error so the foot can't claim `connected` over a failed drill
    // [foot-audit HIGH-1]
    let legErr = null;
    const [fills, ctx] = await Promise.all([
      _ptJson(`/fragments/history/position_fills?position_id=${row.id}&format=json`).catch((e) => { legErr = legErr || e; return { fills: [] }; }),
      _ptJson(`/context/position/${encodeURIComponent(row.terminal_position_id || row.id)}`).catch((e) => { legErr = legErr || e; return null; }),
    ]);
    if (seq === drillSeq.current) {
      setDrill({ fills: (fills && fills.fills) || [], ctx });
      setNetDrill(legErr ? { err: legErr } : { err: null, ms: performance.now() - t0 });
    }
  };

  const rows = (data && data.rows) || [];
  const total = (data && data.total) || 0;
  const totalPages = Math.max(1, Math.ceil(total / perPage));

  const exportCsv = () => {
    if (!rows.length) return;
    const cols = Object.keys(rows[0]).filter((k) => !k.startsWith('_'));
    const esc = (v) => { const s = String(v == null ? '' : v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = `qe-history-${tab}-${period}-p${page}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const exitCell = (r) => {
    const er = r.exit_reason || '';
    if (er.startsWith('MANUAL') || er === 'manual' || er === 'limit_close') {
      return (
        <span style={{ cursor: 'pointer' }} onClick={(e) => { e.stopPropagation(); setModal(r); }} title="Set / edit the close reason">
          <ExitBadge reason={er.startsWith('MANUAL') ? er : 'MANUAL_OTHER'} note={r.close_note} />
        </span>
      );
    }
    return <ExitBadge reason={er || null} note={r.close_note} pending={!er} />;
  };

  const COLS = {
    positions: [
      { key: 'exit_time_ms', label: 'CLOSED', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{_hFmtTs(r.exit_time_ms)}</span> },
      { key: 'symbol', label: 'SYM', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.symbol}</span> },
      { key: 'direction', label: 'SIDE', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{r.direction}</Badge> },
      { key: 'model_name', label: 'MODEL', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{r.model_name || '—'}</span> },
      { key: 'plan', label: 'PLAN', sort: false, render: (r) => r.calc_id ? <DevBadge pos={{ ...r, amendment_count: r.cumulative_amendment_count }} /> : <span style={{ color: 'var(--qe-muted)' }}>—</span> },
      { key: 'quantity', label: 'QTY', align: 'right', render: (r) => _ptFmtSz(r.quantity) },
      { key: 'entry_price', label: 'ENTRY', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.entry_price)}</span> },
      { key: 'exit_price', label: 'EXIT', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.exit_price)}</span> },
      { key: 'net_pnl', label: 'NET', align: 'right', render: (r) => <span style={{ color: lpSgn(r.net_pnl), fontWeight: 700 }}>{lpUsd(r.net_pnl)}</span> },
      { key: 'pct', label: '%', align: 'right', sort: false, render: (r) => {
          const den = (r.entry_price || 0) * (r.quantity || 0);
          const pct = den ? (r.net_pnl / den) * 100 : null;
          return pct == null ? '—' : <span style={{ color: lpSgn(pct) }}>{lpPct(pct)}</span>;
        } },
      { key: 'mr', label: 'M·R', align: 'right', sort: false, render: (r) => {
          // M·R = MFE / |MAE| (the Jinja twin's column, restored L3-F2).
          // NULL mae/mfe = UNKNOWN → '—'; ∞ only on a MEASURED zero MAE
          // with positive MFE (wave-2 audit F2 — the ||0 coercion
          // fabricated certainty on unbackfilled rows). Named deviation
          // from the twin (which blankets '—' on any falsy mae/ratio):
          // measured values render numerically — more truthful, kept.
          if (r.mae == null || r.mfe == null) return <span style={{ color: 'var(--qe-muted)' }}>—</span>;
          const mae = Math.abs(+r.mae);
          if (!mae) return (+r.mfe) > 0
            ? <span style={{ color: 'var(--qe-green)' }}>∞</span>
            : <span style={{ color: 'var(--qe-muted)' }}>—</span>;
          const mr = (+r.mfe || 0) / mae;
          return <span style={{ color: mr >= 2 ? 'var(--qe-green)' : mr >= 1 ? 'var(--qe-text)' : 'var(--qe-red)' }}>{mr.toFixed(2)}</span>;
        } },
      { key: 'heat', label: 'MAE◂ ▸MFE', align: 'right', sort: false, render: (r) => <HistHeat mfe={r.mfe} mae={r.mae} /> },
      { key: 'total_fees', label: 'FEE', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{_ptFmtN(r.total_fees, 4)}</span> },
      { key: 'hold_time_ms', label: 'DUR', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{_hDur(r.hold_time_ms)}</span> },
      { key: 'exit_reason', label: 'REASON', render: exitCell },
    ],
    orders: [
      { key: 'updated_at_ms', label: 'TIME', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{_hFmtTs(r.updated_at_ms)}</span> },
      { key: 'exchange_order_id', label: 'ORDER ID', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{String(r.exchange_order_id || '').slice(0, 12)}</span> },
      { key: 'symbol', label: 'SYM', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.symbol}</span> },
      { key: 'side', label: 'SIDE', render: (r) => <Badge tone={(r.side || '').toUpperCase() === 'BUY' ? 'ok' : 'err'}>{(r.side || '').toUpperCase()}</Badge> },
      { key: 'order_type', label: 'TYPE', render: (r) => <Badge tone="mute">{(r.order_type || '').toUpperCase()}</Badge> },
      { key: 'quantity', label: 'QTY', align: 'right' },
      { key: 'price', label: 'PRICE', align: 'right', render: (r) => lpPx(r.price) },
      { key: 'avg_fill_price', label: 'AVG FILL', align: 'right', render: (r) => lpPx(r.avg_fill_price) },
      { key: 'status', label: 'STATUS', render: (r) => <Badge tone={r.status === 'filled' ? 'ok' : r.status === 'new' ? 'info' : 'mute'}>{(r.status || '').toUpperCase()}</Badge> },
      { key: 'link_status', label: 'LINK', render: (r) => <LinkBadge status={r.link_status} variant={3} /> },
    ],
    fills: [
      { key: 'timestamp_ms', label: 'TIME', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{_hFmtTs(r.timestamp_ms)}</span> },
      { key: 'symbol', label: 'SYM', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.symbol}</span> },
      { key: 'is_close', label: 'ACTION', render: (r) => <Badge tone={r.is_close ? 'mute' : 'info'}>{r.is_close ? 'CLOSE' : 'OPEN'}</Badge> },
      { key: 'direction', label: 'SIDE', render: (r) => <Badge tone={r.direction === 'LONG' ? 'ok' : 'err'}>{r.direction}</Badge> },
      { key: 'price', label: 'PRICE', align: 'right', render: (r) => lpPx(r.price) },
      { key: 'quantity', label: 'QTY', align: 'right' },
      { key: 'fee', label: 'FEE', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{_ptFmtN(r.fee, 4)} {r.fee_asset || ''}</span> },
      { key: 'role', label: 'ROLE', render: (r) => <Badge tone="mute">{(r.role || '').toUpperCase()}</Badge> },
      { key: 'realized_pnl', label: 'PnL', align: 'right', render: (r) => (r.realized_pnl == null || r.realized_pnl === 0) ? <span style={{ color: 'var(--qe-muted)' }}>—</span> : <span style={{ color: lpSgn(r.realized_pnl) }}>{lpUsd(r.realized_pnl)}</span> },
    ],
    events: [
      /* trade_events rows carry an ISO-string timestamp, not epoch-ms [P4 audit #1] */
      { key: 'timestamp', label: 'TIME', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{String(r.timestamp || '').slice(0, 16).replace('T', ' ') || '—'}</span> },
      { key: '_symbol', label: 'SYM', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r._symbol || '—'}</span> },
      { key: 'event_type', label: 'TYPE', render: (r) => <Badge tone="info">{r.event_type}</Badge> },
      { key: 'calc_id', label: 'CALC', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{r.calc_id ? String(r.calc_id).slice(-8) : '—'}</span> },
      { key: 'source', label: 'SRC', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{r.source || ''}</span> },
      /* the event's SUBSTANCE — restored L3-F3 (the door parses _payload
         per row; the tab consumed only _symbol) */
      { key: 'summary', label: 'SUMMARY', sort: false, render: (r) => <span style={{ color: 'var(--qe-sub)', fontSize: '0.6rem', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block', verticalAlign: 'bottom' }}>{_hEvtSummary(r) || '—'}</span> },
    ],
    pretrade: [
      { key: 'timestamp', label: 'TIME', render: (r) => <span style={{ color: 'var(--qe-muted)' }}>{String(r.timestamp || '').slice(0, 16).replace('T', ' ')}</span> },
      { key: 'calc_id', label: 'CALC ID', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontFamily: 'var(--qe-mono)' }}>{String(r.calc_id || '').slice(-8)}</span> },
      { key: 'ticker', label: 'SYM', render: (r) => <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{r.ticker}</span> },
      { key: 'side', label: 'SIDE', render: (r) => <Badge tone={(r.side || '').toLowerCase() === 'long' ? 'ok' : 'err'}>{(r.side || '').toUpperCase()}</Badge> },
      { key: 'average', label: 'ENTRY', align: 'right', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{lpPx(r.average)}</span> },
      { key: 'tp_price', label: 'TP', align: 'right', render: (r) => <span className="qe-up">{lpPx(r.tp_price)}</span> },
      { key: 'sl_price', label: 'SL', align: 'right', render: (r) => <span className="qe-dn">{lpPx(r.sl_price)}</span> },
      { key: 'size', label: 'SIZE', align: 'right', render: (r) => _ptFmtSz(r.size) },
      { key: 'model_display', label: 'MODEL', render: (r) => <span style={{ color: 'var(--qe-sub)' }}>{r.model_display || '—'}</span> },
      { key: 'status', label: 'LINK', render: (r) => <Badge tone={['matched', 'linked'].includes(r.status) ? 'ok' : r.status === 'active' ? 'info' : 'mute'}>{(r.status || '').toUpperCase()}</Badge> },
    ],
  };

  const summary = (() => {
    if (tab !== 'positions' || !rows.length) return null;
    const net = rows.reduce((s, r) => s + (r.net_pnl || 0), 0);
    const wins = rows.filter((r) => (r.net_pnl || 0) >= 0).length;
    const fees = rows.reduce((s, r) => s + (r.total_fees || 0), 0);
    return [
      { label: 'ROWS', value: String(rows.length) },
      { label: 'WINS', value: String(wins), color: 'var(--qe-green)' },
      { label: 'LOSSES', value: String(rows.length - wins), color: 'var(--qe-red)' },
      { label: 'WINRATE', value: rows.length ? Math.round((wins / rows.length) * 100) + '%' : '—' },
      { label: 'FEES', value: _ptFmtN(fees), color: 'var(--qe-sub)' },
      { label: 'NET', value: lpUsd(net), color: lpSgn(net) },
    ];
  })();

  const dp = sel;
  return (
    <div className="qe-scope" data-screen-label="04 History" style={{ width: '100%', height: '100%', background: 'var(--qe-bg)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <TopNavStd page="History" variant="line" dense />
      <PageHeader title="History" subtitle="closed positions · orders · fills · events · pre-trade log">
        <PeriodSelector options={[['7d', '7D'], ['15d', '15D'], ['30d', '30D'], ['90d', '90D'], ['ytd', 'YTD'], ['all', 'ALL']]} value={period} onChange={setPeriod} />
        <input className="qe-input" placeholder="filter symbol…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') setQ(''); }} style={{ width: 180, height: 22, boxSizing: 'border-box' }} />
        <button className="qe-btn qe-btn-sm" onClick={exportCsv} title="Download the loaded rows as CSV">Export CSV</button>
      </PageHeader>

      {summary ? <Strip dense style={{ margin: 6, marginBottom: 0 }} items={summary} /> : null}

      <TabStrip value={tab} onChange={setTab} tabs={H_TABS.map(([k, l]) => [k, l, tab === k && data ? total : null])} />

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <GridWorkspace>
          <GridItem x={0} y={0} w={16} h={24} minW={8} minH={6}>
            <Pane title={H_TABS.find(([k]) => k === tab)[1]} count={total || null} onRefresh={load}
              style={{ height: '100%' }} bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column' }}
              foot={qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: rows.length > 0, ms: net.ms, retrying: true })}>
              <div style={{ flex: 1, overflow: 'auto' }}>
                {loading && !data ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> :
                 // operator-bug #2: tools stay OFF here by design — this table is
                 // SERVER-PAGED (rows = one page only), and the page already owns
                 // search (symbol filter → server `search`), date presets, and
                 // paging. Client-side DataList tools would search/sort just the
                 // visible page, contradicting the server-owned window. Page size
                 // is operator-selectable (25/50/75/100, default 75) instead.
                 <DataList dense tools={false} columns={COLS[tab]} rows={rows}
                   selKey="id" selected={tab === 'positions' && sel ? sel.id : null}
                   onClick={tab === 'positions' ? (r) => openDrill(r) : undefined}
                   emptyMsg="no rows in this window" />}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', borderTop: '1px solid var(--qe-line)', fontFamily: 'var(--qe-mono)', fontSize: '0.58rem' }}>
                <span style={{ color: 'var(--qe-muted)' }}>{total} rows · page {page}/{totalPages}</span>
                <div className="qe-grow" />
                <select className="qe-input qe-select" style={{ width: 'auto', height: 20, fontSize: '0.56rem' }} value={String(perPage)}
                  onChange={(e) => { setPerPage(+e.target.value); setPage(1); }}>
                  <option value="25">25</option><option value="50">50</option>
                  <option value="75">75</option><option value="100">100</option>
                </select>
                <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>‹</button>
                <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>›</button>
              </div>
            </Pane>
          </GridItem>

          <GridItem x={16} y={0} w={8} h={24} minW={6} minH={6}>
            <Pane title="Position Detail" style={{ height: '100%' }} bodyStyle={{ overflow: 'auto' }}
              foot={!sel ? { tone: 'sub', msg: 'select a position' }
                : qeFootState({ loading: drill == null && !netDrill.err, err: netDrill.err, hasData: drill != null, ms: netDrill.ms })}>
              {!dp ? (
                <EmptyState tone="neutral" glyph="◎" msg="Select a closed position" hint="Click a row to inspect its fills, exec link and amendments." />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <SecLbl rule right={<button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => { setSel(null); setDrill(null); }}>✕</button>}>
                    {dp.symbol} · CLOSED · {dp.direction}
                  </SecLbl>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 10px' }}>
                    <KV l="Net" v={lpUsd(dp.net_pnl)} color={lpSgn(dp.net_pnl)} />
                    <KV l="Duration" v={_hDur(dp.hold_time_ms)} />
                    <KV l="Entry" v={lpPx(dp.entry_price)} />
                    <KV l="Exit" v={lpPx(dp.exit_price)} />
                    <KV l="TP plan" v={lpPx(dp.tp_price)} color="var(--qe-green)" />
                    <KV l="SL plan" v={lpPx(dp.sl_price)} color="var(--qe-red)" />
                    <KV l="MFE / MAE" v={`${_ptFmtN(dp.mfe)} / ${_ptFmtN(dp.mae)}`} />
                    <KV l="Funding" v={lpUsd(dp.funding_fees, 3)} color={lpSgn(dp.funding_fees)} />
                    <KV l="Model" v={dp.model_name || '—'} />
                    <KV l="Calc" v={dp.calc_id ? String(dp.calc_id).slice(-8) : '—'} color="var(--qe-cyan)" />
                  </div>
                  <div style={{ borderTop: '1px solid var(--qe-line)' }} />
                  <SecLbl rule>Fills</SecLbl>
                  {drill == null ? <Spinner label="loading" /> :
                   !drill.fills.length ? <div className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-muted)' }}>No fills recorded for this position.</div> : (
                    // operator-bug #2: drilldown fills — tools off; a handful of
                    // rows inside a modal, no search/sort need.
                    <DataList dense tools={false} selKey="id" columns={[
                      { key: 'timestamp_ms', label: 'TIME', render: (f) => <span style={{ color: 'var(--qe-muted)' }}>{_hFmtTs(f.timestamp_ms)}</span> },
                      { key: 'is_close', label: 'ACT', render: (f) => <Badge tone={f.is_close ? 'mute' : 'info'}>{f.is_close ? 'C' : 'O'}</Badge> },
                      { key: 'price', label: 'PRICE', align: 'right', render: (f) => lpPx(f.price) },
                      { key: 'quantity', label: 'QTY', align: 'right' },
                      { key: 'exec', label: 'EXEC LINK', sort: false, render: (f) =>
                          f.is_close || !f.calc_id ? <span style={{ color: 'var(--qe-muted)' }}>—</span>
                          : f.exec_link_status === 'linked' ? <Badge tone="ok">● LINKED</Badge>
                          : f.exec_link_status === 'partial' ? <Badge tone="warn">⚠ {f.exec_match_count}/1</Badge>
                          : <Badge tone="err">✗ UNLINKED</Badge> },
                    ]} rows={drill.fills} />
                  )}
                  {drill && drill.ctx && Array.isArray(drill.ctx.amendments) && drill.ctx.amendments.length ? (
                    <React.Fragment>
                      <SecLbl rule>Amendments · {drill.ctx.amendments.length}</SecLbl>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        {drill.ctx.amendments.slice(0, 12).map((a, i) => (
                          <div key={i} className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-sub)' }}>
                            {_hFmtTs(a.ts_ms)} · <span style={{ color: 'var(--qe-amber)' }}>{a.field}</span> {a.old_value} → {a.new_value}
                            {a.deviation_pct != null ? <span style={{ color: 'var(--qe-muted)' }}> ({lpPct(a.deviation_pct)})</span> : null}
                          </div>
                        ))}
                      </div>
                    </React.Fragment>
                  ) : null}
                </div>
              )}
            </Pane>
          </GridItem>
        </GridWorkspace>
      </div>
      {modal ? <HReasonModal row={modal} onClose={() => setModal(null)} onSaved={load} /> : null}
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { HistoryPage });
