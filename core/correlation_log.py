"""Correlation log — the observability spine (CL.T0a: emit side).

Design: docs/design/correlation_log_spec.md (rev 2). This module owns:

- the corr_id contextvar + ``mint`` / ``correlation_scope`` /
  ``current_corr_id`` (spec §3);
- the category REGISTRY with groups, from which the profiles are DERIVED
  (single source of truth — spec §5.8 / D8);
- ``emit()`` — the one public tap function, callable from sync, async,
  and pool-thread contexts (spec §6.1 pipeline order);
- central secret redaction (spec §7.2 / D10).

The sink (CL.T0b) is a dedicated daemon WRITER THREAD — not a coroutine
(``SimpleQueue.get`` blocks its calling thread; a coroutine drain would
stall the event loop): blocking ``get(timeout=0.25)`` → ``get_nowait``
batch drain → buffered append to the date-stamped
``corr-YYYY-MM-DD.jsonl`` (UTC), flush per batch. Rollover = close+open
a new dated file, NO rename (Windows-safe, spec §6.3); prune at startup
+ rollover; per-day MB guard; queue overflow = drop + count + recovery
marker (spec §6.1, D19 — NOT an engine_events row). ``start()`` is
called from the ``main.py`` lifespan BEFORE ``start_background_tasks``;
``close()`` from lifespan teardown (sentinel → drain → flush → join).

Import discipline: this module imports ONLY stdlib + ``config``. It will
be imported by low-level modules (event_bus, adapters, db_orders,
data_cache), so any engine-side import here is a cycle landmine — the
``app_state`` read in ``_resolve_account_id`` is deliberately
function-level for that reason.

Redaction model limit (for tap authors): ``_redact`` is KEY-based — a
secret embedded in a plain string value (``["Authorization: Bearer X"]``)
or in an object's ``str()`` is invisible to it. Taps MUST pass
dict-shaped headers/params and pre-summarized args, never raw
request/exchange objects (re-checked by the T5 redaction audit).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import math
import os
import queue
import re
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, Optional

import config

logger = logging.getLogger("correlation_log")

# ── corr_id (spec §3) ────────────────────────────────────────────────────────

corr_id_var: ContextVar[str] = ContextVar("corr_id", default="")


def mint(prefix: str) -> str:
    """New chain id: ``{prefix}-{8 hex}`` (spec §3.2). Not a security token."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def current_corr_id() -> str:
    """The ambient chain id; ``""`` outside any scope."""
    return corr_id_var.get()


@contextmanager
def correlation_scope(prefix: str = "", *, corr_id: Optional[str] = None) -> Iterator[str]:
    """Bind a chain id for the duration of the block (mint+reset symmetric).

    Entry points pass a ``prefix`` to mint a fresh id; queue-consumer
    re-binding (spec §6.2 — the bus dispatch loop, the webhook worker)
    passes the carried id via ``corr_id=`` instead.
    """
    cid = corr_id if corr_id is not None else mint(prefix)
    token = corr_id_var.set(cid)
    try:
        yield cid
    finally:
        corr_id_var.reset(token)


# ── category registry (spec §5.8) ────────────────────────────────────────────
# category → group; profiles are DERIVED from groups so a future category
# can never be silently absent from the `linkage` profile (the rev-1 drift
# trap). Adding a tap = one register() line here + a `# corr-tap:` anchor
# at the callsite. The conformance test asserts emitted ⊆ registry.

GROUP_HTTP = "http"
GROUP_MARKET = "market"
GROUP_LIFECYCLE = "lifecycle"
GROUP_STATE = "state"
GROUP_ATTR = "attr"
GROUP_BUS = "bus"
GROUP_WS_LIFECYCLE = "ws_lifecycle"
GROUP_OUTBOUND = "outbound"
GROUP_DB = "db"
# Sink self-describing envelopes (overflow markers etc.) — always on in any
# non-off profile; not part of the spec §5 boundary taxonomy.
GROUP_META = "meta"

