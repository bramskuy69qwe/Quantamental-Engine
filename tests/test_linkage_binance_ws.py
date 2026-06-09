"""
Calc-linkage on the live Binance-WS (observe-only) path — defects 1 & 2.
Debug session 2026-06-07.

The operator trades directly on Binance; the engine observes via the user-data
WS. Quantower (which supplies a per-position id + TP/SL brackets) is NOT in the
loop, so the linkage chain produced ZERO links: positions_calcs empty,
calc_match_audit empty, every order calc_id/link_status NULL, closed positions
terminal_position_id='' + lifecycle_id NULL.

Defect 1: no terminal_position_id (tpid) minted on the live open. Fix mints a
  deterministic, broker-agnostic tpid in DataCache at the WS-create seam and
  back-fills it onto the entry order in _link_position_calc_on_open.
Defect 2: the matcher never ran because _populate_tp_sl_trigger_prices bailed on
  an empty exchange_position_id. Fix falls back to broker-agnostic bracket
  detection (symbol + position_side + time window) to source TP/SL triggers.

Intent (Rule 8) — these fail if the linkage breaks:
  - the mint is deterministic + broker-agnostic (prefix from source, not a
    literal) and never overwrites a real upstream id (Quantower-path safety);
  - DataCache mints on a live WS open;
  - the bracket fallback populates trigger prices when exchange_position_id is
    empty, so the matcher RUNS (link_status goes from NULL to a decision);
  - the entry order's tpid is back-filled and the positions_calcs junction is
    created on a minted-tpid open.

Run: pytest tests/test_linkage_binance_ws.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.position_grouping import mint_terminal_position_id


# ── Defect 1: mint helper (pure, broker-agnostic, deterministic) ──────────────

class TestMintTerminalPositionId:
    def test_deterministic(self):
        a = mint_terminal_position_id(source="binance_ws", symbol="BTCUSDT", direction="LONG", entry_ms=123)
        b = mint_terminal_position_id(source="binance_ws", symbol="BTCUSDT", direction="LONG", entry_ms=123)
        assert a == b == "binance:BTCUSDT:LONG:123"

    def test_prefix_is_venue_derived_not_hardcoded(self):
        # Prefix comes from the source token — works for ANY adapter.
        assert mint_terminal_position_id(source="binance_ws", symbol="S", direction="LONG", entry_ms=1).startswith("binance:")
        assert mint_terminal_position_id(source="Binance", symbol="S", direction="LONG", entry_ms=1).startswith("binance:")
        assert mint_terminal_position_id(source="mexc_ws", symbol="S", direction="SHORT", entry_ms=1).startswith("mexc:")
        assert mint_terminal_position_id(source="", symbol="S", direction="LONG", entry_ms=1).startswith("live:")

    def test_distinct_across_reopen(self):
        # Different first-open time -> different id (no reuse across close->reopen).
        a = mint_terminal_position_id(source="binance_ws", symbol="S", direction="LONG", entry_ms=1000)
        b = mint_terminal_position_id(source="binance_ws", symbol="S", direction="LONG", entry_ms=2000)
        assert a != b

    def test_no_collision_with_rebuilt_or_bf_prefixes(self):
        mid = mint_terminal_position_id(source="binance_ws", symbol="S", direction="LONG", entry_ms=1)
        assert not mid.startswith("rebuilt:")
        assert not mid.startswith("bf:")

    def test_no_hardcoded_binance_literal_in_source(self):
        # The helper must not hardcode a venue; grep its source.
        import inspect
        src = inspect.getsource(mint_terminal_position_id)
        body = src.split('"""')[-1]  # exclude the docstring (which names binance as an example)
        assert "binance" not in body.lower()


# ── Defect 1: DataCache mints on a live WS open ───────────────────────────────

@pytest.fixture
def restore_app_state():
    """Isolate the global app_state mutations apply_position_update_incremental
    makes (account_state totals) so these DataCache tests can't pollute the
    rest of the suite. (The earlier version of these tests set
    app_state._data_cache = dc and leaked positions into later phase2/phase7
    tests via the app_state.positions property — a real test-pollution bug.)"""
    from core.state import app_state
    saved = (app_state._data_cache,
             app_state.account_state.total_unrealized,
             app_state.account_state.balance_usdt)
    yield
    (app_state._data_cache,
     app_state.account_state.total_unrealized,
     app_state.account_state.balance_usdt) = saved


