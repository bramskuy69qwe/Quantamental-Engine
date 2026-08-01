/* v3.0 SSE client-adapter (P0 skeleton).
 *
 * ONE EventSource per active account → a live-value registry that leaf
 * LiveValue components subscribe to. P0 lands the transport + the 5 REAL
 * channels and the subscribe/registry API; P1 (Dashboard) binds specific tiles
 * to data-live-id keys and replaces the nav-and-data random-walk placeholder.
 *
 * Verified against the engine surface (docs/design/v3.0_ui_rebuild_plan.md §1.2
 * + P0 executed-notes):
 *   - Endpoint: GET /stream/account/{id} (multiplexed), one connection.
 *   - Bus: core/pubsub InProcessBus (NOT core/event_bus) — in-process, no broker.
 *   - 5 LIVE channels (SSE `event:` = channel suffix): position_update,
 *     equity_update, dd_state, order_update, fill.
 *   - weekly_pnl is a DEAD channel (defined but never published) — do NOT wire
 *     an SSE listener; weekly-PnL state comes from the /api/state poll instead.
 *   - Scoping caveat: position_update/equity_update/dd_state publish only to the
 *     ACTIVE account; fill/order_update carry a true per-order account id.
 */
const QE_SSE = (function () {
  // Exactly the 5 channels the engine actually publishes. weekly_pnl omitted.
  const CHANNELS = ['position_update', 'equity_update', 'dd_state', 'order_update', 'fill'];

  const chanSubs = new Map();   // channel -> Set(fn(payload))
  const values = new Map();     // data-live-id -> latest value (P1 populates)
  const valSubs = new Map();    // data-live-id -> Set(fn(value))
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

    /* Subscribe to a raw channel's decoded payloads. Returns an unsubscribe fn. */
    onChannel(channel, fn) {
      if (!chanSubs.has(channel)) chanSubs.set(channel, new Set());
      chanSubs.get(channel).add(fn);
      return () => { const s = chanSubs.get(channel); if (s) s.delete(fn); };
    },

    /* data-live-id registry — P1 maps channel payloads → live-id values here so
       leaf LiveValue spans re-render without touching their surrounding pane. */
    setValue(liveId, v) { values.set(liveId, v); fanout(valSubs, liveId, v); },
    getValue(liveId) { return values.get(liveId); },
    onValue(liveId, fn) {
      if (!valSubs.has(liveId)) valSubs.set(liveId, new Set());
      valSubs.get(liveId).add(fn);
      return () => { const s = valSubs.get(liveId); if (s) s.delete(fn); };
    },
  };
})();

/* React hook: subscribe a component to a channel's latest payload (P1 binds
   tiles with this). Ships unused-but-ready in P0. */
const useSSEChannel = (channel) => {
  const [payload, setPayload] = React.useState(null);
  React.useEffect(() => QE_SSE.onChannel(channel, setPayload), [channel]);
  return payload;
};

/* React hook: subscribe to a single data-live-id's latest value. */
const useLiveId = (liveId, initial) => {
  const [v, setV] = React.useState(() =>
    QE_SSE.getValue(liveId) !== undefined ? QE_SSE.getValue(liveId) : initial);
  React.useEffect(() => QE_SSE.onValue(liveId, setV), [liveId]);
  return v;
};

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

Object.assign(window, { QE_SSE, useSSEChannel, useLiveId });
