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

  /* Deadline per read — see primitives' _ptJson block for the full argument.
     This store is the one that matters most for it: the nav strip and the
     footer render on EVERY page, and their whole degradation contract is the
     `*Err` flags below. A hung poll wrote neither the payload nor the flag and
     never even reached emit(), so the strip kept flying last-good DD / EXP /
     OPEN / P&L numbers under a GREEN engine dot — the same lie the tier-3 rule
     fixed for a failed poll, arriving by the one route that fix could not see.
     `_ptJson` is defined in primitives.jsx, which the build loads first. */
  const j = (url, deadlineMs) => _ptJson(url, deadlineMs);

  const poll = (url, key, errKey, ms) => {
    // The deadline is DERIVED from this poll's own interval, so the two cannot
    // drift apart when someone retunes the cadence.
    const deadlineMs = qePollDeadline(ms);
    const run = async () => {
      try { st[key] = await j(url, deadlineMs); st[errKey] = false; }
      catch (e) { st[errKey] = true; }  // keep last-good; flag the pipe
      emit();
    };
    run();
    setInterval(run, ms);
    return run;
  };

  const _runState = poll('/api/state', 'state', 'stateErr', 10_000);
  const _runSnap = poll('/api/dashboard/snapshot', 'snap', 'snapErr', 30_000);
  const _runSys = poll('/api/system', 'sys', 'sysErr', 60_000);

  /* The half of the seam a deadline cannot reach: while the page is HIDDEN its
     timers are throttled to ~1/min (frozen pages stop entirely), so no request
     is outstanding to time out and the strip keeps a `connected` dot over
     minute-old numbers the moment the operator alt-tabs back from Quantower.
     Re-poll on return — a fresh answer beats a staleness label, and a
     timestamp-based one could not fire here anyway (its clock is throttled by
     the same rule). */
  qeOnVisible(() => { _runState(); _runSnap(); _runSys(); });

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