_REGISTRY: Dict[str, str] = {}


def register(category: str, group: str) -> str:
    """Register a category under a group. Returns the category (constant idiom).

    Re-registering under a DIFFERENT group raises at import: a silent
    re-group would move the category in/out of the `linkage` profile —
    exactly the §5.8 drift class the registry exists to kill.
    """
    existing = _REGISTRY.get(category)
    if existing is not None and existing != group:
        raise ValueError(
            f"correlation-log category {category!r} already registered "
            f"under group {existing!r} (attempted {group!r})"
        )
    _REGISTRY[category] = group
    return category


# §5.1 HTTP
CAT_HTTP_REQUEST = register("http_request", GROUP_HTTP)
CAT_HTTP_RESPONSE = register("http_response", GROUP_HTTP)
# §5.2 event_bus
CAT_BUS_PUBLISH = register("bus_publish", GROUP_BUS)
CAT_BUS_DELIVER = register("bus_deliver", GROUP_BUS)
# §5.3 venue REST + §5.3b other outbound HTTP
CAT_REST_CALL = register("rest_call", GROUP_OUTBOUND)
CAT_REST_RETURN = register("rest_return", GROUP_OUTBOUND)
CAT_HTTP_OUT_CALL = register("http_out_call", GROUP_OUTBOUND)
CAT_HTTP_OUT_RETURN = register("http_out_return", GROUP_OUTBOUND)
# §5.4 inbound WS frames
CAT_WS_ACCOUNT_UPDATE = register("ws_account_update", GROUP_LIFECYCLE)
CAT_WS_ORDER_UPDATE = register("ws_order_update", GROUP_LIFECYCLE)
CAT_WS_ALGO_UPDATE = register("ws_algo_update", GROUP_LIFECYCLE)
CAT_PLATFORM_FILL = register("platform_fill", GROUP_LIFECYCLE)
CAT_PLATFORM_SNAPSHOT = register("platform_snapshot", GROUP_LIFECYCLE)
CAT_PLATFORM_HELLO = register("platform_hello", GROUP_LIFECYCLE)
CAT_PLATFORM_PUSH = register("platform_push", GROUP_LIFECYCLE)
CAT_WS_NEWS = register("ws_news", GROUP_MARKET)
CAT_WS_KLINE = register("ws_kline", GROUP_MARKET)
CAT_WS_DEPTH = register("ws_depth", GROUP_MARKET)
CAT_WS_MARK_PRICE = register("ws_mark_price", GROUP_MARKET)
# §5.7 UI pub/sub — volume-gated like market data, hence the market group
# (also keeps it out of the `linkage` profile).
CAT_PUBSUB_PUBLISH = register("pubsub_publish", GROUP_MARKET)
# §5.4b WS connection lifecycle
CAT_WS_CONNECT = register("ws_connect", GROUP_WS_LIFECYCLE)
CAT_WS_CONNECTED = register("ws_connected", GROUP_WS_LIFECYCLE)
CAT_WS_DISCONNECT = register("ws_disconnect", GROUP_WS_LIFECYCLE)
CAT_WS_STREAM_REBUILD = register("ws_stream_rebuild", GROUP_WS_LIFECYCLE)
CAT_CALC_SYMBOL_CHANGE = register("calc_symbol_change", GROUP_WS_LIFECYCLE)
CAT_WS_LISTENKEY_KEEPALIVE = register("ws_listenkey_keepalive", GROUP_WS_LIFECYCLE)
# §5.5 state mutation + persistence
CAT_POSITION_SNAPSHOT_APPLIED = register("position_snapshot_applied", GROUP_STATE)
CAT_POSITION_INCREMENTAL_APPLIED = register("position_incremental_applied", GROUP_STATE)
CAT_ACCOUNT_UPDATE_APPLIED = register("account_update_applied", GROUP_STATE)
CAT_PORTFOLIO_RECALCULATED = register("portfolio_recalculated", GROUP_STATE)
CAT_CALC_TRANSITION = register("calc_transition", GROUP_STATE)
CAT_LINK_TRANSITION = register("link_transition", GROUP_STATE)
CAT_ORDER_STATUS_APPLIED = register("order_status_applied", GROUP_STATE)
CAT_RECONCILE_PROMOTE = register("reconcile_promote", GROUP_STATE)
CAT_DB_WRITE = register("db_write", GROUP_DB)
# §5.6 attribution decisions (the nine)
CAT_ATTR_MATCH_ATTEMPT = register("attr_match_attempt", GROUP_ATTR)
CAT_ATTR_TPID_RESOLVE = register("attr_tpid_resolve", GROUP_ATTR)
CAT_ATTR_CLOSE_BUILD = register("attr_close_build", GROUP_ATTR)
CAT_ATTR_BRACKET_INHERIT = register("attr_bracket_inherit", GROUP_ATTR)
CAT_ATTR_REENRICH_TRIGGER = register("attr_reenrich_trigger", GROUP_ATTR)
CAT_ATTR_JUNCTION_FORM = register("attr_junction_form", GROUP_ATTR)
CAT_ATTR_ENRICH = register("attr_enrich", GROUP_ATTR)
CAT_ATTR_DRIFT_CHECK = register("attr_drift_check", GROUP_ATTR)
CAT_ATTR_FUNDING_ASSIGN = register("attr_funding_assign", GROUP_ATTR)
# meta
CAT_OVERFLOW = register("overflow", GROUP_META)

