/* v3.0 — Config page (P2). Ported from the Meridian reference (pages.jsx
   ConfigPage) and WIRED to real engine data:
     · Accounts     ← GET /accounts + GET /api/config/account/{id}
                      writes: POST /accounts/{id}/update (form-encoded creds +
                      sizing params) · POST /accounts/{id}/activate ·
                      POST /accounts/{id}/test
     · Connections  ← GET /api/connections; writes reuse the existing HTML
                      endpoints (POST /connections · POST /connections/{p}/test
                      · DELETE /connections/{p}) — responses are HTML snippets,
                      stripped to text for the status line.
     · Presets      ← GET /api/config/presets; Apply = POST
                      /api/config/apply-preset (FULL: DD posture + sizing —
                      operator-ratified), confirm-gated, active account only.
     · System       ← GET /api/system (G-O8; read-only facts).
   The inline mock literals (accounts/conns arrays, defaultValue inputs) are
   stripped. TWO DISJOINT RISK STORES (HANDOFF ★ P2): account_params sizing
   knobs are EDITABLE here (validated /update path); account_settings DD/weekly
   posture is DISPLAY-ONLY — written only by preset Apply; the enforcement-mode
   flip is DEFERRED to a later phase (needs the name-confirm safety gate).
   Add/Delete Account are NOT wired in P2 (spec scope: safe writes only) —
   rendered disabled; the Jinja /config page remains the management surface.
   Micro-deviations vs the reference ConfigPage (all deliberate): paper-env
   badge tone `blue` (matches the Primitives PAPER badge, not the ref's warn);
   Exchange is free text (server-side adapter-registry whitelist; no
   supported-exchanges endpoint exists to feed a select); the Connections
   CATEGORY column is dropped (no category field in the backend catalog) and a
   provider-id column added; connection save button says "Save" (POST
   /connections does not actually test); Presets pane h=16 vs the ref's 14
   (cards also show the sizing envelope Apply writes). */

/* ── fetch helpers ───────────────────────────────────────────────────────── */
/* This page's reads are ONE-SHOTS (mount / selection change), so they cannot
   go stale behind a green foot the way a poll can — their warm-hang symptom is
   a spinner that never resolves and a Test/Reload button that stays busy
   forever. Delegating to _ptJson gives them the same deadline discipline as
   every other read; the error contract (status / corrupt / now timeoutMs) is
   identical, which is why this wrapper survives as a one-liner rather than
   being inlined at 8 call sites (warm-hang sweep, 2026-08-01). */
const _cfgJson = (url) => _ptJson(url, QE_READ_DEADLINE_MS);

/* Strip an HTML-snippet response (the Jinja-era endpoints answer with styled
   <span>s) to plain text via an inert DOMParser document. */
const _cfgStrip = (html) => {
  try {
    return (new DOMParser().parseFromString(html || '', 'text/html').body.textContent || '').trim();
  } catch (e) { return (html || '').trim(); }
};

/* Compact a raw FastAPI 422/error JSON body into a readable one-liner (else
   the msg line would show the serialized {"detail":[{...}]} blob verbatim). */
const _cfgFriendly = (raw) => {
  const t = (raw || '').trim();
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
    } catch (e) { /* not JSON after all — fall through */ }
  }
  return t;
};

const _cfgPostForm = async (url, fields, method = 'POST', opts = {}) => {
  const body = new URLSearchParams();
  Object.entries(fields || {}).forEach(([k, v]) => { if (v != null) body.append(k, v); });
  const r = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  const raw = await r.text();
  // `json`: the door answers JSON (POST /accounts), so return the parsed body
  // — HTML-stripping it would hand the caller a JSON string to read by eye.
  if (opts.json) {
    let data = {};
    try { data = JSON.parse(raw) || {}; } catch (e) { /* non-JSON error page */ }
    return { ok: r.ok, data, text: data.error || _cfgFriendly(_cfgStrip(raw)) };
  }
  return { ok: r.ok, text: _cfgFriendly(_cfgStrip(raw)) };
};

const _cfgPostJson = async (url, payload) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: payload != null ? { 'Content-Type': 'application/json' } : {},
    body: payload != null ? JSON.stringify(payload) : undefined,
  });
  let data = null;
  try { data = await r.json(); } catch (e) { /* non-JSON error body */ }
  return { ok: r.ok, data };
};

/* fraction → percent display ("0.06" → "6%", "0.095" → "9.5%") */
const _cfgPct = (v) => (v == null || isNaN(v)) ? '—' : ((+v * 100).toFixed(1).replace(/\.0$/, '') + '%');

const _cfgUptime = (s) => {
  if (s == null || isNaN(s)) return '—';
  s = Math.floor(+s);
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return (d ? d + 'd ' : '') + h + 'h ' + String(m).padStart(2, '0') + 'm';
};

/* ── shared bits ─────────────────────────────────────────────────────────── */
const CfgMsgLine = ({ msg }) => msg ? (
  <div className="qe-mono" style={{
    fontSize: '0.62rem', marginTop: 6,
    color: msg.tone === 'ok' ? 'var(--qe-green)' : msg.tone === 'err' ? 'var(--qe-red)' : 'var(--qe-sub)',
  }}>{msg.text}</div>
) : null;

/* config-1 — the warn/hard-stop ratios must be posted PAIRWISE.
 *
 * core.state.validate_params gates its warn<limit check on BOTH keys being
 * present in the dict it receives, and routes_accounts hands it the SUPPLIED
 * subset — not the merged result. So sending only one member of a pair skips
 * the cross-check entirely and the merged store can end up inverted
 * (warn >= limit), with the endpoint still answering 200 "Saved.". An inversion
 * is not cosmetic: the weekly pair is consumed unconditionally by
 * core/data_cache and the limit branch is evaluated first, so it deletes the
 * whole "warning" tier.
 *
 * Blank still means "leave unchanged" — but if EITHER member of a pair is
 * filled we send BOTH, backfilling the blank one from the stored value so the
 * validator always sees a complete pair. If both are blank the pair is omitted
 * entirely and nothing about it changes.
 */
const CFG_RATIO_PAIRS = [
  ['max_dd_warning_pct', 'max_dd_limit_pct'],
  ['weekly_loss_warning_pct', 'weekly_loss_limit_pct'],
];

