"""Engine-Log LIVE feed (option-3 fix, 2026-08-05).

The Dashboard's Engine-Log tile used to tail engine_events alone — an audit
trail of RARE stateful risk events that on a quiet account goes weeks without
a row while the pane wears a LIVE badge (investigated 2026-08-05: the newest
row was 13 days old, rendered time-only so it read as today's activity).

The fix: GET /api/engine/log/live merges the actual rolling engine log
(config.LOG_FILE — risk_engine.jsonl, byte-offset cursor) with NEW
engine_events rows (id cursor, highlighted src='event'); non-today stamps
carry an "MM-DD " date prefix; the pane's LOG dot mirrors the pipe instead of
a hardcoded ok.

Backend tests EXECUTE the helpers and the route (monkeypatched module attrs —
a direct handler call bypasses FastAPI DI, so no TestClient and no live-DB
contact). Frontend pins are structural over the stripped source and are each
mutation-checked by scripts run at authoring time (anchors chosen brace/
ternary-head-tight per the substring-contains-mutant class).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config  # noqa: E402
import api.routes_dashboard as rd  # noqa: E402
from api.routes_dashboard import (  # noqa: E402
    _engine_log_line,
    _jsonl_live_line,
    _tail_jsonl_lines,
)
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent


def _write_jsonl(path: Path, records: list[dict], *, trailing_newline: bool = True) -> None:
    body = "\n".join(json.dumps(r) for r in records)
    if trailing_newline and records:
        body += "\n"
    path.write_bytes(body.encode("utf-8"))


def _rec(i: int, *, ts: str = "2026-08-05T08:00:00+00:00", level: str = "INFO",
         logger: str = "main", message: str | None = None) -> dict:
    return {"ts": ts, "level": level, "logger": logger,
            "message": message if message is not None else f"line {i}"}


# ── 1. the tail helper, executed ────────────────────────────────────────────

class TestTailJsonlLines:
    def test_seed_returns_last_n_complete_lines_oldest_first(self, tmp_path):
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(i) for i in range(10)])
        lines, off = _tail_jsonl_lines(str(f), 0, 5)
        assert [d["message"] for d in lines] == [f"line {i}" for i in range(5, 10)]
        assert off == f.stat().st_size

    def test_poll_returns_only_new_lines_and_advances(self, tmp_path):
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(i) for i in range(4)])
        _, off = _tail_jsonl_lines(str(f), 0, 60)
        with open(f, "ab") as fh:
            for i in (4, 5, 6):
                fh.write((json.dumps(_rec(i)) + "\n").encode())
        lines, off2 = _tail_jsonl_lines(str(f), off, 60)
        assert [d["message"] for d in lines] == ["line 4", "line 5", "line 6"]
        assert off2 == f.stat().st_size
        # a further poll from the new offset is quiet
        assert _tail_jsonl_lines(str(f), off2, 60) == ([], off2)

    def test_valid_json_without_trailing_newline_is_not_consumed(self, tmp_path):
        """The partial-line contract: bytes after the last newline are a write
        in progress — even when they happen to parse as complete JSON. A
        consume-everything mutant returns the row now AND again after the
        newline lands (duplicate feed lines). Two lanes: an all-partial chunk
        (the early return) AND a mixed complete+partial chunk (the slice —
        the first harness run proved the all-partial lane alone never
        executes the slice, so a `complete = chunk` mutant survived it)."""
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(0)])
        _, off = _tail_jsonl_lines(str(f), 0, 60)
        with open(f, "ab") as fh:
            fh.write(json.dumps(_rec(1)).encode())  # valid JSON, NO newline
        # lane 1: chunk is ALL partial — nothing consumed
        lines, off2 = _tail_jsonl_lines(str(f), off, 60)
        assert lines == [] and off2 == off
        partial3 = json.dumps(_rec(3)).encode()
        with open(f, "ab") as fh:
            fh.write(b"\n")                                  # completes line 1
            fh.write((json.dumps(_rec(2)) + "\n").encode())  # complete line 2
            fh.write(partial3)                               # valid JSON, NO newline
        # lane 2: mixed chunk — complete lines returned, the partial is not,
        # and the offset stops exactly before it
        lines, off3 = _tail_jsonl_lines(str(f), off2, 60)
        assert [d["message"] for d in lines] == ["line 1", "line 2"]
        assert off3 == f.stat().st_size - len(partial3)
        with open(f, "ab") as fh:
            fh.write(b"\n")
        lines, off4 = _tail_jsonl_lines(str(f), off3, 60)
        assert [d["message"] for d in lines] == ["line 3"]
        assert off4 == f.stat().st_size

    def test_rotation_reseeds_from_the_new_file(self, tmp_path):
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(i) for i in range(50)])
        _, off = _tail_jsonl_lines(str(f), 0, 60)
        _write_jsonl(f, [_rec(100), _rec(101)])  # rotated: new, smaller file
        assert f.stat().st_size < off
        lines, off2 = _tail_jsonl_lines(str(f), off, 60)
        assert [d["message"] for d in lines] == ["line 100", "line 101"]
        assert off2 == f.stat().st_size

    def test_missing_file_is_empty_at_offset_zero(self, tmp_path):
        assert _tail_jsonl_lines(str(tmp_path / "absent.jsonl"), 12345, 60) == ([], 0)

    def test_malformed_and_non_dict_lines_are_skipped(self, tmp_path):
        f = tmp_path / "log.jsonl"
        good = _rec(1)
        f.write_bytes(
            (json.dumps(good) + "\n").encode()
            + b"{not json at all\n"
            + b'"a bare string"\n'
            + (json.dumps(_rec(2)) + "\n").encode()
        )
        lines, off = _tail_jsonl_lines(str(f), 0, 60)
        assert [d["message"] for d in lines] == ["line 1", "line 2"]
        assert off == f.stat().st_size  # skipped lines are still consumed

    def test_oversized_line_skips_forward_instead_of_wedging(self, tmp_path):
        """audit MED-1: a single line larger than max_bytes must not freeze
        the lane at its own offset until rotation — a full window with no
        newline advances past itself, and parsing resumes at the next real
        line (the giant line itself is dropped as an unparseable fragment)."""
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(0)])
        _, off = _tail_jsonl_lines(str(f), 0, 60, max_bytes=100)
        giant = json.dumps(_rec(1, message="g" * 400))
        with open(f, "ab") as fh:
            fh.write((giant + "\n").encode())
            fh.write((json.dumps(_rec(2)) + "\n").encode())
        seen, cur = [], off
        for _ in range(12):  # bounded walk — must drain well within this
            lines, nxt = _tail_jsonl_lines(str(f), cur, 60, max_bytes=100)
            seen += [d["message"] for d in lines]
            if nxt == cur:
                break
            cur = nxt
        assert "line 2" in seen          # the lane healed past the giant line
        assert cur == f.stat().st_size   # and fully drained

    def test_poll_burst_respects_limit_but_consumes_everything(self, tmp_path):
        """audit LOW-6: the poll path honors `limit` (newest wins) while the
        offset still advances past every parsed line."""
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(0)])
        _, off = _tail_jsonl_lines(str(f), 0, 60)
        with open(f, "ab") as fh:
            for i in range(1, 11):
                fh.write((json.dumps(_rec(i)) + "\n").encode())
        lines, off2 = _tail_jsonl_lines(str(f), off, 3)
        assert [d["message"] for d in lines] == ["line 8", "line 9", "line 10"]
        assert off2 == f.stat().st_size

    def test_seed_window_cut_drops_the_leading_partial_line(self, tmp_path):
        """When the byte window opens mid-line, the fragment is dropped — every
        returned record parsed from a COMPLETE line."""
        f = tmp_path / "log.jsonl"
        _write_jsonl(f, [_rec(i, message="x" * 40) for i in range(30)])
        lines, off = _tail_jsonl_lines(str(f), 0, 60, max_bytes=500)
        assert lines, "window too small to fit any complete line"
        assert all(d["message"] == "x" * 40 for d in lines)
        assert off == f.stat().st_size


# ── 2. the jsonl line formatter, executed ───────────────────────────────────

class TestJsonlLiveLine:
    @pytest.mark.parametrize("level,tone", [
        ("INFO", "sub"), ("DEBUG", "sub"), ("WARNING", "warn"),
        ("ERROR", "err"), ("CRITICAL", "err"), ("bogus", "sub"),
    ])
    def test_level_maps_to_tone(self, level, tone):
        assert _jsonl_live_line(_rec(0, level=level))["tone"] == tone

    def test_message_newlines_collapse_and_long_messages_cap(self):
        line = _jsonl_live_line(_rec(0, message="a\nb\n  c"))
        assert line["msg"] == "a b c"
        line = _jsonl_live_line(_rec(0, message="y" * 500))
        assert len(line["msg"]) == 241 and line["msg"].endswith("…")

    def test_tag_is_last_logger_segment_upper_capped(self):
        assert _jsonl_live_line(_rec(0, logger="core.risk_engine"))["tag"] == "RISK_E"
        assert _jsonl_live_line(_rec(0, logger="main"))["tag"] == "MAIN"

    def test_src_and_sort_key_ride_the_line(self):
        line = _jsonl_live_line(_rec(0, ts="2026-08-05T08:00:01+00:00"))
        assert line["src"] == "jsonl"
        assert line["_ts"] == "2026-08-05T08:00:01+00:00"

    def test_today_rows_are_time_only_and_other_days_gain_the_date(self):
        r = _rec(0, ts="2026-07-23T11:42:33+00:00")
        assert _jsonl_live_line(r, None, today="2026-07-23")["t"] == "11:42:33"
        assert _jsonl_live_line(r, None, today="2026-08-05")["t"] == "07-23 11:42:33"


# ── 3. the events formatter keeps its old default (existing pins) ───────────

class TestEngineLogLineDateAwareness:
    _ROW = {"id": 7, "event_type": "manual_override",
            "payload_json": "{}", "timestamp": "2026-07-23T11:42:33+00:00"}

    def test_default_stays_time_only(self):
        assert _engine_log_line(self._ROW)["t"] == "11:42:33"

    def test_today_kwarg_prefixes_other_days_only(self):
        assert _engine_log_line(self._ROW, None, today="2026-08-05")["t"] == "07-23 11:42:33"
        assert _engine_log_line(self._ROW, None, today="2026-07-23")["t"] == "11:42:33"


# ── 4. the route, executed via direct handler call ──────────────────────────

class TestLiveRoute:
    """Monkeypatched module attrs; asyncio.run drives the async handler. No
    TestClient (house rule) and no live data/ contact — LOG_FILE and the
    events query are both swapped for test doubles."""

    def _call(self, monkeypatch, tmp_path, *, off=0, eid=0,
              jsonl=None, events=None, newest_id=0, tail_raises=False,
              tz_raises=False):
        f = tmp_path / "risk_engine.jsonl"
        _write_jsonl(f, jsonl or [])
        monkeypatch.setattr(config, "LOG_FILE", str(f))
        monkeypatch.setattr(rd, "app_state", SimpleNamespace(active_account_id=1))
        if tz_raises:
            def _tzboom(aid):
                raise RuntimeError("settings DB locked")
            monkeypatch.setattr(rd, "get_account_tz", _tzboom)
        else:
            monkeypatch.setattr(rd, "get_account_tz", lambda aid: None)
        if tail_raises:
            def _boom(*a, **k):
                raise OSError("disk gone")
            monkeypatch.setattr(rd, "_tail_jsonl_lines", _boom)

        def _fake_query(account_id, *, since_id=0, limit=100, data_dir=None):
            if events is None:
                raise RuntimeError("events lane down")
            if since_id and since_id > 0:
                return [r for r in events if r["id"] > since_id][:limit]
            newest = [r for r in events if r["id"] == newest_id]
            return newest[-1:]

        import core.event_log as ev
        monkeypatch.setattr(ev, "query_events_since", _fake_query)
        resp = asyncio.run(rd.api_engine_log_live(off=off, eid=eid, limit=60))
        return json.loads(resp.body)

    _EV = [
        {"id": 1217, "event_type": "dd_state_transition",
         "payload_json": json.dumps({"from": "normal", "to": "caution"}),
         "timestamp": "2026-08-05T08:00:02+00:00"},
        {"id": 1218, "event_type": "manual_override",
         "payload_json": "{}", "timestamp": "2026-08-05T08:00:04+00:00"},
    ]

    def test_seed_sets_the_event_cursor_without_historical_rows(self, monkeypatch, tmp_path):
        """The option-3 decision: the seed must NOT resurrect weeks-old audit
        rows — it shows recent jsonl lines and arms the id cursor."""
        d = self._call(monkeypatch, tmp_path, off=0, eid=0,
                       jsonl=[_rec(i) for i in range(3)],
                       events=self._EV, newest_id=1218)
        assert d["eid"] == 1218
        assert [x for x in d["lines"] if x.get("src") == "event"] == []
        assert [x["msg"] for x in d["lines"]] == ["line 0", "line 1", "line 2"]
        assert d["off"] > 0

    def test_poll_merges_new_events_highlighted_in_ts_order(self, monkeypatch, tmp_path):
        already_seen = _rec(0, ts="2026-08-05T07:59:59+00:00")
        jsonl = [
            already_seen,
            _rec(1, ts="2026-08-05T08:00:01+00:00"),
            _rec(3, ts="2026-08-05T08:00:03+00:00"),
        ]
        # poll from the REAL line boundary after the already-seen first line
        # (an offset cut mid-line is the rotation self-heal lane, not this test)
        boundary = len((json.dumps(already_seen) + "\n").encode("utf-8"))
        d = self._call(monkeypatch, tmp_path, off=boundary, eid=1216,
                       jsonl=jsonl, events=self._EV, newest_id=1218)
        srcs = [(x.get("src"), x.get("id")) for x in d["lines"]]
        # ts-interleaved: jsonl 08:00:01 < event 08:00:02 < jsonl 08:00:03 < event 08:00:04
        assert srcs == [("jsonl", None), ("event", 1217), ("jsonl", None), ("event", 1218)]
        assert d["eid"] == 1218
        ev_rows = [x for x in d["lines"] if x.get("src") == "event"]
        assert ev_rows and all("_ts" not in x for x in d["lines"])
        assert ev_rows[0]["msg"].startswith("DD normal → caution")

    def test_both_lanes_fail_soft_with_cursors_unchanged(self, monkeypatch, tmp_path):
        d = self._call(monkeypatch, tmp_path, off=777, eid=1216,
                       jsonl=None, events=None, tail_raises=True)
        assert d == {"lines": [], "off": 777, "eid": 1216}

    def test_route_never_500s_shape(self, monkeypatch, tmp_path):
        """Empty file + empty events table: the honest empty page, with the
        events cursor armed at the -1 sentinel (armed-at-empty, audit LOW-4)."""
        d = self._call(monkeypatch, tmp_path, off=0, eid=0, jsonl=[], events=[])
        assert d == {"lines": [], "off": 0, "eid": -1}

    def test_armed_at_empty_delivers_the_first_ever_event(self, monkeypatch, tmp_path):
        """audit LOW-4: with the table empty at arming (eid=-1), the first
        event ever written must be DELIVERED by the next poll — the old
        re-arming pass consumed it unseen."""
        first = {"id": 1, "event_type": "manual_override",
                 "payload_json": "{}", "timestamp": "2026-08-05T09:00:00+00:00"}
        d = self._call(monkeypatch, tmp_path, off=1, eid=-1,
                       jsonl=[], events=[first], newest_id=1)
        ev = [x for x in d["lines"] if x.get("src") == "event"]
        assert [x["id"] for x in ev] == [1]
        assert d["eid"] == 1

    def test_tz_lookup_failure_does_not_500(self, monkeypatch, tmp_path):
        """audit LOW-7: tz is presentation-only — a settings-DB failure must
        not break the poll loop."""
        d = self._call(monkeypatch, tmp_path, off=0, eid=0,
                       jsonl=[_rec(0)], events=[], tz_raises=True)
        assert [x["msg"] for x in d["lines"]] == ["line 0"]


# ── 5. frontend pins (stripped source; every pin mutation-checked) ──────────

_DASH = _code((_ROOT / "frontend" / "src" / "dash-tiled.jsx").read_text(encoding="utf-8"))


def _slice(src: str, start_marker: str) -> str:
    i = src.index(start_marker)
    j = src.find("\nconst ", i + 1)
    return src[i:j if j > 0 else len(src)]


class TestFrontendLiveFeedPins:
    def test_the_stripper_is_not_vacuous(self):
        assert len([ln for ln in _DASH.splitlines() if ln.strip()]) > 300

    def test_loadlog_polls_the_live_route_with_both_cursors(self):
        body = _slice(_DASH, "async function loadLog(")
        assert "'/api/engine/log/live?off=' + state.logOff + '&eid=' + state.logEid" in body
        # two-sided: the retired single-cursor URL is gone from the whole file
        assert "/api/engine/log?since=" not in _DASH

    def test_the_store_holds_both_cursors_and_the_old_one_is_gone(self):
        assert "logOff: 0" in _DASH and "logEid: 0" in _DASH
        assert "logCursor" not in _DASH

    def test_loadlog_echoes_the_server_cursors(self):
        body = _slice(_DASH, "async function loadLog(")
        assert "if (d.off != null) state.logOff = d.off;" in body
        assert "if (d.eid != null) state.logEid = d.eid;" in body

    def test_loadlog_carries_the_overlap_latch(self):
        """audit MED-2: the 5 s deadline exceeds the 4 s interval, so without
        a latch two overlapping polls carry the same cursors and prepend the
        same lines twice (and a late stale response regresses the cursors).
        Safe now BECAUSE every read carries the settlement-guaranteed
        deadline — the pre-deadline latch-wedge class cannot recur."""
        body = _slice(_DASH, "async function loadLog(")
        assert "if (_logInFlight) return;" in body
        assert "finally { _logInFlight = false; }" in body

    def test_event_rows_skip_the_fade_and_bold_the_tag(self):
        body = _slice(_DASH, "const EngineLogBody")
        # brace/ternary-head anchored (substring-contains-mutant class)
        assert "opacity: (l.src === 'event' || i === 0) ? 1 :" in body
        assert "fontWeight: l.src === 'event' ? 700 : 400" in body

    def test_the_log_dot_mirrors_the_pipe_not_a_hardcoded_ok(self):
        pane = _slice(_DASH, "const EngineLogPane")
        assert "logNet.err ? 'err' : (logNet.ms != null ? 'ok' : 'off')" in pane
        assert "tone={logTone}" in pane
        assert 'tone="ok"' not in pane


# ── 6. the route registration is two-sided ──────────────────────────────────

class TestRouteRegistration:
    _SRC = (_ROOT / "api" / "routes_dashboard.py").read_text(encoding="utf-8")

    def test_live_route_is_registered_once(self):
        assert self._SRC.count('@router.get("/api/engine/log/live")') == 1

    def test_the_old_tail_route_survives(self):
        """Deliberately kept (read-only door, existing pins). Its LAST frontend
        consumer moved to /live — if this pin ever blocks a retirement sweep,
        retire the route WITH it."""
        assert self._SRC.count('@router.get("/api/engine/log")') == 1
