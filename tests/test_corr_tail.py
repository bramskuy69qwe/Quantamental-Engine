"""CL.T4 — tests for ``scripts/corr_tail.py`` (plan Phase-4 Tests row).

Coverage mandated by the plan: each filter returns the right subset from
a synthetic NDJSON fixture; chain output is seq-ordered; interleave and
dups modes; a fixture line with an unknown extra field parses fine.
Plus the CL.T4 binding queue: --dups must not assume one dedup_key shape
(HA-32) and must default-exclude benign funding re-polls (HA-33); the
cookbook must ship the as-built keys (E23 terminal_position_id,
row_written, rowcount, build_incomplete — pinned as a docs-wiring test).
"""

from __future__ import annotations

import json
import os

import pytest

from scripts.corr_tail import (
    Filters,
    category_matches,
    find_dups,
    follow_stream,
    format_line,
    main,
    parse_envelope,
    resolve_files,
    run_follow,
    scan,
    sort_key,
)

DAY = "2026-06-12"


def ts(sec: int, micro: int = 0, minute: int = 0) -> str:
    return f"{DAY}T09:{minute:02d}:{sec:02d}.{micro:06d}Z"


def mk(seq, ts_, corr="wsu-aaaa0001", cat="ws_order_update", payload=None,
       symbol=None, task="ws-user", component="ws_manager", **extra) -> str:
    env = {
        "ts": ts_, "seq": seq, "corr_id": corr, "task": task,
        "account_id": 1, "symbol": symbol, "component": component,
        "peer": "binance", "direction": "in", "category": cat,
        "payload": {} if payload is None else payload,
    }
    env.update(extra)
    return json.dumps(env)


def write_day(tmp_path, lines, day=DAY):
    p = tmp_path / f"corr-{day}.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def out_lines(capsys):
    captured = capsys.readouterr()
    return [l for l in captured.out.splitlines() if l], captured.err


def seqs_of(raw_stdout_lines):
    return [json.loads(l)["seq"] for l in raw_stdout_lines]


# ── parsing & tolerance (plan: unknown-field line parses fine) ───────────────


class TestParseTolerance:
    def test_unknown_extra_field_parses_and_prints(self, tmp_path, capsys):
        line = mk(1, ts(1), future_field={"nested": True})
        path = write_day(tmp_path, [line])
        assert main([path, "--raw"]) == 0
        out, _err = out_lines(capsys)
        assert out == [line]

    def test_unknown_category_tolerated(self, tmp_path, capsys):
        # forward compat: a category added mid-week must not break the reader
        path = write_day(tmp_path, [mk(1, ts(1), cat="category_from_the_future")])
        assert main([path]) == 0
        out, _err = out_lines(capsys)
        assert len(out) == 1
        assert "category_from_the_future" in out[0]

    def test_malformed_lines_skipped_and_counted(self, tmp_path, capsys):
        good = mk(1, ts(1))
        path = tmp_path / f"corr-{DAY}.jsonl"
        path.write_text(
            good + "\n" + "{this is not json\n" + "\n" + '"a bare string"\n',
            encoding="utf-8",
        )
        assert main([str(path), "--raw"]) == 0
        out, err = out_lines(capsys)
        assert out == [good]
        # garbage + non-object counted; the blank line is not
        assert "skipped 2 unparseable line(s)" in err

    def test_parse_envelope_rejects_non_objects(self):
        assert parse_envelope("") is None
        assert parse_envelope("[1,2]") is None
        assert parse_envelope("not json") is None
        assert parse_envelope('{"seq": 1}') == {"seq": 1}


# ── filters (plan: each filter returns the right subset) ────────────────────


