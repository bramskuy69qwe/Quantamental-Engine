/* v3.0 SSE client-adapter (P0 skeleton).
 *
 * ONE EventSource per active account → per-channel subscribers. Pages bind by
 * calling onChannel(), folding the payload into their own module store, and
 * notifying their leaves. (The P0 header promised a data-live-id VALUE
 * REGISTRY that leaf LiveValue spans would subscribe to; P1 shipped the
 * store-fold instead and the registry never gained a writer — deleted
 * 2026-08-05, see the note below.)
 *
 * Verified against the engine surface (docs/design/v3.0_ui_rebuild_plan.md §1.2
 * + P0 executed-notes):
 *   - Endpoint: GET /stream/account/{id} (multiplexed), one connection.
 *   - Bus: core/pubsub InProcessBus (NOT core/event_bus) — in-process, no broker.
 *   - 6 LIVE channels (SSE `event:` = channel suffix): position_update,
 *     equity_update, dd_state, order_update, fill, engine_log (a
 *     content-free "new log line exists" nudge from main.py's
 *     _EngineLogNudgeHandler — consumers re-poll, payload carries no text).
 *   - weekly_pnl is a DEAD channel (defined but never published) — do NOT wire
 *     an SSE listener; weekly-PnL state comes from the /api/state poll instead.
 *   - Scoping caveat: position_update/equity_update/dd_state publish only to the
 *     ACTIVE account; fill/order_update carry a true per-order account id.
 */
const QE_SSE = (function () {
  // Exactly the 6 channels the engine actually publishes. weekly_pnl omitted.
  const CHANNELS = ['position_update', 'equity_update', 'dd_state', 'order_update', 'fill', 'engine_log'];

  const chanSubs = new Map();   // channel -> Set(fn(payload))
  let source = null;
  let streamId = null;          // the account this `source` is subscribed to
  let status = 'idle';          // idle | connecting | open | error | disabled

  /* The LIVE active account, not the page-load one. QE_CHROME keeps it current
     off /api/state; it seeds itself from QE_BOOTSTRAP, so the cold start here
     is unchanged. The fallback covers this module being loaded on its own —
     the build orders chrome-live.js before it (build.mjs JSX_ORDER), so in the
     app it is never taken. */
  const accountId = () => (window.QE_CHROME ? window.QE_CHROME.accountId()
    : (window.QE_BOOTSTRAP && window.QE_BOOTSTRAP.activeAccountId));

  function fanout(map, key, arg) {
    const subs = map.get(key);
    if (subs) subs.forEach((fn) => { try { fn(arg); } catch (e) { /* isolate */ } });
  }

  function connect(explicitId) {
    if (source) return status;
    // `explicitId` is what retarget() is switching TO. Without it this read the
    // live store instead, so `retarget(N)` did not actually target N — it tore
    // the connection down and reopened it on whatever the store happened to
    // say. In production those are the same value (QE_CHROME updates _acctId
    // BEFORE firing onAccountChange), so this was never a live mis-target — but
    // the parameter looked like a destination while behaving as a mere trigger,
    // and a manual retarget(N) churned the socket for nothing. Found by calling
    // it against the live engine and watching the stream id not move.
    const id = explicitId != null ? explicitId : accountId();
    if (id == null || typeof EventSource === 'undefined') { status = 'disabled'; return status; }
    status = 'connecting';
    try {
      source = new EventSource('/stream/account/' + id);
      streamId = id;
    } catch (e) { status = 'error'; return status; }
    source.onopen = () => { status = 'open'; };
    source.onerror = () => { status = 'error'; };   // browser auto-reconnects
    // NB the per-channel `event:` names depend on the InProcessBus injecting
    // `_channel_suffix` (in_process_bus.py:42-43); RedisBus does NOT, so under
    // PUBSUB_BACKEND=redis every event arrives as `event: update` and these
    // per-channel listeners never fire. Localhost defaults to inprocess.
    CHANNELS.forEach((ch) => {
      source.addEventListener(ch, (ev) => {
        let data;
        try { data = JSON.parse(ev.data); } catch (e) { return; }
        fanout(chanSubs, ch, data);
      });
    });
    return status;
  }

  function disconnect() {
    if (source) { try { source.close(); } catch (e) {} source = null; }
    streamId = null;
    status = 'idle';
  }

  /* Re-point the stream at a different account (H1).
   *
   * `connect()` early-returns while a `source` exists, and it was only ever
   * called once at load, so this stream used to stay bound to the page-load
   * account for the life of the page. The nav picker hid that by reloading
   * after a switch; the Config page's Activate does not reload, so from there
   * on the Dashboard's live equity, position and dd_state events belonged to
   * the account the operator had just LEFT — with nothing on screen saying so.
   *
   * The channel subscriptions live in `chanSubs`, outside the source, so every
   * subscriber survives this and is re-bound to the new EventSource by
   * connect(). Idempotent on the id that is already streaming, so a caller
   * that fires on every poll cannot churn the connection.
   */
  function retarget(id) {
    if (id == null || String(id) === String(streamId)) return status;
    disconnect();
    return connect(id);
  }

  return {
    connect,
    disconnect,
    retarget,
    streamAccountId: () => streamId,
    status: () => status,
    channels: CHANNELS.slice(),

    /* Subscribe to a raw channel's decoded payloads. Returns an unsubscribe fn.
       THE binding mechanism: pages subscribe here, fold the payload into their
       own module store, and notify — see dash-tiled.jsx's _wireSSE. */
    onChannel(channel, fn) {
      if (!chanSubs.has(channel)) chanSubs.set(channel, new Set());
      chanSubs.get(channel).add(fn);
      return () => { const s = chanSubs.get(channel); if (s) s.delete(fn); };
    },
  };
})();

/* The P0 data-live-id VALUE REGISTRY (values/valSubs + setValue/getValue/
   onValue) and the useLiveId / useSSEChannel hooks were DELETED in the
   2026-08-05 LOW batch. `setValue` was the registry's only writer and had zero
   callers repo-wide: P1 shipped a different mechanism — onChannel → per-page
   store → notify() — and every page followed it, so the registry sat dead from
   the day it was written. NOTE the `LiveValue` PRIMITIVE is unaffected and very
   much alive (~30 call sites): it takes its value as a PROP and its
   data-live-id attribute is a server-side htmx/OOB swap target, not a lookup
   into this registry. DESIGN.md's binding rules were corrected in the same
   commit — a ratified rule naming a deleted symbol is worse than the dead code
   it described. */

/* Open the stream once the app boots. No-op (status 'disabled') when there is no
   account id or no EventSource; a failed connect just sits in 'error' and the
   browser auto-reconnects — nothing renders off it until P1 binds tiles. */
QE_SSE.connect();

/* …and FOLLOW the account from then on. Without this the stream is pinned to
   whatever account the page was rendered for; see retarget() for what that
   cost. QE_CHROME only fires this on a real change and never off an errored
   /api/state, so a flapping engine cannot thrash the connection. */
if (window.QE_CHROME && window.QE_CHROME.onAccountChange) {
  window.QE_CHROME.onAccountChange(QE_SSE.retarget);
}

Object.assign(window, { QE_SSE });
