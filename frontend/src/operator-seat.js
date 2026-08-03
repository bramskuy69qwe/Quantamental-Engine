/* H6 (wiring inventory, fixed 2026-08-03) — operator-seat session for the
 * React shell.
 *
 * THE DEFECT: seat registration only ever existed in templates/base.html's
 * IIFE, and the Jinja pages stopped serving the app at the retirement — so
 * the operator_id columns P9.T3 added (pre_trade_log / orders /
 * order_amendments) recorded NOTHING for any action taken through the React
 * UI. Attribution is resolved SERVER-side from the active operator_sessions
 * row (core/auth_state.current_operator_id + the on-duty cache the register
 * door write-through fills), so no per-write client change is needed — the
 * whole fix is: register this seat, keep it alive, follow the account.
 *
 * Parity with base.html's IIFE, plus the two things a reloading page never
 * needed:
 *   · SAME localStorage key ('op_seat') — one seat identity per browser
 *     profile across BOTH UIs, so using the legacy /config page and the
 *     React app doesn't read as two operators fighting over the account.
 *   · RE-REGISTER ON ACCOUNT SWITCH. All three doors bind
 *     app_state.active_account_id server-side; the Jinja page re-registered
 *     by reloading after a switch, the React app switches without reloading
 *     (the H1/H2 fix), so the seat must follow via QE_CHROME.onAccountChange
 *     — the same hook the SSE retarget rides.
 *   · REGISTER-RETRY: the Jinja IIFE registered once at load; boot with the
 *     engine down and the seat never existed (heartbeat deliberately makes
 *     no ownership claim). Here the 60 s tick registers until one register
 *     has APPLIED, then heartbeats — chrome-live's accounts-retry idiom.
 *
 * These are session WRITES (register claims ownership, heartbeat bumps
 * last_seen_ts), so they carry NO read deadline — the deadline doctrine is
 * reads-only by design. All failures are swallowed: this subsystem is
 * advisory attribution, and a dead engine is already loudly visible in the
 * nav strip; the banner only ever renders on a CONFIRMED foreign state.
 */
const QE_SEAT = (function () {
  const st = {
    state: 'idle',        // idle | owner | foreign  (idle = never confirmed)
    foreign: null,        // the OTHER seat's id when state === 'foreign'
    sinceMs: null,        // when the foreign session started
    accountId: null,      // the account the last register bound (server truth)
    dismissed: false,     // operator waved the advisory away (until a switch)
  };
  const subs = new Set();
  const emit = () => subs.forEach((f) => { try { f(); } catch (e) { /* isolate */ } });

  // Seat token — SAME key + mint shape as base.html's seatToken(), on purpose.
  const seatToken = () => {
    try {
      let t = localStorage.getItem('op_seat');
      if (!t) {
        t = (window.crypto && crypto.randomUUID)
          ? crypto.randomUUID()
          : 'seat-' + Date.now() + '-' + Math.floor(Math.random() * 1e9);
        localStorage.setItem('op_seat', t);
      }
      return t;
    } catch (e) { return 'seat-nostore'; }
  };
  const seat = seatToken();

  const post = (url) => fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'operator_id=' + encodeURIComponent(seat),
  }).then((r) => (r.ok ? r.json() : null));

  let applied = false;   // has ANY register/takeover result landed THIS epoch?
  // ★ THE EPOCH GUARD (audit HIGH, proven by execution): these posts carry no
  // deadline (writes are deadline-exempt by doctrine), so an in-flight
  // register from account A can land AFTER the switch reset below. Without
  // the guard it stamped A's answer over B's reset — a stale `foreign` banner
  // making a claim about an account nobody asked about — AND latched
  // `applied`, so the tick heartbeated forever and account B was never
  // registered: H6's own defect, restored by its fix. Answers minted under
  // an older epoch are dropped on the floor.
  let epoch = 0;
  const apply = (d) => {
    if (!d || !d.state) return;
    applied = true;
    st.state = d.state;
    st.foreign = d.foreign_operator_id || null;
    st.sinceMs = d.since_ms || null;
    if (d.account_id != null) st.accountId = d.account_id;
    emit();
  };

  const register = () => {
    const e = epoch;
    return post('/operator/session/register')
      .then((d) => { if (e === epoch) apply(d); })
      .catch(() => {});
  };
  const takeover = () => {
    const e = epoch;
    return post('/operator/session/takeover')
      .then((d) => { if (e === epoch) apply(d); })
      .catch(() => {});
  };

  register();
  // One app-lifetime tick. Register until a result APPLIES; while FOREIGN,
  // keep re-registering — a foreign seat's heartbeat is a documented server
  // no-op, so heartbeating there froze the store on a banner that outlives
  // its cause: once the foreign owner's session is reaped (30 min idle),
  // re-registering CLAIMS the seat and attribution comes alive, with no
  // operator action. (base.html defers this re-check and says so; under
  // P9.T3's cache the cost of not having it is dead attribution, so the
  // React store ships it — audit MED.) When OWNER, heartbeat; `bumped:false`
  // means the seat lost ownership (taken over elsewhere, or the session was
  // reaped while this tab was frozen) — re-register instead of silently
  // heartbeating a session that is no longer ours, so the banner learns
  // about the takeover within a tick. Deliberately never cleared, like
  // chrome-live's polls; a frozen tab stopping entirely is CORRECT — an
  // abandoned seat is exactly what the P9.T4 reaper exists to end.
  setInterval(() => {
    if (!applied || st.state === 'foreign') { register(); return; }
    const e = epoch;
    post('/operator/session/heartbeat')
      .then((d) => { if (e === epoch && d && d.bumped === false) register(); })
      .catch(() => {});
  }, 60_000);

  if (window.QE_CHROME && window.QE_CHROME.onAccountChange) {
    window.QE_CHROME.onAccountChange(() => {
      // A switch changes what the doors bind to, so the old answer — owner OR
      // foreign OR a dismissal of either — says nothing about the new account.
      // RESET to idle rather than keep it (executed probe: with the engine
      // down mid-switch, keep-last held the PREVIOUS account's state — a
      // stale `foreign` would keep a wrong banner up, the same
      // stale-shown-as-live family every recent fix has been closing).
      // `applied` drops too, so the 60 s tick RE-REGISTERS until the new
      // account answers instead of heartbeating an unclaimed seat. The epoch
      // bump invalidates every answer still in flight from the old account.
      epoch += 1;
      st.state = 'idle';
      st.foreign = null;
      st.sinceMs = null;
      st.dismissed = false;
      applied = false;
      emit();
      register();
    });
  }

  return {
    get: () => st,
    sub: (f) => { subs.add(f); return () => subs.delete(f); },
    takeover,
    dismiss: () => { st.dismissed = true; emit(); },
    seatId: () => seat,
  };
})();

/* React hook — subscribe a component to the seat store (QE_CHROME idiom). */
const useQeSeat = () => {
  const [, force] = React.useReducer((x) => x + 1, 0);
  React.useEffect(() => QE_SEAT.sub(force), []);
  return QE_SEAT.get();
};

Object.assign(window, { QE_SEAT, useQeSeat });
