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
const _cfgJson = async (url) => {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(url + ' ' + r.status);
  return r.json();
};

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

const _cfgPostForm = async (url, fields, method = 'POST') => {
  const body = new URLSearchParams();
  Object.entries(fields || {}).forEach(([k, v]) => { if (v != null) body.append(k, v); });
  const r = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  return { ok: r.ok, text: _cfgFriendly(_cfgStrip(await r.text())) };
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
  }));
  const [busy, setBusy] = React.useState(null);   // 'save' | 'test' | 'activate'
  const [msg, setMsg]   = React.useState(null);

  const set = (k) => (e) => { const v = e.target.value; setForm((f) => ({ ...f, [k]: v })); };

  const doSave = async () => {
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
        The DD gate reads THIS store. Values are written by preset Apply (Presets tab).
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

const CfgAccountsTab = () => {
  const [accounts, setAccounts] = React.useState(null);  // null = loading
  const [acct, setAcct]         = React.useState(null);  // selected id
  const [detail, setDetail]     = React.useState(null);  // {params, settings} for acct
  const acctRef = React.useRef(null);                    // live selection, for async guards

  const loadAccounts = React.useCallback(async (keepSelection) => {
    try {
      const rows = await _cfgJson('/accounts');
      setAccounts(rows);
      setAcct((cur) => {
        if (keepSelection && cur != null && rows.some((a) => a.id === cur)) return cur;
        const act = rows.find((a) => a.is_active) || rows[0];
        return act ? act.id : null;
      });
    } catch (e) { setAccounts([]); }
  }, []);
  React.useEffect(() => { loadAccounts(false); }, [loadAccounts]);

  React.useEffect(() => {
    acctRef.current = acct;
    if (acct == null) return;
    setDetail(null);
    let alive = true;
    _cfgJson('/api/config/account/' + acct)
      .then((d) => { if (alive) setDetail(d); })
      .catch(() => { if (alive) setDetail({ params: {}, settings: {} }); });
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
    <GridWorkspace>
      <GridItem x={0} y={0} w={6} h={20} minW={4} minH={6}>
        <Pane title="Accounts" count={accounts ? accounts.length : null} style={{ height: '100%' }}
          onRefresh={() => loadAccounts(true)}
          foot={{ tone: 'sub', msg: accounts ? `${accounts.length} accounts · add/delete on Jinja /config` : 'loading…' }}>
          {accounts == null ? <Spinner label="loading" /> :
           !accounts.length ? <EmptyState tone="warn" glyph="∅" msg="No accounts" hint="Engine unreachable, or no accounts configured." /> : (
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
              <button className="qe-btn qe-btn-primary qe-btn-sm" disabled
                title="Not wired in P2 — add accounts via the current /config page"
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
          foot={{ tone: 'sub', msg: 'two stores · sizing (account_params) + DD posture (account_settings, display-only)' }}>
          {!sel ? <EmptyState tone="neutral" glyph="◇" msg="No account selected" /> :
           detail == null ? <Spinner label="loading" /> :
           <CfgAccountForm key={sel.id} account={sel} detail={detail} onReload={reload} />}
        </Pane>
      </GridItem>
    </GridWorkspace>
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

  const load = React.useCallback(async () => {
    try { setConns((await _cfgJson('/api/connections')).connections || []); }
    catch (e) { setConns([]); }
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
          foot={{ tone: 'sub', msg: conns ? `${conns.length} providers · ${conns.filter((c) => c.has_key).length} connected` : 'loading…' }}>
          {conns == null ? <div style={{ padding: 10 }}><Spinner label="loading" /></div> : (
            <React.Fragment>
              <DataList
                dense={false}
                selKey="provider"
                tools={false}
                emptyMsg="no connections"
                columns={[
                  { key: 'label',    label: 'PROVIDER', render: (c) => <span style={{ fontWeight: 700 }}>{c.label}</span> },
                  { key: 'provider', label: 'ID', render: (c) => <span style={{ color: 'var(--qe-muted)', fontFamily: 'var(--qe-mono)' }}>{c.provider}</span> },
                  { key: 'status',   label: 'STATUS', render: (c) => c.has_key ? <StatusDot tone="ok" label="CONNECTED" /> : <StatusDot tone="off" label="NOT SET" /> },
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
  const [current, setCurrent] = React.useState('');   // active acct strategy_preset
  const [busy, setBusy]     = React.useState(null);
  const [msg, setMsg]       = React.useState(null);

  const load = React.useCallback(async () => {
    try {
      const [pc, accounts] = await Promise.all([_cfgJson('/api/config/presets'), _cfgJson('/accounts')]);
      setCat(pc.presets || []);
      const act = (accounts || []).find((a) => a.is_active) || null;
      setActive(act);
      // scoped: a failing CURRENT-badge lookup must not blank the loaded
      // catalog — degrade to "no badge" [P2 audit LOW]
      if (act) {
        try {
          const d = await _cfgJson('/api/config/account/' + act.id);
          setCurrent((d.settings || {}).strategy_preset || '');
        } catch (e) { setCurrent(''); }
      }
    } catch (e) { setCat([]); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const apply = async (name) => {
    const target = active ? active.name : 'the active account';
    if (!window.confirm(
      `Apply preset ${name.toUpperCase()} to ${target}?\n\n` +
      'FULL apply — writes BOTH risk stores:\n' +
      '· DD posture (window / warn / limit / recovery + analytics period)\n' +
      '· sizing envelope (risk/trade, weekly loss, max DD, exposure, positions, corr. cap)\n\n' +
      'Enforcement mode is NOT changed.')) return;
    setBusy(name); setMsg(null);
    try {
      const r = await _cfgPostJson('/api/config/apply-preset', { preset: name });
      if (r.ok && r.data && r.data.status === 'ok') {
        setMsg({ text: `preset ${name.toUpperCase()} applied to ${target}`, tone: 'ok' });
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
          foot={{ tone: 'sub', msg: 'Apply = FULL write (both stores) · confirm-gated' }}>
          <div className="qe-mono" style={{ fontSize: '0.6rem', color: 'var(--qe-sub)', marginBottom: 8, lineHeight: 1.5 }}>
            Apply is FULL: writes the DD posture (account_settings — the store the DD gate reads)
            AND the sizing envelope (account_params). Applies to the active account
            {active ? <span> — <span style={{ color: 'var(--qe-cyan)', fontWeight: 700 }}>{active.name}</span></span> : null}.
            Enforcement mode never changes here.
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
  const load = React.useCallback(async () => {
    try { setSys(await _cfgJson('/api/system')); } catch (e) { setSys({}); }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const c = (sys && sys.cadences) || {};
  return (
    <GridWorkspace>
      <GridItem x={0} y={0} w={24} h={12} minW={10} minH={5}>
        <Pane title="System" style={{ height: '100%' }} bodyStyle={{ overflow: 'auto' }} onRefresh={load}
          foot={{ tone: 'sub', msg: 'read-only engine facts · /api/system' }}>
          {sys == null ? <Spinner label="loading" /> :
           !sys.version ? <EmptyState tone="warn" glyph="∅" msg="Engine unreachable" hint="/api/system did not answer." /> : (
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
