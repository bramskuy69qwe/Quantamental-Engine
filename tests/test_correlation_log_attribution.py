"""CL.T3b-entry — attribution entry-side taps (spec §5.6).

Covers the four entry-side categories under the three §5.6 mandates
(one envelope per invocation incl. outcome=SKIPPED with a machine-
readable reason and outcome=ERROR on exception paths; identity tuple
VERBATIM including ""; dedup_key of the triggering order/fill):

- attr_match_attempt — the strict matcher's wrapper (every decision,
  every defensive early return distinguishable — query_failed is no
  longer ambiguous with no_candidates_in_window), _try_correlate's
  pre-matcher gates (the historical silent-skip class), and the manual
  operator paths (manual_link / mark_unplanned).
- attr_junction_form — the junction builder's gates (no_position_key is
  the historical empty-tpid shape) + FORMED with the mint-vs-reuse and
  scale-in signals, plus the post-link replay path.
- attr_bracket_inherit — per-leg INHERITED lines + skip reasons + the
  idempotent re-run.
- attr_reenrich_trigger — the child-arrival → parent-re-enrich decision
  (historical bug #g) + the fill-arrival variant.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

import pytest

import core.correlation_log as cl


def _drain():
    out = []
    while True:
        try:
            item = cl._queue.get_nowait()
        except Exception:
            break
        if isinstance(item, str):
            out.append(json.loads(item))
    return out


def _by_cat(envs, cat):
    return [e for e in envs if e["category"] == cat]


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    _drain()
    monkeypatch.setattr(cl, "_enabled", True)
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    yield
    _drain()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _mk_matcher_db(tmp_path, calcs=()):
    """A minimal sqlite file with the tables the matcher path touches."""
    p = str(tmp_path / "matcher.db")
    conn = sqlite3.connect(p)
    conn.execute(
        "CREATE TABLE pre_trade_log ("
        " calc_id TEXT, timestamp TEXT, side TEXT, effective_entry REAL,"
        " tp_price REAL, sl_price REAL, status TEXT, window_seconds INT,"
        " account_id INT, ticker TEXT)",
    )
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, config_json TEXT)")
    conn.execute("INSERT INTO accounts (id, config_json) VALUES (1, NULL)")
    for c in calcs:
        conn.execute(
            "INSERT INTO pre_trade_log (calc_id, timestamp, side,"
            " effective_entry, tp_price, sl_price, status, window_seconds,"
            " account_id, ticker) VALUES (?,?,?,?,?,?,?,?,?,?)",
            c,
        )
    conn.commit()
    conn.close()
    return p


def _order(**kw):
    base = {
        "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
        "order_type": "limit", "price": 100.0, "avg_fill_price": 0.0,
        "tp_trigger_price": 110.0, "sl_trigger_price": 95.0,
        "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
        "exchange_order_id": "E-1", "terminal_position_id": "",
        "lifecycle_id": "", "status": "new", "quantity": 1.0,
    }
    base.update(kw)
    return base


# ── attr_match_attempt: the matcher wrapper (spec §5.6) ─────────────────────

class TestMatchAttemptMatcher:
    def _calc(self, calc_id="CALC-1", tp=110.0, sl=95.0, entry=100.0):
        return (calc_id, _now_iso(), "long", entry, tp, sl, "active", None, 1,
                "BTCUSDT")

    def test_linked_decision_one_envelope_with_trace(self, tmp_path):
        from core.calc_correlation import correlate_order_to_calc

        db = _mk_matcher_db(tmp_path, [self._calc()])
        result = correlate_order_to_calc(
            _order(), order_id=5, tick_size=0.5, db_path=db,
        )
        assert result.calc_id == "CALC-1"
        envs = _by_cat(_drain(), "attr_match_attempt")
        assert len(envs) == 1  # mandate 1: exactly one per invocation
        e = envs[0]
        assert e["component"] == "calc_correlation"
        assert e["symbol"] == "BTCUSDT"
        p = e["payload"]
        assert p["outcome"] == "LINKED"
        assert p["calc_id"] == "CALC-1"
        assert p["candidates"] == [{"calc_id": "CALC-1", "failed": []}]
        assert p["n_prefilter_rows"] == 1
        assert p["dedup_key"] == "E-1:new:1.0"
        assert p["tolerances"]["entry_pct"] == 0.25
        assert p["exchange_order_id"] == "E-1"
        assert p["terminal_position_id"] == ""  # verbatim ""
        assert p["duration_ms"] >= 0

    def test_manual_review_lists_failed_criteria(self, tmp_path):
        from core.calc_correlation import correlate_order_to_calc

        db = _mk_matcher_db(tmp_path, [self._calc(tp=200.0)])
        result = correlate_order_to_calc(
            _order(), order_id=5, tick_size=0.5, db_path=db,
        )
        assert result.link_status == "NEEDS_MANUAL_REVIEW"
        p = _by_cat(_drain(), "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "NEEDS_MANUAL_REVIEW"
        assert p["reason"] == "no_full_match"
        assert p["candidates"] == [{"calc_id": "CALC-1", "failed": ["tp"]}]
        assert p["calc_id"] == ""  # no winner — verbatim ""

    def test_unplanned_zero_candidates_distinct_from_failure(self, tmp_path):
        from core.calc_correlation import correlate_order_to_calc

        db = _mk_matcher_db(tmp_path, [])
        correlate_order_to_calc(_order(), order_id=5, tick_size=0.5, db_path=db)
        p = _by_cat(_drain(), "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "UNPLANNED"
        assert p["reason"] == "no_candidates_in_window"
        assert p["n_prefilter_rows"] == 0

    def test_query_failure_is_skipped_not_unplanned(self, tmp_path):
        from core.calc_correlation import correlate_order_to_calc

        # a DB file WITHOUT pre_trade_log — the query raises; pre-tap this
        # was indistinguishable from a genuine zero-candidate UNPLANNED
        p_db = str(tmp_path / "empty.db")
        sqlite3.connect(p_db).close()
        result = correlate_order_to_calc(
            _order(), order_id=5, tick_size=0.5, db_path=p_db,
        )
        assert result.link_status == "UNPLANNED"  # caller behavior unchanged
        p = _by_cat(_drain(), "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "SKIPPED"
        assert p["reason"] == "query_failed"

    def test_defensive_skip_no_tp_sl(self, tmp_path):
        from core.calc_correlation import correlate_order_to_calc

        correlate_order_to_calc(
            _order(tp_trigger_price=None), order_id=5, tick_size=0.5,
            db_path=str(tmp_path / "x.db"),
        )
        p = _by_cat(_drain(), "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "SKIPPED"
        assert p["reason"] == "no_tp_sl_on_order"

    def test_exception_emits_error_then_raises(self, tmp_path):
        from core.calc_correlation import correlate_order_to_calc

        db = _mk_matcher_db(tmp_path, [self._calc()])
        with pytest.raises(TypeError):
            # tick_size=None blows the TP comparison inside the loop —
            # mandate 1: the exception path is a line (then re-raises)
            correlate_order_to_calc(
                _order(), order_id=5, tick_size=None, db_path=db,
            )
        envs = _by_cat(_drain(), "attr_match_attempt")
        assert len(envs) == 1
        p = envs[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["error_type"] == "TypeError"


# ── attr_match_attempt: _try_correlate's pre-matcher gates ──────────────────

class TestMatchAttemptGateSkips:
    def _orders_db(self, tmp_path, row=None):
        p = str(tmp_path / "orders.db")
        conn = sqlite3.connect(p)
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, account_id INT,"
            " exchange_order_id TEXT, calc_id TEXT, link_status TEXT,"
            " tp_trigger_price REAL, sl_trigger_price REAL, price REAL,"
            " avg_fill_price REAL, created_at_ms INT,"
            " terminal_position_id TEXT, lifecycle_id TEXT,"
            " reduce_only INT DEFAULT 0, order_type TEXT DEFAULT 'limit',"
            " symbol TEXT, position_side TEXT DEFAULT '')",
        )
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, config_json TEXT)")
        conn.execute("INSERT INTO accounts (id, config_json) VALUES (1, NULL)")
        if row is not None:
            cols = ", ".join(row.keys())
            ph = ", ".join("?" for _ in row)
            conn.execute(f"INSERT INTO orders ({cols}) VALUES ({ph})",
                         list(row.values()))
        conn.commit()
        conn.close()
        return p

    def _skip_of(self, envs):
        envs = _by_cat(envs, "attr_match_attempt")
        assert len(envs) == 1
        assert envs[0]["component"] == "order_enrichment"
        return envs[0]["payload"]

    def test_close_type_gate(self, tmp_path):
        from core.order_enrichment import _try_correlate

        asyncio.run(_try_correlate(
            _order(order_type="stop_loss"), str(tmp_path / "x.db"),
        ))
        p = self._skip_of(_drain())
        assert p["outcome"] == "SKIPPED"
        assert p["reason"] == "close_type_or_reduce_only"
        assert p["dedup_key"] == "E-1:new:1.0"

    def test_already_correlated_gate_carries_existing_calc(self, tmp_path):
        from core.order_enrichment import _try_correlate

        db = self._orders_db(tmp_path, {
            "id": 9, "account_id": 1, "exchange_order_id": "E-1",
            "calc_id": "CALC-X", "tp_trigger_price": 110.0,
            "sl_trigger_price": 95.0, "price": 100.0,
            "terminal_position_id": "POS-7", "lifecycle_id": "",
        })
        asyncio.run(_try_correlate(_order(), db))
        p = self._skip_of(_drain())
        assert p["reason"] == "already_correlated"
        assert p["calc_id"] == "CALC-X"  # the existing link, verbatim
        assert p["order_id"] == 9

    def test_manual_review_sticky_gate(self, tmp_path):
        from core.order_enrichment import _try_correlate

        db = self._orders_db(tmp_path, {
            "id": 9, "account_id": 1, "exchange_order_id": "E-1",
            "link_status": "NEEDS_MANUAL_REVIEW",
            "tp_trigger_price": 110.0, "sl_trigger_price": 95.0,
        })
        asyncio.run(_try_correlate(_order(), db))
        assert self._skip_of(_drain())["reason"] == "manual_review_sticky"

    def test_missing_trigger_prices_gate(self, tmp_path):
        from core.order_enrichment import _try_correlate

        db = self._orders_db(tmp_path, {
            "id": 9, "account_id": 1, "exchange_order_id": "E-1",
            "tp_trigger_price": 110.0,
        })
        asyncio.run(_try_correlate(_order(), db))
        p = self._skip_of(_drain())
        assert p["reason"] == "missing_trigger_prices"
        assert p["has_tp"] is True and p["has_sl"] is False

    def test_market_awaiting_fill_gate(self, tmp_path):
        from core.order_enrichment import _try_correlate

        db = self._orders_db(tmp_path, {
            "id": 9, "account_id": 1, "exchange_order_id": "E-1",
            "tp_trigger_price": 110.0, "sl_trigger_price": 95.0,
            "avg_fill_price": 0.0,
        })
        asyncio.run(_try_correlate(_order(order_type="market"), db))
        assert self._skip_of(_drain())["reason"] == "market_awaiting_fill"

    def test_full_run_threads_identity_and_chains(self, tmp_path):
        """The matcher's envelope carries the orders row's identity tuple,
        rides the ambient corr scope, and the auto_classify link write
        emits the (T3a) link_transition on the same chain."""
        from core.order_enrichment import _try_correlate

        db = self._orders_db(tmp_path, {
            "id": 9, "account_id": 1, "exchange_order_id": "E-1",
            "tp_trigger_price": 110.0, "sl_trigger_price": 95.0,
            "price": 100.0, "avg_fill_price": 0.0,
            "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "terminal_position_id": "POS-7", "lifecycle_id": "",
        })
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE pre_trade_log (calc_id TEXT, timestamp TEXT,"
            " side TEXT, effective_entry REAL, tp_price REAL, sl_price REAL,"
            " status TEXT, window_seconds INT, account_id INT, ticker TEXT)",
        )
        conn.execute(
            "INSERT INTO pre_trade_log VALUES"
            " ('CALC-1', ?, 'long', 100.0, 110.0, 95.0, 'active', NULL, 1,"
            "  'BTCUSDT')", (_now_iso(),),
        )
        conn.execute(
            "CREATE TABLE calc_match_audit (order_id INT, calc_id TEXT,"
            " criterion TEXT, calc_value TEXT, order_value TEXT,"
            " tolerance_used REAL, matched INT, ts_ms INT, winning INT)",
        )
        conn.execute(
            "CREATE TABLE order_amendments (id INTEGER PRIMARY KEY,"
            " order_id INT, calc_id TEXT)",
        )
        conn.commit()
        conn.close()

        async def main():
            with cl.correlation_scope("wsu") as cid:
                await _try_correlate(_order(), db)
            return cid

        cid = asyncio.run(main())
        envs = _drain()
        match = _by_cat(envs, "attr_match_attempt")
        assert len(match) == 1
        e = match[0]
        assert e["component"] == "calc_correlation"
        assert e["corr_id"] == cid
        p = e["payload"]
        assert p["outcome"] == "LINKED" and p["calc_id"] == "CALC-1"
        assert p["exchange_order_id"] == "E-1"
        assert p["terminal_position_id"] == "POS-7"  # threaded from the row
        link = _by_cat(envs, "link_transition")
        assert len(link) == 1
        assert link[0]["corr_id"] == cid
        assert link[0]["payload"]["via"] == "auto_classify"
        assert link[0]["payload"]["to"] == "LINKED"


# ── attr_junction_form + attr_bracket_inherit + attr_reenrich_trigger ───────

async def _mk_db(tmp_path):
    from core.database import DatabaseManager
    d = DatabaseManager(path=str(tmp_path / "t3b.db"))
    await d.initialize()
    return d


class TestJunctionForm:
    def _fill(self, **kw):
        base = {"account_id": 1, "exchange_order_id": "E-1",
                "terminal_position_id": "POS-1", "is_close": 0,
                "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
                "price": 100.0, "timestamp_ms": 5,
                "exchange_fill_id": "F-1"}
        base.update(kw)
        return base

    def test_formed_with_mint_and_dedup(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 0.0, "updated_at_ms": 1000,
                }])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-1' "
                    "WHERE exchange_order_id='E-1'",
                )
                await db._conn.commit()
                _drain()
                await om._link_position_calc_on_open(1, self._fill())
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        formed = _by_cat(envs, "attr_junction_form")
        assert len(formed) == 1
        p = formed[0]["payload"]
        assert p["outcome"] == "FORMED"
        assert p["calc_id"] == "CALC-1"
        assert p["terminal_position_id"] == "POS-1"
        assert p["lifecycle_id"]  # minted UUID, non-empty
        assert p["lifecycle_minted"] is True
        assert p["scale_in"] is False
        assert p["contributed_qty"] == 1.0
        assert p["dedup_key"] == "junction:F-1"
        # the paired db_write for the junction rides the same drain
        junction_writes = [e for e in _by_cat(envs, "db_write")
                           if e["payload"]["table"] == "positions_calcs"]
        assert len(junction_writes) == 1

    def test_skip_reasons(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                out = {}
                await om._link_position_calc_on_open(
                    1, self._fill(is_close=1))
                out["close"] = _drain()
                await om._link_position_calc_on_open(
                    1, self._fill(exchange_order_id=""))
                out["no_eoid"] = _drain()
                await om._link_position_calc_on_open(1, self._fill())
                out["no_row"] = _drain()
                # unlinked order with NO position key anywhere
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 0.0, "updated_at_ms": 1000,
                }])
                _drain()
                await om._link_position_calc_on_open(
                    1, self._fill(terminal_position_id=""))
                out["no_pos_key"] = _drain()
                # tpid present but order unlinked
                await om._link_position_calc_on_open(1, self._fill())
                out["not_linked"] = _drain()
                return out
            finally:
                await db.close()

        out = asyncio.run(main())

        def reason(envs):
            j = _by_cat(envs, "attr_junction_form")
            assert len(j) == 1
            assert j[0]["payload"]["outcome"] == "SKIPPED"
            return j[0]["payload"]["reason"]

        assert reason(out["close"]) == "close_fill"
        assert reason(out["no_eoid"]) == "no_exchange_order_id"
        assert reason(out["no_row"]) == "order_row_missing"
        # the historical empty-tpid shape — now a LINE, not an absence
        assert reason(out["no_pos_key"]) == "no_position_key"
        assert reason(out["not_linked"]) == "not_linked"

    def test_replay_path_delegates_then_forms(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 1.0, "updated_at_ms": 1000,
                }])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-1',"
                    " terminal_position_id='POS-1' "
                    "WHERE exchange_order_id='E-1'",
                )
                await db._conn.commit()
                out = {}
                _drain()
                # no opening fill yet
                await om._ensure_junction_if_linked(1, "E-1")
                out["no_fill"] = _drain()
                await db.upsert_fill({
                    "account_id": 1, "exchange_fill_id": "F-1",
                    "exchange_order_id": "E-1", "symbol": "BTCUSDT",
                    "direction": "LONG", "quantity": 1.0, "price": 100.0,
                    "terminal_position_id": "POS-1", "is_close": 0,
                    "timestamp_ms": 5,
                })
                _drain()
                await om._ensure_junction_if_linked(1, "E-1")
                out["replay"] = _drain()
                await om._ensure_junction_if_linked(1, "E-1")
                out["exists"] = _drain()
                return out
            finally:
                await db.close()

        out = asyncio.run(main())
        j1 = _by_cat(out["no_fill"], "attr_junction_form")
        assert len(j1) == 1
        assert j1[0]["payload"]["reason"] == "no_opening_fill"
        assert j1[0]["payload"]["via"] == "post_link_replay"
        j2 = _by_cat(out["replay"], "attr_junction_form")
        # DELEGATED (replay decision) + FORMED (the builder) — two
        # correlated decision lines
        assert [e["payload"]["outcome"] for e in j2] == ["DELEGATED", "FORMED"]
        # mandate 3 on the replay path (audit T3bE-4): the triggering
        # order id keys the dedup
        assert j2[0]["payload"]["dedup_key"] == "replay:E-1"
        j3 = _by_cat(out["exists"], "attr_junction_form")
        assert len(j3) == 1
        assert j3[0]["payload"]["reason"] == "junction_exists"


class TestBracketInherit:
    def test_inherits_then_idempotent_skip(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                now = int(datetime.now(timezone.utc).timestamp() * 1000)
                await db.upsert_order_batch([
                    {"account_id": 1, "exchange_order_id": "E-ENT",
                     "symbol": "BTCUSDT", "status": "filled",
                     "order_type": "limit", "quantity": 1.0,
                     "filled_qty": 1.0, "reduce_only": 0,
                     "position_side": "LONG", "created_at_ms": now,
                     "updated_at_ms": now},
                    {"account_id": 1, "exchange_order_id": "E-SL",
                     "symbol": "BTCUSDT", "status": "new",
                     "order_type": "stop_market", "quantity": 1.0,
                     "filled_qty": 0.0, "reduce_only": 1,
                     "position_side": "LONG", "created_at_ms": now + 500,
                     "updated_at_ms": now},
                ])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-9' "
                    "WHERE exchange_order_id='E-ENT'",
                )
                await db._conn.commit()
                _drain()
                await om._propagate_bracket_calc_id(1, "BTCUSDT")
                first = _drain()
                await om._propagate_bracket_calc_id(1, "BTCUSDT")
                second = _drain()
                async with db._conn.execute(
                    "SELECT calc_id, link_status FROM orders "
                    "WHERE exchange_order_id='E-SL'",
                ) as cur:
                    leg = await cur.fetchone()
                return first, second, leg
            finally:
                await db.close()

        first, second, leg = asyncio.run(main())
        assert leg[0] == "CALC-9" and leg[1] == "LINKED"
        bi = _by_cat(first, "attr_bracket_inherit")
        assert len(bi) == 1
        p = bi[0]["payload"]
        assert p["outcome"] == "INHERITED" and p["applied"] is True
        assert p["calc_id"] == "CALC-9"
        assert p["parent_exchange_order_id"] == "E-ENT"
        assert p["child_exchange_order_id"] == "E-SL"
        assert p["dedup_key"] == "E-SL:inherit:CALC-9"
        # idempotent re-run: the leg now carries calc_id → SKIPPED
        bi2 = _by_cat(second, "attr_bracket_inherit")
        assert len(bi2) == 1
        assert bi2[0]["payload"]["outcome"] == "SKIPPED"
        assert bi2[0]["payload"]["reason"] == "no_uninherited_protective"

    def test_skip_reasons(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                out = {}
                await om._propagate_bracket_calc_id(1, "")
                out["no_symbol"] = _drain()
                await om._propagate_bracket_calc_id(1, "NOSUCH")
                out["no_orders"] = _drain()
                return out
            finally:
                await db.close()

        out = asyncio.run(main())
        for key, reason in (("no_symbol", "no_symbol"),
                            ("no_orders", "no_recent_orders")):
            bi = _by_cat(out[key], "attr_bracket_inherit")
            assert len(bi) == 1, key
            assert bi[0]["payload"]["outcome"] == "SKIPPED"
            assert bi[0]["payload"]["reason"] == reason


class TestReenrichTrigger:
    def test_child_arrival_triggered_and_no_parent(self, tmp_path, monkeypatch):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import config
                monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t3b.db"))
                from core.order_manager import OrderManager
                om = OrderManager(db)
                calls = []

                async def _spy(order):
                    calls.append(order.get("exchange_order_id"))

                om._enrich_order_best_effort = _spy
                child = {"account_id": 1, "exchange_order_id": "E-SL",
                         "reduce_only": 1, "order_type": "stop_market",
                         "symbol": "BTCUSDT", "position_side": "LONG",
                         "exchange_position_id": "", "status": "new",
                         "quantity": 1.0}
                out = {}
                await om._re_enrich_parent_on_child_arrival(1, child)
                out["no_parent"] = _drain()
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-ENT",
                    "symbol": "BTCUSDT", "status": "filled",
                    "order_type": "limit", "quantity": 1.0,
                    "filled_qty": 1.0, "reduce_only": 0,
                    "position_side": "LONG", "updated_at_ms": 1000,
                }])
                _drain()
                await om._re_enrich_parent_on_child_arrival(1, child)
                out["found"] = _drain()
                return out, calls
            finally:
                await db.close()

        out, calls = asyncio.run(main())
        miss = _by_cat(out["no_parent"], "attr_reenrich_trigger")
        assert len(miss) == 1
        p = miss[0]["payload"]
        assert p["outcome"] == "SKIPPED" and p["reason"] == "no_parent_found"
        assert p["via"] == "child_arrival"
        assert p["parent_lookup"] == "symbol_position_side"
        assert p["parent_found"] is False
        hit = _by_cat(out["found"], "attr_reenrich_trigger")
        assert len(hit) == 1
        p2 = hit[0]["payload"]
        assert p2["outcome"] == "TRIGGERED"
        assert p2["parent_exchange_order_id"] == "E-ENT"
        assert p2["dedup_key"] == "E-SL:new:1.0"
        assert calls == ["E-ENT"]  # the re-enrich actually fired

    def test_non_child_is_domain_filtered_no_envelope(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await om._re_enrich_parent_on_child_arrival(
                    1, {"order_type": "limit", "reduce_only": 0},
                )
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        assert _by_cat(envs, "attr_reenrich_trigger") == []

    def test_fill_arrival_variant(self, tmp_path, monkeypatch):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import config
                import core.order_enrichment as oe
                monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t3b.db"))

                async def _noop(order, db_path):
                    pass

                monkeypatch.setattr(oe, "enrich_order", _noop)
                from core.order_manager import OrderManager
                om = OrderManager(db)
                out = {}
                await om._reenrich_parent_after_fill(1, "E-MISSING")
                out["miss"] = _drain()
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-MKT",
                    "symbol": "BTCUSDT", "status": "filled",
                    "order_type": "market", "quantity": 1.0,
                    "filled_qty": 1.0, "reduce_only": 0,
                    "updated_at_ms": 1000,
                }])
                _drain()
                await om._reenrich_parent_after_fill(1, "E-MKT")
                out["hit"] = _drain()
                return out
            finally:
                await db.close()

        out = asyncio.run(main())
        miss = _by_cat(out["miss"], "attr_reenrich_trigger")
        assert len(miss) == 1
        assert miss[0]["payload"]["outcome"] == "SKIPPED"
        assert miss[0]["payload"]["reason"] == "parent_not_found_or_reduce_only"
        assert miss[0]["payload"]["via"] == "fill_arrival"
        hit = _by_cat(out["hit"], "attr_reenrich_trigger")
        assert len(hit) == 1
        assert hit[0]["payload"]["outcome"] == "TRIGGERED"
        assert hit[0]["payload"]["dedup_key"] == "E-MKT:reenrich_fill"


# ── attr_match_attempt: the manual operator paths ───────────────────────────

class TestManualPaths:
    def test_manual_link_skip_and_happy_path(self, tmp_path, monkeypatch):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import core.link_actions as la
                monkeypatch.setattr(la, "db", db)
                out = {}
                out["missing"] = await la.manual_link_order(1, 5, "  ")
                out["missing_envs"] = _drain()
                out["not_found"] = await la.manual_link_order(1, 5, "CALC-1")
                out["not_found_envs"] = _drain()
                # seed an NMR order + an active calc → happy path
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 0.0, "updated_at_ms": 1000,
                }])
                await db._conn.execute(
                    "UPDATE orders SET link_status='NEEDS_MANUAL_REVIEW',"
                    " terminal_position_id='POS-3' "
                    "WHERE exchange_order_id='E-1'",
                )
                await db.insert_pre_trade_log({
                    "account_id": 1, "ticker": "BTCUSDT",
                    "calc_id": "CALC-1", "eligible": True,
                })
                await db._conn.commit()
                async with db._conn.execute(
                    "SELECT id FROM orders WHERE exchange_order_id='E-1'",
                ) as cur:
                    oid = (await cur.fetchone())[0]
                _drain()
                out["linked"] = await la.manual_link_order(1, oid, "CALC-1")
                out["linked_envs"] = _drain()
                out["oid"] = oid
                return out
            finally:
                await db.close()

        out = asyncio.run(main())
        assert out["missing"] == "missing_calc_id"
        p = _by_cat(out["missing_envs"], "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "SKIPPED" and p["reason"] == "missing_calc_id"
        assert p["via"] == "manual_link"
        assert p["calc_id"] == ""  # verbatim empty operator input

        assert out["not_found"] == "order_not_found"
        p = _by_cat(out["not_found_envs"], "attr_match_attempt")[0]["payload"]
        assert p["reason"] == "order_not_found"

        assert out["linked"] == "linked"
        match = _by_cat(out["linked_envs"], "attr_match_attempt")
        assert len(match) == 1
        p = match[0]["payload"]
        assert p["outcome"] == "LINKED" and p["result"] == "linked"
        assert p["calc_id"] == "CALC-1"
        assert p["exchange_order_id"] == "E-1"
        assert p["terminal_position_id"] == "POS-3"
        assert p["dedup_key"] == f"manual:{out['oid']}:CALC-1"
        # the operator path drives the same chokepoints: link_transition
        # (via=transition) + calc_transition ride the same drain
        link = _by_cat(out["linked_envs"], "link_transition")
        assert any(e["payload"]["via"] == "transition" for e in link)
        calc = _by_cat(out["linked_envs"], "calc_transition")
        assert len(calc) == 1
        assert calc[0]["payload"]["to"] == "matched"

    def test_mark_unplanned_paths(self, tmp_path, monkeypatch):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import core.link_actions as la
                monkeypatch.setattr(la, "db", db)
                out = {}
                out["not_found"] = await la.mark_order_unplanned(1, 99)
                out["not_found_envs"] = _drain()
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-2",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 0.0, "updated_at_ms": 1000,
                }])
                await db._conn.execute(
                    "UPDATE orders SET link_status='NEEDS_MANUAL_REVIEW' "
                    "WHERE exchange_order_id='E-2'",
                )
                await db._conn.commit()
                async with db._conn.execute(
                    "SELECT id FROM orders WHERE exchange_order_id='E-2'",
                ) as cur:
                    oid = (await cur.fetchone())[0]
                _drain()
                out["marked"] = await la.mark_order_unplanned(1, oid)
                out["marked_envs"] = _drain()
                return out
            finally:
                await db.close()

        out = asyncio.run(main())
        assert out["not_found"] == "order_not_found"
        p = _by_cat(out["not_found_envs"], "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "SKIPPED" and p["via"] == "mark_unplanned"
        assert out["marked"] == "marked"
        p = _by_cat(out["marked_envs"], "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "UNPLANNED" and p["result"] == "marked"
        assert p["exchange_order_id"] == "E-2"


# ── audit-fold pins: error twins, applied:false, already_linked ─────────────

class TestAuditFoldPins:
    def test_try_correlate_order_read_failure_is_an_error_line(self, tmp_path):
        """Audit T3bE-2: the pre-matcher orders SELECT raising (contention /
        unmigrated schema) was the one remaining SILENT matcher exit; it
        must be an ERROR line and must not raise past _try_correlate."""
        from core.order_enrichment import _try_correlate

        p = str(tmp_path / "noschema.db")
        sqlite3.connect(p).close()  # a DB with no orders table
        asyncio.run(_try_correlate(_order(), p))
        envs = _by_cat(_drain(), "attr_match_attempt")
        assert len(envs) == 1
        pl = envs[0]["payload"]
        assert pl["outcome"] == "ERROR"
        assert pl["reason"] == "order_read_failed"
        assert pl["error_type"] == "OperationalError"

    def test_upsert_position_calc_link_returns_ok_flag(self, tmp_path):
        import sqlite3 as _s

        async def main():
            db = await _mk_db(tmp_path)
            try:
                orig = db._conn.execute

                def _boom(sql, *a, **k):
                    if "INSERT INTO positions_calcs" in sql:
                        raise _s.OperationalError("locked")
                    return orig(sql, *a, **k)

                db._conn.execute = _boom
                try:
                    bad = await db.upsert_position_calc_link({
                        "position_id": "P", "calc_id": "C", "order_id": 1,
                        "account_id": 1, "contributed_qty": 1.0,
                        "first_fill_ts": 1, "last_fill_ts": 1,
                    })
                finally:
                    db._conn.execute = orig
                good = await db.upsert_position_calc_link({
                    "position_id": "P", "calc_id": "C", "order_id": 1,
                    "account_id": 1, "contributed_qty": 1.0,
                    "first_fill_ts": 1, "last_fill_ts": 1,
                })
                return bad, good
            finally:
                await db.close()

        bad, good = asyncio.run(main())
        assert bad is False and good is True

    def test_junction_builder_error_line_on_failed_write(self, tmp_path):
        """Audit T3bE-3: a swallowed junction-write failure must NOT read
        as FORMED — that is the historical 'junction missing' shape."""
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 0.0, "updated_at_ms": 1000,
                }])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-1' "
                    "WHERE exchange_order_id='E-1'",
                )
                await db._conn.commit()

                async def _fail(row):
                    return False

                db.upsert_position_calc_link = _fail
                _drain()
                await om._link_position_calc_on_open(1, {
                    "account_id": 1, "exchange_order_id": "E-1",
                    "terminal_position_id": "POS-1", "is_close": 0,
                    "symbol": "BTCUSDT", "direction": "LONG",
                    "quantity": 1.0, "price": 100.0, "timestamp_ms": 5,
                    "exchange_fill_id": "F-1",
                })
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        j = _by_cat(envs, "attr_junction_form")
        assert len(j) == 1
        p = j[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["reason"] == "junction_write_failed"

    def test_bracket_error_twin(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                now = int(datetime.now(timezone.utc).timestamp() * 1000)
                await db.upsert_order_batch([
                    {"account_id": 1, "exchange_order_id": "E-ENT",
                     "symbol": "BTCUSDT", "status": "filled",
                     "order_type": "limit", "quantity": 1.0,
                     "filled_qty": 1.0, "reduce_only": 0,
                     "position_side": "LONG", "created_at_ms": now,
                     "updated_at_ms": now},
                    {"account_id": 1, "exchange_order_id": "E-SL",
                     "symbol": "BTCUSDT", "status": "new",
                     "order_type": "stop_market", "quantity": 1.0,
                     "filled_qty": 0.0, "reduce_only": 1,
                     "position_side": "LONG", "created_at_ms": now + 500,
                     "updated_at_ms": now},
                ])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-9' "
                    "WHERE exchange_order_id='E-ENT'",
                )
                await db._conn.commit()

                def _boom(candidates):
                    raise RuntimeError("detector down")

                om._detect_brackets = _boom
                _drain()
                await om._propagate_bracket_calc_id(1, "BTCUSDT")
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        bi = _by_cat(envs, "attr_bracket_inherit")
        assert len(bi) == 1
        assert bi[0]["payload"]["outcome"] == "ERROR"
        assert bi[0]["payload"]["error_type"] == "RuntimeError"

    def test_bracket_applied_false_when_leg_raced(self, tmp_path):
        """The WHERE calc_id IS NULL idempotency no-op must be VISIBLE
        (applied:false), not silently merged with a real stamp."""
        async def main():
            db = await _mk_db(tmp_path)
            db_file = str(tmp_path / "t3b.db")
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                now = int(datetime.now(timezone.utc).timestamp() * 1000)
                await db.upsert_order_batch([
                    {"account_id": 1, "exchange_order_id": "E-ENT",
                     "symbol": "BTCUSDT", "status": "filled",
                     "order_type": "limit", "quantity": 1.0,
                     "filled_qty": 1.0, "reduce_only": 0,
                     "position_side": "LONG", "created_at_ms": now,
                     "updated_at_ms": now},
                    {"account_id": 1, "exchange_order_id": "E-SL",
                     "symbol": "BTCUSDT", "status": "new",
                     "order_type": "stop_market", "quantity": 1.0,
                     "filled_qty": 0.0, "reduce_only": 1,
                     "position_side": "LONG", "created_at_ms": now + 500,
                     "updated_at_ms": now},
                ])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-9' "
                    "WHERE exchange_order_id='E-ENT'",
                )
                await db._conn.commit()

                orig_detect = om._detect_brackets

                def _race_then_detect(candidates):
                    # interpose between the candidate read and the apply:
                    # another writer links the leg → the UPDATE's
                    # WHERE calc_id IS NULL no-ops
                    rconn = sqlite3.connect(db_file, timeout=10.0)
                    rconn.execute(
                        "UPDATE orders SET calc_id='CALC-RACE' "
                        "WHERE exchange_order_id='E-SL'",
                    )
                    rconn.commit()
                    rconn.close()
                    return orig_detect(candidates)

                om._detect_brackets = _race_then_detect
                _drain()
                await om._propagate_bracket_calc_id(1, "BTCUSDT")
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        bi = _by_cat(envs, "attr_bracket_inherit")
        assert len(bi) == 1
        p = bi[0]["payload"]
        assert p["outcome"] == "INHERITED"
        assert p["applied"] is False  # the raced no-op is a visible fact

    def test_ensure_junction_error_twin(self, tmp_path):
        import sqlite3 as _s

        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                orig = db._conn.execute

                def _boom(sql, *a, **k):
                    if "SELECT calc_id, terminal_position_id FROM orders" in sql:
                        raise _s.OperationalError("locked")
                    return orig(sql, *a, **k)

                db._conn.execute = _boom
                _drain()
                try:
                    await om._ensure_junction_if_linked(1, "E-1")
                finally:
                    db._conn.execute = orig
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        j = _by_cat(envs, "attr_junction_form")
        assert len(j) == 1
        p = j[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["via"] == "post_link_replay"
        assert p["error_type"] == "OperationalError"
        assert p["dedup_key"] == "replay:E-1"

    def test_manual_link_error_wrapper_emits_then_raises(self, monkeypatch):
        import core.link_actions as la

        class _BadConn:
            def execute(self, *a, **k):
                raise RuntimeError("db down")

        class _BadDb:
            _conn = _BadConn()

        monkeypatch.setattr(la, "db", _BadDb())
        with pytest.raises(RuntimeError):
            asyncio.run(la.manual_link_order(1, 5, "CALC-1"))
        envs = _by_cat(_drain(), "attr_match_attempt")
        assert len(envs) == 1
        p = envs[0]["payload"]
        assert p["outcome"] == "ERROR" and p["via"] == "manual_link"
        assert p["error_type"] == "RuntimeError"

    def test_manual_link_already_linked_carries_existing_calc(
        self, tmp_path, monkeypatch,
    ):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import core.link_actions as la
                monkeypatch.setattr(la, "db", db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new", "quantity": 1.0,
                    "filled_qty": 0.0, "updated_at_ms": 1000,
                }])
                await db._conn.execute(
                    "UPDATE orders SET calc_id='CALC-OLD' "
                    "WHERE exchange_order_id='E-1'",
                )
                await db._conn.commit()
                async with db._conn.execute(
                    "SELECT id FROM orders WHERE exchange_order_id='E-1'",
                ) as cur:
                    oid = (await cur.fetchone())[0]
                _drain()
                result = await la.manual_link_order(1, oid, "CALC-NEW")
                return result, _drain()
            finally:
                await db.close()

        result, envs = asyncio.run(main())
        assert result == "already_linked"
        p = _by_cat(envs, "attr_match_attempt")[0]["payload"]
        assert p["outcome"] == "SKIPPED" and p["reason"] == "already_linked"
        assert p["calc_id"] == "CALC-NEW"          # the operator's request
        assert p["existing_calc_id"] == "CALC-OLD"  # the standing link

    def test_reenrich_child_error_twin(self, tmp_path, monkeypatch):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import config
                # an unopenable DB path → sqlite3.connect raises inside the
                # child-arrival body → the ERROR twin fires (swallow kept)
                monkeypatch.setattr(
                    config, "DB_PATH", str(tmp_path / "nodir" / "x.db"),
                )
                from core.order_manager import OrderManager
                om = OrderManager(db)
                _drain()
                await om._re_enrich_parent_on_child_arrival(1, {
                    "account_id": 1, "exchange_order_id": "E-SL",
                    "reduce_only": 1, "order_type": "stop_market",
                    "symbol": "BTCUSDT", "position_side": "LONG",
                    "exchange_position_id": "", "status": "new",
                    "quantity": 1.0,
                })
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        rt = _by_cat(envs, "attr_reenrich_trigger")
        assert len(rt) == 1
        p = rt[0]["payload"]
        assert p["outcome"] == "ERROR" and p["via"] == "child_arrival"
        assert p["error_type"] == "OperationalError"


# ════ CL.T3b-close — the close-side categories (spec §5.6) ══════════════════

def _pos_info(ticker="BTCUSDT", direction="LONG", tpid="POS-1", **kw):
    from core.state import PositionInfo
    base = dict(
        ticker=ticker, direction=direction, contract_amount=1.0,
        average=100.0, fair_price=100.0, individual_unrealized=0.0,
        position_value_usdt=100.0,
        entry_timestamp="2026-06-12T00:00:00+00:00",
        sector="", position_id=tpid,
    )
    base.update(kw)
    return PositionInfo(**base)


@pytest.fixture
def _restore_positions():
    from core.state import app_state
    snap = list(app_state.positions)
    app_state.positions = []
    yield app_state
    app_state.positions = snap


class TestTpidResolve:
    def _fill(self, **kw):
        base = {"symbol": "BTCUSDT", "direction": "LONG",
                "exchange_fill_id": "F-9", "exchange_order_id": "E-9"}
        base.update(kw)
        return base

    def test_tier1_live_position(self, _restore_positions):
        from core.order_manager import OrderManager

        app_state = _restore_positions
        app_state.positions = [_pos_info(tpid="POS-1")]
        om = OrderManager(db=None)
        got = asyncio.run(om._resolve_close_tpid(1, self._fill()))
        assert got == "POS-1"
        envs = _by_cat(_drain(), "attr_tpid_resolve")
        assert len(envs) == 1  # mandate 1: one envelope per invocation
        p = envs[0]["payload"]
        assert p["outcome"] == "RESOLVED" and p["tier"] == "live_position"
        assert p["terminal_position_id"] == "POS-1"
        assert p["via"] == "close_fill"
        assert p["dedup_key"] == "F-9:tpid_resolve"

    def test_tier2_entry_order_fallback(self, _restore_positions):
        from core.order_manager import OrderManager

        class _Db:
            async def get_open_entry_tpids_by_symbol_side(self, account_id):
                return {("BTCUSDT", "LONG"): "POS-2"}

        om = OrderManager(_Db())
        got = asyncio.run(om._resolve_close_tpid(1, self._fill()))
        assert got == "POS-2"
        p = _by_cat(_drain(), "attr_tpid_resolve")[0]["payload"]
        assert p["outcome"] == "RESOLVED"
        assert p["tier"] == "entry_order_fallback"

    def test_unresolved_no_match_is_a_line(self, _restore_positions):
        from core.order_manager import OrderManager

        class _Db:
            async def get_open_entry_tpids_by_symbol_side(self, account_id):
                return {}

        om = OrderManager(_Db())
        got = asyncio.run(om._resolve_close_tpid(1, self._fill()))
        assert got == ""
        p = _by_cat(_drain(), "attr_tpid_resolve")[0]["payload"]
        assert p["outcome"] == "UNRESOLVED" and p["reason"] == "no_match"
        assert p["terminal_position_id"] == ""  # verbatim — stranded shape

    def test_fallback_read_error_twin(self, _restore_positions):
        from core.order_manager import OrderManager

        class _Db:
            async def get_open_entry_tpids_by_symbol_side(self, account_id):
                raise RuntimeError("db down")

        om = OrderManager(_Db())
        got = asyncio.run(om._resolve_close_tpid(1, self._fill()))
        assert got == ""
        p = _by_cat(_drain(), "attr_tpid_resolve")[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["reason"] == "fallback_read_failed"
        assert p["error_type"] == "RuntimeError"  # audit T3bC-4

    def test_skip_no_symbol_or_direction(self, _restore_positions):
        from core.order_manager import OrderManager

        om = OrderManager(db=None)
        got = asyncio.run(
            om._resolve_close_tpid(1, {"symbol": "", "direction": ""}),
        )
        assert got == ""
        p = _by_cat(_drain(), "attr_tpid_resolve")[0]["payload"]
        assert p["outcome"] == "SKIPPED"
        assert p["reason"] == "no_symbol_or_direction"


class TestCloseBuild:
    def test_strict_miss_walk_backfill_written_on_one_line(
        self, tmp_path, _restore_positions,
    ):
        """The ⑨-shape headline: closing fill carries the tpid, opening
        fills were written empty — strict misses, the walk finds them,
        the backfill stamps them, the row lands. Root cause on ONE line."""
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_fill({
                    "account_id": 1, "exchange_fill_id": "F-OPEN",
                    "exchange_order_id": "E-OPEN", "symbol": "BTCUSDT",
                    "direction": "LONG", "price": 100.0, "quantity": 1.0,
                    "is_close": 0, "timestamp_ms": 1000,
                    "terminal_position_id": "",
                })
                close = {
                    "account_id": 1, "exchange_fill_id": "F-CLOSE",
                    "exchange_order_id": "E-CLOSE", "symbol": "BTCUSDT",
                    "direction": "LONG", "price": 110.0, "quantity": 1.0,
                    "is_close": 1, "timestamp_ms": 2000,
                    "terminal_position_id": "POS-9", "realized_pnl": 10.0,
                }
                await db.upsert_fill(dict(close))
                _drain()
                await om._build_close_row_for_fill(1, close)
                envs = _drain()
                async with db._conn.execute(
                    "SELECT COUNT(*) FROM closed_positions "
                    "WHERE terminal_position_id='POS-9'",
                ) as cur:
                    n_rows = (await cur.fetchone())[0]
                async with db._conn.execute(
                    "SELECT terminal_position_id FROM fills "
                    "WHERE exchange_fill_id='F-OPEN'",
                ) as cur:
                    open_tpid = (await cur.fetchone())[0]
                return envs, n_rows, open_tpid
            finally:
                await db.close()

        envs, n_rows, open_tpid = asyncio.run(main())
        assert n_rows == 1
        assert open_tpid == "POS-9"  # the backfill landed
        cb = _by_cat(envs, "attr_close_build")
        assert len(cb) == 1  # mandate 1: one envelope per invocation
        p = cb[0]["payload"]
        assert p["outcome"] == "WRITTEN" and p["row_written"] is True
        assert p["strict_key"] == "POS-9"
        assert p["opens_found_strict"] == 0
        assert p["walk_used"] is True
        assert p["opens_found_walk"] == 1
        assert p["open_fill_tpids"] == {"empty": 1, "populated": 0}
        assert p["backfilled"] == 1
        assert p["entry_source"] == "opens_vwap"
        assert p["is_final"] is True
        assert p["dedup_key"] == "close:F-CLOSE"
        # the paired db_write for closed_positions rides the same drain
        w = [e for e in _by_cat(envs, "db_write")
             if e["payload"]["table"] == "closed_positions"]
        assert len(w) == 1 and w[0]["payload"]["ok"] is True

    def test_no_closing_fills_is_a_skipped_line(
        self, tmp_path, _restore_positions,
    ):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                _drain()
                await om._build_close_row_for_fill(1, {
                    "account_id": 1, "exchange_fill_id": "F-X",
                    "exchange_order_id": "E-NONE", "symbol": "BTCUSDT",
                    "direction": "LONG", "terminal_position_id": "POS-X",
                    "timestamp_ms": 2000,
                })
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        cb = _by_cat(envs, "attr_close_build")
        assert len(cb) == 1
        p = cb[0]["payload"]
        assert p["outcome"] == "SKIPPED"
        assert p["reason"] == "no_closing_fills"
        assert p["walk_used"] is True and p["opens_found_walk"] == 0

    def test_build_exception_is_an_error_line_and_swallowed(
        self, tmp_path, _restore_positions,
    ):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)

                async def _boom(*a, **k):
                    raise RuntimeError("reader down")

                db.get_position_fills = _boom
                _drain()
                # must NOT raise (the builder's swallow contract holds)
                await om._build_close_row_for_fill(1, {
                    "account_id": 1, "exchange_fill_id": "F-E",
                    "exchange_order_id": "E-E", "symbol": "BTCUSDT",
                    "direction": "LONG", "terminal_position_id": "POS-E",
                    "timestamp_ms": 2000,
                })
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        cb = _by_cat(envs, "attr_close_build")
        assert len(cb) == 1
        p = cb[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["error_type"] == "RuntimeError"
        assert p["strict_key"] == "POS-E"

    def test_row_write_failure_is_error_not_written(
        self, tmp_path, _restore_positions,
    ):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                close = {
                    "account_id": 1, "exchange_fill_id": "F-C2",
                    "exchange_order_id": "E-C2", "symbol": "BTCUSDT",
                    "direction": "LONG", "price": 110.0, "quantity": 1.0,
                    "is_close": 1, "timestamp_ms": 2000,
                    "terminal_position_id": "POS-W",
                }
                await db.upsert_fill(dict(close))

                async def _fail(row, commit=True):
                    return False

                db.insert_closed_position = _fail
                _drain()
                await om._build_close_row_for_fill(1, close)
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        p = _by_cat(envs, "attr_close_build")[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["reason"] == "row_write_failed"
        assert p["row_written"] is False


class TestEnrichAndDrift:
    def test_no_position_key_skip_is_gated(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                pos = _pos_info(tpid="")
                _drain()
                await om._enrich_positions_calc_id(1, [pos])
                first = _drain()
                await om._enrich_positions_calc_id(1, [pos])
                second = _drain()
                return first, second
            finally:
                await db.close()

        first, second = asyncio.run(main())
        skip = _by_cat(first, "attr_enrich")
        assert len(skip) == 1
        assert skip[0]["payload"]["reason"] == "no_position_key"
        recover = _by_cat(first, "attr_tpid_resolve")
        assert len(recover) == 1
        assert recover[0]["payload"]["outcome"] == "UNRESOLVED"
        assert recover[0]["payload"]["via"] == "snapshot_recovery"
        # §7.3 on-change gate: the second identical pass is SILENT
        assert _by_cat(second, "attr_enrich") == []
        assert _by_cat(second, "attr_tpid_resolve") == []

    def test_snapshot_recovery_resolves_and_clears(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-ENT",
                    "symbol": "BTCUSDT", "status": "filled",
                    "order_type": "limit", "quantity": 1.0,
                    "filled_qty": 1.0, "reduce_only": 0,
                    "position_side": "LONG",
                    "terminal_position_id": "POS-7",
                    "created_at_ms": 1000, "updated_at_ms": 1000,
                }])
                pos = _pos_info(tpid="")
                _drain()
                await om._enrich_positions_calc_id(1, [pos])
                first = _drain()
                # audit T3bC-1: the recovered flag flips False next pass —
                # the sig must EXCLUDE it, so an unchanged outcome is silent
                await om._enrich_positions_calc_id(1, [pos])
                second = _drain()
                return pos.position_id, first, second
            finally:
                await db.close()

        tpid, envs, second = asyncio.run(main())
        assert tpid == "POS-7"  # the #1 unminted-snapshot recovery
        assert _by_cat(second, "attr_enrich") == []
        assert _by_cat(second, "attr_tpid_resolve") == []
        rec = _by_cat(envs, "attr_tpid_resolve")
        assert len(rec) == 1
        p = rec[0]["payload"]
        assert p["outcome"] == "RESOLVED" and p["via"] == "snapshot_recovery"
        assert p["tier"] == "entry_order"
        assert p["terminal_position_id"] == "POS-7"
        en = _by_cat(envs, "attr_enrich")
        assert len(en) == 1
        pe = en[0]["payload"]
        assert pe["outcome"] == "CLEARED" and pe["reason"] == "no_junction"
        assert pe["recovered"] is True
        assert pe["recovery_source"] == "entry_order"
        assert pe["badge"] == "red"

    def test_stamped_then_sl_removal_badge_transition(self, tmp_path):
        """Historical bug #h on one line: planned_sl present, live_sl=0,
        sl_removed flag + badge green→yellow — then gated silence."""
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_position_calc_link({
                    "position_id": "POS-1", "calc_id": "CALC-1",
                    "order_id": 1, "account_id": 1,
                    "contributed_qty": 1.0, "first_fill_ts": 1,
                    "last_fill_ts": 1, "planned_size": 1.0,
                    "planned_tp": 110.0, "planned_sl": 95.0,
                })
                pos = _pos_info(
                    tpid="POS-1",
                    individual_tp_price=110.0, individual_sl_price=95.0,
                )
                _drain()
                await om._enrich_positions_calc_id(1, [pos])
                first = _drain()
                pos.individual_sl_price = 0.0   # the operator pulled the stop
                await om._enrich_positions_calc_id(1, [pos])
                second = _drain()
                await om._enrich_positions_calc_id(1, [pos])
                third = _drain()
                return first, second, third, pos
            finally:
                await db.close()

        first, second, third, pos = asyncio.run(main())
        en1 = _by_cat(first, "attr_enrich")
        assert len(en1) == 1
        assert en1[0]["payload"]["outcome"] == "STAMPED"
        assert en1[0]["payload"]["calc_id"] == "CALC-1"
        assert en1[0]["payload"]["badge"] == "green"
        d1 = _by_cat(first, "attr_drift_check")
        assert len(d1) == 1
        p1 = d1[0]["payload"]
        assert p1["badge_before"] is None and p1["badge"] == "green"
        assert p1["sl_removed"] is False
        # SL pulled → drift transition line (bug #h's exact shape)
        d2 = _by_cat(second, "attr_drift_check")
        assert len(d2) == 1
        p2 = d2[0]["payload"]
        assert p2["planned_sl"] == 95.0 and p2["live_sl"] == 0.0
        assert p2["sl_removed"] is True
        assert p2["badge_before"] == "green" and p2["badge"] == "yellow"
        assert pos.deviation_badge == "yellow"
        # audit T3bC-3c: the badge change also re-emits the enrich STAMPED
        # line (badge is in the enrich sig)
        en2 = _by_cat(second, "attr_enrich")
        assert len(en2) == 1
        assert en2[0]["payload"]["outcome"] == "STAMPED"
        assert en2[0]["payload"]["badge"] == "yellow"
        # unchanged state → gated silence
        assert _by_cat(third, "attr_drift_check") == []
        assert _by_cat(third, "attr_enrich") == []

    def test_flat_interim_reopen_gets_fresh_first_stamp(self, tmp_path):
        """Audit T3bC-2: the memo prunes ON ENTRY, so a flat pass clears
        it and a same-(ticker,direction) reopen re-emits its first stamp
        (the tail cleanup was unreachable on the early-return paths)."""
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                _drain()
                await om._enrich_positions_calc_id(1, [_pos_info(tpid="")])
                first = _drain()
                await om._enrich_positions_calc_id(1, [])   # flat interim
                await om._enrich_positions_calc_id(1, [_pos_info(tpid="")])
                reopen = _drain()
                return first, reopen
            finally:
                await db.close()

        first, reopen = asyncio.run(main())
        assert len(_by_cat(first, "attr_enrich")) == 1
        re_en = _by_cat(reopen, "attr_enrich")
        assert len(re_en) == 1  # fresh first stamp, not gate-suppressed
        assert re_en[0]["payload"]["reason"] == "no_position_key"

    def test_junction_read_failure_error_twin(self, tmp_path):
        import sqlite3 as _s

        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                orig = db._conn.execute

                def _boom(sql, *a, **k):
                    if "FROM positions_calcs WHERE account_id" in sql:
                        raise _s.OperationalError("locked")
                    return orig(sql, *a, **k)

                db._conn.execute = _boom
                _drain()
                try:
                    await om._enrich_positions_calc_id(
                        1, [_pos_info(tpid="POS-1")],
                    )
                finally:
                    db._conn.execute = orig
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        en = _by_cat(envs, "attr_enrich")
        assert len(en) == 1
        p = en[0]["payload"]
        assert p["outcome"] == "ERROR"
        assert p["reason"] == "junction_read_failed"
        assert p["error_type"] == "OperationalError"


# ── registry conformance ─────────────────────────────────────────────────────

class TestT3bEntryRegistryConformance:
    def test_entry_side_categories_in_attr_group(self):
        reg = cl.registry()
        for cat in ("attr_match_attempt", "attr_bracket_inherit",
                    "attr_junction_form", "attr_reenrich_trigger",
                    "attr_tpid_resolve", "attr_close_build",
                    "attr_enrich", "attr_drift_check"):
            assert reg[cat] == "attr"