class TestFilters:
    def test_corr_id_chain_seq_ordered(self, tmp_path, capsys):
        # written out of order; one foreign chain interleaved
        lines = [
            mk(3, ts(3), corr="wsu-chain0001"),
            mk(1, ts(1), corr="wsu-chain0001"),
            mk(7, ts(2), corr="sch-other0001"),
            mk(2, ts(2), corr="wsu-chain0001"),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--corr-id", "wsu-chain0001"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1, 2, 3]

    def test_sort_across_restart_ts_wins(self, tmp_path, capsys):
        # seq resets per process run (spec §7.5): the restarted run's seq=1
        # must sort AFTER the prior run's higher seqs, by ts
        lines = [
            mk(100, ts(1)),
            mk(101, ts(2)),
            mk(1, ts(3)),  # post-restart
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [100, 101, 1]

    def test_symbol_filter(self, tmp_path, capsys):
        lines = [
            mk(1, ts(1), symbol="XAUUSDT"),
            mk(2, ts(2), symbol="BTCUSDT"),
            mk(3, ts(3), symbol=None),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--symbol", "XAUUSDT"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1]

    def test_category_exact_and_prefix(self, tmp_path, capsys):
        lines = [
            mk(1, ts(1), cat="ws_order_update"),
            mk(2, ts(2), cat="attr_close_build"),
            mk(3, ts(3), cat="attr_enrich"),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--category", "attr_*"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [2, 3]
        assert main([path, "--raw", "--category", "ws_order_update"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1]

    def test_category_repeatable_is_or(self, tmp_path, capsys):
        lines = [
            mk(1, ts(1), cat="ws_order_update"),
            mk(2, ts(2), cat="attr_close_build"),
            mk(3, ts(3), cat="db_write"),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--category", "ws_order_update",
                     "--category", "db_write"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1, 3]

    def test_category_matches_unit(self):
        assert category_matches("attr_close_build", "attr_*")
        assert category_matches("attr_close_build", "attr_close_build")
        assert not category_matches("attr_close_build", "attr_close")
        assert not category_matches("ws_order_update", "attr_*")

    def test_calc_id_substring_matches_payload_and_dedup_tag(self, tmp_path, capsys):
        # HA-26 rationale: the id may live under a prefixed key or inside a
        # dedup tag — the substring match catches both; exact-key would miss
        lines = [
            mk(1, ts(1), payload={"calc_id": "CALC-777"}),
            mk(2, ts(2), payload={"dedup_key": "manual:42:CALC-777"}),
            mk(3, ts(3), payload={"calc_id": "CALC-999"}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--calc-id", "CALC-777"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1, 2]

    def test_time_window_half_open(self, tmp_path, capsys):
        lines = [
            mk(1, ts(0)),
            mk(2, ts(30)),
            mk(3, ts(0, minute=1)),
        ]
        path = write_day(tmp_path, lines)
        # inclusive lower bound; trailing Z and space both normalized
        assert main([path, "--raw", "--since", f"{DAY}T09:00:30Z"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [2, 3]
        # exclusive upper bound at the given precision
        assert main([path, "--raw", "--until", f"{DAY} 09:01"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1, 2]

    def test_filters_compose_and(self, tmp_path, capsys):
        lines = [
            mk(1, ts(1), symbol="XAUUSDT", cat="attr_close_build"),
            mk(2, ts(2), symbol="XAUUSDT", cat="ws_order_update"),
            mk(3, ts(3), symbol="BTCUSDT", cat="attr_close_build"),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--symbol", "XAUUSDT",
                     "--category", "attr_*"]) == 0
        out, _ = out_lines(capsys)
        assert seqs_of(out) == [1]

    def test_no_ts_line_excluded_from_time_window_only(self):
        f = Filters(since=f"{DAY}T09:00:00")
        env = {"seq": 1, "category": "x"}  # no ts at all
        assert not f.matches(env, json.dumps(env))
        assert Filters().matches(env, json.dumps(env))

    def test_zero_matches_reported_to_stderr(self, tmp_path, capsys):
        path = write_day(tmp_path, [mk(1, ts(1))])
        assert main([path, "--corr-id", "nope"]) == 0
        out, err = out_lines(capsys)
        assert out == []
        assert "0 lines matched" in err

    def test_days_cross_file_merge_sorted(self, tmp_path, capsys):
        # the --calc-id ... --days N acceptance path: two day files whose
        # lines interleave by ts must come out globally (ts, seq)-ordered,
        # and the --calc-id substring must cross both days
        write_day(tmp_path, [
            mk(10, "2026-06-11T23:59:00.000000Z", payload={"calc_id": "CALC-X"}),
            mk(11, "2026-06-11T23:59:30.000000Z", payload={"calc_id": "CALC-X"}),
        ], day="2026-06-11")
        write_day(tmp_path, [
            mk(1, "2026-06-12T00:00:01.000000Z", payload={"calc_id": "CALC-X"}),
            mk(2, "2026-06-12T00:00:02.000000Z", payload={"calc_id": "CALC-Y"}),
        ], day="2026-06-12")
        rc = main(["--dir", str(tmp_path), "--date", "2026-06-12", "--days", "2",
                   "--raw", "--calc-id", "CALC-X"])
        assert rc == 0
        out, _ = out_lines(capsys)
        # CALC-Y dropped; the three CALC-X lines merge-sorted across the day
        # boundary by ts (the older file's lines first), seq reset honored
        assert seqs_of(out) == [10, 11, 1]


# ── formatting ───────────────────────────────────────────────────────────────


class TestFormat:
    def test_format_line_carries_the_slice_axes(self):
        env = json.loads(mk(42, ts(5), corr="wsu-deadbeef", symbol="XAUUSDT",
                            cat="attr_close_build", component="order_manager",
                            task="ws-user",
                            payload={"row_written": True}))
        line = format_line(env)
        for needle in ("42", ts(5), "wsu-deadbeef", "ws-user",
                       "order_manager/attr_close_build", "XAUUSDT",
                       '"row_written":true'):
            assert needle in line

    def test_format_gist_truncation_is_flagged(self):
        env = json.loads(mk(1, ts(1), payload={"big": "x" * 500}))
        line = format_line(env, gist_max=40)
        assert line.endswith("...")
        assert "x" * 500 not in line

    def test_missing_fields_render_dashes(self):
        line = format_line({"seq": 1})
        assert " - " in line  # absent fields never raise

    def test_sort_key_tolerates_garbage(self):
        assert sort_key({}) == ("", 0)
        assert sort_key({"ts": None, "seq": "weird"}) == ("", 0)


# ── interleave (plan: race-forensics window) ─────────────────────────────────


class TestInterleave:
    def test_window_inclusive_sorted_with_chain_columns(self, tmp_path, capsys):
        lines = [
            mk(5, ts(5), corr="wsu-aaaa0001", task="ws-user"),
            mk(8, ts(8), corr="wsu-aaaa0001", task="ws-user"),
            mk(6, ts(6), corr="sch-bbbb0002", task="sched",
               cat="position_snapshot_applied", component="data_cache"),
            mk(7, ts(7), corr="wsu-aaaa0001", task="ws-user",
               cat="attr_tpid_resolve", component="order_manager"),
            mk(9, ts(9), corr="sch-bbbb0002", task="sched"),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--interleave", "6", "8"]) == 0
        out, _ = out_lines(capsys)
        assert len(out) == 3
        # both chains visible side by side, in (ts, seq) order
        assert "sch-bbbb0002" in out[0] and "sched" in out[0]
        assert "wsu-aaaa0001" in out[1] and "ws-user" in out[1]
        assert "attr_tpid_resolve" in out[1]
        assert "wsu-aaaa0001" in out[2]

    def test_interleave_gists_payload(self, tmp_path, capsys):
        path = write_day(tmp_path, [mk(6, ts(6), payload={"big": "y" * 500})])
        assert main([path, "--interleave", "1", "10"]) == 0
        out, _ = out_lines(capsys)
        assert out[0].endswith("...")
        assert "y" * 500 not in out[0]


# ── dups (plan: dedup_keys seen >1x; HA-32/HA-33) ────────────────────────────


class TestDups:
    def test_same_category_same_key_flagged(self, tmp_path, capsys):
        key = "8821:FILLED:0.42"
        lines = [
            mk(1, ts(1), payload={"dedup_key": key}),
            mk(2, ts(2), payload={"dedup_key": key}),
            mk(3, ts(3), payload={"dedup_key": "8822:NEW:1.0"}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups"]) == 0
        out, _ = out_lines(capsys)
        assert len(out) == 1
        assert out[0].startswith("2x")
        assert key in out[0]
        assert "seqs=1,2" in out[0]

    def test_cross_category_same_key_not_a_dup(self, tmp_path, capsys):
        # HA-32: tag styles are heterogeneous; the same id under two
        # categories is chain pairing, not a double-process
        lines = [
            mk(1, ts(1), cat="ws_order_update", payload={"dedup_key": "K1"}),
            mk(2, ts(2), cat="order_status_applied", payload={"dedup_key": "K1"}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups"]) == 0
        out, err = out_lines(capsys)
        assert out == []
        assert "no duplicate dedup_keys found" in err

    def test_heterogeneous_tag_shapes_are_opaque(self, tmp_path, capsys):
        # a colon-rich manual tag and a bare venue id both group correctly
        lines = [
            mk(1, ts(1), cat="attr_match_attempt",
               payload={"dedup_key": "manual:42:CALC-7"}),
            mk(2, ts(2), cat="attr_match_attempt",
               payload={"dedup_key": "manual:42:CALC-7"}),
            mk(3, ts(3), cat="attr_funding_assign",
               payload={"dedup_key": "9000001", "inserted": True}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups"]) == 0
        out, _ = out_lines(capsys)
        assert len(out) == 1
        assert "manual:42:CALC-7" in out[0]

    def test_funding_repoll_hidden_by_default_ha33(self, tmp_path, capsys):
        veid = "evt-123"
        lines = [
            mk(1, ts(1), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": True}),
            mk(2, ts(2), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": False}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups"]) == 0
        out, err = out_lines(capsys)
        assert out == []
        assert "1 benign funding re-poll line(s) hidden" in err
        assert "--include-benign" in err

    def test_include_benign_counts_repolls(self, tmp_path, capsys):
        veid = "evt-123"
        lines = [
            mk(1, ts(1), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": True}),
            mk(2, ts(2), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": False}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups", "--include-benign"]) == 0
        out, _ = out_lines(capsys)
        assert len(out) == 1
        assert out[0].startswith("2x")

    def test_genuine_funding_double_insert_still_flagged(self, tmp_path, capsys):
        # two inserted:true = a real double-insert; the re-poll is excluded
        # from the count but must not mask it
        veid = "evt-456"
        lines = [
            mk(1, ts(1), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": True}),
            mk(2, ts(2), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": False}),
            mk(3, ts(3), cat="attr_funding_assign",
               payload={"dedup_key": veid, "inserted": True}),
        ]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups"]) == 0
        out, err = out_lines(capsys)
        assert len(out) == 1
        assert out[0].startswith("2x")
        assert "seqs=1,3" in out[0]
        assert "1 benign" in err

    def test_dups_seq_truncation(self, tmp_path, capsys):
        # a single (category, key) group with >10 lines shows the first 10
        # seqs plus a "+N more" tail (no silent cap)
        key = "8821:FILLED:0.42"
        lines = [mk(i, ts(i), payload={"dedup_key": key}) for i in range(1, 14)]
        path = write_day(tmp_path, lines)
        assert main([path, "--dups"]) == 0
        out, _ = out_lines(capsys)
        assert len(out) == 1
        assert out[0].startswith("13x")
        assert "seqs=1,2,3,4,5,6,7,8,9,10 +3 more" in out[0]

    def test_find_dups_ignores_lines_without_key(self):
        parsed = [
            (json.loads(mk(1, ts(1), payload={})), ""),
            (json.loads(mk(2, ts(2), payload={"dedup_key": ""})), ""),
            (json.loads(mk(3, ts(3), payload={"dedup_key": None})), ""),
        ]
        dups, hidden = find_dups(parsed)
        assert dups == [] and hidden == 0


# ── raw passthrough ──────────────────────────────────────────────────────────


class TestRawMode:
    def test_raw_passthrough_is_byte_faithful(self, tmp_path, capsys):
        lines = [mk(1, ts(1), corr="wsu-x1"), mk(2, ts(2), corr="wsu-x1")]
        path = write_day(tmp_path, lines)
        assert main([path, "--raw", "--corr-id", "wsu-x1"]) == 0
        out, _ = out_lines(capsys)
        assert out == lines


# ── file resolution ──────────────────────────────────────────────────────────


class TestResolveFiles:
    def test_explicit_files_win(self, tmp_path):
        p = write_day(tmp_path, [mk(1, ts(1))])
        assert resolve_files([p], None, None, 1) == [p]

    def test_explicit_missing_file_errors(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_files([str(tmp_path / "nope.jsonl")], None, None, 1)

    def test_date_days_selection_oldest_first(self, tmp_path):
        for day in ("2026-06-10", "2026-06-11", "2026-06-12"):
            write_day(tmp_path, [mk(1, f"{day}T00:00:00.000000Z")], day=day)
        got = resolve_files([], str(tmp_path), "2026-06-12", 2)
        assert [os.path.basename(p) for p in got] == [
            "corr-2026-06-11.jsonl", "corr-2026-06-12.jsonl",
        ]
        got = resolve_files([], str(tmp_path), "2026-06-12", 30)
        assert len(got) == 3  # missing days silently absent, existing kept

    def test_no_files_resolved_is_exit_1(self, tmp_path, capsys):
        rc = main(["--dir", str(tmp_path), "--date", "2026-06-12"])
        assert rc == 1
        _, err = out_lines(capsys)
        assert "no correlation files found" in err

    def test_bad_date_is_exit_1(self, tmp_path, capsys):
        rc = main(["--dir", str(tmp_path), "--date", "12-06-2026"])
        assert rc == 1
        _, err = out_lines(capsys)
        assert "YYYY-MM-DD" in err


# ── follow ───────────────────────────────────────────────────────────────────


class TestFollow:
    def test_follow_stream_yields_appended_lines(self, tmp_path):
        p = str(tmp_path / f"corr-{DAY}.jsonl")
        line1, line2 = mk(1, ts(1)), mk(2, ts(2))
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line1 + "\n")
        state = {"calls": 0}

        def hook():
            state["calls"] += 1
            if state["calls"] == 1:
                with open(p, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line2 + "\n")
                return False
            return True

        got = list(follow_stream(lambda: p, {p: 0}, poll=0, should_stop=hook))
        assert got == [line1, line2]

    def test_follow_stream_respects_initial_offset(self, tmp_path):
        p = str(tmp_path / f"corr-{DAY}.jsonl")
        line1, line2 = mk(1, ts(1)), mk(2, ts(2))
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line1 + "\n")
        offset = os.path.getsize(p)

        def hook():
            with open(p, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(line2 + "\n")
            hook_calls.append(1)
            return len(hook_calls) > 1

        hook_calls = []
        got = list(follow_stream(lambda: p, {p: offset}, poll=0,
                                 should_stop=hook))
        assert got == [line2]  # the already-scanned line is not re-emitted

    def test_follow_stream_buffers_partial_lines(self, tmp_path):
        p = str(tmp_path / f"corr-{DAY}.jsonl")
        line1, line2 = mk(1, ts(1)), mk(2, ts(2))
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(line1 + "\n" + line2[:10])  # torn mid-write
        state = {"calls": 0}

        def hook():
            state["calls"] += 1
            if state["calls"] == 1:
                with open(p, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(line2[10:] + "\n")
                return False
            return True

        got = list(follow_stream(lambda: p, {p: 0}, poll=0, should_stop=hook))
        assert got == [line1, line2]  # the torn line arrives once, whole

    def test_follow_stream_rolls_to_new_day_file(self, tmp_path):
        f1 = str(tmp_path / f"corr-{DAY}.jsonl")
        f2 = str(tmp_path / "corr-2026-06-13.jsonl")
        a, b, c = mk(1, ts(1)), mk(2, ts(2)), mk(1, "2026-06-13T00:00:00.000001Z")
        with open(f1, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(a + "\n")
        state = {"calls": 0, "target": f1}

        def hook():
            state["calls"] += 1
            if state["calls"] == 1:
                with open(f1, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(b + "\n")  # lands just before rollover
                with open(f2, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(c + "\n")
                state["target"] = f2
                return False
            return True

        got = list(follow_stream(lambda: state["target"], {f1: os.path.getsize(f1)},
                                 poll=0, should_stop=hook))
        assert got == [b, c]  # old file drained before the switch

    def test_run_follow_applies_filters_to_new_lines(self, tmp_path, capsys):
        p = str(tmp_path / f"corr-{DAY}.jsonl")
        keep0 = mk(1, ts(1), corr="wsu-keep0001")
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(keep0 + "\n")
        keep1 = mk(2, ts(2), corr="wsu-keep0001")
        drop1 = mk(3, ts(3), corr="sch-drop0001")
        state = {"calls": 0}

        def hook():
            state["calls"] += 1
            if state["calls"] == 1:
                with open(p, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(drop1 + "\n" + keep1 + "\n")
                return False
            return True

        rc = run_follow([p], Filters(corr_id="wsu-keep0001"), raw=True,
                        dir_mode_dir=None, poll=0, should_stop=hook)
        assert rc == 0
        out, _ = out_lines(capsys)
        assert out == [keep0, keep1]  # scan output, then the filtered tail


# ── CLI guards ───────────────────────────────────────────────────────────────


class TestCliGuards:
    def test_modes_mutually_exclusive(self, tmp_path):
        p = write_day(tmp_path, [mk(1, ts(1))])
        with pytest.raises(SystemExit):
            main([p, "--dups", "--follow"])
        with pytest.raises(SystemExit):
            main([p, "--interleave", "1", "2", "--dups"])

    def test_include_benign_requires_dups(self, tmp_path):
        p = write_day(tmp_path, [mk(1, ts(1))])
        with pytest.raises(SystemExit):
            main([p, "--include-benign"])

    def test_unknown_category_warns_but_runs(self, tmp_path, capsys):
        # the registry import is available in the test env, so the typo
        # (the spec's own example: attr_tpid_resolved) must warn
        p = write_day(tmp_path, [mk(1, ts(1), cat="attr_tpid_resolve")])
        assert main([p, "--category", "attr_tpid_resolved"]) == 0
        out, err = out_lines(capsys)
        assert out == []
        assert "not in the registry" in err

    def test_known_category_no_warning(self, tmp_path, capsys):
        p = write_day(tmp_path, [mk(1, ts(1), cat="attr_tpid_resolve")])
        assert main([p, "--category", "attr_tpid_resolve"]) == 0
        out, err = out_lines(capsys)
        assert len(out) == 1
        assert "not in the registry" not in err


# ── the cookbook ships the as-built keys (the CL.T4 binding queue) ───────────


class TestCookbookDoc:
    @pytest.fixture(scope="class")
    def cookbook(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, "docs", "correlation_log_cookbook.md")
        assert os.path.exists(path), "CL.T4 cookbook missing"
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def test_e23_real_identity_key(self, cookbook):
        # the stranded-row recipe must use the real envelope key, and must
        # call the spec's tpid shorthand out as not-a-key (the cookbook
        # quotes the broken form only as a warning)
        assert 'select(.payload.terminal_position_id=="")' in cookbook
        assert "shorthand" in cookbook

    def test_ha32_landed_close_predicate(self, cookbook):
        # the working landed-close recipe, not the outcome=="WRITTEN" trap
        assert "(.payload.row_written|not)" in cookbook

    def test_ha33_funding_repoll_caveat(self, cookbook):
        assert "inserted:false" in cookbook

    def test_ha34_terminal_replay_discriminator(self, cookbook):
        # recipe-specific anchor, not a bare "rowcount" (which appears in
        # several unrelated bullets — a dropped HA-34 recipe must FAIL here)
        assert "Terminal replays" in cookbook
        assert "rowcount: 0" in cookbook

    def test_ha38_cancelled_close_build_line(self, cookbook):
        assert "build_incomplete" in cookbook

    def test_dedup_styles_documented_as_heterogeneous(self, cookbook):
        for shape in ("tpid_resolve", "junction:", "manual:", "venue_event_id"):
            assert shape in cookbook