const cfgRatioPairs = (form, stored) => {
  const out = {};
  for (const [warnKey, limitKey] of CFG_RATIO_PAIRS) {
    const w = (form[warnKey] || '').trim();
    const l = (form[limitKey] || '').trim();
    if (!w && !l) continue;                       // untouched pair — omit both
    const fallback = (k) => (stored && stored[k] != null ? String(stored[k]) : null);
    out[warnKey]  = w || fallback(warnKey);
    out[limitKey] = l || fallback(limitKey);
  }
  return out;
};

/* Client-side pre-check so an inverted pair is rejected before it reaches the
 * endpoint's partial-write path (params are written field-by-field BEFORE
 * validate_params runs — a pre-existing behaviour shared with the Jinja form,
 * which this keeps out of reach rather than widening). Returns an error string
 * or null. */
const cfgRatioError = (form) => {
  for (const [warnKey, limitKey] of CFG_RATIO_PAIRS) {
    const w = parseFloat(form[warnKey]), l = parseFloat(form[limitKey]);
    if (!isNaN(w) && !isNaN(l) && w >= l) {
      return `${warnKey} (${w}) must be BELOW ${limitKey} (${l})`;
    }
    for (const [k, v] of [[warnKey, w], [limitKey, l]]) {
      if (!isNaN(v) && (v < 0.5 || v > 1.0)) return `${k} (${v}) is outside 0.50–1.00`;
    }
  }
  return null;
};

