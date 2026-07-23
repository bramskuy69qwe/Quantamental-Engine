/* v3.0 P8 wave 1 — the shared chrome data store (the plan's named
 * "small /api/state+SSE adapter feeding the chrome on every page").
 *
 * Replaces the P0 QE_LIVE/MOCK placeholder walks in nav-and-data.jsx with
 * REAL sources, one shared poller for the whole app (every page renders
 * TopNavStd/WorkspaceBar/StatusFooter, so this store is app-lifetime —
 * intervals are deliberately never cleared):
 *   - /api/state              10s  — dd/exposure/drawdown/position_count
 *                                    (halt UI itself stays Pre-Trade-scoped)
 *   - /api/dashboard/snapshot 30s  — P&L d/w/m %, positions_max, regime label
 *   - /api/system             60s  — uptime_s, version (G-O9 footer truth)
 *   - /accounts               once — the real account picker rows
 *   - QE_SSE.status()         2s sample — connection state for the WS dot
 *
 * Truthfulness contract: consumers render '—' when a source has no data;
 * per-source err flags let the footer dots show real health instead of the
 * old always-green fabrication. Keep-last-good on transient failures (the
 * flags carry the degradation, PaneFoot-v2 idiom).
 */
const QE_CHROME = (function () {
  const st = {
    state: null, snap: null, sys: null, accounts: null,
    stateErr: false, snapErr: false, sysErr: false,
    sse: 'idle',
  };
  const subs = new Set();
  const emit = () => subs.forEach((f) => { try { f(); } catch (e) { /* isolate */ } });

  const j = async (url) => {
    const r = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(url + ' ' + r.status);
    return r.json();
  };

  const poll = (url, key, errKey, ms) => {
    const run = async () => {
      try { st[key] = await j(url); st[errKey] = false; }
      catch (e) { st[errKey] = true; }  // keep last-good; flag the pipe
      emit();
    };
    run();
    setInterval(run, ms);
  };

  poll('/api/state', 'state', 'stateErr', 10_000);
  poll('/api/dashboard/snapshot', 'snap', 'snapErr', 30_000);
  poll('/api/system', 'sys', 'sysErr', 60_000);

  // audit LOW-3: retry until first success (a transient boot failure would
  // otherwise leave the picker at "— no accounts —" for the whole session).
  const loadAccounts = async () => {
    try { st.accounts = await j('/accounts'); } catch (e) { st.accounts = null; }
    emit();
    if (st.accounts == null) setTimeout(loadAccounts, 60_000);
  };
  loadAccounts();

  setInterval(() => {
    const s = (window.QE_SSE && window.QE_SSE.status()) || 'idle';
    if (s !== st.sse) { st.sse = s; emit(); }
  }, 2_000);

  return {
    get: () => st,
    sub: (f) => { subs.add(f); return () => subs.delete(f); },
    reloadAccounts: loadAccounts,
  };
})();

/* React hook — subscribe a chrome component to the store. */
const useQeChrome = () => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => QE_CHROME.sub(force), []);
  return QE_CHROME.get();
};

Object.assign(window, { QE_CHROME, useQeChrome });
