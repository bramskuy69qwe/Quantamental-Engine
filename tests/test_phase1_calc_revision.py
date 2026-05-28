"""
Phase 1 Task 3 (P1.T3 / plan §1 task 1.5) — calc-revision detection.

Pins the supersede semantics:

- Operator clicks Calculate twice for the same ``(account_id, ticker,
  side)`` → the OLD calc transitions ``active → superseded``, with
  ``superseded_by_calc_id`` pointing at the NEW calc.
- ``calc:superseded`` event fires through ``calc_state.transition``.
- Side normalization (T211 H1): a prior calc with ``side='long'`` IS
  superseded by a new calc with ``side='LONG'``.
- Different side / different ticker / non-active status → no supersede.

Why this matters: without supersede, multiple ``active`` calcs would
accumulate for the same key, and the matcher's "most-recent wins"
tie-break would silently pick one — but the others would still pollute
the candidate set on subsequent matcher invocations. Supersede is the
clean lifecycle exit for stale calcs.

Run: pytest tests/test_phase1_calc_revision.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
        (1, "Test"),
    )
    await db._conn.commit()
    yield db, tmp.name
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest_asyncio.fixture
async def wired_handlers(db, monkeypatch):
    """Wire core.handlers.db to point at the test DB."""
    d, db_path = db
    from core import handlers
    monkeypatch.setattr(handlers, "db", d)
    yield handlers, d, db_path


async def _insert_calc(db, **kwargs) -> None:
    """Insert a calc row via the DB helper (writes status, window_seconds, etc.)."""
    await db.insert_pre_trade_log({
        "account_id":      kwargs.get("account_id", 1),
        "timestamp":       kwargs.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "ticker":          kwargs.get("ticker", "BTCUSDT"),
        "side":            kwargs.get("side", "long"),
        "effective_entry": kwargs.get("effective_entry", 50000.0),
        "tp_price":        kwargs.get("tp_price", 55000.0),
        "sl_price":        kwargs.get("sl_price", 48000.0),
        "calc_id":         kwargs.get("calc_id"),
        "status":          kwargs.get("status", "active"),
    })


async def _read_calc(db, calc_id: str) -> Dict[str, Any] | None:
    """Read a calc row by calc_id, return as dict (or None if missing)."""
    async with db._conn.execute(
        "SELECT calc_id, status, superseded_by_calc_id, ticker, side "
        "FROM pre_trade_log WHERE calc_id = ?",
        (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "calc_id":               row[0],
        "status":                row[1],
        "superseded_by_calc_id": row[2],
        "ticker":                row[3],
        "side":                  row[4],
    }


def _drain_events(channel_filter: str | None = None) -> List[tuple]:
    """Drain the event_bus queue, optionally filtering by channel."""
    from core.event_bus import event_bus
    events = []
    while not event_bus._queue.empty():
        events.append(event_bus._queue.get_nowait())
    if channel_filter:
        return [(c, p) for c, p in events if c == channel_filter]
    return events


# ── 1. Supersede the same (account, ticker, side) ─────────────────────


class TestSupersedeBasic:
    """The core flow: new calc with same key supersedes the old."""

    @pytest.mark.asyncio
    async def test_same_key_supersedes(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="old-1", ticker="BTCUSDT", side="long")
        _drain_events()  # clear any stale events

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT",
            "side": "long",
            "effective_entry": 50100.0,  # tweaked values; same key
            "tp_price": 55100.0,
            "sl_price": 48100.0,
            "calc_id": "new-1",
        })

        old = await _read_calc(d, "old-1")
        new = await _read_calc(d, "new-1")

        assert old["status"] == "superseded"
        assert old["superseded_by_calc_id"] == "new-1"
        assert new["status"] == "active"
        assert new["superseded_by_calc_id"] is None

    @pytest.mark.asyncio
    async def test_calc_superseded_event_fires(self, wired_handlers):
        """Spec §9: ``calc:superseded`` event emitted with old_calc_id +
        new_calc_id via calc_state.transition.
        """
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="old-2", ticker="BTCUSDT", side="long")
        _drain_events()

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "new-2",
        })

        events = _drain_events("calc:superseded")
        assert len(events) == 1, f"expected 1 calc:superseded event, got {events!r}"
        channel, payload = events[0]
        assert payload["calc_id"] == "old-2"
        assert payload["new_calc_id"] == "new-2"
        assert payload["from_status"] == "active"
        assert payload["to_status"] == "superseded"
        assert payload.get("reason_note") == "operator_recalc"


# ── 2. No supersede when keys differ ──────────────────────────────────


class TestNoSupersedeOnKeyMismatch:
    """Supersede MUST scope to (account, ticker, side). Mismatched
    keys leave the old calc alone.

    Why this matters: a long-BTC calc must not silently kill a short-BTC
    calc, nor a long-ETH calc. The whole point of supersede is "same
    intent re-stated"; different keys = different intents.
    """

    @pytest.mark.asyncio
    async def test_different_side_no_supersede(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="long-1", ticker="BTCUSDT", side="long")

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT",
            "side": "short",  # opposite side
            "effective_entry": 50000.0, "tp_price": 45000.0, "sl_price": 52000.0,
            "calc_id": "short-1",
        })

        old = await _read_calc(d, "long-1")
        assert old["status"] == "active"  # unchanged
        assert old["superseded_by_calc_id"] is None

    @pytest.mark.asyncio
    async def test_different_ticker_no_supersede(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="btc-1", ticker="BTCUSDT", side="long")

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "ETHUSDT",  # different symbol
            "side": "long",
            "effective_entry": 3000.0, "tp_price": 3500.0, "sl_price": 2800.0,
            "calc_id": "eth-1",
        })

        old = await _read_calc(d, "btc-1")
        assert old["status"] == "active"
        assert old["superseded_by_calc_id"] is None


# ── 3. Only ACTIVE calcs are superseded ───────────────────────────────


class TestOnlyActiveSuperseded:
    """Released, matched, expired, cancelled, completed_via_position —
    none of these are eligible for supersede. The state machine is
    explicit: only ``active → superseded`` is a valid transition (per
    core/calc_state.py CALC_TRANSITIONS).

    Why this matters: a 'released' calc (Phase 1.7 — order cancelled,
    calc back in pool for re-match) is INTENTIONALLY available again.
    A new Calculate click shouldn't kill it; it should sit alongside
    the new active calc. Spec §5 allows both `released` and `active`
    to be matcher candidates.
    """

    @pytest.mark.asyncio
    async def test_released_calc_not_superseded(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="rel-1", ticker="BTCUSDT", side="long",
                            status="released")
        _drain_events()

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "new-rel",
        })

        old = await _read_calc(d, "rel-1")
        assert old["status"] == "released"  # untouched

        # No supersede event fired for the released calc
        events = _drain_events("calc:superseded")
        assert events == []

    @pytest.mark.asyncio
    async def test_matched_calc_not_superseded(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="match-1", ticker="BTCUSDT", side="long",
                            status="matched")

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "new-match",
        })

        old = await _read_calc(d, "match-1")
        assert old["status"] == "matched"

    @pytest.mark.asyncio
    async def test_expired_calc_not_superseded(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="exp-1", ticker="BTCUSDT", side="long",
                            status="expired")

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "new-exp",
        })

        old = await _read_calc(d, "exp-1")
        assert old["status"] == "expired"


# ── 4. Multiple prior active calcs (defensive — shouldn't happen) ─────


class TestMultiplePriorActive:
    """If the DB somehow has multiple active calcs for the same key
    (race lost, manual SQL edit, pre-T214 migration artifact), the
    supersede pass should handle ALL of them.

    Why this matters: drift detection — if there are leftover active
    calcs that supersede missed, the new calc should still take over
    the (key) cleanly and the matcher's candidate pool should shrink
    to just the new one.
    """

    @pytest.mark.asyncio
    async def test_multiple_active_all_superseded(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="multi-1", ticker="BTCUSDT", side="long",
                            timestamp="2026-01-01T00:00:00+00:00")
        await _insert_calc(d, calc_id="multi-2", ticker="BTCUSDT", side="long",
                            timestamp="2026-01-01T00:01:00+00:00")
        _drain_events()

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "new-multi",
        })

        c1 = await _read_calc(d, "multi-1")
        c2 = await _read_calc(d, "multi-2")
        new = await _read_calc(d, "new-multi")
        assert c1["status"] == "superseded"
        assert c1["superseded_by_calc_id"] == "new-multi"
        assert c2["status"] == "superseded"
        assert c2["superseded_by_calc_id"] == "new-multi"
        assert new["status"] == "active"

        # Two supersede events should have fired
        events = _drain_events("calc:superseded")
        assert len(events) == 2


# ── 5. Side-vocabulary normalization (T211 H1 + T214) ─────────────────


class TestCrossAccountIsolation:
    """T215 M1: supersede is scoped per-account. A Calculate on
    account 2 must NOT supersede an active calc on account 1, even for
    the identical (ticker, side).

    Why this matters: calcs are per-account (spec §2.4 / Q22). Without
    the account_id filter in the supersede SELECT, a multi-account
    operator computing the same setup on two accounts would silently
    kill the first account's calc.
    """

    @pytest.mark.asyncio
    async def test_account2_calc_does_not_supersede_account1(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        # Seed account 2 in the same DB (the fixture seeds account 1)
        await d._conn.execute(
            "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
            (2, "Test2"),
        )
        await d._conn.commit()

        # Active calc on account 1
        await _insert_calc(d, account_id=1, calc_id="acct1-calc",
                           ticker="BTCUSDT", side="long")

        # The supersede helper is account-scoped; invoke directly with
        # account_id=2 to simulate a Calculate on the other account.
        await handlers._supersede_prior_active_calcs(
            account_id=2,
            ticker="BTCUSDT",
            side="long",
            new_calc_id="acct2-calc",
        )

        # Account 1's calc must be untouched.
        old = await _read_calc(d, "acct1-calc")
        assert old["status"] == "active"
        assert old["superseded_by_calc_id"] is None


class TestSidesAreNormalized:
    """If a future calculator writes uppercase side, supersede should
    still match against the lowercase prior. T211 H1 already canonicalizes
    in the matcher; this test pins the same behavior at supersede time.

    Why this matters: vocabulary drift between writers would break the
    "same intent" guarantee. A calc with side='long' followed by a
    re-click writing side='LONG' must still trigger supersede.
    """

    @pytest.mark.asyncio
    async def test_long_vs_LONG_supersedes(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="case-1", ticker="BTCUSDT", side="long")

        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT",
            "side": "LONG",  # different casing
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "case-2",
        })

        old = await _read_calc(d, "case-1")
        assert old["status"] == "superseded"
        assert old["superseded_by_calc_id"] == "case-2"


# ── 6. Missing fields (defensive) ─────────────────────────────────────


class TestDefensiveMissingFields:
    """Calls missing calc_id / ticker / side should NOT crash and should
    NOT trigger spurious supersede.
    """

    @pytest.mark.asyncio
    async def test_missing_calc_id_skips_supersede(self, wired_handlers):
        handlers, d, db_path = wired_handlers
        await _insert_calc(d, calc_id="should-survive", ticker="BTCUSDT", side="long")

        # Payload with no calc_id → supersede skipped (can't link)
        await handlers.handle_risk_calculated({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            # no calc_id
        })

        old = await _read_calc(d, "should-survive")
        assert old["status"] == "active"  # untouched
