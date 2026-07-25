/* v3.0 — Pre-Trade / Calculator page (P3). Ported from the Meridian reference
   (pages.jsx CalculatorPage) and WIRED to real engine data:
     · calc submit   → POST /calculator/calculate?format=json (form-encoded;
                       manual submits persist + supersede via the event bus,
                       auto-refresh re-submits send auto_refresh=1 = compute-only
                       — the persistence-suppressor contract)
     · countdown     → GET /calculator/link-window-status/{id}?format=json
                       (the Task-139/146 state machine reproduced client-side:
                       PENDING polls 1s echoing t0, stable states 5s, terminal
                       states stop; remaining time ticks locally off
                       expires_at_ms between polls)
     · live price    → GET /api/price/{ticker} 1 Hz (this poll also keeps the
                       backend calc-symbol stream subscription current)
     · orderbook     → GET /api/calculator/orderbook/{ticker} 2s
     · regime        → GET /api/regime/current (60s)
     · halt state    → GET /api/state 5s (G-O2) — drives the §1.3 blur/freeze
                       overlay: ENFORCED halt → blur + pointer-freeze + scrim
                       reason card over the workspace; advisory breach → warn
                       banner only, trading continues. NO "positions frozen"
                       fiction — the gate blocks NEW calcs only.
     · models        → GET /api/models picker + GET /calculator/prefill/{id}
                       (?model_id= handoff consumed, provisional option idiom)
     · match window  → POST /calculator/window (account default, 60/300/900)
     · clear         → POST /calculator/clear (drops the calc-symbol WS sub)
   Side is SERVER-derived from SL-vs-entry geometry — never submitted.
   Named deviations vs the Jinja page / design reference:
     · page restore renders the CACHED result + live countdown state instead of
       auto-resubmitting (the Jinja restore minted a fresh pre_trade_log row on
       every page load);
     · the design's PRICE/TICKS Setup-Summary toggle is dropped (no tick-size
       in the calc payload; tick-size lookup was rejected in Task 152);
     · design's "Leverage" row renders as portfolio Exposure × (est_exposure —
       the engine has no per-position leverage field);
     · orderbook polls once a ticker is entered (Jinja waited for first calc);
     · recent-setup recall repopulates the form but does NOT auto-submit, and
       restores the CORE fields only (ticker/type/entry/TP/SL — not
       amounts/model/pct-mode);
     · form state persists on successful manual calcs (Jinja saved every
       keystroke debounced);
     · pane-foot last-response lines and the design's RegimeBadge tone-mapping
       are omitted (no engine feed for either). */

/* ── helpers ─────────────────────────────────────────────────────────────── */
/* Last-submit result foot for the calc-result family of panes (Position
   Result / Setup Summary / Correlated Exposure): POST state, not a poll pipe
   (DESIGN.md §5 — non-fetch panes carry their nearest truthful state). */
const _ptCalcFoot = (busy, calcErr, calc) => {
  if (busy) return { tone: 'sub', busy: true, msg: 'calculating…' };
  if (calcErr) {
    return calc
      ? { tone: 'warn', msg: 'calc failed · showing last result' }
      : { tone: 'err', msg: String(calcErr).slice(0, 80) };
  }
  return calc ? { tone: 'ok', msg: 'calc ok' } : { tone: 'sub', msg: 'no calc yet' };
};

/* _ptJson (the status/corrupt-tagging JSON fetch) now lives in
   primitives.jsx — hoisted in P8 wave 2 (audit L1-F8) so every consumer
   (dash-tiled loads BEFORE this module) sits forward of the definition. */
const _ptStrip = (html) => {
  let t;
  try {
    t = (new DOMParser().parseFromString(html || '', 'text/html').body.textContent || '').trim();
  } catch (e) { t = (html || '').trim(); }
  // compact a raw FastAPI 422 {"detail":[...]} body into a readable line
  if (t.startsWith('{') || t.startsWith('[')) {
    try {
      const j = JSON.parse(t);
      const det = j && j.detail;
      if (Array.isArray(det)) {
        return det.map((d) =>
          ((d.loc && d.loc.length ? d.loc[d.loc.length - 1] + ': ' : '') + (d.msg || d.type || 'invalid'))
        ).join(' · ');
      }
      if (typeof det === 'string') return det;
      if (j && j.error) return j.error;
    } catch (e) { /* not JSON — fall through */ }
  }
  return t;
};
/* magnitude-adaptive price display — mirrors core/formatters.format_price */
const _ptFmtP = (v) => {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(+v);
  const d = a >= 1000 ? 2 : a >= 1 ? 4 : 6;
  return (+v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
};
/* fixed 4-dp size — mirrors core/formatters.format_size */
const _ptFmtSz = (v) => (v == null || isNaN(v)) ? '—'
  : (+v).toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
const _ptFmtN = (v, d = 2) => (v == null || isNaN(v)) ? '—'
  : (+v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const _ptSign = (v, d = 2) => (v == null || isNaN(v)) ? '—' : (v >= 0 ? '+' : '') + _ptFmtN(v, d);

const _ptAge = (ts) => {
  const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm ago';
};
/* self-ticking relative age (30s) — keeps the 1s/30s ticks OUT of the page
   tree so the whole workspace doesn't re-render on a timer [P3 audit L4] */
const PtAge = ({ ts }) => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => { const t = setInterval(force, 30000); return () => clearInterval(t); }, []);
  return <React.Fragment>{_ptAge(ts)}</React.Fragment>;
};
/* hybrid remaining display — mirrors link_window_countdown.html */
const _ptRemain = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h >= 1 ? `~${h}h ${m}m` : `${m}m ${s}s`;
};

const PT_STATE_KEY  = 'qe.v3.calc_state';
const PT_RESULT_KEY = 'qe.v3.calc_result';   // sessionStorage
const PT_HIST_KEY   = 'qe.v3.calc_history';
const PT_COMMODITY_RE = /^(XAU|XAG|XPT|XPD|WTI|BRN)/i;

const PT_FORM_DEFAULTS = {
  orderType: 'market', ticker: '', limitPrice: '',
  tpslMode: 'price', sideSel: 'long',
  tpPrice: '', slPrice: '', tpPct: '', slPct: '',
  tpAmountPct: '100', slAmountPct: '100',
  modelId: '', modelName: '', modelDesc: '',
  linkOverride: '', sizeOverride: '',
  applyMult: true,
  ladder: [],                      // [{price:'', pct:''}] — serialized on submit
};

const _ptReadJSON = (store, key) => {
  try { const s = store.getItem(key); return s ? JSON.parse(s) : null; } catch (e) { return null; }
};
const _ptWriteJSON = (store, key, v) => { try { store.setItem(key, JSON.stringify(v)); } catch (e) {} };

/* ── countdown chip (the refresh-strip LINKABLE chip, all 7 states).
   Self-ticking (1s, only while a countdown is live) so the page tree never
   re-renders on a timer [P3 audit L4]. Remaining time = the server's
   remaining_s minus client elapsed-since-receipt (lw._at) — immune to
   client-vs-server clock skew [P3 audit L5]; the 5s re-polls re-anchor. ── */