class TestDataCacheMint:
    @pytest.mark.asyncio
    async def test_mints_tpid_on_live_open(self, restore_app_state):
        from core.data_cache import DataCache, UpdateSource
        # Do NOT assign app_state._data_cache: the DataCache works standalone
        # (reads app_state.account_state / mark_price_cache, writes only its own
        # _positions). Read dc._positions directly to avoid polluting the global.
        dc = DataCache(MagicMock())
        np_pos = SimpleNamespace(symbol="BTCUSDT", side="LONG", size=0.01,
                                 entry_price=70000.0, unrealized_pnl=0.0)
        await dc.apply_position_update_incremental(
            UpdateSource.WS_USER, [np_pos], {}, ts_ms=1775300000000,
        )
        pos = next(p for p in dc._positions if p.ticker == "BTCUSDT" and p.direction == "LONG")
        assert pos.position_id == "binance:BTCUSDT:LONG:1775300000000"

    @pytest.mark.asyncio
    async def test_does_not_override_upstream_id(self, restore_app_state):
        # Quantower-path safety: a real upstream position id is NEVER overwritten.
        from core.data_cache import DataCache, UpdateSource
        dc = DataCache(MagicMock())
        np_pos = SimpleNamespace(symbol="ETHUSDT", side="SHORT", size=1.0,
                                 entry_price=3000.0, unrealized_pnl=0.0,
                                 position_id="QT-OPAQUE-9")
        await dc.apply_position_update_incremental(
            UpdateSource.WS_USER, [np_pos], {}, ts_ms=1775300000000,
        )
        pos = next(p for p in dc._positions if p.ticker == "ETHUSDT" and p.direction == "SHORT")
        assert pos.position_id == "QT-OPAQUE-9"


# ── real-DB fixture ───────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_and_path():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) VALUES (1, 'Test', '{}')"
    )
    await d._conn.commit()
    yield d, tmp.name
    try:
        await d.close()
    except Exception:
        pass
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp.name + ext)
        except OSError:
            pass


def _entry(eid, ts, **kw):
    o = {
        "account_id": 1, "exchange_order_id": eid, "symbol": "BTCUSDT",
        "side": "BUY", "order_type": "market", "status": "filled",
        "price": 0.0, "stop_price": 0.0, "quantity": 0.01, "filled_qty": 0.01,
        "avg_fill_price": 70000.0, "reduce_only": 0, "time_in_force": "GTC",
        "position_side": "BOTH", "exchange_position_id": "",
        "terminal_position_id": "", "source": "binance_ws",
        "created_at_ms": ts, "updated_at_ms": ts,
    }
    o.update(kw)
    return o


# ── Defect 2: bracket fallback populates triggers + matcher runs ──────────────

@pytest.mark.asyncio
async def test_bracket_fallback_populates_triggers_and_runs_matcher(db_and_path):
    db, path = db_and_path
    from core.order_enrichment import enrich_order
    ts = 1775300000000
    entry = _entry("E1", ts)
    tp = _entry("TP1", ts + 500, side="SELL", order_type="take_profit",
                status="new", stop_price=72000.0, avg_fill_price=0.0, reduce_only=1)
    sl = _entry("SL1", ts + 800, side="SELL", order_type="stop_loss",
                status="new", stop_price=68000.0, avg_fill_price=0.0, reduce_only=1)
    await db.upsert_order_batch([entry, tp, sl])

    await enrich_order(entry, path)

    async with db._conn.execute(
        "SELECT tp_trigger_price, sl_trigger_price, link_status "
        "FROM orders WHERE exchange_order_id = 'E1'"
    ) as cur:
        row = await cur.fetchone()
    # Defect-2: triggers sourced via the bracket fallback (empty exchange_position_id).
    assert row[0] == 72000.0
    assert row[1] == 68000.0
    # The matcher RAN — link_status is no longer NULL (it never ran pre-fix).
    assert row[2] is not None