# Profiles = group sets (spec §7.3). `linkage` carries the full debugging
# signal (attr/state/db/bus/ws_lifecycle + the lifecycle frames that trigger
# them); market + http + outbound are the volume/noise groups it drops.
_PROFILES: Dict[str, frozenset] = {
    "full": frozenset({
        GROUP_HTTP, GROUP_MARKET, GROUP_LIFECYCLE, GROUP_STATE, GROUP_ATTR,
        GROUP_BUS, GROUP_WS_LIFECYCLE, GROUP_OUTBOUND, GROUP_DB, GROUP_META,
    }),
    "linkage": frozenset({
        GROUP_LIFECYCLE, GROUP_STATE, GROUP_ATTR, GROUP_BUS,
        GROUP_WS_LIFECYCLE, GROUP_DB, GROUP_META,
    }),
    "off": frozenset(),
}

# Per-category default-off within an enabled group (spec §7.3): depth is
# pure noise unless explicitly chased; mark-price is opt-in via the sample
# knob (0 = drop).
_CATEGORY_DEFAULT_OFF = frozenset({CAT_WS_DEPTH})

_enabled: bool = bool(config.CORR_LOG_ENABLED)
if config.CORR_LOG_PROFILE in _PROFILES:
    _profile: str = config.CORR_LOG_PROFILE
else:
    logger.error(
        "CORR_LOG_PROFILE=%r unknown (expected one of %s) — falling back to 'full'",
        config.CORR_LOG_PROFILE, sorted(_PROFILES),
    )
    _profile = "full"

_mark_price_sample: int = max(0, int(config.CORR_LOG_MARK_PRICE_SAMPLE))


def enabled(category: str) -> bool:
    """Is this category currently emitted? PURE — safe to call any number of
    times (the documented pre-gate pattern ``if enabled(c): emit(...)`` must
    not perturb anything; the 1-in-N sampling draw happens once, inside
    ``emit``). Raises on an unregistered category (fail-loud — the
    conformance precursor; ``emit`` converts the raise into a
    once-per-category error log so a typo can never stall the engine)."""
    group = _REGISTRY.get(category)
    if group is None:
        raise ValueError(f"unregistered correlation-log category: {category!r}")
    if not _enabled:
        return False
    if group not in _PROFILES[_profile]:
        return False
    if category in _CATEGORY_DEFAULT_OFF:
        return False
    if category == CAT_WS_MARK_PRICE and _mark_price_sample <= 0:
        return False
    return True