/* ── Accounts tab ────────────────────────────────────────────────────────── */
const CfgAccountForm = ({ account, detail, onReload }) => {
  const p = detail.params || {};
  const s = detail.settings || {};
  const [form, setForm] = React.useState(() => ({
    exchange:          account.exchange || '',
    market_type:       account.market_type || 'future',
    environment:       account.environment || 'live',
    api_key: '', api_secret: '',
    broker_account_id: account.broker_account_id || '',
    individual_risk_per_trade: p.individual_risk_per_trade != null ? String(p.individual_risk_per_trade) : '',
    max_w_loss_percent:        p.max_w_loss_percent        != null ? String(p.max_w_loss_percent)        : '',
    max_dd_percent:            p.max_dd_percent            != null ? String(p.max_dd_percent)            : '',
    max_exposure:              p.max_exposure              != null ? String(p.max_exposure)              : '',
    max_position_count:        p.max_position_count        != null ? String(p.max_position_count)        : '',
    max_correlated_exposure:   p.max_correlated_exposure   != null ? String(p.max_correlated_exposure)   : '',
    /* config-1 (2026-07-25 Meridian audit): the four warn/hard-stop RATIOS. They
       live in account_params (NOT the account_settings block rendered read-only
       below), are bounded in core/state.PARAM_BOUNDS, pair-validated warn<limit
       by validate_params, live-consumed by core/data_cache for pf.dd_state and
       pf.weekly_pnl_state — and POST /accounts/{id}/update already accepted them
       as Form fields. The form simply never sent them, so they were editable
       nowhere in v3 (the legacy Jinja account form still exposes all four). */
    weekly_loss_warning_pct:   p.weekly_loss_warning_pct   != null ? String(p.weekly_loss_warning_pct)   : '',
    weekly_loss_limit_pct:     p.weekly_loss_limit_pct     != null ? String(p.weekly_loss_limit_pct)     : '',
    max_dd_warning_pct:        p.max_dd_warning_pct        != null ? String(p.max_dd_warning_pct)        : '',
    max_dd_limit_pct:          p.max_dd_limit_pct          != null ? String(p.max_dd_limit_pct)          : '',
    timezone:                  s.timezone || '',   // config-3 (account_settings, not params)
  }));
  const [busy, setBusy] = React.useState(null);   // 'save' | 'test' | 'activate'
  const [msg, setMsg]   = React.useState(null);

  const set = (k) => (e) => { const v = e.target.value; setForm((f) => ({ ...f, [k]: v })); };

  const doSave = async () => {
    // config-1: refuse an inverted / out-of-range ratio pair locally. The
    // endpoint writes params field-by-field BEFORE validating, so a rejected
    // save can still have moved other fields — keeping this unreachable is
    // cheaper than widening that window.
    const ratioErr = cfgRatioError(form);
    if (ratioErr) { setMsg({ text: ratioErr, tone: 'err' }); return; }
    setBusy('save'); setMsg(null);
    try {
      const r = await _cfgPostForm(`/accounts/${account.id}/update`, {
        exchange:          form.exchange.trim() || null,
        market_type:       form.market_type,
        environment:       form.environment,
        broker_account_id: form.broker_account_id,
        // blank = keep current (endpoint ignores falsy credentials); trimmed so
        // an accidental whitespace-only paste can't overwrite a stored key
        api_key:    form.api_key.trim() || null,
        api_secret: form.api_secret.trim() || null,
        individual_risk_per_trade: form.individual_risk_per_trade.trim() || null,
        max_w_loss_percent:        form.max_w_loss_percent.trim()        || null,
        max_dd_percent:            form.max_dd_percent.trim()            || null,
        max_exposure:              form.max_exposure.trim()              || null,
        max_position_count:        form.max_position_count.trim()        || null,
        max_correlated_exposure:   form.max_correlated_exposure.trim()   || null,
        // config-1: warn/hard-stop ratios, sent PAIRWISE — see _cfgPair.
        ...cfgRatioPairs(form, p),
        // config-3: blank keeps the stored value; the endpoint ZoneInfo-validates
        // and rejects an unknown zone rather than silently storing it.
        timezone: form.timezone.trim() || null,
      });
      const ok = r.ok && /saved/i.test(r.text);
      setMsg({ text: r.text || (r.ok ? 'Saved.' : 'save failed'), tone: ok ? 'ok' : 'err' });
      // reload accounts too — env/exchange/market edits must refresh the list
      // row + header badges, not just the detail stores [P2 audit MED-2]
      if (ok) { setForm((f) => ({ ...f, api_key: '', api_secret: '' })); onReload(true); }
    } catch (e) { setMsg({ text: 'save failed — engine unreachable?', tone: 'err' }); }
    setBusy(null);
  };

  const doTest = async () => {
    setBusy('test'); setMsg(null);
    try {
      const r = await _cfgPostJson(`/accounts/${account.id}/test`);
      const d = r.data || {};
      setMsg(d.ok
        ? { text: `connection OK · ${d.latency_ms} ms` + (d.fees_updated ? ` · fees ${d.maker_fee}/${d.taker_fee}` : ''), tone: 'ok' }
        : { text: d.error || 'connection test failed', tone: 'err' });
    } catch (e) { setMsg({ text: 'test failed — engine unreachable?', tone: 'err' }); }
    setBusy(null);
  };

  const doActivate = async () => {
    if (!window.confirm('Activate this account? This will restart the exchange connection (WS teardown + reinit).')) return;
    setBusy('activate'); setMsg(null);
    try {
      const r = await _cfgPostJson(`/accounts/${account.id}/activate`);
      const d = r.data || {};
      if (d.status === 'ok') {
        setMsg({ text: d.message === 'already active' ? 'already active' : `activated · ${d.name || account.name}`, tone: 'ok' });
        onReload(true);
      } else {
        setMsg({ text: d.error || 'activate failed', tone: 'err' });
      }
    } catch (e) { setMsg({ text: 'activate failed — engine unreachable?', tone: 'err' }); }
    setBusy(null);
  };

  const envTone = account.environment === 'live' ? 'err' : account.environment === 'testnet' ? 'info' : 'blue';

  return (
    <React.Fragment>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.9rem', fontWeight: 700 }}>{account.name}</span>
        {account.is_active ? <Badge tone="ok">Active</Badge> : null}
        <Badge tone={envTone}>{(account.environment || 'live').toUpperCase()}</Badge>
        <div className="qe-grow" />
        <button className="qe-btn qe-btn-sm" onClick={doTest} disabled={!!busy}>
          {busy === 'test' ? <Spinner size="0.7rem" label="testing" /> : 'Test Connection'}
        </button>
      </div>

      <SecLbl rule>Credentials</SecLbl>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 10 }}>
        <div><Lbl>Exchange</Lbl><input className="qe-input" value={form.exchange} onChange={set('exchange')} placeholder="binance" /></div>
        <div><Lbl>Market Type</Lbl>
          <select className="qe-input qe-select" value={form.market_type} onChange={set('market_type')}>
            <option value="future">USD-M Futures</option>
            <option value="spot">Spot</option>
          </select>
        </div>
        <div><Lbl>Environment</Lbl>
          <select className="qe-input qe-select" value={form.environment} onChange={set('environment')}>
            <option value="live">Live</option>
            <option value="paper">Paper</option>
            <option value="testnet">Testnet</option>
          </select>
        </div>
        <div><Lbl>API Key</Lbl><input className="qe-input" type="password" value={form.api_key} onChange={set('api_key')} placeholder="Leave blank to keep current" /></div>
        <div><Lbl>API Secret</Lbl><input className="qe-input" type="password" value={form.api_secret} onChange={set('api_secret')} placeholder="Leave blank to keep current" /></div>
        <div><Lbl>Broker Account ID</Lbl><input className="qe-input" value={form.broker_account_id} onChange={set('broker_account_id')} /></div>
        <div><Lbl>Timezone (IANA)</Lbl><input className="qe-input" value={form.timezone} onChange={set('timezone')} placeholder="Asia/Bangkok"
          title="Every timestamp on the page renders against this. IANA name, e.g. UTC or Asia/Bangkok — the engine validates it." /></div>
      </div>

      <SecLbl rule>Risk Parameters · sizing (account_params)</SecLbl>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 10 }}>
        <div><Lbl>Risk / Trade (fraction)</Lbl><input className="qe-input" value={form.individual_risk_per_trade} onChange={set('individual_risk_per_trade')} placeholder="0.01" /></div>
        <div><Lbl>Max Weekly Loss (fraction)</Lbl><input className="qe-input" value={form.max_w_loss_percent} onChange={set('max_w_loss_percent')} placeholder="0.05" /></div>
        <div><Lbl>Max Drawdown (fraction)</Lbl><input className="qe-input" value={form.max_dd_percent} onChange={set('max_dd_percent')} placeholder="0.10" /></div>
        <div><Lbl>Max Exposure ×</Lbl><input className="qe-input" value={form.max_exposure} onChange={set('max_exposure')} placeholder="5.0" /></div>
        <div><Lbl>Max Positions</Lbl><input className="qe-input" value={form.max_position_count} onChange={set('max_position_count')} placeholder="10" /></div>
        <div><Lbl>Max Corr. Exposure (fraction)</Lbl><input className="qe-input" value={form.max_correlated_exposure} onChange={set('max_correlated_exposure')} placeholder="0.50" /></div>
      </div>

      {/* config-1: the warn / hard-stop ratios. Expressed as a FRACTION OF the
          budget above them (0.80 = warn once 80% of the Max-DD budget is used),
          which is exactly how core/migrations/convert_thresholds derives the
          absolute account_settings thresholds shown read-only below. */}
      <SecLbl rule right={<span style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>fraction of the budget above · warn &lt; limit</span>}>
        Warn &amp; Hard-stop ratios (account_params)
      </SecLbl>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, marginBottom: 4 }}>
        <div><Lbl>DD Warn × Max DD</Lbl><input className="qe-input" value={form.max_dd_warning_pct} onChange={set('max_dd_warning_pct')} placeholder="0.80" /></div>
        <div><Lbl>DD Hard-stop × Max DD</Lbl><input className="qe-input" value={form.max_dd_limit_pct} onChange={set('max_dd_limit_pct')} placeholder="0.95" /></div>
        <div><Lbl>Weekly Warn × Max W. Loss</Lbl><input className="qe-input" value={form.weekly_loss_warning_pct} onChange={set('weekly_loss_warning_pct')} placeholder="0.80" /></div>
        <div><Lbl>Weekly Hard-stop × Max W. Loss</Lbl><input className="qe-input" value={form.weekly_loss_limit_pct} onChange={set('weekly_loss_limit_pct')} placeholder="0.95" /></div>
      </div>
      <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', margin: '0 0 10px', lineHeight: 1.5 }}>
        Range 0.50–0.99 (hard-stop to 1.00); warn must stay below its hard-stop or the save is rejected.
        Leave a field blank to keep its stored value — edit either half of a pair and both are sent.<br />
        <span style={{ color: 'var(--qe-sub)' }}>WEEKLY</span> drives the live weekly state machine.
        <span style={{ color: 'var(--qe-sub)' }}> DD</span> is a FALLBACK only — the rolling-DD path uses the
        absolute thresholds below, and these two are read solely if that path errors.
      </div>

      <SecLbl rule right={<span style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>READ-ONLY · set via Presets tab</span>}>
        Enforcement &amp; Recovery · DD posture (account_settings)
      </SecLbl>
      <FieldList cols={2} rows={[
        { label: 'Strategy preset', value: (s.strategy_preset || 'custom').toUpperCase(), color: 'cyan' },
        { label: 'DD window',       value: s.dd_rolling_window_days != null ? s.dd_rolling_window_days + 'd' : '—' },
        { label: 'DD warn',         value: _cfgPct(s.dd_warning_threshold), color: 'amber' },
        { label: 'DD limit',        value: _cfgPct(s.dd_limit_threshold), color: 'red' },
        { label: 'DD recovery',     value: _cfgPct(s.dd_recovery_threshold), color: 'green' },
        { label: 'DD enforcement',  value: (s.dd_enforcement_mode || '—').toUpperCase() },
        { label: 'Weekly warn',     value: _cfgPct(s.weekly_pnl_warning_threshold), color: 'amber' },
        { label: 'Weekly limit',    value: _cfgPct(s.weekly_pnl_limit_threshold), color: 'red' },
        { label: 'Weekly enforcement', value: (s.weekly_pnl_enforcement_mode || '—').toUpperCase() },
      ]} />
      <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', margin: '6px 0 10px', lineHeight: 1.5 }}>
        The rolling-DD gate reads THIS store — ABSOLUTE thresholds, written by preset Apply (Presets tab).
        Disjoint from the ratios above, which live in account_params. Note a preset rewrites these
        thresholds and the six sizing knobs, but NOT the four ratios — those stay as you set them.
        The advisory→enforced flip ships with its name-confirm safety gate in a later phase.
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 8, alignItems: 'center' }}>
        <button className="qe-btn qe-btn-primary" onClick={doSave} disabled={!!busy}>
          {busy === 'save' ? <Spinner size="0.7rem" label="saving" /> : 'Save'}
        </button>
        <button className="qe-btn" onClick={doActivate} disabled={!!busy || !!account.is_active}
          title={account.is_active ? 'Already the active account' : 'Switch the engine to this account'}>
          {busy === 'activate' ? <Spinner size="0.7rem" label="switching" /> : 'Activate'}
        </button>
        <div className="qe-grow" />
        <button className="qe-btn qe-btn-danger" disabled
          title="Not wired in P2 — delete via the current /config page">Delete Account</button>
      </div>
      <CfgMsgLine msg={msg} />
    </React.Fragment>
  );
};

