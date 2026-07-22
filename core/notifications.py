"""
P8.T7 (spec §12.5): in-app notification center.

A small in-memory, per-account ring buffer of notifiable calc-linkage events.
An ``event_bus.subscribe_all`` catch-all routes the notifiable subset into the
buffer; ``GET /notifications/poll`` returns new entries filtered by the
account's ``config_json.notification_subscriptions``; base.html toasts them +
shows an unseen-count bell badge.

Ephemeral by design — transient toasts don't need persistence; a restart
starts fresh (the durable record lives in trade_events / engine_events).

Delivery is POLL (not SSE): notifications must surface on EVERY page, and a
global poll (the existing nav-badge idiom) is simpler + cheaper than a second
SSE connection in base.html alongside the dashboard's stream.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("notifications")

# (domain, event suffix) on the Phase-6 topic -> notification-subscription key.
# Only events with a real producer are mapped; near_replacement_match is a
# subscription key (settings UI / future T5-derived emit) with no producer yet.
_NOTIFIABLE: Dict[Tuple[str, str], str] = {
    ("calc", "expired"):             "calc_expired",
    ("position", "liquidated"):      "position_liquidated",
    ("position", "size_drift"):      "position_size_drift",
    ("order", "duplicate_detected"): "duplicate_order_detected",
}

_CH_RE = re.compile(r"^engine:account:(\d+):([a-z_]+):([a-z_]+)$")
_MAX_PER_ACCOUNT = 200


def _message(ntype: str, p: Dict[str, Any]) -> str:
    """A short operator-facing line for the toast."""
    p = p or {}
    if ntype == "calc_expired":
        return f"Calc expired: {p.get('ticker', '?')} {p.get('direction', '')}".strip()
    if ntype == "position_liquidated":
        return f"Position LIQUIDATED: {p.get('position_id', '?')}"
    if ntype == "position_size_drift":
        return f"Size drift: {p.get('position_id', '?')} (Δ {p.get('delta', '?')})"
    if ntype == "duplicate_order_detected":
        n = len(p.get("order_ids", []) or [])
        return f"Duplicate orders detected ({n})"
    return ntype.replace("_", " ")


# v3.0 P1 (G-O3): notification-type -> (design category, priority) for the
# React notification center. Only the 4 real producer types are mapped; any
# other type falls back to SYSTEM/routine. Adding REGIME/NEWS/SYSTEM/FILLS
# producers is deferred out of P1.
_TYPE_UI: Dict[str, Tuple[str, str]] = {
    "calc_expired":             ("LINK",  "routine"),
    "position_size_drift":      ("LINK",  "risk"),
    "position_liquidated":      ("RISK",  "risk"),
    "duplicate_order_detected": ("FILLS", "risk"),
}


def ui_event(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a notification entry with the v3.0 UI event shape (G-O3):
    ``{ch, pri, head, detail, ts}`` ALONGSIDE the legacy ``{id, type, message,
    ts_ms}`` (the base.html poller keeps working — it reads the legacy keys and
    ignores the rest). ``head`` = the compact message line; ``detail`` is left
    empty for P1 (a richer head/detail split is a later refinement)."""
    ch, pri = _TYPE_UI.get(entry.get("type", ""), ("SYSTEM", "routine"))
    return {
        **entry,
        "ch": ch,
        "pri": pri,
        "head": entry.get("message", ""),
        "detail": "",
        "ts": entry.get("ts_ms"),
    }


class NotificationCenter:
    """Per-account ring buffer of notifiable events, keyed by a global
    monotonic id so a browser can poll for "everything since id N"."""

    def __init__(self) -> None:
        self._buf: Dict[int, List[Dict[str, Any]]] = {}
        self._next_id = 1

    def add(self, account_id: int, ntype: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        entry = {
            "id":      self._next_id,
            "type":    ntype,
            "message": _message(ntype, payload),
            "ts_ms":   int(time.time() * 1000),
        }
        self._next_id += 1
        buf = self._buf.setdefault(account_id, [])
        buf.append(entry)
        if len(buf) > _MAX_PER_ACCOUNT:        # bound memory; drop oldest
            del buf[: len(buf) - _MAX_PER_ACCOUNT]
        return entry

    async def on_event(self, channel: str, payload: Dict[str, Any]) -> None:
        """event_bus.subscribe_all handler — buffer the notifiable subset.

        Buffers ALL notifiable types (no per-account subscription check here);
        the poll endpoint applies the operator's subscription filter, so a
        config change takes effect immediately without re-buffering."""
        m = _CH_RE.match(channel or "")
        if not m:
            return
        ntype = _NOTIFIABLE.get((m.group(2), m.group(3)))
        if ntype:
            self.add(int(m.group(1)), ntype,
                     payload if isinstance(payload, dict) else {})

    def latest_id(self, account_id: int) -> int:
        buf = self._buf.get(account_id, [])
        return buf[-1]["id"] if buf else 0

    def poll(
        self, account_id: int, since_id: int,
        subscribed: Optional[set] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Return (new_entries, latest_id). Entries with ``id > since_id``,
        filtered to ``subscribed`` types (None = all). ``latest_id`` is the
        newest id in the account's buffer (the next ``since`` cursor)."""
        buf = self._buf.get(account_id, [])
        # Clamp the returned cursor so it never regresses below the caller's
        # since_id. The id space is GLOBAL-monotonic across accounts, so the
        # active account's newest buffered id can be < the client's cursor (the
        # client carries one cursor across a reload-less account switch). Without
        # the clamp, switching to such an account walks the client cursor
        # backward, and switching back replays that account's already-seen
        # entries. (Audit P8.T7, MED.) Skipping an inactive account's backlog on
        # switch-in is intentional (no-backlog-replay; new events get fresh
        # global ids > cursor anyway).
        newest = buf[-1]["id"] if buf else 0
        latest = max(since_id, newest)
        out = [
            e for e in buf
            if e["id"] > since_id and (subscribed is None or e["type"] in subscribed)
        ]
        return out, latest


# Module-level singleton.
notification_center = NotificationCenter()


def start_notification_center(bus: Any) -> NotificationCenter:
    """Wire the center as an event_bus catch-all subscriber (P8.T7). Called in
    schedulers._startup_fetch BEFORE event_bus.run() so no event is missed."""
    bus.subscribe_all(notification_center.on_event)
    log.info("NotificationCenter: subscribed to event_bus (all channels)")
    return notification_center