def _sample_rate(category: str) -> int:
    """Per-category keep-1-in-N rate; 0/1 = keep every enabled hit.

    Generalized so future sampled categories (pubsub_publish, plan 2b.4/5.1)
    plug in here rather than special-casing emit.
    """
    if category == CAT_WS_MARK_PRICE:
        return _mark_price_sample
    return 1


# One atomic counter per sampled category, consumed ONLY by emit (never by
# enabled() — the audit's finding 1: a draw inside enabled() makes the
# pre-gate pattern consume the draw and deterministically skip every emit).
_sample_counters: Dict[str, Any] = {}


def _sample_pass(category: str) -> bool:
    rate = _sample_rate(category)
    if rate <= 1:
        return True
    counter = _sample_counters.get(category)
    if counter is None:
        counter = _sample_counters.setdefault(category, itertools.count(1))
    return next(counter) % rate == 0


# ── envelope + emit (spec §4, §6.1) ──────────────────────────────────────────

# Module-level at import (spec §6.5): emits from requests served before
# startup completes simply buffer until the writer thread drains them.
# Items are pre-serialized line strings; None is the shutdown sentinel.
_queue: queue.SimpleQueue = queue.SimpleQueue()
_seq = itertools.count(1)  # next() is atomic under the GIL — true emit order

# Envelope fields are small and bounded (~hundreds of bytes); the payload cap
# is enforced on the single serialized line with this fixed allowance.
_ENVELOPE_ALLOWANCE = 512

_REDACTED = "[REDACTED]"
# Substring match on normalized keys (lower, -/_ stripped). "token" also
# catches platform_token / access_token; "cookie" catches set-cookie.
_REDACT_KEY_TOKENS = (
    "authorization", "cookie", "apikey", "secret", "signature",
    "listenkey", "password", "token", "privatekey", "credential",
)

_emit_error_logged: set = set()  # categories whose emit failure was already logged


