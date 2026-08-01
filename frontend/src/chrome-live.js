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
 *   - /accounts               on boot, on an account SWITCH, and whenever
 *                                    Config writes the list (see reloadAccounts)
 *   - QE_SSE.status()         2s sample — connection state for the WS dot
 *
 * It also owns THE CURRENT ACCOUNT for the whole app (accountId /
 * onAccountChange / useQeAccount) — see the block beside _noteAccount.
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

  const poll = (url, key, errKey, ms, after) => {
    // The deadline is DERIVED from this poll's own interval, so the two cannot
    // drift apart when someone retunes the cadence.
    const deadlineMs = qePollDeadline(ms);
    /* ★ GENERATION GUARD — last to ISSUE wins, not last to RESOLVE.
     *
     * These runs can overlap: refreshAccount() deliberately fires one out of
     * band, qeOnVisible fires all three on return, and a slow answer can still
     * be in flight when the next tick lands. Without this, an OLDER response
     * overwrites a newer one, and for /api/state that is not merely stale — it
     * is the whole account switch running backwards. Executed: a scheduled
     * poll issued just before Config ▸ Activate answers AFTER the push, so
     * _acctId reverts to the previous account, the SSE stream is torn off the
     * new one and re-pointed at the old, and Pre-Trade reloads the previous
     * account's risk %. It self-heals on the next tick, so the operator gets
     * up to one poll interval of a risk console on the wrong book — exactly
     * what the stateErr guard below exists to prevent, arriving by the one
     * route that guard cannot see. (The Activate confirm even warns it
     * restarts the exchange connection, which is what makes /api/state slow
     * at precisely that moment.)
     *
     * Same cure the codebase already uses twice: useAnaJson's seqRef and
     * Config's cross-account response guard (P2 audit MED-1).
     */
    let issued = 0, applied = 0;
    const run = async () => {
      const mine = ++issued;
      let payload = null, failed = false;
      try { payload = await j(url, deadlineMs); }
      catch (e) { failed = true; }
      if (mine < applied) return;   // superseded in flight — drop it whole,
      applied = mine;               // flag included (a newer run answered)
      if (failed) st[errKey] = true;                       // keep last-good
      else { st[key] = payload; st[errKey] = false; }
      if (after) after();
      emit();
    };
    run();
    setInterval(run, ms);
    return run;
  };

  // audit LOW-3: retry until first success (a transient boot failure would
  // otherwise leave the picker at "— no accounts —" for the whole session).
  const loadAccounts = async () => {
    try { st.accounts = await j('/accounts'); } catch (e) { st.accounts = null; }
    emit();
    if (st.accounts == null) setTimeout(loadAccounts, 60_000);
  };

  /* ── THE CURRENT ACCOUNT — one live source, and NOT QE_BOOTSTRAP ─────────
   *
   * `QE_BOOTSTRAP.activeAccountId` is baked into the page at render time and
   * has no way to change afterwards. Two routes switch the engine's account:
   * the nav picker, which reloads the whole page (so bootstrap is re-baked and
   * everything is correct), and the Config page's Activate, which refetches
   * data WITHOUT reloading. Down that second route every consumer holding the
   * page-load id silently kept targeting the PREVIOUS account:
   *   · the SSE stream stayed subscribed to it, so live equity / position /
   *     dd_state events on the Dashboard belonged to an account the operator
   *     had already left — a risk console showing another book's numbers;
   *   · Pre-Trade's individual_risk_per_trade was read for it, so the sizing
   *     input on screen disagreed with what the engine would actually size;
   *   · this store's `accounts` list was fetched ONCE, so the nav picker and
   *     the WorkspaceBar EXCH cell went on NAMING the old account beside
   *     numbers that were already the new one's.
   *
   * So the id lives here, seeded from bootstrap for the cold start and kept
   * live from `/api/state.account_id` — the same door the DD-override write
   * already reads for exactly this reason (dash-tiled's DdOverrideDialog).
   * Consumers take `accountId()` / `onAccountChange()` / the useQeAccount hook
   * and never touch QE_BOOTSTRAP.
   */
  let _acctId = (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.activeAccountId);
  if (_acctId === undefined) _acctId = null;
  const acctSubs = new Set();

  const _noteAccount = () => {
    // stateErr FIRST — the rule the nav strip and the pane foots already
    // follow. On a failed or timed-out poll this store KEEPS the last-good
    // payload and raises only the flag, so reading st.state here without the
    // guard would re-derive the account from a stale body. Acting on that is
    // worse than not acting: it could tear down a healthy SSE stream and
    // re-point it using an id the engine may have moved on from.
    if (st.stateErr || !st.state) return;
    const id = st.state.account_id;
    // String() on BOTH sides is defensive, not load-bearing: today the seed is
    // `{{ active_account_id | tojson }}` (a JSON number) and /api/state returns
    // the same number, so `===` would do. It is here because a type change on
    // either side would otherwise make this compare unequal on EVERY poll —
    // tearing down and reopening the SSE stream six times a minute — and that
    // failure is invisible until someone watches the network panel.
    if (id == null || String(id) === String(_acctId)) return;
    _acctId = id;
    loadAccounts();   // the picker + EXCH cell must follow the switch
    acctSubs.forEach((f) => { try { f(id); } catch (e) { /* isolate */ } });
  };

  const _runState = poll('/api/state', 'state', 'stateErr', 10_000, _noteAccount);
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

  loadAccounts();

  setInterval(() => {
    const s = (window.QE_SSE && window.QE_SSE.status()) || 'idle';
    if (s !== st.sse) { st.sse = s; emit(); }
  }, 2_000);

  return {
    get: () => st,
    sub: (f) => { subs.add(f); return () => subs.delete(f); },

    /* The accounts list changes for reasons the account-id watcher cannot see
       — a new account, a rename, an exchange/env edit. Config calls this from
       the ONE funnel every such write already goes through, which is what
       stops the nav picker from listing a set of accounts that no longer
       exists. (Before, this had zero callers and the list was whatever it was
       at page load.) */
    reloadAccounts: loadAccounts,

    /* The ACTIVE account, live. Null until the first /api/state answers if the
       page carried no bootstrap id. */
    accountId: () => _acctId,

    /* Fires with the new id when the engine's active account CHANGES, and
       never off an errored poll. Returns unsubscribe.
       It does NOT fire on the first successful poll of a page whose bootstrap
       already named the account (the normal case — the seed matches, so there
       is no change). It DOES fire on a page rendered with no active account
       (`activeAccountId` is `null` then), and that firing is what connects the
       stream at all — so subscribers must be idempotent, not once-only. */
    onAccountChange: (f) => { acctSubs.add(f); return () => acctSubs.delete(f); },

    /* Out-of-band /api/state pull, so a switch the operator just made lands
       without waiting out the 10 s poll. Same idiom as QE_DASH.refreshState.
       The poll stays the backstop: it catches a switch made from anywhere
       else (another tab, the engine itself) that never calls this. */
    refreshAccount: () => _runState(),
  };
})();

/* React hook — subscribe a chrome component to the store. */
const useQeChrome = () => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => QE_CHROME.sub(force), []);
  return QE_CHROME.get();
};

/* React hook — the CURRENT account id, re-rendering the caller when it
   changes. Use this as an effect dependency for anything account-scoped; a
   page that reads the id once at mount goes stale on a Config-page Activate
   (which does not reload). */
const useQeAccount = () => {
  const [id, setId] = React.useState(() => QE_CHROME.accountId());
  React.useEffect(() => {
    // Re-read on COMMIT before subscribing. The initializer above runs during
    // RENDER, and a switch landing in the gap between the two would never be
    // delivered — the component would hold the stale id for its whole life,
    // which is the failure this hook exists to prevent. setId with an equal
    // value bails out, so the extra read costs nothing.
    setId(QE_CHROME.accountId());
    return QE_CHROME.onAccountChange(setId);
  }, []);
  return id;
};

Object.assign(window, { QE_CHROME, useQeChrome, useQeAccount });