/* Add Account (wired 2026-07-30 — operator report "add account in config not
   working"). This button shipped DISABLED at P2 with the title "add accounts
   via the current /config page", so on the React app it genuinely did nothing;
   the workaround pointed at a Jinja page that is now the last of its kind.

   POSTs form-encoded to /accounts, which answers JSON. `environment` and
   `params_source` used to be accepted only by the HTML-returning
   /accounts/add-and-reload twin — they are now on the JSON door too, which is
   what unblocked this. Credentials are typed by the operator and posted
   straight to the engine; nothing is logged or echoed back. */
const CfgAddAccountDialog = ({ accounts, onClose, onCreated }) => {
  const [f, setF] = React.useState({
    name: '', exchange: 'binance', market_type: 'future',
    environment: 'live', params_source: 'defaults',
    api_key: '', api_secret: '',
  });
  const [cat, setCat] = React.useState(null);     // /api/config/exchanges
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState(null);
  const set = (k) => (e) => setF((p) => ({ ...p, [k]: e.target.value }));

  React.useEffect(() => {
    let alive = true;
    _cfgJson('/api/config/exchanges')
      .then((d) => { if (alive) setCat(d); })
      .catch(() => { if (alive) setCat({ exchanges: [], market_types: [] }); });
    return () => { alive = false; };
  }, []);

  const incomplete = !f.name.trim() || !f.api_key.trim() || !f.api_secret.trim();
  const submit = async () => {
    if (busy || incomplete) return;
    setBusy(true); setErr(null);
    try {
      const r = await _cfgPostForm('/accounts', f, 'POST', { json: true });
      if (r.ok && r.data.status === 'ok') { onCreated(r.data.id); onClose(); return; }
      setErr(r.text || 'could not create the account');
    } catch (e) { setErr('create failed — engine unreachable?'); }
    setBusy(false);
  };

  const Field = ({ label, children }) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span style={{ fontFamily: 'var(--qe-ui)', fontSize: '0.52rem', fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase', color: 'var(--qe-sub)' }}>{label}</span>
      {children}
    </label>
  );

  return (
    <ModelDialog title="Add Account" width={480} onClose={() => { if (!busy) onClose(); }}
      footer={<React.Fragment>
        <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={busy || incomplete}
          title={incomplete ? 'name, API key and API secret are required' : 'Create the account'}
          onClick={submit}>{busy ? <Spinner size="0.62rem" /> : 'Add account'}</button>
      </React.Fragment>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}
        onKeyDown={(e) => { if (e.key === 'Enter' && !incomplete) { e.preventDefault(); submit(); } }}>
        <Field label="Account name">
          <input className="qe-input" autoFocus value={f.name} placeholder="e.g. Binance Main"
            onChange={set('name')} style={{ height: 24, boxSizing: 'border-box' }} />
        </Field>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <Field label="Exchange">
            <select className="qe-input qe-select" value={f.exchange} onChange={set('exchange')}
              style={{ height: 24 }} disabled={!cat}>
              {(cat && cat.exchanges || []).map((x) => (
                <option key={x.value} value={x.value}>{x.label}</option>
              ))}
              {/* pre-catalog placeholder so the control is never an empty box */}
              {!cat ? <option value="binance">loading…</option> : null}
            </select>
          </Field>
          <Field label="Market type">
            <select className="qe-input qe-select" value={f.market_type} onChange={set('market_type')}
              style={{ height: 24 }} disabled={!cat}>
              {(cat && cat.market_types || ['future']).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </Field>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <Field label="Environment">
            <select className="qe-input qe-select" value={f.environment} onChange={set('environment')} style={{ height: 24 }}>
              <option value="live">Live</option>
              <option value="paper">Paper</option>
              <option value="testnet">Testnet</option>
            </select>
          </Field>
          <Field label="Initial parameters">
            <select className="qe-input qe-select" value={f.params_source} onChange={set('params_source')} style={{ height: 24 }}>
              <option value="defaults">Use defaults</option>
              {(accounts || []).map((a) => (
                <option key={a.id} value={'copy_' + a.id}>Copy from: {a.name}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="API key">
          <input className="qe-input" value={f.api_key} onChange={set('api_key')}
            autoComplete="off" spellCheck={false} placeholder="API key"
            style={{ height: 24, boxSizing: 'border-box', fontFamily: 'var(--qe-mono)' }} />
        </Field>
        <Field label="API secret">
          <input className="qe-input" type="password" value={f.api_secret} onChange={set('api_secret')}
            autoComplete="new-password" placeholder="API secret"
            style={{ height: 24, boxSizing: 'border-box', fontFamily: 'var(--qe-mono)' }} />
        </Field>
        <div className="qe-mono" style={{ fontSize: '0.54rem', color: 'var(--qe-muted)', lineHeight: 1.5 }}>
          Credentials are encrypted at rest by the engine. The new account is
          NOT activated — use Activate on its card once you have tested the
          connection.
        </div>
        {err ? <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-red)' }}>{err}</span> : null}
      </div>
    </ModelDialog>
  );
};

const CfgAccountsTab = () => {
  const [adding, setAdding] = React.useState(false);
  const [accounts, setAccounts] = React.useState(null);  // null = loading
  const [acct, setAcct]         = React.useState(null);  // selected id
  const [detail, setDetail]     = React.useState(null);  // {params, settings} for acct
  const acctRef = React.useRef(null);                    // live selection, for async guards

  const [netA, setNetA] = React.useState({});   // /accounts pipe (qeFootState)
  const [netD, setNetD] = React.useState({});   // /api/config/account/{id} pipe
  const loadAccounts = React.useCallback(async (keepSelection) => {
    const t0 = performance.now();
    try {
      const rows = await _cfgJson('/accounts');
      setNetA({ err: null, ms: performance.now() - t0 });
      setAccounts(rows);
      setAcct((cur) => {
        if (keepSelection && cur != null && rows.some((a) => a.id === cur)) return cur;
        const act = rows.find((a) => a.is_active) || rows[0];
        return act ? act.id : null;
      });
    } catch (err) { setAccounts([]); setNetA((n) => ({ ...n, err })); }
  }, []);
  React.useEffect(() => { loadAccounts(false); }, [loadAccounts]);

  React.useEffect(() => {
    acctRef.current = acct;
    if (acct == null) return;
    setDetail(null);
    let alive = true;
    const t0 = performance.now();
    _cfgJson('/api/config/account/' + acct)
      .then((d) => { if (alive) { setDetail(d); setNetD({ err: null, ms: performance.now() - t0 }); } })
      // _placeholder: the empty-defaults form is NOT "last data" — the foot
      // must report tier-3, not keep-last-good [foot-audit MED-3]
      .catch((err) => { if (alive) { setDetail({ params: {}, settings: {}, _placeholder: true }); setNetD((n) => ({ ...n, err })); } });
    return () => { alive = false; };
  }, [acct]);

  // reload after a write: detail always; accounts list too after activate or an
  // env/exchange edit. GUARDED like the effect above: a refetch issued for
  // account A must not seed the form after the operator switched to B — the
  // endpoint echoes account_id, so drop any response that no longer matches the
  // live selection [P2 audit MED-1: cross-account form-seed race].
  const reload = (accountsToo) => {
    if (accountsToo) loadAccounts(true);
    const target = acct;
    if (target != null) {
      _cfgJson('/api/config/account/' + target)
        .then((d) => { if (acctRef.current === target && d.account_id === target) setDetail(d); })
        .catch(() => {});
    }
  };

  const sel = (accounts || []).find((a) => a.id === acct);

  return (
    <React.Fragment>
    <GridWorkspace>
      <GridItem x={0} y={0} w={6} h={20} minW={4} minH={6}>
        <Pane title="Accounts" count={accounts ? accounts.length : null} style={{ height: '100%' }}
          onRefresh={() => loadAccounts(true)}
          foot={qeFootState({ loading: netA.ms == null && !netA.err, err: netA.err, hasData: accounts != null && accounts.length > 0, ms: netA.ms })}>
          {accounts == null ? <Spinner label="loading" /> :
           !accounts.length ? <EmptyState fill tone="warn" glyph="∅" msg="No accounts" hint="Engine unreachable, or no accounts configured." /> : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {accounts.map((a) => (
                <Card key={a.id} tight style={{
                  cursor: 'pointer',
                  borderColor: acct === a.id ? 'var(--qe-cyan)' : 'var(--qe-line)',
                  background: acct === a.id ? 'var(--qe-active)' : 'var(--qe-card)',
                }} onClick={() => setAcct(a.id)}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <StatusDot tone={a.is_active ? 'ok' : 'off'} label="" />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'var(--qe-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.name}</div>
                      <div style={{ fontSize: '0.58rem', color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>{a.exchange} · {a.market_type}</div>
                    </div>
                    <Badge tone={a.environment === 'live' ? 'err' : a.environment === 'testnet' ? 'info' : 'blue'}>{(a.environment || 'live').toUpperCase()}</Badge>
                  </div>
                </Card>
              ))}
              <button className="qe-btn qe-btn-primary qe-btn-sm"
                title="Add a new exchange account"
                onClick={() => setAdding(true)}
                style={{ marginTop: 4, justifyContent: 'center' }}>+ Add Account</button>
            </div>
          )}
        </Pane>
      </GridItem>

      <GridItem x={6} y={0} w={18} h={20} minW={8} minH={6}>
        {/* ↻ remounts the form body (Pane key-bump) — unsaved edits are
            deliberately discarded on an explicit reload; onRefresh makes it
            also refetch server truth [P2 audit LOW-1] */}
        <Pane title="Account Settings" style={{ height: '100%' }} bodyStyle={{ overflow: 'auto' }}
          onRefresh={() => reload(true)}
          foot={!sel ? { tone: 'sub', msg: 'no account selected' }
            : qeFootState({ loading: detail == null && !netD.err, err: netD.err, hasData: detail != null && !detail._placeholder, ms: netD.ms })}>
          {!sel ? <EmptyState fill tone="neutral" glyph="◇" msg="No account selected" /> :
           detail == null ? <Spinner label="loading" /> :
           <CfgAccountForm key={sel.id} account={sel} detail={detail} onReload={reload} />}
        </Pane>
      </GridItem>
    </GridWorkspace>
    {/* Sibling of the workspace, NOT inside a Pane: ModelDialog is
        position:absolute and Pane is position:relative, so a dialog mounted
        in a tile would be clipped to it. */}
    {adding && (
      <CfgAddAccountDialog
        accounts={accounts || []}
        onClose={() => setAdding(false)}
        onCreated={async (id) => { await loadAccounts(true); setAcct(id); }} />
    )}
    </React.Fragment>
  );
};

/* ── Connections tab ─────────────────────────────────────────────────────── */
const CfgConnectionsTab = () => {
  const [conns, setConns]     = React.useState(null);
  const [drafts, setDrafts]   = React.useState({});     // provider -> key draft
  const [editing, setEditing] = React.useState(null);   // provider in edit mode
  const [busyP, setBusyP]     = React.useState(null);   // provider with an action in flight
  const [msg, setMsg]         = React.useState(null);
  const [add, setAdd]         = React.useState({ provider: '', label: '', key: '' });

  const [net, setNet] = React.useState({});
  const load = React.useCallback(async () => {
    const t0 = performance.now();
    try {
      setConns((await _cfgJson('/api/connections')).connections || []);
      setNet({ err: null, ms: performance.now() - t0 });
    } catch (err) { setConns([]); setNet((n) => ({ ...n, err })); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const upsert = async (provider, label, key) => {
    if (!key || !key.trim()) { setMsg({ text: `${label}: enter an API key first`, tone: 'err' }); return false; }
    setBusyP(provider); setMsg(null);
    let saved = false;
    try {
      // Existing HTML endpoint — returns the re-rendered Jinja list; ignore the
      // body and re-fetch the JSON mirror instead.
      const r = await _cfgPostForm('/connections', { provider, label, api_key: key.trim() });
      if (r.ok) {
        saved = true;
        setMsg({ text: `${label}: key saved`, tone: 'ok' });
        setDrafts((d) => ({ ...d, [provider]: '' }));
        setEditing(null);
        await load();
      } else {
        setMsg({ text: `${label}: save failed — ${r.text || 'error'}`, tone: 'err' });
      }
    } catch (e) { setMsg({ text: `${label}: save failed — engine unreachable?`, tone: 'err' }); }
    setBusyP(null);
    return saved;
  };

  const test = async (provider, label) => {
    setBusyP(provider); setMsg(null);
    try {
      const r = await fetch(`/connections/${encodeURIComponent(provider)}/test`, { method: 'POST' });
      const text = _cfgStrip(await r.text());
      setMsg({ text: `${label}: ${text}`, tone: text.startsWith('✓') ? 'ok' : 'err' });
    } catch (e) { setMsg({ text: `${label}: test failed — engine unreachable?`, tone: 'err' }); }
    setBusyP(null);
  };

  const remove = async (provider, label) => {
    if (!window.confirm(`Remove ${label} connection?`)) return;
    setBusyP(provider); setMsg(null);
    try {
      const r = await fetch(`/connections/${encodeURIComponent(provider)}`, { method: 'DELETE' });
      setMsg(r.ok ? { text: `${label}: removed`, tone: 'ok' } : { text: `${label}: remove failed`, tone: 'err' });
      await load();
    } catch (e) { setMsg({ text: `${label}: remove failed — engine unreachable?`, tone: 'err' }); }
    setBusyP(null);
  };

  const keyInput = (c) => (
    <input className="qe-input" type="password" placeholder="API Key"
      value={drafts[c.provider] || ''}
      onChange={(e) => { const v = e.target.value; setDrafts((d) => ({ ...d, [c.provider]: v })); }}
      onClick={(e) => e.stopPropagation()}
      style={{ width: 200, height: 22, fontSize: '0.62rem' }} />
  );

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={24} h={20} minW={10} minH={6}>
        <Pane title="Data & Exchange Connections" count={conns ? conns.length : null}
          style={{ height: '100%' }} bodyStyle={{ padding: 0 }} onRefresh={load}
          foot={qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: conns != null && conns.length > 0, ms: net.ms })}>
          {conns == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> : (
            <React.Fragment>
              <DataList
                dense={false}
                selKey="provider"
                emptyMsg="no connections"
                columns={[
                  { key: 'label',    label: 'PROVIDER', render: (c) => <span style={{ fontWeight: 700 }}>{c.label}</span> },
                  { key: 'provider', label: 'ID', render: (c) => <span style={{ color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{c.provider}</span> },
                  /* 'status' is RENDER-ONLY — the row carries has_key, not a
                     status field — so facet derivation and presentKeys both
                     skipped it: no FILTER dropdown and an inert STATUS header.
                     Project has_key onto the same two strings the cell shows. */
                  { key: 'status',   label: 'STATUS',
                    filter: true,
                    filterVal: (c) => (c.has_key ? 'CONNECTED' : 'NOT SET'),
                    sortVal:   (c) => (c.has_key ? 'CONNECTED' : 'NOT SET'),
                    render: (c) => c.has_key ? <StatusDot tone="ok" label="CONNECTED" /> : <StatusDot tone="off" label="NOT SET" /> },
                  { key: 'key',      label: 'KEY', render: (c) =>
                      c.has_key && editing !== c.provider
                        ? <span style={{ color: 'var(--qe-sub)', fontFamily: 'var(--qe-mono)' }}>{c.api_key_hint || '••••••'}</span>
                        : keyInput(c) },
                  { key: 'act', label: '', align: 'right', render: (c) => {
                      const busy = busyP === c.provider;
                      if (!c.has_key || editing === c.provider) {
                        return (
                          <span style={{ display: 'inline-flex', gap: 4 }}>
                            {/* "Save", not the design's "Save & Test" — POST
                                /connections only upserts (no test runs); the
                                Test button is the honest probe [P2 audit LOW] */}
                            <button className="qe-btn qe-btn-sm qe-btn-primary" disabled={busy}
                              onClick={(e) => { e.stopPropagation(); upsert(c.provider, c.label, drafts[c.provider]); }}>
                              {busy ? <Spinner size="0.62rem" /> : 'Save'}
                            </button>
                            {c.has_key ? (
                              <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy}
                                onClick={(e) => { e.stopPropagation(); setEditing(null); }}>Cancel</button>
                            ) : null}
                          </span>
                        );
                      }
                      return (
                        <span style={{ display: 'inline-flex', gap: 4 }}>
                          <button className="qe-btn qe-btn-sm" disabled={busy}
                            onClick={(e) => { e.stopPropagation(); test(c.provider, c.label); }}>
                            {busy ? <Spinner size="0.62rem" /> : 'Test'}
                          </button>
                          <button className="qe-btn qe-btn-sm qe-btn-ghost" disabled={busy}
                            onClick={(e) => { e.stopPropagation(); setEditing(c.provider); }}>Edit</button>
                          <button className="qe-btn qe-btn-sm qe-btn-danger" disabled={busy}
                            onClick={(e) => { e.stopPropagation(); remove(c.provider, c.label); }}>Remove</button>
                        </span>
                      );
                    } },
                ]}
                rows={conns}
              />
              <div style={{ padding: '8px 10px', borderTop: '1px solid var(--qe-line)' }}>
                <Lbl>+ Add custom provider</Lbl>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 4 }}>
                  <input className="qe-input" placeholder="provider id (e.g. alphavantage)" value={add.provider}
                    onChange={(e) => { const v = e.target.value; setAdd((a) => ({ ...a, provider: v })); }} style={{ maxWidth: 180 }} />
                  <input className="qe-input" placeholder="label" value={add.label}
                    onChange={(e) => { const v = e.target.value; setAdd((a) => ({ ...a, label: v })); }} style={{ maxWidth: 180 }} />
                  <input className="qe-input" type="password" placeholder="API key" value={add.key}
                    onChange={(e) => { const v = e.target.value; setAdd((a) => ({ ...a, key: v })); }} style={{ maxWidth: 220 }} />
                  <button className="qe-btn qe-btn-sm qe-btn-primary"
                    disabled={!add.provider.trim() || !add.label.trim() || !add.key.trim() || !!busyP}
                    onClick={() => upsert(add.provider.trim(), add.label.trim(), add.key)
                      .then((ok) => { if (ok) setAdd({ provider: '', label: '', key: '' }); })}>
                    Add
                  </button>
                </div>
                <div className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-muted)', marginTop: 6 }}>
                  Keys are encrypted at rest with AES-256 (Fernet).
                </div>
                <CfgMsgLine msg={msg} />
              </div>
            </React.Fragment>
          )}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Presets tab ─────────────────────────────────────────────────────────── */
const CfgPresetsTab = () => {
  const [cat, setCat]       = React.useState(null);   // [{name, dd, sizing}]
  const [active, setActive] = React.useState(null);   // active account meta
  const [accts, setAccts]   = React.useState([]);     // config-2: every account
  const [target, setTarget] = React.useState(null);   // config-2: write target id
  const tgtRef = React.useRef(null);                  // load() reads it without re-binding
  const [current, setCurrent] = React.useState('');   // TARGET acct strategy_preset
  const [busy, setBusy]     = React.useState(null);
  const [msg, setMsg]       = React.useState(null);

  const [net, setNet] = React.useState({});
  const load = React.useCallback(async () => {
    const t0 = performance.now();
    try {
      const [pc, accounts] = await Promise.all([_cfgJson('/api/config/presets'), _cfgJson('/accounts')]);
      setNet({ err: null, ms: performance.now() - t0 });
      setCat(pc.presets || []);
      const act = (accounts || []).find((a) => a.is_active) || null;
      setActive(act);
      setAccts(accounts || []);
      // config-2: default the target to the ACTIVE account (the prior
      // behaviour), but keep an existing choice across refreshes so a reload
      // mid-edit cannot silently retarget the write.
      if (!(tgtRef.current != null && (accounts || []).some((a) => a.id === tgtRef.current))) {
        tgtRef.current = act ? act.id : null;
      }
      setTarget(tgtRef.current);
      // scoped: a failing CURRENT-badge lookup must not blank the loaded
      // catalog — degrade to "no badge" [P2 audit LOW]
      // the CURRENT badge describes the TARGET account, not always the active one
      if (tgtRef.current != null) {
        try {
          const d = await _cfgJson('/api/config/account/' + tgtRef.current);
          setCurrent((d.settings || {}).strategy_preset || '');
        } catch (e) { setCurrent(''); }
      }
    } catch (err) { setCat([]); setNet((n) => ({ ...n, err })); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const apply = async (name) => {
    const tgt = accts.find((a) => a.id === target) || active;
    if (!tgt) { setMsg({ text: 'no account selected', tone: 'err' }); return; }
    // config-2: name the ACTUAL target and say plainly when it is NOT the
    // running account — writing another account's risk posture must never be
    // mistakable for changing the one currently trading.
    const label = tgt.name + (tgt.is_active ? ' (ACTIVE — currently trading)' : ' (not active)');
    if (!window.confirm(
      `Apply preset ${name.toUpperCase()} to ${label}?\n\n` +
      'FULL apply — writes BOTH risk stores:\n' +
      '· DD posture (window / warn / limit / recovery + analytics period)\n' +
      '· sizing envelope (risk/trade, weekly loss, max DD, exposure, positions, corr. cap)\n\n' +
      'Enforcement mode is NOT changed.')) return;
    setBusy(name); setMsg(null);
    try {
      const r = await _cfgPostJson('/api/config/apply-preset', { preset: name, account_id: tgt.id });
      if (r.ok && r.data && r.data.status === 'ok') {
        setMsg({ text: `preset ${name.toUpperCase()} applied to ${tgt.name}`
          + (r.data.is_active ? '' : ' — NOT the active account'), tone: 'ok' });
        await load();
      } else {
        setMsg({ text: (r.data && r.data.error) || 'apply failed', tone: 'err' });
      }
    } catch (e) { setMsg({ text: 'apply failed — engine unreachable?', tone: 'err' }); }
    setBusy(null);
  };

  const fRow = (l, v, color) => (
    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
      <span style={{ color: 'var(--qe-muted)' }}>{l}</span>
      <span style={{ fontWeight: 700, color: color || 'var(--qe-text)' }}>{v}</span>
    </div>
  );

  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={24} h={16} minW={10} minH={6}>
        <Pane title="Risk Presets" style={{ height: '100%' }} bodyStyle={{ overflow: 'auto' }} onRefresh={load}
          foot={qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: (cat || []).length > 0, ms: net.ms })}>
          <div className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-sub)', marginBottom: 8, lineHeight: 1.5 }}>
            Apply is FULL: writes the DD posture (account_settings — the store the DD gate reads)
            AND the sizing envelope (account_params). Enforcement mode never changes here.
          </div>
          {/* config-2: WHICH account gets written. Presets used to be hard-wired
              to the active account server-side, so an account that had never
              been activated could not be given a preset at all. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <Lbl>Apply to</Lbl>
            <select className="qe-input qe-select" style={{ height: 22, fontSize: '0.62rem', width: 240 }}
              value={target != null ? String(target) : ''}
              onChange={(e) => { const v = Number(e.target.value); tgtRef.current = v; setTarget(v); load(); }}>
              {accts.map((a) => (
                <option key={a.id} value={String(a.id)}>{a.name}{a.is_active ? ' — ACTIVE' : ''}</option>
              ))}
            </select>
            {target != null && active && target !== active.id ? (
              <span className="qe-mono" style={{ fontSize: '0.56rem', color: 'var(--qe-amber)' }}>
                writing a NON-active account — the running account is unaffected
              </span>
            ) : null}
          </div>
          {cat == null ? <Spinner label="loading" /> :
           !cat.length ? <EmptyState tone="warn" glyph="∅" msg="No presets" hint="Engine unreachable?" /> : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 6 }}>
              {cat.map((p) => {
                const dd = p.dd || {}, sz = p.sizing || {};
                const isCur = current === p.name;
                return (
                  <Card key={p.name} ticks>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 }}>
                      <span style={{ fontFamily: 'var(--qe-mono)', fontSize: '0.78rem', fontWeight: 700, color: 'var(--qe-cyan)', letterSpacing: '0.08em' }}>
                        {p.name.replace('_', ' ').toUpperCase()}
                      </span>
                      {isCur ? <Badge tone="info">CURRENT</Badge> : null}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.66rem', fontFamily: 'var(--qe-mono)' }}>
                      {fRow('DD window', dd.dd_rolling_window_days != null ? dd.dd_rolling_window_days + 'd' : '—')}
                      {fRow('warn', _cfgPct(dd.dd_warning_threshold), 'var(--qe-amber)')}
                      {fRow('limit', _cfgPct(dd.dd_limit_threshold), 'var(--qe-red)')}
                      {fRow('recovery', _cfgPct(dd.dd_recovery_threshold), 'var(--qe-green)')}
                      {fRow('period', dd.analytics_default_period || '—')}
                      <div style={{ borderTop: '1px solid var(--qe-line)', margin: '3px 0' }} />
                      {fRow('risk/trade', _cfgPct(sz.individual_risk_per_trade), 'var(--qe-cyan)')}
                      {fRow('wk loss cap', _cfgPct(sz.max_w_loss_percent))}
                      {fRow('max DD cap', _cfgPct(sz.max_dd_percent))}
                      {fRow('exposure', sz.max_exposure != null ? sz.max_exposure + '×' : '—')}
                      {fRow('positions', sz.max_position_count != null ? String(sz.max_position_count) : '—')}
                      {fRow('corr. cap', _cfgPct(sz.max_correlated_exposure))}
                    </div>
                    <button className="qe-btn qe-btn-sm" disabled={!!busy}
                      style={{ width: '100%', marginTop: 8, justifyContent: 'center' }}
                      onClick={() => apply(p.name)}>
                      {busy === p.name ? <Spinner size="0.62rem" label="applying" /> : 'Apply Preset'}
                    </button>
                  </Card>
                );
              })}
            </div>
          )}
          <CfgMsgLine msg={msg} />
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── System tab ──────────────────────────────────────────────────────────── */
const CfgSystemTab = () => {
  const [sys, setSys] = React.useState(null);
  const [net, setNet] = React.useState({});
  const load = React.useCallback(async () => {
    const t0 = performance.now();
    try { setSys(await _cfgJson('/api/system')); setNet({ err: null, ms: performance.now() - t0 }); }
    catch (err) { setSys({}); setNet((n) => ({ ...n, err })); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const c = (sys && sys.cadences) || {};
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={24} h={12} minW={10} minH={5}>
        <Pane title="System" style={{ height: '100%' }} bodyStyle={{ overflow: 'auto' }} onRefresh={load}
          foot={qeFootState({ loading: net.ms == null && !net.err, err: net.err, hasData: !!(sys && sys.version), ms: net.ms })}>
          {sys == null ? <Spinner label="loading" /> :
           !sys.version ? <EmptyState fill tone="warn" glyph="∅" msg="Engine unreachable" hint="/api/system did not answer." /> : (
            <React.Fragment>
              <SecLbl rule right={<span style={{ color: 'var(--qe-muted)', fontSize: '0.54rem' }}>READ-ONLY · G-O8</span>}>Engine</SecLbl>
              <FieldList cols={2} rows={[
                { label: 'Engine',   value: sys.short_name || sys.name || '—' },
                { label: 'Version',  value: sys.version || '—', color: 'cyan' },
                { label: 'Pub/Sub backend', value: sys.bus_backend || '—' },
                { label: 'Uptime',   value: _cfgUptime(sys.uptime_s), color: 'green' },
                { label: 'Started',  value: sys.started_at || '—' },
              ]} />
              <div className="qe-mono" style={{ fontSize: '0.58rem', color: 'var(--qe-sub)', margin: '4px 0 10px' }}>{sys.description || ''}</div>
              <SecLbl rule>Poll cadences</SecLbl>
              <FieldList cols={2} rows={[
                { label: 'Dashboard poll',  value: c.dashboard_poll_s  != null ? c.dashboard_poll_s  + 's' : '—' },
                { label: 'Calculator poll', value: c.calculator_poll_s != null ? c.calculator_poll_s + 's' : '—' },
                { label: 'History poll',    value: c.history_poll_s    != null ? c.history_poll_s    + 's' : '—' },
                { label: 'WS status poll',  value: c.ws_status_poll_s  != null ? c.ws_status_poll_s  + 's' : '—' },
                { label: 'WS ping',         value: c.ws_ping_s         != null ? c.ws_ping_s         + 's' : '—' },
              ]} />
            </React.Fragment>
          )}
        </Pane>
      </GridItem>
    </GridWorkspace>
  );
};

/* ── Config page ─────────────────────────────────────────────────────────── */
const ConfigPage = () => {
  const [tab, setTab] = React.useState('accounts');
  return (
    <div className="qe-scope" data-screen-label="08 Config" style={{
      width: '100%', height: '100%', background: 'var(--qe-bg)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      // anchors the Add-Account ModelDialog, matching the other dialog-hosting
      // page roots (linkage / models / dashboard)
      position: 'relative',
    }}>
      <TopNavStd page="Config" variant="line" dense />
      <PageHeader title="Configuration" subtitle="accounts · connections · risk parameters · presets" />

      <TabStrip value={tab} onChange={setTab} tabs={[
        ['accounts', 'Accounts'], ['connections', 'Connections'], ['presets', 'Presets'], ['system', 'System'],
      ]} />

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'auto' }}>
        {tab === 'accounts'    && <CfgAccountsTab />}
        {tab === 'connections' && <CfgConnectionsTab />}
        {tab === 'presets'     && <CfgPresetsTab />}
        {tab === 'system'      && <CfgSystemTab />}
      </div>
      <StatusFooter />
    </div>
  );
};

Object.assign(window, { ConfigPage });