def _redact(obj: Any) -> Any:
    """Replace values of secret-looking keys, recursively (spec §7.2)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            norm = str(k).lower().replace("-", "").replace("_", "")
            if any(tok in norm for tok in _REDACT_KEY_TOKENS):
                out[k] = _REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


def _json_safe(obj: Any) -> Any:
    """Non-finite floats → None, recursively.

    Duplicate of core.context_query.json_safe — duplicated rather than
    imported so this module stays import-cycle-free (context_query pulls
    db/state modules that will themselves import correlation_log for taps).
    Value semantics are frozen; if one changes, change both. This copy
    ADDITIONALLY stringifies non-finite dict KEYS (tap payloads are
    arbitrary; a ``{float("nan"): ...}`` key would crash ``dumps`` with
    ``allow_nan=False`` and drop the whole envelope).
    """
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {
            (str(k) if isinstance(k, float) and not math.isfinite(k) else k):
                _json_safe(v)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def _resolve_task() -> str:
    """Spec §4 `task` rule: asyncio task name on-loop, thread name off-loop.

    ``asyncio.current_task()`` RAISES RuntimeError in a non-loop thread (and
    returns None on a loop outside any task) — both fall back to the thread
    name.
    """
    try:
        t = asyncio.current_task()
    except RuntimeError:
        t = None
    if t is not None:
        return t.get_name()
    return threading.current_thread().name


def _resolve_account_id() -> Optional[int]:
    # Function-level import: cycle-break (module docstring). Best-effort —
    # account_id is nullable by spec §4.
    try:
        from core.state import app_state
        return app_state.active_account_id
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def emit(
    component: str,
    peer: str,
    direction: str,
    category: str,
    payload: Dict[str, Any],
    *,
    account_id: Optional[int] = None,
    symbol: Optional[str] = None,
) -> None:
    """The one public tap (spec §6.1). Non-blocking; never raises.

    Pipeline order is load-bearing:
      1. enabled-check FIRST (a disabled category costs ~a dict lookup;
         callsites with expensive payload *construction* should gate on
         ``enabled(category)`` before building arguments);
      2. envelope build (ts, atomic seq, ambient corr_id, task, scope);
      3. redact + json_safe + ONE json.dumps producing the line string —
         the dumps doubles as the size-cap measurement, and emit-side
         serialization is the mutation snapshot (D16): the drain runs later,
         live dicts mutate; serializing here freezes what this chain saw;
      4. enqueue the string (SimpleQueue — callable from any context).
    """
    try:
        if not enabled(category):
            return
        if not _sample_pass(category):
            return
        envelope: Dict[str, Any] = {
            "ts": _now_iso(),
            "seq": next(_seq),
            "corr_id": corr_id_var.get(),
            "task": _resolve_task(),
            "account_id": account_id if account_id is not None else _resolve_account_id(),
            "symbol": symbol,
            "component": component,
            "peer": peer,
            "direction": direction,
            "category": category,
            "payload": _json_safe(_redact(payload)),
        }
        # default=str: a non-JSON type becomes its str() — an observability
        # log prefers a stringified field over a dropped envelope.
        # NB the size cap below relies on dumps' default ensure_ascii=True:
        # the line is pure ASCII, so len(line) == byte length. Don't change
        # one without the other.
        line = json.dumps(envelope, default=str, allow_nan=False)
        max_len = config.CORR_LOG_MAX_PAYLOAD_BYTES + _ENVELOPE_ALLOWANCE
        if len(line) > max_len:
            # Never silently dropped (spec §7.4): summarise + flag. Key
            # strings are themselves capped so the summary can't blow the
            # cap it exists to enforce.
            envelope["payload"] = {
                "_truncated": True,
                "_bytes": len(line),
                "keys": sorted(str(k)[:64] for k in payload)[:50],
            }
            line = json.dumps(envelope, default=str, allow_nan=False)
        _enqueue(line)
    except Exception:
        # A tap must never stall or crash the engine (D7). Log loudly, once
        # per category, so a broken tap is visible without being fatal.
        # str() + nested guard: even an unhashable/unprintable `category`
        # must not let emit raise.
        try:
            key = str(category)
        except Exception:
            key = "<unprintable-category>"
        if key not in _emit_error_logged:
            _emit_error_logged.add(key)
            logger.exception("correlation-log emit failed (category=%s)", key)


def registry() -> Dict[str, str]:
    """A copy of category → group (conformance tests; corr_tail tooling)."""
    return dict(_REGISTRY)


# ── sink: overflow guard (spec §6.1, D19) ────────────────────────────────────

def _max_inflight() -> int:
    return config.CORR_LOG_MAX_INFLIGHT


_overflow_lock = threading.Lock()
_dropping = False
_dropped = 0
_drop_since = ""


def _meta_line(category: str, payload: Dict[str, Any]) -> str:
    """A sink self-describing envelope (overflow / day-cap markers)."""
    envelope = {
        "ts": _now_iso(),
        "seq": next(_seq),
        "corr_id": corr_id_var.get(),
        "task": _resolve_task(),
        "account_id": None,
        "symbol": None,
        "component": "correlation_log",
        "peer": "internal",
        "direction": "internal",
        "category": category,
        "payload": payload,
    }
    return json.dumps(envelope, default=str, allow_nan=False)


def _enqueue(line: str) -> None:
    """Bounded enqueue: past ``CORR_LOG_MAX_INFLIGHT``, drop + count + ONE
    rate-limited error log per episode; on recovery below the bound, enqueue
    a self-describing ``overflow`` marker with the episode's drop count.
    Normal operation never takes the lock (qsize check only)."""
    global _dropping, _dropped, _drop_since
    if _queue.qsize() >= _max_inflight():
        with _overflow_lock:
            _dropped += 1
            if not _dropping:
                _dropping = True
                _drop_since = _now_iso()
                logger.error(
                    "correlation-log queue overflow (>=%d in flight) — dropping envelopes",
                    _max_inflight(),
                )
        return
    if _dropping:
        marker_payload = None
        with _overflow_lock:
            if _dropping:
                marker_payload = {"reason": "queue_overflow", "dropped": _dropped,
                                  "since": _drop_since, "until": _now_iso()}
                _dropping = False
                _dropped = 0
                _drop_since = ""
        if marker_payload is not None:
            _queue.put_nowait(_meta_line(CAT_OVERFLOW, marker_payload))
    _queue.put_nowait(line)


# ── sink: the writer thread (spec §6.1, §6.3, §6.4) ──────────────────────────
# A dedicated daemon thread, NOT a coroutine: SimpleQueue.get blocks its
# calling thread, so a coroutine drain would stall the event loop, and a
# get_nowait+sleep poll cannot implement a batch wakeup. The thread owns the
# file handle exclusively (no cross-thread handle races).

_FILE_RE = re.compile(r"^corr-(\d{4}-\d{2}-\d{2})\.jsonl$")
_BATCH_MAX = 1000

_writer_thread: Optional[threading.Thread] = None
# Lifecycle: start()/close() are serialized by a lock (check-then-act would
# otherwise allow two writers on one file). The shutdown sentinel is a
# GENERATION-tagged object recreated by every start(): a stale sentinel left
# over from a timed-out close() of a PREVIOUS writer generation is skipped,
# not honored — otherwise the next start()'s fresh thread would consume it
# and exit immediately (silent dead sink; audit finding 2).
_lifecycle_lock = threading.Lock()
_sentinel_gen: object = object()


def _resolve_sink_dir() -> str:
    """The sink directory. A FUNCTION so the test conftest can patch it
    (mirror of the `_resolve_db_path` guard pattern) — config env reads
    happen at import, so an env monkeypatch would land too late."""
    return config.CORR_LOG_DIR


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _retention_days() -> int:
    return config.CORR_LOG_RETENTION_DAYS


def _max_day_bytes() -> int:
    return config.CORR_LOG_MAX_MB_PER_DAY * 1024 * 1024


def _prune(dir_: str) -> None:
    """Delete corr-*.jsonl older than the retention window. Runs at writer
    start + rollover (startup covers engine-down-at-rollover, spec §6.3).
    Only files matching the sink's own date-stamped pattern are touched.
    Cutoff compares ISO date strings (they sort lexicographically)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_retention_days())).strftime("%Y-%m-%d")
    try:
        names = os.listdir(dir_)
    except OSError:
        return
    for name in names:
        m = _FILE_RE.match(name)
        if m and m.group(1) < cutoff:
            try:
                os.remove(os.path.join(dir_, name))
                logger.info("correlation-log pruned %s (retention %dd)", name, _retention_days())
            except OSError:
                logger.warning("correlation-log could not prune %s", name)