const PtCountdownChip = ({ lw }) => {
  const s = lw && lw.status;
  const ticking = s === 'LINKABLE' || s === 'EXPIRING_SOON';
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => {
    if (!ticking) return;
    const t = setInterval(force, 1000);
    return () => clearInterval(t);
  }, [ticking, lw]);
  if (!lw) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 8px', border: '1px solid var(--qe-line)', fontSize: '0.62rem', fontFamily: 'var(--qe-mono)', color: 'var(--qe-muted)' }}>
        no active calc
      </div>
    );
  }
  const box = (color, children) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 8px', border: `1px solid ${color}`, borderLeft: `3px solid ${color}`, fontSize: '0.62rem', fontFamily: 'var(--qe-mono)' }}>
      {children}
    </div>
  );
  if (s === 'PENDING')  return box('var(--qe-line-2)', <span style={{ color: 'var(--qe-muted)', fontWeight: 700 }}>⌛ Confirming calc…</span>);
  if (s === 'ERROR')    return box('var(--qe-red)', <><span style={{ color: 'var(--qe-red)', fontWeight: 700 }}>✗ Submission failed to record</span><span style={{ color: 'var(--qe-muted)' }}>— please retry</span></>);
  if (s === 'LINKED')   return box('var(--qe-green)', <><span style={{ color: 'var(--qe-green)', fontWeight: 700 }}>✓ LINKED</span><span style={{ color: 'var(--qe-muted)' }}>— matched to an order</span></>);
  if (s === 'LINKED_CONFIRMED') return box('var(--qe-green)', <><span style={{ color: 'var(--qe-green)', fontWeight: 700 }}>✓ LINKED (CONFIRMED)</span><span style={{ color: 'var(--qe-muted)' }}>— operator confirmation bypasses window check</span></>);
  if (s === 'EXPIRED')  return box('var(--qe-red)', <><span style={{ color: 'var(--qe-red)', fontWeight: 700 }}>✗ PLAN EXPIRED</span><span style={{ color: 'var(--qe-muted)' }}>— recalculate to link new fills</span></>);
  // LINKABLE / EXPIRING_SOON — server remaining_s anchored at receipt time
  const elapsed = lw._at ? (Date.now() - lw._at) / 1000 : 0;
  const rem = (lw.remaining_s || 0) - elapsed;
  const warn = s === 'EXPIRING_SOON';
  const col = warn ? 'var(--qe-amber)' : 'var(--qe-green)';
  return box(col, <>
    <span style={{ color: col, fontWeight: 700 }}>{warn ? '⚠ EXPIRING SOON' : '✓ LINKABLE'}</span>
    <span style={{ color: 'var(--qe-text)' }}>{_ptRemain(rem)} left</span>
    <span style={{ color: 'var(--qe-muted)' }}>(window {Math.round((lw.effective_window_s || 0) / 60)} min)</span>
  </>);
};

/* hoisted Setup-Summary copy cell — stable component type so the 6 cells are
   never unmounted/remounted by parent re-renders [P3 audit L3] */