@pytest.mark.asyncio
async def test_naked_entry_no_bracket_stays_deferred(db_and_path):
    # A naked market entry (no TP/SL legs) has no bracket -> triggers stay NULL
    # -> matcher correctly stays deferred (spec: can't satisfy 6/6). No audit explosion.
    db, path = db_and_path
    from core.order_enrichment import enrich_order
    ts = 1775300000000
    entry = _entry("N1", ts)
    await db.upsert_order_batch([entry])

    await enrich_order(entry, path)

    async with db._conn.execute(
        "SELECT tp_trigger_price, sl_trigger_price FROM orders WHERE exchange_order_id = 'N1'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] is None and row[1] is None
    async with db._conn.execute("SELECT COUNT(*) FROM calc_match_audit") as cur:
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_ambiguous_multi_entry_cluster_bails(db_and_path):
    # Ambiguity guard: two sets of ACTIVE TP/SL for the same (symbol, position_side)
    # — i.e. >1 distinct active TP (and SL) trigger — must make the fallback BAIL
    # (triggers stay NULL -> matcher defers) rather than assign the wrong trade's
    # TP/SL to this entry. (Can't happen with a single open position, but a
    # stale-active leftover could.)
    db, path = db_and_path
    from core.order_enrichment import enrich_order
    ts = 1775300000000
    e1 = _entry("ME1", ts, position_side="LONG")
    e1tp = _entry("ME1TP", ts + 100, side="SELL", order_type="take_profit",
                  status="new", stop_price=72000.0, avg_fill_price=0.0, reduce_only=1, position_side="LONG")
    e1sl = _entry("ME1SL", ts + 200, side="SELL", order_type="stop_loss",
                  status="new", stop_price=68000.0, avg_fill_price=0.0, reduce_only=1, position_side="LONG")
    e2 = _entry("ME2", ts + 500, position_side="LONG")
    e2tp = _entry("ME2TP", ts + 600, side="SELL", order_type="take_profit",
                  status="new", stop_price=75000.0, avg_fill_price=0.0, reduce_only=1, position_side="LONG")
    e2sl = _entry("ME2SL", ts + 700, side="SELL", order_type="stop_loss",
                  status="new", stop_price=69000.0, avg_fill_price=0.0, reduce_only=1, position_side="LONG")
    await db.upsert_order_batch([e1, e1tp, e1sl, e2, e2tp, e2sl])

    await enrich_order(e1, path)

    async with db._conn.execute(
        "SELECT tp_trigger_price, sl_trigger_price FROM orders WHERE exchange_order_id = 'ME1'"
    ) as cur:
        row = await cur.fetchone()
    # Bailed on the ambiguous 2-entry cluster — did NOT take ME2's 75000/69000.
    assert row[0] is None and row[1] is None


@pytest.mark.asyncio
async def test_end_to_end_linked_via_bracket(db_and_path):
    # The full payoff: a Binance-WS entry (empty exchange_position_id) with a
    # bracket and a MATCHING calc links end-to-end -> calc_id + LINKED + audit.
    db, path = db_and_path
    from core.order_enrichment import enrich_order
    from datetime import datetime, timezone
    ts = 1775300000000
    iso = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(calc_id, account_id, ticker, side, effective_entry, average, "
        " tp_price, sl_price, status, window_seconds, eligible, timestamp) "
        "VALUES ('LNK1', 1, 'BTCUSDT', 'long', 70000.0, 70000.0, "
        " 72000.0, 68000.0, 'active', 300, 1, ?)",
        (iso,),
    )
    await db._conn.commit()
    entry = _entry("L1", ts)  # BUY market, avg_fill_price=70000 (matches effective_entry)
    tp = _entry("LTP", ts + 300, side="SELL", order_type="take_profit",
                status="new", stop_price=72000.0, avg_fill_price=0.0, reduce_only=1)
    sl = _entry("LSL", ts + 600, side="SELL", order_type="stop_loss",
                status="new", stop_price=68000.0, avg_fill_price=0.0, reduce_only=1)
    await db.upsert_order_batch([entry, tp, sl])

    await enrich_order(entry, path)

    async with db._conn.execute(
        "SELECT calc_id, link_status FROM orders WHERE exchange_order_id = 'L1'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "LNK1"      # full 6/6 match -> calc_id written (the whole point)
    assert row[1] == "LINKED"    # link_status LINKED
    async with db._conn.execute(
        "SELECT COUNT(*) FROM calc_match_audit WHERE calc_id = 'LNK1'"
    ) as cur:
        assert (await cur.fetchone())[0] > 0  # per-criterion decision trace recorded


# ── Defect 1: order tpid back-fill + junction creation on a minted-tpid open ──

@pytest.mark.asyncio
async def test_order_tpid_backfilled_on_open(db_and_path):
    # Even an UNLINKED order (calc_id NULL) gets its tpid back-filled so
    # reverse-query can find it under the position.
    db, path = db_and_path
    from core.order_manager import OrderManager
    om = OrderManager(db)
    tpid = "binance:BTCUSDT:LONG:1775300000000"
    await db.upsert_order_batch([_entry("BF1", 1775300000000)])

    fill = {
        "account_id": 1, "exchange_order_id": "BF1", "terminal_position_id": tpid,
        "is_close": 0, "symbol": "BTCUSDT", "direction": "LONG",
        "quantity": 0.01, "price": 70000.0, "timestamp_ms": 1775300000000,
    }
    await om._link_position_calc_on_open(1, fill)

    async with db._conn.execute(
        "SELECT terminal_position_id FROM orders WHERE exchange_order_id = 'BF1'"
    ) as cur:
        assert (await cur.fetchone())[0] == tpid


@pytest.mark.asyncio
async def test_junction_created_with_minted_tpid(db_and_path):
    db, path = db_and_path
    from core.order_manager import OrderManager
    om = OrderManager(db)
    tpid = "binance:BTCUSDT:LONG:1775300000000"
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(calc_id, ticker, side, status, size, tp_price, sl_price, timestamp, eligible) "
        "VALUES ('C1', 'BTCUSDT', 'LONG', 'matched', 0.01, 72000.0, 68000.0, "
        "'2026-06-07T00:00:00+00:00', 1)"
    )
    await db.upsert_order_batch([_entry("J1", 1775300000000)])
    # calc_id is not part of upsert_order_batch's columns (matcher sets it separately)
    await db._conn.execute(
        "UPDATE orders SET calc_id = 'C1' WHERE exchange_order_id = 'J1' AND account_id = 1"
    )
    await db._conn.commit()

    fill = {
        "account_id": 1, "exchange_order_id": "J1", "terminal_position_id": tpid,
        "is_close": 0, "symbol": "BTCUSDT", "direction": "LONG",
        "quantity": 0.01, "price": 70000.0, "timestamp_ms": 1775300000000,
    }
    await om._link_position_calc_on_open(1, fill)

    # tpid back-filled onto the order
    async with db._conn.execute(
        "SELECT terminal_position_id FROM orders WHERE exchange_order_id = 'J1'"
    ) as cur:
        assert (await cur.fetchone())[0] == tpid
    # junction row created keyed on the minted tpid
    async with db._conn.execute(
        "SELECT calc_id FROM positions_calcs WHERE position_id = ? AND calc_id = 'C1'",
        (tpid,),
    ) as cur:
        assert (await cur.fetchone()) is not None


# ── Defect 4: effective_entry is the entry PRICE, not the (1 - slippage) factor ──

def test_effective_entry_is_a_price_not_factor(monkeypatch):
    """Defect-4 (debug 2026-06-08): risk_engine must write effective_entry as the
    slippage-adjusted ENTRY PRICE (= est_fill_price) — the value calc_correlation
    matches an order's fill price against. It previously stored `1 - est_slippage`
    (~1.0 for any real-priced asset), so the matcher's entry criterion could never
    pass on the live path -> zero auto-links. This fails if the factor regresses."""
    from unittest.mock import MagicMock
    import core.risk_engine as re

    monkeypatch.setattr("core.monitoring.ReadyStateEvaluator",
                        lambda: MagicMock(evaluate=lambda: (True, "")))
    monkeypatch.setattr(re, "calculate_atr_coefficient",
                        lambda sym: (0.5, "normal", 1.0, 1.0))
    # known (est_slippage, est_fill_price) — fill price is a real ~0.2336 price
    monkeypatch.setattr(re, "calculate_slippage", lambda *a, **k: (0.001, 0.2336))
    monkeypatch.setattr(re, "app_state",
                        MagicMock(params={"individual_risk_per_trade": 0.01}))

    res = re.calculate_position_size(
        symbol="VELVETUSDT", average=0.234, sl_price=0.230,
        total_equity=100.0, side="long",
    )
    # effective_entry is the slippage-adjusted price, equal to est_fill_price...
    assert res["effective_entry"] == res["est_fill_price"] == 0.2336
    # ...and emphatically NOT the old ~1.0 (1 - est_slippage) factor.
    assert abs(res["effective_entry"] - 1.0) > 0.5


# ── Defect 6: observe-path TP/SL child re-enriches its parent entry ──

@pytest.mark.asyncio
async def test_observe_path_child_reenriches_parent(db_and_path, monkeypatch):
    """Defect-6 (debug 2026-06-08): when a TP/SL child with NO venue
    exchange_position_id arrives, the parent entry must be re-enriched (by
    symbol+position_side) so its tp/sl_trigger_price populate and the matcher
    can run. Without it, a market entry that fills BEFORE its bracket lands
    never gets its triggers -> never links. (Found in live verification.)"""
    db, path = db_and_path
    import config
    monkeypatch.setattr(config, "DB_PATH", path)
    from core.order_manager import OrderManager
    om = OrderManager(db)
    ts = 1775300000000
    entry = _entry("PE1", ts)  # BUY market, exchange_position_id="", position_side="BOTH"
    tp = _entry("PTP", ts + 1, side="SELL", order_type="take_profit",
                status="new", stop_price=72000.0, avg_fill_price=0.0, reduce_only=1)
    sl = _entry("PSL", ts + 2, side="SELL", order_type="stop_loss",
                status="new", stop_price=68000.0, avg_fill_price=0.0, reduce_only=1)
    await db.upsert_order_batch([entry, tp, sl])

    # The TP child arrives -> should re-enrich the parent entry via the
    # (symbol, position_side) fallback (no exchange_position_id).
    await om._re_enrich_parent_on_child_arrival(1, tp)

    async with db._conn.execute(
        "SELECT tp_trigger_price, sl_trigger_price FROM orders WHERE exchange_order_id = 'PE1'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 72000.0 and row[1] == 68000.0


# ── Defect 7: junction forms via the order's tpid when the fill's is empty ──

@pytest.mark.asyncio
async def test_junction_forms_when_fill_tpid_empty_via_order(db_and_path):
    """Defect-7 (debug 2026-06-08, fill-before-mint race): the opening fill can
    beat the position mint -> fill.terminal_position_id is empty, but the entry
    ORDER carries the minted tpid. The positions_calcs junction must still form
    (using the order's tpid) so the Position-History drilldown lights up. Found
    in live verification: the order LINKED but the junction stayed empty."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    om = OrderManager(db)
    tpid = "binance:ETHUSDT:LONG:1780858800000"
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(calc_id, account_id, ticker, side, status, size, tp_price, sl_price, "
        " timestamp, eligible) "
        "VALUES ('C7', 1, 'ETHUSDT', 'long', 'matched', 0.01, 1700.0, 1590.0, "
        "'2026-06-07T00:00:00+00:00', 1)"
    )
    await db.upsert_order_batch([_entry("F7", 1780858800000, symbol="ETHUSDT", position_side="LONG")])
    # The entry order carries the minted tpid + a matched calc_id (set the way
    # the engine does, separately from upsert_order_batch).
    await db._conn.execute(
        "UPDATE orders SET terminal_position_id = ?, calc_id = 'C7' "
        "WHERE exchange_order_id = 'F7' AND account_id = 1",
        (tpid,),
    )
    await db._conn.commit()

    # The opening fill arrives with an EMPTY tpid (lost the mint race).
    fill = {
        "account_id": 1, "exchange_order_id": "F7", "terminal_position_id": "",
        "is_close": 0, "symbol": "ETHUSDT", "direction": "LONG",
        "quantity": 0.01, "price": 1629.0, "timestamp_ms": 1780858800000,
    }
    await om._link_position_calc_on_open(1, fill)

    async with db._conn.execute(
        "SELECT calc_id FROM positions_calcs WHERE position_id = ? AND calc_id = 'C7'",
        (tpid,),
    ) as cur:
        assert (await cur.fetchone()) is not None


# ── Defect 8: junction (re)created when the matcher links AFTER the fill ──

@pytest.mark.asyncio
async def test_junction_ensured_when_matcher_links_after_fill(db_and_path):
    """Defect-8 (debug 2026-06-08): on the observe path the matcher sets calc_id
    AFTER the opening fill (once the TP/SL bracket arrives), so the fill-time
    junction creation was skipped (calc_id was NULL then) and nothing re-created
    it -> order LINKED but positions_calcs empty (the live symptom). The
    junction must be (re)created once the order is linked."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    om = OrderManager(db)
    tpid = "binance:ETHUSDT:LONG:1780858800000"
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(calc_id, account_id, ticker, side, status, size, tp_price, sl_price, "
        " timestamp, eligible) "
        "VALUES ('C8', 1, 'ETHUSDT', 'long', 'matched', 0.01, 1700.0, 1590.0, "
        "'2026-06-07T00:00:00+00:00', 1)"
    )
    await db.upsert_order_batch([_entry("F8", 1780858800000, symbol="ETHUSDT", position_side="LONG")])
    # Order is now linked (matcher set calc_id) + carries the minted tpid, and an
    # opening fill already exists (it arrived BEFORE the link).
    await db._conn.execute(
        "UPDATE orders SET terminal_position_id = ?, calc_id = 'C8' "
        "WHERE exchange_order_id = 'F8' AND account_id = 1",
        (tpid,),
    )
    await db.upsert_fill({
        "account_id": 1, "exchange_fill_id": "fill-F8", "exchange_order_id": "F8",
        "symbol": "ETHUSDT", "side": "BUY", "direction": "LONG", "price": 1629.0,
        "quantity": 0.01, "is_close": 0, "terminal_position_id": tpid,
        "timestamp_ms": 1780858800000,
    })
    await db._conn.commit()

    # Precondition: no junction was formed at fill time (calc_id was NULL then).
    async with db._conn.execute("SELECT COUNT(*) FROM positions_calcs") as cur:
        assert (await cur.fetchone())[0] == 0

    # The matcher having linked the order -> the junction must now be ensured.
    await om._ensure_junction_if_linked(1, "F8")

    async with db._conn.execute(
        "SELECT calc_id FROM positions_calcs WHERE position_id = ? AND calc_id = 'C8'",
        (tpid,),
    ) as cur:
        assert (await cur.fetchone()) is not None


# ── Unminted-snapshot recovery: re-derive tpid for a snapshot-seeded position ──

@pytest.mark.asyncio
async def test_snapshot_position_recovers_tpid_and_links(db_and_path):
    """Unminted-snapshot recovery (debug 2026-06-08): a position first seen via a
    REST snapshot (engine restarted while it was already open) has an EMPTY
    position_id — the snapshot path doesn't mint (no stable first-open time). Its
    entry order still carries the WS-minted tpid and the positions_calcs junction
    is keyed on it. The live enrichment must re-derive the tpid from the entry
    order so the position re-acquires its calc linkage (and the cockpit Plan
    badge) instead of rendering a blank cell. This was the visible bug: XAUUSDT
    LONG open + linked in the DB, but blank Plan column after a restart."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    from core.state import PositionInfo
    om = OrderManager(db)
    tpid = "binance:BTCUSDT:LONG:1775300000000"
    # Persisted entry order carries the minted tpid (back-filled on open).
    # position_side="LONG" = hedge mode (the operator's live config); the
    # recovery keys on (symbol, direction) so a one-way "BOTH" order wouldn't
    # match — that's the documented latent one-way gap, not this path.
    await db.upsert_order_batch([_entry("S1", 1775300000000, position_side="LONG")])
    await db._conn.execute(
        "UPDATE orders SET terminal_position_id = ? "
        "WHERE exchange_order_id = 'S1' AND account_id = 1",
        (tpid,),
    )
    # Junction keyed on the minted tpid (formed at open, survives restart).
    await db._conn.execute(
        "INSERT INTO positions_calcs "
        "(account_id, position_id, calc_id, order_id, contributed_qty, planned_size, first_fill_ts) "
        "VALUES (1, ?, 'CS1', 1, 0.01, 0.01, 1775300000000)",
        (tpid,),
    )
    await db._conn.commit()

    # Snapshot-seeded live position: empty position_id (the bug precondition).
    pos = PositionInfo(ticker="BTCUSDT", direction="LONG", contract_amount=0.01)
    assert pos.position_id == ""
    await om._enrich_positions_calc_id(1, [pos])

    # tpid recovered from the entry order...
    assert pos.position_id == tpid
    # ...so the junction links it: calc_id stamped + a real (non-empty) badge.
    assert pos.calc_id == "CS1"
    assert pos.deviation_badge != ""   # the visible fix: Plan column no longer blank


@pytest.mark.asyncio
async def test_snapshot_no_entry_order_stays_unlinked(db_and_path):
    """Negative: a snapshot position with NO recoverable entry order (truly no
    prior link) keeps its empty position_id and isn't force-linked. Guards the
    recovery from inventing a tpid for a genuinely unlinked position."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    from core.state import PositionInfo
    om = OrderManager(db)
    pos = PositionInfo(ticker="NOPEUSDT", direction="LONG", contract_amount=1.0)
    await om._enrich_positions_calc_id(1, [pos])
    assert pos.position_id == ""
    assert pos.calc_id == ""


# ── Follow-up ⑨: close-side tpid resolution (closing fill arrives empty) ──

@pytest.mark.asyncio
async def test_close_tpid_resolved_from_live_position(db_and_path):
    """⑨ tier-1 (debug 2026-06-08): a closing fill that arrives with an empty
    terminal_position_id resolves it from the live PositionInfo being closed
    (which carries the snapshot-recovered tpid), so the closed_positions row,
    close events, and calc/lifecycle attribution don't lose position identity."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    from core.state import app_state, PositionInfo
    om = OrderManager(db)
    tpid = "binance:ETHUSDT:LONG:1780000000000"
    saved_dc, saved_pos = app_state._data_cache, app_state._positions_legacy
    try:
        app_state._data_cache = None
        app_state.positions = [PositionInfo(ticker="ETHUSDT", direction="LONG",
                                            contract_amount=0.01, position_id=tpid)]
        fill = {"account_id": 1, "symbol": "ETHUSDT", "direction": "LONG",
                "is_close": 1, "terminal_position_id": ""}
        assert await om._resolve_close_tpid(1, fill) == tpid
    finally:
        app_state._data_cache, app_state._positions_legacy = saved_dc, saved_pos


@pytest.mark.asyncio
async def test_close_tpid_resolved_from_entry_order_when_position_gone(db_and_path):
    """⑨ tier-2 (full-close race): the ACCOUNT_UPDATE that REMOVES the position
    beats the TRADE event, so the live position is gone -> fall back to the
    persisted entry order's minted tpid (which survives the removal)."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    from core.state import app_state
    om = OrderManager(db)
    tpid = "binance:ETHUSDT:LONG:1780000000000"
    await db.upsert_order_batch([_entry("EO9", 1780000000000, symbol="ETHUSDT",
                                        position_side="LONG")])
    await db._conn.execute(
        "UPDATE orders SET terminal_position_id = ? "
        "WHERE exchange_order_id='EO9' AND account_id=1",
        (tpid,),
    )
    await db._conn.commit()
    saved_dc, saved_pos = app_state._data_cache, app_state._positions_legacy
    try:
        app_state._data_cache = None
        app_state.positions = []   # position already removed from the snapshot
        fill = {"account_id": 1, "symbol": "ETHUSDT", "direction": "LONG",
                "is_close": 1, "terminal_position_id": ""}
        assert await om._resolve_close_tpid(1, fill) == tpid
    finally:
        app_state._data_cache, app_state._positions_legacy = saved_dc, saved_pos


@pytest.mark.asyncio
async def test_close_tpid_unresolvable_returns_empty(db_and_path):
    """⑨ negative: no live position + no entry order -> "" (genuine one-way /
    unlinked path unchanged; the resolution never invents a tpid)."""
    db, path = db_and_path
    from core.order_manager import OrderManager
    from core.state import app_state
    om = OrderManager(db)
    saved_dc, saved_pos = app_state._data_cache, app_state._positions_legacy
    try:
        app_state._data_cache = None
        app_state.positions = []
        fill = {"account_id": 1, "symbol": "NOPEUSDT", "direction": "LONG",
                "is_close": 1, "terminal_position_id": ""}
        assert await om._resolve_close_tpid(1, fill) == ""
    finally:
        app_state._data_cache, app_state._positions_legacy = saved_dc, saved_pos