def _open_day_file(dir_: str, date_str: str):
    """Open today's file for append; returns (handle, existing_bytes).
    newline="\\n" suppresses Windows \\n→\\r\\n translation so the byte
    accounting (len(line) == bytes, ensure_ascii) stays exact."""
    path = os.path.join(dir_, f"corr-{date_str}.jsonl")
    existing = os.path.getsize(path) if os.path.exists(path) else 0
    fh = open(path, "a", encoding="utf-8", newline="\n")
    return fh, existing


def _writer_loop(my_sentinel: object) -> None:
    """The single writer. ``my_sentinel`` is this generation's shutdown
    token; sentinel objects from older generations (a timed-out close of a
    previous writer) are skipped, never honored.

    Pre-capped-at-open (restart into an already-over-cap day file) logs
    loudly but writes NO new marker — the run that tripped the cap already
    wrote one; the only marker-less over-cap file requires a crash inside
    the cap-trip→marker-write window (accepted)."""
    fh = None
    try:
        dir_ = _resolve_sink_dir()
        os.makedirs(dir_, exist_ok=True)
        _prune(dir_)
        date_str = _today_utc()
        fh, written = _open_day_file(dir_, date_str)
        capped = written > _max_day_bytes()
        if capped:
            logger.error(
                "correlation-log day file already exceeds CORR_LOG_MAX_MB_PER_DAY "
                "(%d MB) at open — discarding today's envelopes", config.CORR_LOG_MAX_MB_PER_DAY,
            )

        def _rotate():
            nonlocal dir_, date_str, fh, written, capped
            fh.flush()
            fh.close()
            dir_ = _resolve_sink_dir()
            os.makedirs(dir_, exist_ok=True)
            _prune(dir_)
            date_str = _today_utc()
            fh, written = _open_day_file(dir_, date_str)
            capped = written > _max_day_bytes()

        stop = False
        while not stop:
            try:
                item = _queue.get(timeout=0.25)
            except queue.Empty:
                if _today_utc() != date_str:
                    _rotate()
                continue
            batch = []
            if isinstance(item, str):
                batch.append(item)
            elif item is my_sentinel:
                stop = True
            # else: stale sentinel from a previous generation — skip it
            while len(batch) < _BATCH_MAX and not stop:
                try:
                    nxt = _queue.get_nowait()
                except queue.Empty:
                    break
                if isinstance(nxt, str):
                    batch.append(nxt)
                elif nxt is my_sentinel:
                    stop = True
                # else: stale sentinel — skip, keep draining
            if _today_utc() != date_str:
                _rotate()
            if batch and not capped:
                data = "\n".join(batch) + "\n"
                fh.write(data)
                written += len(data)
                fh.flush()
                if written > _max_day_bytes():
                    # Loud, once, with a final marker line — then discard
                    # for the rest of the UTC day (spec §6.3, D20).
                    capped = True
                    logger.error(
                        "correlation-log day file exceeded CORR_LOG_MAX_MB_PER_DAY "
                        "(%d MB) — discarding further envelopes for %s",
                        config.CORR_LOG_MAX_MB_PER_DAY, date_str,
                    )
                    fh.write(_meta_line(CAT_OVERFLOW, {
                        "reason": "day_cap",
                        "max_mb": config.CORR_LOG_MAX_MB_PER_DAY,
                        "bytes_written": written,
                    }) + "\n")
                    fh.flush()
        fh.flush()
    except Exception:
        # The engine must never be harmed by its own observability (D7).
        logger.exception("correlation-log writer thread died — sink disabled for this run")
    finally:
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass


