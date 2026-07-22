"""P1 backend-gap unit tests (v3.0 Dashboard): the pure mappers + the
engine-log id-cursor read. The live-state endpoints (/api/state halt surface,
/api/dashboard/snapshot, engine-log, macro-signals, notifications) get 200 +
shape smokes in tests/test_routes.py via the isolated TestClient (LOW-023: one
TestClient per process). Here we pin the logic that doesn't need app_state/db.
"""
import os
import sqlite3

from core.notifications import ui_event
from core.event_log import query_events_since
from api.routes_dashboard import _engine_log_line, _serialize_positions


class TestNotificationUIShape:
    def test_maps_the_four_real_types(self):
        cases = {
            "calc_expired":             ("LINK",  "routine"),
            "position_size_drift":      ("LINK",  "risk"),
            "position_liquidated":      ("RISK",  "risk"),
            "duplicate_order_detected": ("FILLS", "risk"),
        }
        for ntype, (ch, pri) in cases.items():
            e = ui_event({"id": 1, "type": ntype, "message": "m", "ts_ms": 123})
            assert e["ch"] == ch and e["pri"] == pri, ntype

    def test_unknown_type_falls_back_system_routine(self):
        e = ui_event({"id": 1, "type": "regime_shift", "message": "m", "ts_ms": 1})
        assert e["ch"] == "SYSTEM" and e["pri"] == "routine"

    def test_preserves_legacy_keys_and_adds_ui_shape(self):
        e = ui_event({"id": 7, "type": "calc_expired", "message": "hi", "ts_ms": 99})
        # legacy keys intact (base.html poller must keep working)
        assert (e["id"], e["type"], e["message"], e["ts_ms"]) == (7, "calc_expired", "hi", 99)
        # v3.0 UI shape added
        assert e["head"] == "hi" and e["detail"] == "" and e["ts"] == 99


class TestEngineLogLine:
    def test_dd_transition_maps_tag_tone_msg(self):
        row = {"id": 5, "event_type": "dd_state_transition",
               "payload_json": '{"from":"ok","to":"limit","drawdown":0.1197}',
               "timestamp": "2026-04-25T20:08:36+00:00", "source": "data_cache"}
        line = _engine_log_line(row)
        assert line["tag"] == "DD" and line["tone"] == "info"
        assert "ok → limit" in line["msg"] and "11.97%" in line["msg"]
        assert line["id"] == 5

    def test_unknown_type_fallback(self):
        row = {"id": 1, "event_type": "mystery", "payload_json": '{"a":1}',
               "timestamp": "2026-04-25T20:00:00+00:00", "source": "x"}
        line = _engine_log_line(row)
        assert line["tag"] == "ENG" and line["tone"] == "sub"
        assert "mystery" in line["msg"] and "a=1" in line["msg"]

    def test_bad_payload_json_is_safe(self):
        row = {"id": 2, "event_type": "webhook_dispatch_failed",
               "payload_json": "not json", "timestamp": "", "source": "x"}
        line = _engine_log_line(row)
        assert line["tag"] == "HOOK" and line["tone"] == "err"
        assert isinstance(line["msg"], str)


class TestSerializePositions:
    def test_serializes_expected_fields(self):
        class P:
            ticker = "BTCUSDT"; direction = "long"; contract_amount = 0.5
            average = 90000.0; fair_price = 90900.0; position_value_usdt = 45000.0
            individual_unrealized = 450.0; individual_tp_price = 92000.0
            individual_sl_price = 89000.0; session_mfe = 500.0; session_mae = -100.0
            individual_fees = -1.0; individual_funding_fees = -0.5
            entry_timestamp = 1700000000000; deviation_badge = None
            size_delta_pct = None; amendment_count = 0; tpsl_amended = 0
        r = _serialize_positions([P()])[0]
        assert r["sym"] == "BTCUSDT" and r["side"] == "long"
        assert r["upnl"] == 450.0
        assert r["pct"] == round(450.0 / 45000.0 * 100, 2)
        assert r["tp"] == 92000.0 and r["sl"] == 89000.0

    def test_zero_notional_no_div_by_zero(self):
        class P:
            ticker = "X"; direction = "long"; contract_amount = 0
            average = 0; fair_price = 0; position_value_usdt = 0
            individual_unrealized = 0
        assert _serialize_positions([P()])[0]["pct"] == 0.0


class TestEngineLogCursor:
    def _seed_db(self, tmpdir):
        """A legacy-shaped risk_engine.db with 5 engine_events rows. _resolve_db_path
        returns this file for a data_dir lacking the .split-complete-v1 marker."""
        path = os.path.join(tmpdir, "risk_engine.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE engine_events (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " account_id INTEGER, event_type TEXT, payload_json TEXT,"
            " timestamp TEXT, source TEXT)"
        )
        for i in range(1, 6):
            conn.execute(
                "INSERT INTO engine_events "
                "(account_id, event_type, payload_json, timestamp, source) "
                "VALUES (1, 'dd_state_transition', '{}', ?, 'test')",
                (f"2026-04-25T20:0{i}:00+00:00",),
            )
        conn.commit()
        conn.close()

    def test_seed_returns_newest_oldest_first(self, tmp_path):
        self._seed_db(str(tmp_path))
        rows = query_events_since(1, since_id=0, limit=3, data_dir=str(tmp_path))
        assert [r["id"] for r in rows] == [3, 4, 5]  # newest 3, oldest-first

    def test_since_cursor_returns_newer_only(self, tmp_path):
        self._seed_db(str(tmp_path))
        rows = query_events_since(1, since_id=3, limit=10, data_dir=str(tmp_path))
        assert [r["id"] for r in rows] == [4, 5]

    def test_since_at_head_is_empty(self, tmp_path):
        self._seed_db(str(tmp_path))
        rows = query_events_since(1, since_id=5, limit=10, data_dir=str(tmp_path))
        assert rows == []