const PtCopyCell = ({ label, value, display, color, copied, onCopy }) => {
  const done = copied === label;
  return (
    <div>
      <Lbl>{label}</Lbl>
      <div onClick={() => onCopy(label, value)} title={`Copy ${label}`} style={{
        display: 'flex', alignItems: 'stretch', height: 22, cursor: 'pointer',
        background: 'var(--qe-panel)', border: `1px solid ${done ? 'var(--qe-green)' : 'var(--qe-line)'}`,
      }}>
        <div style={{ flex: 1, minWidth: 0, padding: '0 7px', display: 'flex', alignItems: 'center', fontFamily: 'var(--qe-mono)', fontSize: '0.7rem', fontWeight: 600, color, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{display != null ? display : value}</div>
        <button title={`Copy ${label}`} onClick={(e) => { e.stopPropagation(); onCopy(label, value); }} style={{
          width: 22, flex: '0 0 22px', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'transparent', border: 'none', borderLeft: `1px solid ${done ? 'var(--qe-green)' : 'var(--qe-line)'}`,
          color: done ? 'var(--qe-green)' : 'var(--qe-muted)', cursor: 'pointer', fontSize: '0.72rem', lineHeight: 1,
        }}><span style={{ display: 'block', transform: 'translateY(1px)' }}>{done ? '✓' : '⧉'}</span></button>
      </div>
    </div>
  );
};

/* ── Pre-Trade page ──────────────────────────────────────────────────────── */
const PreTradePage = () => {
  /* server context */
  const [st, setSt]           = React.useState(null);
  const [regime, setRegime]   = React.useState(null);
  const [models, setModels]   = React.useState(null);
  const [ctxInfo, setCtxInfo] = React.useState(null);
  const [riskPct, setRiskPct] = React.useState(null);

  /* form (restored from localStorage) */
  const [form, setForm] = React.useState(() => {
    const saved = _ptReadJSON(localStorage, PT_STATE_KEY);
    return saved ? { ...PT_FORM_DEFAULTS, ...saved, ladder: Array.isArray(saved.ladder) ? saved.ladder : [] } : { ...PT_FORM_DEFAULTS };
  });
  const set = (k) => (e) => {
    const v = e && e.target ? (e.target.type === 'checkbox' ? e.target.checked : e.target.value) : e;
    setForm((f) => ({ ...f, [k]: v }));
  };

  /* live data + result */
  const [livePrice, setLivePrice] = React.useState(null);
  const [ob, setOb]               = React.useState(null);
  const [calc, setCalc]           = React.useState(() => _ptReadJSON(sessionStorage, PT_RESULT_KEY));
  const [calcErr, setCalcErr]     = React.useState(null);
  const [busy, setBusy]           = React.useState(false);
  const [lwCalcId, setLwCalcId]   = React.useState(() => {
    const c = _ptReadJSON(sessionStorage, PT_RESULT_KEY);
    return c && c.calc_id && c.eligible ? c.calc_id : null;
  });
  const [lw, setLw]               = React.useState(null);
  const [autoRate, setAutoRate]   = React.useState(() => {
    // restored limit/stop forms keep the 30s cadence (parity) [P3 audit L2]
    const saved = _ptReadJSON(localStorage, PT_STATE_KEY);
    return saved && saved.orderType && saved.orderType !== 'market' ? 30 : 1;
  });
  const [sizeUnit, setSizeUnit]   = React.useState('notional');
  const [copied, setCopied]       = React.useState(null);
  const [recent, setRecent]       = React.useState(() => _ptReadJSON(localStorage, PT_HIST_KEY) || []);
  const [winSaved, setWinSaved]   = React.useState(null);

  const tickerRef  = React.useRef(form.ticker.trim().toUpperCase());
  const inFlight   = React.useRef(false);
  const pendingManual = React.useRef(false);  // manual click during an in-flight auto [P3 audit MED-1]
  const t0Ref      = React.useRef(0);
  const formRef    = React.useRef(form);
  formRef.current  = form;
  const liveRef    = React.useRef(null);
  liveRef.current  = livePrice;
  const stRef      = React.useRef(null);      // live halt state for submit/auto guards
  stRef.current    = st;
  const regimeRef  = React.useRef(null);      // read by doCalculate without a dep [P3 audit L1]
  regimeRef.current = regime;
  // the ticker the last calc actually ran against — auto-refresh pauses when
  // the form ticker diverges (the Jinja _calcTicker guard) [P3 audit HIGH-2].
  // Seeded from the restored session so a restored result keeps refreshing.
  const calcTickerRef = React.useRef(calc ? calc.ticker : null);

  /* ── context fetches + polls ── */
  const [netRegime, setNetRegime] = React.useState({});   // regime-poll pipe (qeFootState)
  React.useEffect(() => {
    let alive = true;
    const load = (url, fn, netFn) => {
      const t0 = performance.now();
      return _ptJson(url)
        .then((d) => { if (alive) { fn(d); if (netFn) netFn({ err: null, ms: performance.now() - t0 }); } })
        .catch((err) => { if (alive && netFn) netFn((n) => ({ ...n, err })); });
    };
    load('/api/state', setSt);
    load('/api/regime/current', setRegime, setNetRegime);
    load('/api/models', (d) => setModels(Array.isArray(d) ? d : (d.models || [])));
    load('/api/calculator/context', setCtxInfo);
    const aid = window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.activeAccountId;
    if (aid != null) load('/api/config/account/' + aid, (d) => setRiskPct((d.params || {}).individual_risk_per_trade));
    const t1 = setInterval(() => load('/api/state', setSt), 5000);
    const t2 = setInterval(() => load('/api/regime/current', setRegime, setNetRegime), 60000);
    return () => { alive = false; clearInterval(t1); clearInterval(t2); };
  }, []);

  /* model prefill — shared by the ?model_id= handoff AND the in-page picker
     change (the Jinja applyModelPrefill lane) [P3 audit MED-2]. Truthy-applied
     like Jinja (a preset stored as 0/1 still applies) [P3 audit LOW-1]. */
  const applyPrefill = React.useCallback((id) => {
    if (!id) return;
    _ptJson('/calculator/prefill/' + encodeURIComponent(id)).then((p) => {
      const rp = (p && p.risk_preset) || {};
      setForm((f) => ({
        ...f,
        applyMult: rp.apply_regime_multiplier != null ? !!rp.apply_regime_multiplier : f.applyMult,
        sizeOverride: rp.size_override_default != null ? String(rp.size_override_default) : f.sizeOverride,
        modelName: f.modelName || p.name || '',
      }));
    }).catch(() => {});
  }, []);

  /* ── ?model_id= handoff (Models → Pre-Trade) ── */
  React.useEffect(() => {
    let qid = null;
    try { qid = new URLSearchParams(window.location.search).get('model_id'); } catch (e) {}
    if (!qid || !/^\d+$/.test(qid)) return;
    setForm((f) => ({ ...f, modelId: qid }));
    applyPrefill(qid);
  }, [applyPrefill]);

  /* ── 1 Hz live price poll (debounced on ticker; also keeps the backend
        calc-symbol subscription current — /api/price side effect) ── */
  const tickerNorm = form.ticker.trim().toUpperCase();
  /* pretrade-4 (2026-07-25 Meridian audit): this poll's failures used to be
     swallowed silently while the pane foot asserted a static ok/'local'. In
     MARKET mode `livePrice` IS the sizing entry (doCalculate reads liveRef), so
     a dead poll sized off a stale price with nothing on screen saying so. Track
     the pipe like every other polled pane on this page (see netOb below) and
     feed qeFootState. */
  const [netPx, setNetPx] = React.useState({});   // price 1s pipe (qeFootState)
  React.useEffect(() => {
    tickerRef.current = tickerNorm;
    setLivePrice(null);
    setNetPx({});
    if (!tickerNorm) return;
    let alive = true, timer = null;
    // Whether THIS ticker has ever yielded a price. Scoped to the effect so a
    // ticker switch resets it; a ref would leak the previous symbol's state.
    let hadPrice = false;
    const poll = async () => {
      const t0 = performance.now();
      try {
        const d = await _ptJson('/api/price/' + encodeURIComponent(tickerNorm));
        if (alive && tickerRef.current === tickerNorm) {
          const ms = performance.now() - t0;
          if (d.price) { hadPrice = true; setLivePrice(d.price); }
          // A 200 carrying no price AFTER we already latched one is feed death,
          // not health: livePrice keeps its last value (the intended keep-last)
          // and in MARKET mode that latched value still drives sizing, so a green
          // foot there would paint health over a stale sizing input — the exact
          // class this fix exists to remove. `corrupt` selects qeFootState's
          // keep-last-good warn tier ("showing last data").
          // Before the first price there is nothing latched and Entry Price
          // honestly reads '—', so the pipe is simply ok — flagging that would
          // fire a red foot through normal warm-up.
          setNetPx((!d.price && hadPrice) ? { err: { corrupt: true }, ms }
                                          : { err: null, ms });
        }
      } catch (err) {
        if (alive && tickerRef.current === tickerNorm) setNetPx((n) => ({ ...n, err }));
      }
      if (alive) timer = setTimeout(poll, 1000);
    };
    const debounce = setTimeout(poll, 500);
    return () => { alive = false; clearTimeout(debounce); clearTimeout(timer); };
  }, [tickerNorm]);

  /* ── 2s orderbook poll ── */
  const [netOb, setNetOb] = React.useState({});   // orderbook 2s pipe (qeFootState)
  React.useEffect(() => {
    setOb(null);
    setNetOb({});
    if (!tickerNorm) return;
    let alive = true, timer = null;
    const poll = async () => {
      const t0 = performance.now();
      try {
        const d = await _ptJson('/api/calculator/orderbook/' + encodeURIComponent(tickerNorm));
        if (alive && tickerRef.current === tickerNorm) { setOb(d); setNetOb({ err: null, ms: performance.now() - t0 }); }
      } catch (err) { if (alive && tickerRef.current === tickerNorm) setNetOb((n) => ({ ...n, err })); }
      if (alive) timer = setTimeout(poll, 2000);
    };
    const debounce = setTimeout(poll, 600);
    return () => { alive = false; clearTimeout(debounce); clearTimeout(timer); };
  }, [tickerNorm]);

  /* ── countdown poller (the Task-139/146 state machine, JSON mirror) ── */
  React.useEffect(() => {
    setLw(null);
    t0Ref.current = 0;
    if (!lwCalcId) return;
    let stop = false, timer = null;
    const poll = async () => {
      try {
        const q = t0Ref.current ? '&t0=' + t0Ref.current : '';
        const d = await _ptJson('/calculator/link-window-status/' + encodeURIComponent(lwCalcId) + '?format=json' + q);
        if (stop) return;
        setLw({ ...d, _at: Date.now() });   // receipt anchor for the skew-immune tick
        if (d.t0) t0Ref.current = d.t0;
        if (d.status === 'PENDING') timer = setTimeout(poll, 1000);
        else if (d.status === 'LINKABLE' || d.status === 'EXPIRING_SOON') timer = setTimeout(poll, 5000);
        /* terminal states (ERROR/LINKED/LINKED_CONFIRMED/EXPIRED): stop */
      } catch (e) {
        if (!stop) timer = setTimeout(poll, 5000);
      }
    };
    poll();
    return () => { stop = true; clearTimeout(timer); };
  }, [lwCalcId]);

  /* ── submit ── */
  const doCalculate = React.useCallback(async (auto) => {
    const f = formRef.current;
    const t = f.ticker.trim().toUpperCase();
    if (inFlight.current) {
      // a manual click colliding with an in-flight auto request is QUEUED,
      // not swallowed — it re-fires after the current request settles
      // [P3 audit MED-1]
      if (!auto) pendingManual.current = true;
      return;
    }
    // enforced DD halt: the server would render the calc ineligible anyway;
    // fail loud client-side and stop auto traffic [P3 audit N1]
    if (stRef.current && stRef.current.halted) {
      if (!auto) setCalcErr('Calculator blocked — DD hard stop (enforced). See the banner.');
      return;
    }
    if (!t) { if (!auto) setCalcErr('Ticker is required.'); return; }
    // auto re-submits only ever refresh the LAST CALCULATED ticker — a
    // half-edited form must never repaint the result (Jinja _calcTicker
    // guard) [P3 audit HIGH-2]
    if (auto && t !== calcTickerRef.current) return;

    const entry = f.orderType === 'market'
      ? liveRef.current
      : parseFloat(f.limitPrice);
    if (!entry || !isFinite(entry) || entry <= 0) {
      if (!auto) setCalcErr(f.orderType === 'market' ? 'No live price yet — wait a beat or switch to LIMIT.' : 'Entry price is required.');
      return;
    }

    let tp = null, sl = null;
    if (f.tpslMode === 'price') {
      tp = f.tpPrice.trim() ? parseFloat(f.tpPrice) : null;
      sl = f.slPrice.trim() ? parseFloat(f.slPrice) : null;
    } else {
      // BY-% requires POSITIVE percents — a negative would silently flip the
      // server-derived side (Jinja guard restored) [P3 audit LOW-2]
      const tpp = parseFloat(f.tpPct), slp = parseFloat(f.slPct);
      if (f.slPct.trim() && (!isFinite(slp) || slp <= 0)) {
        if (!auto) setCalcErr('SL % must be a positive number.');
        return;
      }
      const dir = f.sideSel === 'short' ? -1 : 1;
      if (isFinite(tpp) && tpp > 0) tp = entry * (1 + dir * tpp / 100);
      if (isFinite(slp) && slp > 0) sl = entry * (1 - dir * slp / 100);
    }
    const ladder = f.ladder
      .map((r) => ({ price: parseFloat(r.price), size_pct: parseFloat(r.pct) }))
      .filter((r) => isFinite(r.price) && r.price > 0 && isFinite(r.size_pct) && r.size_pct > 0);
    // TP blank, zero or negative + a ladder → TP1 feeds the single TP
    // (matches the Jinja configRequest tpP<=0 branch) [P3 audit NIT-1]
    if ((tp == null || !isFinite(tp) || tp <= 0) && ladder.length) tp = ladder[0].price;
    if (sl == null || !isFinite(sl) || sl <= 0) {
      if (!auto) setCalcErr('SL is required.');
      return;
    }

    inFlight.current = true;
    if (!auto) { setBusy(true); setCalcErr(null); }
    try {
      const body = new URLSearchParams({
        ticker: t,
        average: String(entry),
        sl_price: String(sl),
        tp_price: tp != null && isFinite(tp) ? String(tp) : '0',
        tp_amount_pct: f.tpAmountPct.trim() || '100',
        sl_amount_pct: f.slAmountPct.trim() || '100',
        model_name: f.modelName, model_desc: f.modelDesc,
        order_type: f.orderType,
        auto_refresh: auto ? '1' : '0',
        apply_regime_multiplier: f.applyMult ? '1' : '0',
        link_window_seconds_override: f.linkOverride,
        size_override: f.sizeOverride.trim(),
        tp_levels: ladder.length ? JSON.stringify(ladder) : '',
        model_id: f.modelId,
      });
      const r = await fetch('/calculator/calculate?format=json', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
      });
      const text = await r.text();
      let data = null;
      try { data = JSON.parse(text); } catch (e) { /* HTML error fragment */ }
      if (tickerRef.current !== t) return;                  // ticker switched mid-flight
      if (!data || !r.ok) {
        if (!auto) setCalcErr(_ptStrip(text) || ('calc failed (' + r.status + ')'));
        return;
      }
      setCalc(data);
      calcTickerRef.current = t;
      if (!auto) {
        setCalcErr(null);
        if (data.calc_id && data.eligible) setLwCalcId(data.calc_id);
        else setLwCalcId(null);
        /* cache + persist on MANUAL calcs ONLY — auto-refresh calc_ids are
           compute-only (never inserted into pre_trade_log); caching one and
           restoring its id produced a false "Submission failed to record"
           on reload [P3 audit HIGH-1] */
        _ptWriteJSON(sessionStorage, PT_RESULT_KEY, data);
        const { ladder: lad, ...rest } = f;
        _ptWriteJSON(localStorage, PT_STATE_KEY, { ...rest, ladder: lad });
        const entryRec = {
          ticker: t, side: data.side ? String(data.side).toUpperCase() : (sl > entry ? 'SHORT' : 'LONG'),
          orderType: f.orderType, entry: entry, tp: tp, sl: sl,
          mult: data.regime_multiplier != null ? data.regime_multiplier : 1,
          regime: data.regime_label || (regimeRef.current && regimeRef.current.label) || '',
          ts: Date.now(),
        };
        setRecent((prev) => {
          const next = [entryRec, ...prev].slice(0, 2);
          _ptWriteJSON(localStorage, PT_HIST_KEY, next);
          return next;
        });
      }
    } catch (e) {
      if (!auto) setCalcErr('calc failed — engine unreachable?');
    } finally {
      inFlight.current = false;
      if (!auto) setBusy(false);
      if (pendingManual.current) {          // re-fire the queued manual click
        pendingManual.current = false;
        setTimeout(() => doCalculate(false), 0);
      }
    }
  }, []);

  /* ── auto-refresh (persistence-suppressed re-submits). Deps are STABLE
        (boolean hasCalc, memoized doCalculate) so the interval isn't re-armed
        by every result object [P3 audit L1]; the cross-ticker + halt guards
        live inside doCalculate. ── */
  const hasCalc = !!calc;
  React.useEffect(() => {
    if (!autoRate || !hasCalc) return;
    const t = setInterval(() => {
      if (!inFlight.current && calcTickerRef.current) doCalculate(true);
    }, autoRate * 1000);
    return () => clearInterval(t);
  }, [autoRate, hasCalc, doCalculate]);

  /* order-type switch: default cadence 1s market / 30s limit+stop (parity);
     a PAUSED auto-refresh stays paused [P3 audit L2] */
  const setOrderType = (k) => {
    setForm((f) => ({ ...f, orderType: k }));
    setAutoRate((r) => (r === 0 ? 0 : (k === 'market' ? 1 : 30)));
  };

  const doClear = async () => {
    setForm({ ...PT_FORM_DEFAULTS });
    setCalc(null); setCalcErr(null); setLwCalcId(null); setLw(null);
    setLivePrice(null); setOb(null);
    setSizeUnit('notional');
    setAutoRate(1);
    calcTickerRef.current = null;
    try { localStorage.removeItem(PT_STATE_KEY); sessionStorage.removeItem(PT_RESULT_KEY); } catch (e) {}
    try { await fetch('/calculator/clear', { method: 'POST' }); } catch (e) {}
  };

  const saveWindow = async (v) => {
    setWinSaved(null);
    try {
      const r = await fetch('/calculator/window', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ window_seconds: v }).toString(),
      });
      const txt = _ptStrip(await r.text());
      const ok = /✓|saved/i.test(txt);
      setWinSaved({ text: txt || (r.ok ? 'saved ✓' : 'save failed'), ok });
      // only reflect the new window when the server actually accepted it
      // [P3 audit NIT-3]
      if (ok) setCtxInfo((c) => (c ? { ...c, window_seconds: +v } : c));
    } catch (e) { setWinSaved({ text: 'save failed — engine unreachable?', ok: false }); }
  };

  const recall = (r) => {
    setForm((f) => ({
      ...f,
      ticker: r.ticker, orderType: r.orderType || 'market',
      limitPrice: r.orderType !== 'market' && r.entry != null ? String(r.entry) : f.limitPrice,
      tpslMode: 'price',
      tpPrice: r.tp != null ? String(r.tp) : '',
      slPrice: r.sl != null ? String(r.sl) : '',
    }));
    setAutoRate((cur) => (cur === 0 ? 0 : ((r.orderType || 'market') === 'market' ? 1 : 30)));
  };

  const copyCell = (label, value) => {
    const clean = String(value).replace(/,/g, '');
    try { navigator.clipboard && navigator.clipboard.writeText(clean).catch(() => {}); } catch (e) {}
    setCopied(label);
    setTimeout(() => setCopied((c) => (c === label ? null : c)), 1200);
  };

  /* ── derived halt state (G-O2 / §1.3) ── */
  const halted  = !!(st && st.halted);
  const blocked = !!(st && st.blocked);
  const gateDot = halted ? ['err', 'HALTED'] : blocked ? ['warn', 'LIMIT'] : ['ok', 'READY'];
  const isCommodity = PT_COMMODITY_RE.test(tickerNorm);
  const effSizeUnit = sizeUnit === 'lot' && !isCommodity ? 'contracts' : sizeUnit;
  const c = calc || {};
  // display form: snake_case keys read as words (P8 audit L2-NIT-6 — the
  // ratified RegimeBadge-map omission left raw RISK_ON_CHOPPY on 4 sites)
  const regLabel = ((calc && calc.regime_label) || (regime && regime.label) || '—').replace(/_/g, ' ');
  const regMult  = (calc && calc.regime_multiplier != null) ? calc.regime_multiplier
                 : (regime && regime.multiplier != null) ? regime.multiplier : 1;

  /* keyboard: Enter walks ticker → entry → TP → SL → submit; Ctrl/Cmd+Enter submits */
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); doCalculate(false); }
  };
  const enterTo = (fn) => (e) => { if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); fn(); } };
  const focusId = (id) => () => { const el = document.getElementById(id); if (el) el.focus(); };

  return (
    <div className="qe-scope" data-screen-label="02 Pre-Trade" style={{
      width: '100%', height: '100%', background: 'var(--qe-bg)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }} onKeyDown={onKey}>
      <TopNavStd page="Pre-Trade" variant="line" dense />

      <PageHeader title="Pre-Trade" subtitle="position sizing · TP/SL · risk gate · exec link">
        <StatusDot tone={gateDot[0]} label="GATE" value={gateDot[1]} />
        <StatusDot tone="info" label="REGIME" value={regLabel !== '—' ? `${String(regLabel).toUpperCase().slice(0, 14)} ×${_ptFmtN(regMult, 1)}` : '—'} />
        <StatusDot tone="info" label="LINK" value={ctxInfo ? Math.round(ctxInfo.window_seconds / 60) + 'm window' : '—'} />
        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.56rem', color: 'var(--qe-muted)' }}>
          risk/trade <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{riskPct != null ? _ptFmtN(riskPct * 100, 2) + '%' : '—'}</span>
        </span>
      </PageHeader>

      {/* §1.3 halt banners — corrected copy: the gate blocks NEW calcs only */}
      {halted && (
        <Banner tone="err" tag="HALT"
          title="CALCULATOR BLOCKED — DD hard stop (enforced)"
          detail={(st.halt_reason || 'drawdown limit breached') + ' · new sizing calcs are gated · open positions are NOT affected · override via Dashboard'} />
      )}
      {!halted && blocked && (
        <Banner tone="warn" tag="RISK"
          title="RISK LIMIT REACHED (advisory)"
          detail={`dd_state=${st.dd_state} · weekly=${st.weekly_pnl_state} · advisory mode — trading continues, calcs stay enabled`} />
      )}

      {/* Auto-refresh + match-window + link-window strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 8px', background: 'var(--qe-page)', borderBottom: '1px solid var(--qe-line)', opacity: halted ? 0.45 : 1 }}>
        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.56rem', color: 'var(--qe-muted)', letterSpacing: '0.1em' }}>↻ AUTO-REFRESH</span>
        <PeriodSelector options={[[1, '1s'], [5, '5s'], [10, '10s'], [30, '30s'], [0, '⏸']]} value={autoRate} onChange={setAutoRate} />
        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.56rem', color: 'var(--qe-muted)', letterSpacing: '0.1em', marginLeft: 10 }}>MATCH WINDOW</span>
        <select className="qe-input qe-select" style={{ width: 'auto', height: 22, fontSize: '0.6rem' }}
          value={ctxInfo ? String(ctxInfo.window_seconds) : '300'}
          onChange={(e) => saveWindow(e.target.value)}>
          {ctxInfo && ![60, 300, 900].includes(ctxInfo.window_seconds)
            ? <option value={String(ctxInfo.window_seconds)}>{ctxInfo.window_seconds} s</option> : null}
          <option value="60">1 min</option>
          <option value="300">5 min</option>
          <option value="900">15 min</option>
        </select>
        {winSaved ? <span className="qe-mono" style={{ fontSize: '0.56rem', color: winSaved.ok ? 'var(--qe-green)' : 'var(--qe-red)' }}>{winSaved.text}</span> : null}
        <div className="qe-grow" />
        <PtCountdownChip lw={lw} />
      </div>

      {/* §1.3 — enforced halt freezes the workspace: blur + pointer-freeze +
          scrim reason card. The wrapper is position:relative; the scrim is a
          SIBLING of the workspace (not blurred itself). */}
      <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <GridWorkspace style={halted ? { filter: 'blur(3px) grayscale(0.4)', pointerEvents: 'none', userSelect: 'none' } : {}}>

          {/* INPUTS pane */}
          <GridItem x={0} y={0} w={10} h={12} minW={6} minH={8}>
            <Pane title="Order Inputs" style={{ height: '100%' }} bodyStyle={{ overflow: 'auto' }}
              right={<Badge tone={form.orderType === 'limit' ? 'ok' : 'warn'}>{form.orderType === 'limit' ? 'MAKER FEE' : 'TAKER FEE'}</Badge>}
              /* pretrade-4: the foot now carries the 1 Hz price poll's REAL state
                 (it used to assert a static ok/'local' while hosting that poll). */
              foot={!tickerNorm ? { tone: 'sub', msg: 'local · enter a ticker to poll price' }
                : qeFootState({ loading: netPx.ms == null && !netPx.err, err: netPx.err,
                                hasData: livePrice != null, ms: netPx.ms, retrying: true })}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>

                <div>
                  <Lbl>Order Type</Lbl>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 4, marginTop: 3 }}>
                    {[['market', 'MARKET'], ['limit', 'LIMIT'], ['stop', 'STOP']].map(([k, l]) => (
                      <button key={k} onClick={() => setOrderType(k)} className={`qe-btn ${form.orderType === k ? 'qe-btn-primary' : ''}`} style={{ height: 26, justifyContent: 'center' }}>{l}</button>
                    ))}
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <div>
                    <Lbl>Ticker</Lbl>
                    <input id="pt-ticker" className="qe-input" value={form.ticker} onChange={set('ticker')}
                      placeholder="BTCUSDT" onKeyDown={enterTo(focusId(form.orderType === 'market' ? 'pt-tp' : 'pt-entry'))} />
                  </div>
                  <div>
                    <Lbl>Entry Price{form.orderType === 'market' && <span style={{ color: 'var(--qe-green)', marginLeft: 4 }}>(live)</span>}</Lbl>
                    {form.orderType === 'market' ? (
                      <input className="qe-input" readOnly value={livePrice != null ? _ptFmtP(livePrice) : '—'}
                        style={{ color: 'var(--qe-green)', borderColor: 'var(--qe-bg-green)' }} />
                    ) : (
                      <input id="pt-entry" className="qe-input" value={form.limitPrice} onChange={set('limitPrice')}
                        placeholder={livePrice != null ? _ptFmtP(livePrice) : ''} onKeyDown={enterTo(focusId('pt-tp'))} />
                    )}
                  </div>
                </div>

                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <Lbl>TP / SL</Lbl>
                    <PeriodSelector options={[['price', 'BY PRICE'], ['pct', 'BY %']]} value={form.tpslMode} onChange={(v) => setForm((f) => ({ ...f, tpslMode: v }))} />
                    {form.tpslMode === 'pct' && (
                      <React.Fragment>
                        <span style={{ color: 'var(--qe-muted)', fontSize: '0.56rem' }}>side</span>
                        <PeriodSelector options={[['long', 'LONG'], ['short', 'SHORT']]} value={form.sideSel} onChange={(v) => setForm((f) => ({ ...f, sideSel: v }))} />
                      </React.Fragment>
                    )}
                  </div>
                  {form.tpslMode === 'price' ? (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      <div><Lbl>TP Price</Lbl><input id="pt-tp" className="qe-input" value={form.tpPrice} onChange={set('tpPrice')} onKeyDown={enterTo(focusId('pt-sl'))} style={{ color: 'var(--qe-green)' }} /></div>
                      <div><Lbl>SL Price</Lbl><input id="pt-sl" className="qe-input" value={form.slPrice} onChange={set('slPrice')} onKeyDown={enterTo(() => doCalculate(false))} style={{ color: 'var(--qe-red)' }} /></div>
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                      <div><Lbl>TP %</Lbl><input id="pt-tp" className="qe-input" value={form.tpPct} onChange={set('tpPct')} onKeyDown={enterTo(focusId('pt-sl'))} style={{ color: 'var(--qe-green)' }} /></div>
                      <div><Lbl>SL %</Lbl><input id="pt-sl" className="qe-input" value={form.slPct} onChange={set('slPct')} onKeyDown={enterTo(() => doCalculate(false))} style={{ color: 'var(--qe-red)' }} /></div>
                    </div>
                  )}
                  {(() => {  /* live TP/SL preview (clamped >100% — FE-LOW-024) */
                    const entry = form.orderType === 'market' ? livePrice : parseFloat(form.limitPrice);
                    if (!entry || !isFinite(entry)) return null;
                    if (form.tpslMode === 'price') {
                      const tpv = parseFloat(form.tpPrice), slv = parseFloat(form.slPrice);
                      if (!isFinite(tpv) && !isFinite(slv)) return null;
                      const pc = (v) => { const p = Math.abs(v - entry) / entry * 100; return p > 100 ? '>100%' : _ptFmtN(p, 2) + '%'; };
                      return (
                        <div style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.6rem', color: 'var(--qe-sub)', marginTop: 3, padding: '2px 4px', background: 'var(--qe-panel)' }}>
                          {isFinite(tpv) ? <>TP <span style={{ color: 'var(--qe-green)' }}>{pc(tpv)}</span></> : null}
                          {isFinite(tpv) && isFinite(slv) ? '  ·  ' : ''}
                          {isFinite(slv) ? <>SL <span style={{ color: 'var(--qe-red)' }}>{pc(slv)}</span></> : null}
                        </div>
                      );
                    }
                    const tpp = parseFloat(form.tpPct), slp = parseFloat(form.slPct);
                    if (!isFinite(tpp) && !isFinite(slp)) return null;
                    const dir = form.sideSel === 'short' ? -1 : 1;
                    return (
                      <div style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.6rem', color: 'var(--qe-sub)', marginTop: 3, padding: '2px 4px', background: 'var(--qe-panel)' }}>
                        {isFinite(tpp) ? <>TP <span style={{ color: 'var(--qe-green)' }}>{_ptFmtP(entry * (1 + dir * tpp / 100))}</span></> : null}
                        {isFinite(tpp) && isFinite(slp) ? '  ·  ' : ''}
                        {isFinite(slp) ? <>SL <span style={{ color: 'var(--qe-red)' }}>{_ptFmtP(entry * (1 - dir * slp / 100))}</span></> : null}
                      </div>
                    );
                  })()}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <div><Lbl>TP Amount %</Lbl><input className="qe-input" value={form.tpAmountPct} onChange={set('tpAmountPct')} /></div>
                  <div><Lbl>SL Amount %</Lbl><input className="qe-input" value={form.slAmountPct} onChange={set('slAmountPct')} /></div>
                </div>

                {/* TP ladder (P8.T4c — max 10 levels, Σ size_pct ≤ 100) */}
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Lbl>TP Ladder <span style={{ color: 'var(--qe-muted)' }}>(optional · TP1 feeds the single TP when blank)</span></Lbl>
                    <div className="qe-grow" />
                    {form.ladder.length < 10 && (
                      <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={() => setForm((f) => ({ ...f, ladder: [...f.ladder, { price: '', pct: '' }] }))}>+ level</button>
                    )}
                  </div>
                  {form.ladder.map((row, i) => (
                    <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 24px', gap: 4, marginTop: 3 }}>
                      <input className="qe-input" placeholder={`TP${i + 1} price`} value={row.price}
                        onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, ladder: f.ladder.map((r, j) => j === i ? { ...r, price: v } : r) })); }} />
                      <input className="qe-input" placeholder="size %" value={row.pct}
                        onChange={(e) => { const v = e.target.value; setForm((f) => ({ ...f, ladder: f.ladder.map((r, j) => j === i ? { ...r, pct: v } : r) })); }} />
                      <button className="qe-btn qe-btn-sm qe-btn-ghost" title="remove level"
                        onClick={() => setForm((f) => ({ ...f, ladder: f.ladder.filter((_, j) => j !== i) }))}>✕</button>
                    </div>
                  ))}
                  {(() => {
                    const sum = form.ladder.reduce((a, r) => a + (parseFloat(r.pct) || 0), 0);
                    if (!form.ladder.length) return null;
                    return (
                      <div className="qe-mono" style={{ fontSize: '0.56rem', marginTop: 2, color: sum > 100 ? 'var(--qe-red)' : 'var(--qe-muted)' }}>
                        Σ {_ptFmtN(sum, 1)}% {sum > 100 ? '— exceeds 100%' : 'of position'}
                      </div>
                    );
                  })()}
                </div>

                {/* Model picker (v2.7 5.2) + free-text */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <div>
                    <Lbl>Model (library)</Lbl>
                    <select className="qe-input qe-select" value={form.modelId}
                      onChange={(e) => {
                        const v = e.target.value;
                        setForm((f) => ({ ...f, modelId: v }));
                        applyPrefill(v);   // picker change applies the model's risk preset [P3 audit MED-2]
                      }}>
                      <option value="">— no model —</option>
                      {/* provisional option — visible while /api/models is pending
                          OR failed, so the intended id stays displayed [P3 audit L8] */}
                      {form.modelId && (!models || !models.some((m) => String(m.id) === String(form.modelId)))
                        ? <option value={form.modelId}>model #{form.modelId}</option> : null}
                      {(models || []).map((m) => <option key={m.id} value={String(m.id)}>{m.name}</option>)}
                    </select>
                  </div>
                  <div><Lbl>Model Name (free text)</Lbl><input className="qe-input" value={form.modelName} onChange={set('modelName')} placeholder="e.g. MA-Cross-V2" /></div>
                </div>
                <div><Lbl>Model Description</Lbl><input className="qe-input" value={form.modelDesc} onChange={set('modelDesc')} placeholder="optional notes" /></div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <div>
                    <Lbl>Link Window Override <span style={{ color: 'var(--qe-muted)' }}>(blank → account default)</span></Lbl>
                    <select className="qe-input qe-select" value={form.linkOverride} onChange={set('linkOverride')}>
                      <option value="">(use account default)</option>
                      <option value="1800">30 min</option>
                      <option value="3600">1 h</option>
                      <option value="14400">4 h</option>
                      <option value="21600">6 h</option>
                      <option value="43200">12 h</option>
                      <option value="86400">24 h</option>
                    </select>
                  </div>
                  <div>
                    <Lbl>Size Override <span style={{ color: 'var(--qe-muted)' }}>(contracts · blank → engine)</span></Lbl>
                    <input className="qe-input" value={form.sizeOverride} onChange={set('sizeOverride')} placeholder="engine-recommended" />
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 6px', background: 'var(--qe-panel)', border: '1px solid var(--qe-line)' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: '0.62rem', color: 'var(--qe-text)', fontFamily: 'var(--qe-mono)' }}>
                    <input type="checkbox" checked={form.applyMult} onChange={set('applyMult')} style={{ accentColor: 'var(--qe-cyan)' }} />
                    Apply regime multiplier
                  </label>
                  <div className="qe-grow" />
                  <span className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-sub)' }}>{regLabel}</span>
                  <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.62rem', color: 'var(--qe-cyan)', fontWeight: 700 }}>×{_ptFmtN(regMult, 1)} size</span>
                </div>

                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="qe-btn qe-btn-primary qe-btn-lg" style={{ flex: 1, justifyContent: 'center' }}
                    onClick={() => doCalculate(false)} disabled={busy}>
                    {busy ? <Spinner size="0.8rem" label="calculating" /> : 'Calculate'}
                  </button>
                  <button className="qe-btn qe-btn-lg" onClick={doClear} disabled={busy}>Clear</button>
                </div>
                {calcErr ? <div className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-red)' }}>{calcErr}</div> : null}
                <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', textAlign: 'center', fontFamily: 'var(--qe-mono)' }}>
                  enter advances fields · enter on SL submits · ctrl+enter anywhere
                </span>
              </div>
            </Pane>
          </GridItem>

          {/* SETUP SUMMARY pane */}
          <GridItem x={0} y={12} w={10} h={6} minW={6} minH={5}>
            <Pane title="Setup Summary" tag="CLICK TO COPY" style={{ height: '100%' }}
              foot={_ptCalcFoot(busy, calcErr, calc)}
              right={<PeriodSelector
                options={isCommodity ? [['notional', 'NOTIONAL'], ['contracts', 'CONTRACTS'], ['lot', 'LOT']] : [['notional', 'NOTIONAL'], ['contracts', 'CONTRACTS']]}
                value={effSizeUnit} onChange={setSizeUnit} />}>
              {!calc ? <EmptyState fill tone="neutral" glyph="◇" msg="No calc yet" hint="Run Calculate to populate the paste-ready setup." /> : (() => {
                const sideUp = (c.side || '').toUpperCase();
                const szVal  = effSizeUnit === 'notional' ? c.notional : c.size;
                const szDisp = effSizeUnit === 'notional' ? _ptFmtN(c.notional) : _ptFmtSz(c.size);
                const copyAll = () => {
                  const block = [
                    `Symbol: ${c.ticker}`, `Direction: ${sideUp}`,
                    `Size (${effSizeUnit}): ${szVal}`, `Entry: ${c.average}`,
                    `TP: ${c.tp_price || '—'}`, `SL: ${c.sl_price}`,
                  ].join('\n');
                  copyCell('ALL', block);
                };
                return (
                  <React.Fragment>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 6 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <PtCopyCell label="Symbol" value={c.ticker || ''} color="var(--qe-cyan)" copied={copied} onCopy={copyCell} />
                        <PtCopyCell label="Direction" value={sideUp} color={sideUp === 'SHORT' ? 'var(--qe-red)' : 'var(--qe-green)'} copied={copied} onCopy={copyCell} />
                        <PtCopyCell label={`Size (${effSizeUnit.toUpperCase()})`} value={szVal != null ? szVal : ''} display={szDisp} color="var(--qe-cyan)" copied={copied} onCopy={copyCell} />
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <PtCopyCell label="Entry" value={c.average != null ? c.average : ''} display={_ptFmtP(c.average)} color="var(--qe-text)" copied={copied} onCopy={copyCell} />
                        <PtCopyCell label="TP Price" value={c.tp_price || ''} display={c.tp_price ? _ptFmtP(c.tp_price) : '—'} color="var(--qe-green)" copied={copied} onCopy={copyCell} />
                        <PtCopyCell label="SL Price" value={c.sl_price != null ? c.sl_price : ''} display={_ptFmtP(c.sl_price)} color="var(--qe-red)" copied={copied} onCopy={copyCell} />
                      </div>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
                      <button className="qe-btn qe-btn-sm qe-btn-ghost" onClick={copyAll}>
                        {copied === 'ALL' ? '✓ copied' : '⧉ copy all'}
                      </button>
                    </div>
                  </React.Fragment>
                );
              })()}
            </Pane>
          </GridItem>

          {/* RECENT pane */}
          <GridItem x={10} y={0} w={7} h={5} minW={5} minH={4}>
            <Pane title="Recent Setups" count={recent.length} style={{ height: '100%' }}
              foot={{ tone: 'ok', msg: 'local' }}>
              {!recent.length ? <EmptyState fill tone="neutral" glyph="◇" msg="No recent setups" /> : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {recent.map((r, i) => (
                    <div key={i} onClick={() => recall(r)} title="Click to recall into the form" style={{
                      padding: '4px 7px', border: '1px solid var(--qe-line)', background: 'var(--qe-panel)', cursor: 'pointer',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.68rem', fontWeight: 700, color: 'var(--qe-cyan)' }}>{r.ticker}</span>
                        <Badge tone={r.side === 'LONG' ? 'ok' : 'err'}>{r.side}</Badge>
                        <span style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', textTransform: 'uppercase' }}>{r.orderType}</span>
                        <div className="qe-grow" />
                        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.54rem', color: 'var(--qe-muted)' }}><PtAge ts={r.ts} /></span>
                      </div>
                      <div style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.6rem', color: 'var(--qe-sub)' }}>
                        Entry {_ptFmtP(r.entry)} · TP <span style={{ color: 'var(--qe-green)' }}>{r.tp != null ? _ptFmtP(r.tp) : '—'}</span> · SL <span style={{ color: 'var(--qe-red)' }}>{_ptFmtP(r.sl)}</span>
                      </div>
                      <div style={{ fontSize: '0.54rem', marginTop: 1, fontFamily: 'var(--qe-mono)' }}>
                        <span style={{ color: 'var(--qe-cyan)' }}>{(r.regime || '').replace(/_/g, ' ').toUpperCase()}</span>
                        <span style={{ color: 'var(--qe-muted)' }}> ×{_ptFmtN(r.mult, 1)} size</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Pane>
          </GridItem>

          {/* REGIME + ATR pane */}
          <GridItem x={17} y={0} w={7} h={5} minW={5} minH={4}>
            <Pane title="Regime · ATR Volatility" hot style={{ height: '100%' }}
              foot={qeFootState({ loading: netRegime.ms == null && !netRegime.err, err: netRegime.err, hasData: regime != null, ms: netRegime.ms, retrying: true })}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div>
                  <Lbl>Current Regime</Lbl>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                    <span className="qe-mono" style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--qe-cyan)' }}>{String(regLabel).toUpperCase()}</span>
                    {(calc && calc.regime_stale) || (!calc && regime && regime.label == null) ? <Badge tone="warn">STALE</Badge> : null}
                    <span className="qe-mono" style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--qe-cyan)' }}>×{_ptFmtN(regMult, 1)} size</span>
                  </div>
                  <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)', marginTop: 2 }}>
                    {riskPct != null ? `${_ptFmtN(riskPct * 100, 2)}% → ${_ptFmtN(riskPct * 100 * regMult, 2)}% risk` : ''}
                    {calc && calc.regime_mode ? ` · mode ${calc.regime_mode}` : (regime && regime.mode ? ` · mode ${regime.mode}` : '')}
                  </div>
                </div>
                <div style={{ borderTop: '1px solid var(--qe-line)' }} />
                <div>
                  <Lbl>Volatility (atr_c)</Lbl>
                  {calc && calc.atr_c != null ? (
                    <React.Fragment>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                        <span className="qe-mono" style={{ fontSize: '1rem', fontWeight: 700 }}>{_ptFmtN(calc.atr_c, 2)}</span>
                        <Badge tone={calc.atr_category === 'normal' ? 'ok' : calc.atr_category === 'not_volatile' ? 'info' : 'warn'}>{String(calc.atr_category || '').toUpperCase()}</Badge>
                      </div>
                      <div style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)', marginTop: 2 }}>
                        ATR({'100'},4h) {_ptFmtP(calc.atr100)} · ATR(14,4h) {_ptFmtP(calc.atr14)}
                      </div>
                    </React.Fragment>
                  ) : <div style={{ fontSize: '0.6rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)', marginTop: 4 }}>run Calculate for the ticker's ATR read</div>}
                </div>
              </div>
            </Pane>
          </GridItem>

          {/* POSITION RESULT pane */}
          <GridItem x={10} y={5} w={14} h={7} minW={8} minH={7}>
            <Pane title="Position Result" style={{ height: '100%' }}
              right={calc ? <Badge tone={c.eligible ? 'ok' : 'err'}>{c.eligible ? '✓ ELIGIBLE' : '⛔ INELIGIBLE'}</Badge> : null}
              bodyStyle={{ padding: 0 }}
              foot={_ptCalcFoot(busy, calcErr, calc)}>
              {!calc ? <div style={{ padding: 10 }}><EmptyState fill tone="neutral" glyph="◇" msg="No calc yet" hint="Size a setup to see the position result." /></div> : (
                <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                  {!c.eligible && c.ineligible_reason ? (
                    <div className="qe-mono" style={{ fontSize: '0.62rem', color: 'var(--qe-red)', padding: '4px 8px', borderBottom: '1px solid var(--qe-line)' }}>⛔ {c.ineligible_reason}</div>
                  ) : null}
                  {(c.equity_stale || c.mark_price_stale) ? (
                    <div className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-amber)', padding: '3px 8px', borderBottom: '1px solid var(--qe-line)' }}>
                      {c.equity_stale ? '⚠ equity snapshot stale' : ''}{c.equity_stale && c.mark_price_stale ? ' · ' : ''}{c.mark_price_stale ? `⚠ mark price stale${c.mark_price_age != null ? ` (${Math.round(c.mark_price_age)}s)` : ''}` : ''}
                    </div>
                  ) : null}
                  <div style={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateColumns: '1fr 1px 1.05fr 1px 1fr', gap: 0 }}>
                    <div style={{ padding: '7px 12px 7px 8px', display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
                      <SecLbl rule>Position</SecLbl>
                      <div style={{ marginBottom: 4 }}>
                        <Lbl>Size (Contracts) {form.applyMult && c.regime_multiplier != null && c.regime_multiplier !== 1 ? <span style={{ color: 'var(--qe-muted)' }}>×{_ptFmtN(c.regime_multiplier, 1)} regime</span> : null} {c.size_overridden ? <Badge tone="warn">OVERRIDE</Badge> : null}</Lbl>
                        <div className="qe-mono" style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--qe-cyan)', lineHeight: 1.05 }}>{_ptFmtSz(c.size)}</div>
                        {c.size_raw != null && c.size_raw !== c.size ? (
                          <div style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>without regime: {_ptFmtSz(c.size_raw)}</div>
                        ) : null}
                        {!c.eligible && c.would_be_size ? (
                          <div style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>would-be: {_ptFmtSz(c.would_be_size)}</div>
                        ) : null}
                      </div>
                      <FieldList rows={[
                        { label: 'Notional', value: _ptFmtN(c.notional) + ' USDT' },
                        { label: 'Exposure ×', value: _ptFmtN(c.est_exposure, 2) + '×' },
                        { label: 'TP → Profit', value: _ptSign(c.tp_usdt), color: 'green' },
                        { label: 'SL → Loss', value: _ptSign(c.sl_usdt != null ? -Math.abs(c.sl_usdt) : null), color: 'red' },
                      ]} />
                    </div>
                    <div style={{ background: 'var(--qe-line)' }} />
                    <div style={{ padding: '7px 12px', display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
                      <SecLbl rule>Pricing</SecLbl>
                      <FieldList dense rows={[
                        { label: 'Ticker', value: c.ticker, color: 'cyan' },
                        { label: 'Side', value: (c.side || '').toUpperCase(), color: (c.side || '') === 'short' ? 'red' : 'green' },
                        { label: 'Order Type', value: (c.order_type || '').toUpperCase() },
                        { label: 'Avg Entry', value: _ptFmtP(c.average) },
                        { label: 'Risk USDT', value: _ptFmtN(c.risk_usdt) },
                        { label: 'Base Size', value: _ptFmtN(c.base_size), hint: 'USDT' },
                        { label: 'Est. Fill', value: _ptFmtP(c.est_fill_price) },
                        { label: '1% Depth / Mid', value: _ptFmtN(c.one_percent_depth) + ' USDT' },
                        { label: 'Best Bid / Ask', value: <><span style={{ color: 'var(--qe-green)' }}>{_ptFmtP(c.best_bid)}</span><span style={{ color: 'var(--qe-muted)' }}> / </span><span style={{ color: 'var(--qe-red)' }}>{_ptFmtP(c.best_ask)}</span></> },
                      ]} />
                    </div>
                    <div style={{ background: 'var(--qe-line)' }} />
                    <div style={{ padding: '7px 8px 7px 12px', display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
                      <SecLbl rule>After Costs</SecLbl>
                      <FieldList dense rows={[
                        { label: 'Est. Slippage', value: c.est_slippage != null ? _ptFmtN(c.est_slippage * 100, 4) + '%' : '—', color: 'amber' },
                        { label: 'Slip USDT', value: _ptFmtN(c.est_slippage_usdt) },
                        { label: 'Net Profit', value: _ptSign(c.est_profit), color: 'green' },
                        { label: 'Net Loss', value: c.est_loss != null ? _ptSign(-Math.abs(c.est_loss)) : '—', color: 'red' },
                        { label: 'Est. R : R', value: _ptFmtN(c.est_r, 2), color: (c.est_r || 0) >= 1 ? 'green' : 'red' },
                        { label: 'Portfolio Exp.', value: _ptFmtN(c.est_exposure, 2) + '×' },
                        { label: `RT Fee (${form.orderType === 'limit' ? 'Maker' : 'Taker'})`, value: c.fee_rate != null ? _ptFmtN(c.fee_rate * 2 * 100, 3) + '%' : '—', color: 'sub' },
                      ]} />
                    </div>
                  </div>
                </div>
              )}
            </Pane>
          </GridItem>

          {/* CORRELATED EXPOSURE pane */}
          <GridItem x={10} y={12} w={7} h={6} minW={5} minH={4}>
            <Pane title="Correlated Sector Exposure" style={{ height: '100%' }}
              foot={_ptCalcFoot(busy, calcErr, calc)}>
              {!calc || !c.correlated_exposure ? <EmptyState fill tone="neutral" glyph="◇" msg="No calc yet" /> : (
                <React.Fragment>
                  {c.exceeds_corr_limit ? (
                    <div className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-red)', marginBottom: 4 }}>⛔ correlated-exposure cap exceeded</div>
                  ) : null}
                  <FieldList rows={[
                    ...Object.entries(c.correlated_exposure).map(([sector, v]) => ({
                      label: sector, value: _ptSign(v), color: v > 0 ? 'green' : v < 0 ? 'red' : undefined,
                    })),
                    { label: `New (${c.ticker})`, value: _ptSign(c.new_sector_exposure) + ' USDT', emphasis: true },
                  ]} />
                </React.Fragment>
              )}
            </Pane>
          </GridItem>

          {/* LIVE ORDERBOOK pane */}
          <GridItem x={17} y={12} w={7} h={6} minW={5} minH={4}>
            <Pane title="Live Orderbook" tag="2s" style={{ height: '100%' }}
              right={ob && (ob.bids || []).length ? <StatusDot tone="ok" label="LIVE" /> : <StatusDot tone="off" label="—" />}
              foot={!tickerNorm ? { tone: 'sub', msg: 'enter a ticker' }
                : qeFootState({ loading: netOb.ms == null && !netOb.err, err: netOb.err, hasData: ob != null, ms: netOb.ms, retrying: true })}>
              {!ob || (!(ob.bids || []).length && !(ob.asks || []).length) ? (
                <EmptyState fill tone="neutral" glyph="〇" msg={tickerNorm ? 'No depth yet' : 'Enter a ticker'} />
              ) : (
                (() => {  /* depth-shading normalized to the visible book's max qty */
                  const maxQ = Math.max(...[...(ob.bids || []), ...(ob.asks || [])].map(([, q]) => parseFloat(q) || 0), 1e-9);
                  const rowFor = (color) => ([p, s], i) => (
                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--qe-mono)', fontSize: '0.62rem', padding: '1px 0', position: 'relative' }}>
                      <span style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: `${Math.min(100, (parseFloat(s) || 0) / maxQ * 100) * 0.5}%`, background: `color-mix(in srgb, ${color} 8%, transparent)` }} />
                      <span style={{ color, position: 'relative' }}>{_ptFmtP(parseFloat(p))}</span>
                      <span style={{ color: 'var(--qe-sub)', position: 'relative' }}>{s}</span>
                    </div>
                  );
                  return (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                      <div>
                        <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'var(--qe-green)', letterSpacing: '0.1em', marginBottom: 3 }}>BIDS</div>
                        {(ob.bids || []).map(rowFor('var(--qe-green)'))}
                      </div>
                      <div>
                        <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'var(--qe-red)', letterSpacing: '0.1em', marginBottom: 3 }}>ASKS</div>
                        {(ob.asks || []).map(rowFor('var(--qe-red)'))}
                      </div>
                    </div>
                  );
                })()
              )}
            </Pane>
          </GridItem>

        </GridWorkspace>

        {/* §1.3 scrim + reason card (sibling — NOT blurred) */}
        {halted && (
          <div style={{
            position: 'absolute', inset: 0, zIndex: 40,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(0,0,0,0.35)',
          }}>
            <div style={{ background: 'var(--qe-card)', border: '1px solid var(--qe-red)', borderLeft: '4px solid var(--qe-red)', padding: '14px 18px', maxWidth: 460 }}>
              <div className="qe-mono" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--qe-red)', letterSpacing: '0.06em' }}>CALCULATOR BLOCKED</div>
              <div className="qe-mono" style={{ fontSize: '0.64rem', color: 'var(--qe-text)', marginTop: 6, lineHeight: 1.6 }}>
                {st.halt_reason || 'DD limit breached · enforcement mode ENFORCED'}
              </div>
              <div className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-sub)', marginTop: 6, lineHeight: 1.6 }}>
                New sizing calcs are gated by the DD hard stop. Open positions are NOT affected.
                Recovery clears the gate automatically; a manual override lives on the Dashboard.
              </div>
            </div>
          </div>
        )}
      </div>
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { PreTradePage });