def start() -> None:
    """Start the writer thread (idempotent; no-op when CORR_LOG_ENABLED=0).
    Called from the main.py lifespan BEFORE start_background_tasks — the
    sink has zero dependencies on REST/bus/Binance (spec §6.5)."""
    global _writer_thread, _sentinel_gen
    if not _enabled:
        return
    with _lifecycle_lock:
        if _writer_thread is not None and _writer_thread.is_alive():
            return
        _sentinel_gen = object()  # new generation — stale sentinels die
        _writer_thread = threading.Thread(
            target=_writer_loop, args=(_sentinel_gen,),
            name="corr-log-writer", daemon=True,
        )
        _writer_thread.start()


def close(timeout: float = 5.0) -> None:
    """Flush-and-stop (idempotent): sentinel → writer drains the queue →
    flush → close → join. The explicit lifespan-teardown call is the only
    reliable flush trigger — today's teardown cancels no background tasks,
    so a cancellation-based flush would never run (spec §6.5)."""
    global _writer_thread
    with _lifecycle_lock:
        t = _writer_thread
        if t is None or not t.is_alive():
            return
        _queue.put_nowait(_sentinel_gen)
        t.join(timeout)
        if t.is_alive():
            logger.error("correlation-log writer did not stop within %.1fs", timeout)
        else:
            _writer_thread = None
