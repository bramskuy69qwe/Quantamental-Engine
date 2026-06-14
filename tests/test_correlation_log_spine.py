"""CL.T0a — correlation-log spine tests (emit side; no file I/O).

Covers the T0a slice of the Phase-0 test list (plan §Phase 0): envelope
shape, seq/task semantics, scope mint/reset, json-safety, size cap,
redaction, registry/profile derivation, disabled short-circuit, sampling.
CL.T0b extends this file with the sink/thread/file tests.

No file I/O here — emits land in the module queue and are drained by the
tests themselves (the conftest sink-dir guard arrives with the writer
thread in T0b; until then nothing touches disk by construction).
"""

import asyncio
import json
import threading

import pytest

import core.correlation_log as cl


# ── harness ──────────────────────────────────────────────────────────────────

def _drain():
    """Pull every queued line, parsed."""
    out = []
    while True:
        try:
            out.append(json.loads(cl._queue.get_nowait()))
        except Exception:
            break
    return out


@pytest.fixture(autouse=True)
def _clean_spine(monkeypatch):
    """Drain the queue and pin emit-side knobs to known defaults per test."""
    _drain()
    monkeypatch.setattr(cl, "_enabled", True)
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_mark_price_sample", 0)
    monkeypatch.setattr(cl, "_sample_counters", {})
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    monkeypatch.setattr(cl, "_dropping", False)
    monkeypatch.setattr(cl, "_dropped", 0)
    monkeypatch.setattr(cl, "_drop_since", "")
    yield
    cl.close(timeout=2.0)
    _drain()


def _emit_simple(category=cl.CAT_ATTR_MATCH_ATTEMPT, **kw):
    kw.setdefault("account_id", 7)
    cl.emit("order_manager", "internal", "internal", category, kw.pop("payload", {"k": 1}), **kw)


# ── envelope shape ───────────────────────────────────────────────────────────

class TestEnvelopeShape:
    def test_all_fields_present_and_typed(self):
        with cl.correlation_scope("wsu"):
            _emit_simple(symbol="XAUUSDT", payload={"calc_id": "C1"})
        (env,) = _drain()
        assert set(env) == {
            "ts", "seq", "corr_id", "task", "account_id", "symbol",
            "component", "peer", "direction", "category", "payload",
        }
        assert env["ts"].endswith("Z")
        # parseable ISO-8601 UTC, microsecond precision
        from datetime import datetime
        datetime.fromisoformat(env["ts"])
        assert isinstance(env["seq"], int)
        assert env["corr_id"].startswith("wsu-")
        assert isinstance(env["task"], str) and env["task"]
        assert env["account_id"] == 7
        assert env["symbol"] == "XAUUSDT"
        assert env["component"] == "order_manager"
        assert env["category"] == "attr_match_attempt"
        assert env["payload"] == {"calc_id": "C1"}

    def test_seq_monotonic_within_emission_order(self):
        for _ in range(5):
            _emit_simple()
        seqs = [e["seq"] for e in _drain()]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == 5

    def test_symbol_defaults_null(self):
        _emit_simple()
        (env,) = _drain()
        assert env["symbol"] is None

    def test_account_id_resolution_does_not_crash_when_unspecified(self):
        cl.emit("http", "operator", "in", cl.CAT_HTTP_REQUEST, {"path": "/"})
        (env,) = _drain()
        assert "account_id" in env  # value is best-effort (app_state or None)


# ── corr_id scope ────────────────────────────────────────────────────────────

class TestCorrelationScope:
    def test_mint_format(self):
        cid = cl.mint("http")
        prefix, _, tail = cid.rpartition("-")
        assert prefix == "http" and len(tail) == 8
        int(tail, 16)  # hex

    def test_scope_sets_and_resets(self):
        assert cl.current_corr_id() == ""
        with cl.correlation_scope("sch-funding") as cid:
            assert cl.current_corr_id() == cid
            assert cid.startswith("sch-funding-")
        assert cl.current_corr_id() == ""

    def test_nested_scopes_restore(self):
        with cl.correlation_scope("wsu") as outer:
            with cl.correlation_scope("sch") as inner:
                assert cl.current_corr_id() == inner
            assert cl.current_corr_id() == outer

    def test_explicit_rebind(self):
        # the queue-consumer re-bind shape (bus dispatch / webhook worker)
        with cl.correlation_scope(corr_id="wsu-deadbeef"):
            assert cl.current_corr_id() == "wsu-deadbeef"

    def test_scope_resets_on_exception(self):
        with pytest.raises(RuntimeError):
            with cl.correlation_scope("boot"):
                raise RuntimeError("boom")
        assert cl.current_corr_id() == ""

    def test_emit_outside_scope_has_empty_corr_id(self):
        _emit_simple()
        (env,) = _drain()
        assert env["corr_id"] == ""


# ── task field + concurrency (spec §4.1) ─────────────────────────────────────

class TestTaskAndConcurrency:
    def test_task_is_asyncio_task_name_on_loop(self):
        async def main():
            async def worker():
                _emit_simple()
            t = asyncio.create_task(worker(), name="ws-user")
            await t
        asyncio.run(main())
        (env,) = _drain()
        assert env["task"] == "ws-user"

    def test_task_is_thread_name_off_loop(self):
        t = threading.Thread(target=_emit_simple, name="adapter-rest-3")
        t.start()
        t.join()
        (env,) = _drain()
        assert env["task"] == "adapter-rest-3"

    def test_scope_propagates_into_created_task(self):
        async def main():
            async def worker():
                _emit_simple()
            with cl.correlation_scope("wsu") as cid:
                await asyncio.create_task(worker(), name="child")
            return cid
        cid = asyncio.run(main())
        (env,) = _drain()
        assert env["corr_id"] == cid and env["task"] == "child"

    def test_interleaved_tasks_distinct_names_increasing_seq(self):
        async def main():
            async def worker(n):
                for _ in range(3):
                    _emit_simple()
                    await asyncio.sleep(0)
            await asyncio.gather(
                asyncio.create_task(worker(1), name="task-a"),
                asyncio.create_task(worker(2), name="task-b"),
            )
        asyncio.run(main())
        envs = _drain()
        assert len(envs) == 6
        assert {e["task"] for e in envs} == {"task-a", "task-b"}
        seqs = [e["seq"] for e in envs]
        assert seqs == sorted(seqs)  # queue order == atomic allocation order

    def test_seq_unique_under_thread_contention(self):
        def burst():
            for _ in range(200):
                _emit_simple()
        threads = [threading.Thread(target=burst) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        seqs = [e["seq"] for e in _drain()]
        assert len(seqs) == 600
        assert len(set(seqs)) == 600  # atomic allocation, no collision


# ── payload safety ───────────────────────────────────────────────────────────

class TestPayloadSafety:
    def test_non_finite_floats_become_null(self):
        _emit_simple(payload={"a": float("nan"), "b": float("inf"),
                              "c": [float("-inf"), 1.5], "d": {"e": float("nan")}})
        (env,) = _drain()
        assert env["payload"] == {"a": None, "b": None, "c": [None, 1.5], "d": {"e": None}}

    def test_oversized_payload_truncated_not_dropped(self):
        _emit_simple(payload={"blob": "x" * (config_max() * 4), "tpid": "POS-9"})
        envs = _drain()
        assert len(envs) == 1  # never dropped
        p = envs[0]["payload"]
        assert p["_truncated"] is True
        assert p["_bytes"] > config_max()
        assert set(p["keys"]) == {"blob", "tpid"}

    def test_normal_payload_not_truncated(self):
        _emit_simple(payload={"k": "v"})
        (env,) = _drain()
        assert "_truncated" not in env["payload"]

    def test_non_json_type_stringified_not_dropped(self):
        class Weird:
            def __str__(self):
                return "<weird>"
        _emit_simple(payload={"obj": Weird()})
        (env,) = _drain()
        assert env["payload"]["obj"] == "<weird>"

    def test_truncation_summary_itself_bounded(self):
        # audit finding 3: a huge KEY must not blow the cap via the summary
        _emit_simple(payload={"k" * 200_000: 1})
        (env_line,) = [json.dumps(e) for e in _drain()]
        assert len(env_line) <= config_max() + 1024
        env = json.loads(env_line)
        assert env["payload"]["_truncated"] is True
        assert all(len(k) <= 64 for k in env["payload"]["keys"])

    def test_non_finite_dict_key_does_not_drop_envelope(self):
        # audit finding 2: {nan: ...} key crashed dumps (allow_nan=False)
        _emit_simple(payload={float("nan"): "v", "ok": 1})
        (env,) = _drain()
        assert env["payload"]["ok"] == 1
        assert env["payload"]["nan"] == "v"  # key stringified, envelope kept


def config_max():
    import config
    return config.CORR_LOG_MAX_PAYLOAD_BYTES


# ── redaction (spec §7.2) ────────────────────────────────────────────────────

class TestRedaction:
    SECRETS = {
        "api_key": "AKIA-SECRET-1",
        "Authorization": "Bearer xyz.secret",
        "listenKey": "lk-secret-2",
        "X-MBX-APIKEY": "mbx-secret-3",
        "signature": "sig-secret-4",
        "platform_token": "pt-secret-5",
        "Cookie": "session=abc",
    }

    def test_secret_keys_redacted_at_all_depths(self):
        _emit_simple(payload={**self.SECRETS,
                              "nested": {"api_secret": "deep-secret-6"},
                              "rows": [{"password": "p7"}],
                              "symbol": "BTCUSDT", "qty": 1.0})
        (env,) = _drain()
        line = json.dumps(env)
        for v in list(self.SECRETS.values()) + ["deep-secret-6", "p7"]:
            assert v not in line
        p = env["payload"]
        assert p["api_key"] == "[REDACTED]" and p["nested"]["api_secret"] == "[REDACTED]"
        assert p["rows"][0]["password"] == "[REDACTED]"
        # non-secret fields untouched
        assert p["symbol"] == "BTCUSDT" and p["qty"] == 1.0


# ── registry / profiles / gating (spec §5.8, §7.3) ───────────────────────────

class TestRegistryAndProfiles:
    def test_every_category_has_a_group(self):
        reg = cl.registry()
        assert reg, "registry must not be empty"
        valid = {cl.GROUP_HTTP, cl.GROUP_MARKET, cl.GROUP_LIFECYCLE, cl.GROUP_STATE,
                 cl.GROUP_ATTR, cl.GROUP_BUS, cl.GROUP_WS_LIFECYCLE, cl.GROUP_OUTBOUND,
                 cl.GROUP_DB, cl.GROUP_META}
        assert set(reg.values()) <= valid

    def test_ten_attr_categories_registered(self):
        # CL.T5 (HA-40) added attr_close_stamp — the 10th. The spec §5.6
        # table named nine; the closing-fill primary-calc inheritance was a
        # §5.6-class decision it never listed.
        attr = [c for c, g in cl.registry().items() if g == cl.GROUP_ATTR]
        assert len(attr) == 10

    def test_registry_snapshot_ha3(self):
        """HA-3: a silent re-group (editing a register() line) would move a
        category in/out of the linkage profile with the suite green — the
        register() conflict guard only sees a SECOND registration. Any
        re-group must be a conscious two-file edit (code + this snapshot)."""
        assert cl.registry() == {
            # http
            "http_request": "http", "http_response": "http",
            # bus
            "bus_publish": "bus", "bus_deliver": "bus",
            # outbound
            "rest_call": "outbound", "rest_return": "outbound",
            "http_out_call": "outbound", "http_out_return": "outbound",
            # lifecycle frames
            "ws_account_update": "lifecycle", "ws_order_update": "lifecycle",
            "ws_algo_update": "lifecycle", "platform_fill": "lifecycle",
            "platform_snapshot": "lifecycle", "platform_hello": "lifecycle",
            # market (volume-gated; OFF in linkage)
            "platform_push": "market", "ws_news": "market",
            "ws_kline": "market", "ws_depth": "market",
            "ws_mark_price": "market", "pubsub_publish": "market",
            # ws_lifecycle
            "ws_connect": "ws_lifecycle", "ws_connected": "ws_lifecycle",
            "ws_disconnect": "ws_lifecycle", "ws_stream_rebuild": "ws_lifecycle",
            "calc_symbol_change": "ws_lifecycle",
            "ws_listenkey_keepalive": "ws_lifecycle",
            # state
            "position_snapshot_applied": "state",
            "position_incremental_applied": "state",
            "account_update_applied": "state", "portfolio_recalculated": "state",
            "calc_transition": "state", "link_transition": "state",
            "order_status_applied": "state", "reconcile_promote": "state",
            # db
            "db_write": "db",
            # attr (the nine + CL.T5 HA-40's attr_close_stamp = ten)
            "attr_match_attempt": "attr", "attr_tpid_resolve": "attr",
            "attr_close_build": "attr", "attr_bracket_inherit": "attr",
            "attr_reenrich_trigger": "attr", "attr_junction_form": "attr",
            "attr_enrich": "attr", "attr_drift_check": "attr",
            "attr_funding_assign": "attr", "attr_close_stamp": "attr",
            # meta
            "overflow": "meta",
        }

    def test_unknown_category_raises_loudly(self):
        with pytest.raises(ValueError, match="unregistered"):
            cl.enabled("attr_typo_category")

    def test_emit_with_unknown_category_logs_once_never_raises(self, caplog):
        for _ in range(3):
            _emit_simple(category="attr_typo_category")
        assert _drain() == []
        assert "attr_typo_category" in cl._emit_error_logged
        assert sum("emit failed" in r.message for r in caplog.records) == 1

    def test_emit_with_unhashable_category_never_raises(self):
        # audit finding 4: TypeError in the once-log set escaped emit
        cl.emit("x", "internal", "internal", ["not-hashable"], {"k": 1})
        assert _drain() == []

    def test_register_conflict_raises(self):
        # audit finding 5: a silent re-group would move a category in/out
        # of the linkage profile — the §5.8 drift class
        with pytest.raises(ValueError, match="already registered"):
            cl.register(cl.CAT_DB_WRITE, cl.GROUP_MARKET)
        cl.register(cl.CAT_DB_WRITE, cl.GROUP_DB)  # idempotent same-group OK
        assert cl.registry()[cl.CAT_DB_WRITE] == cl.GROUP_DB

    def test_linkage_profile_derivation(self, monkeypatch):
        monkeypatch.setattr(cl, "_profile", "linkage")
        assert cl.enabled(cl.CAT_ATTR_MATCH_ATTEMPT)
        assert cl.enabled(cl.CAT_BUS_DELIVER)
        assert cl.enabled(cl.CAT_DB_WRITE)
        assert cl.enabled(cl.CAT_WS_ORDER_UPDATE)        # lifecycle frames stay
        assert cl.enabled(cl.CAT_WS_STREAM_REBUILD)      # ws_lifecycle stays
        assert cl.enabled(cl.CAT_OVERFLOW)               # meta always-on
        assert not cl.enabled(cl.CAT_WS_KLINE)           # market dropped
        assert not cl.enabled(cl.CAT_PUBSUB_PUBLISH)     # market-grouped
        assert not cl.enabled(cl.CAT_HTTP_REQUEST)       # http dropped
        assert not cl.enabled(cl.CAT_REST_CALL)          # outbound dropped

    def test_off_profile_disables_everything(self, monkeypatch):
        monkeypatch.setattr(cl, "_profile", "off")
        for cat in cl.registry():
            assert not cl.enabled(cat)

    def test_master_switch_disables_everything(self, monkeypatch):
        monkeypatch.setattr(cl, "_enabled", False)
        assert not cl.enabled(cl.CAT_ATTR_MATCH_ATTEMPT)
        _emit_simple()
        assert _drain() == []

    def test_depth_default_off_in_full(self):
        assert not cl.enabled(cl.CAT_WS_DEPTH)
        assert cl.enabled(cl.CAT_WS_KLINE)

    def test_mark_price_off_at_sample_zero(self):
        assert not cl.enabled(cl.CAT_WS_MARK_PRICE)

    def test_enabled_is_pure_for_sampled_categories(self, monkeypatch):
        # audit finding 1: a sampling draw inside enabled() made the
        # documented pre-gate pattern consume the draw → zero emissions.
        monkeypatch.setattr(cl, "_mark_price_sample", 3)
        assert all(cl.enabled(cl.CAT_WS_MARK_PRICE) for _ in range(10))

    def test_mark_price_one_in_n_sampling_is_emit_driven(self, monkeypatch):
        monkeypatch.setattr(cl, "_mark_price_sample", 3)
        for _ in range(6):
            _emit_simple(category=cl.CAT_WS_MARK_PRICE)
        assert len(_drain()) == 2  # 3rd and 6th

    def test_pre_gate_pattern_still_samples_correctly(self, monkeypatch):
        # the exact callsite shape emit's docstring recommends
        monkeypatch.setattr(cl, "_mark_price_sample", 3)
        for _ in range(6):
            if cl.enabled(cl.CAT_WS_MARK_PRICE):
                _emit_simple(category=cl.CAT_WS_MARK_PRICE)
        assert len(_drain()) == 2  # NOT zero (the finding-1 regression)

    def test_disabled_category_short_circuits_before_payload_work(self, monkeypatch):
        calls = {"n": 0}
        real = cl._redact
        def counting_redact(obj):
            calls["n"] += 1
            return real(obj)
        monkeypatch.setattr(cl, "_redact", counting_redact)
        monkeypatch.setattr(cl, "_profile", "off")
        _emit_simple()
        assert calls["n"] == 0 and _drain() == []
        monkeypatch.setattr(cl, "_profile", "full")
        _emit_simple()
        # _redact recurses into values, so the count is >=1, not exactly 1 —
        # the load-bearing assertion is the 0 above (disabled = no payload work).
        assert calls["n"] >= 1 and len(_drain()) == 1


# ── sink: writer thread / file / rotation / bounds (CL.T0b) ──────────────────

def _sink_dir():
    from pathlib import Path
    return Path(cl._resolve_sink_dir())  # conftest patches this to a tmp dir


def _day_file(date_str=None):
    return _sink_dir() / f"corr-{date_str or cl._today_utc()}.jsonl"


def _read_lines(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]


def _wait_for(cond, timeout=3.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestSinkWriter:
    def test_writer_drains_and_close_flushes_ndjson_in_seq_order(self):
        with cl.correlation_scope("boot"):
            for i in range(5):
                _emit_simple(payload={"i": i})
        cl.start()
        cl.close()
        lines = _read_lines(_day_file())
        assert [l["payload"]["i"] for l in lines] == [0, 1, 2, 3, 4]
        seqs = [l["seq"] for l in lines]
        assert seqs == sorted(seqs)

    def test_restart_same_day_appends_not_truncates(self):
        _emit_simple(payload={"batch": 1})
        cl.start()
        cl.close()
        _emit_simple(payload={"batch": 2})
        cl.start()
        cl.close()
        batches = [l["payload"]["batch"] for l in _read_lines(_day_file())]
        assert batches == [1, 2]

    def test_start_idempotent_and_close_without_start_is_noop(self):
        cl.close()  # never started — no raise
        cl.start()
        t1 = cl._writer_thread
        cl.start()
        assert cl._writer_thread is t1
        cl.close()
        assert cl._writer_thread is None

    def test_start_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr(cl, "_enabled", False)
        cl.start()
        assert cl._writer_thread is None

    def test_rollover_mid_run_opens_new_dated_file_no_rename(self, monkeypatch):
        real_today = cl._today_utc()
        from datetime import datetime, timedelta
        next_day = (datetime.fromisoformat(real_today) + timedelta(days=1)).strftime("%Y-%m-%d")
        day = {"v": real_today}
        monkeypatch.setattr(cl, "_today_utc", lambda: day["v"])
        cl.start()
        _emit_simple(payload={"day": 1})
        assert _wait_for(lambda: _day_file(real_today).exists()
                         and len(_read_lines(_day_file(real_today))) == 1)
        # plant an over-retention file: the ROLLOVER prune must delete it
        stale = _sink_dir() / "corr-2020-01-01.jsonl"
        stale.write_text("{}\n", encoding="utf-8")
        day["v"] = next_day  # UTC date rolls
        _emit_simple(payload={"day": 2})
        cl.close()
        assert [l["payload"]["day"] for l in _read_lines(_day_file(real_today))] == [1]
        assert [l["payload"]["day"] for l in _read_lines(_day_file(next_day))] == [2]
        assert not stale.exists()  # rollover-path prune (not just startup)

    def test_stale_sentinel_from_previous_generation_is_skipped(self):
        # audit finding 2: a sentinel left by a timed-out close of an OLD
        # writer generation must not kill the NEXT writer.
        cl._queue.put_nowait(object())  # stale foreign sentinel
        _emit_simple(payload={"alive": True})
        cl.start()
        cl.close()
        lines = _read_lines(_day_file())
        assert [l["payload"].get("alive") for l in lines] == [True]

    def test_prune_at_start_deletes_only_old_sink_files(self):
        d = _sink_dir()
        d.mkdir(parents=True, exist_ok=True)
        old = d / "corr-2020-01-01.jsonl"
        old.write_text("{}\n", encoding="utf-8")
        bystander = d / "corr-garbage.txt"
        bystander.write_text("keep me", encoding="utf-8")
        cl.start()
        cl.close()
        assert not old.exists()           # older than retention → pruned
        assert bystander.exists()         # non-matching name → untouched
        assert _day_file().exists()       # current day file created

    def test_day_cap_marker_once_then_discard(self, monkeypatch):
        monkeypatch.setattr(cl, "_max_day_bytes", lambda: 300)
        for i in range(3):
            _emit_simple(payload={"b1": i})
        cl.start()
        # first batch (3 lines ≈ 800B) lands, blows the cap → one marker
        assert _wait_for(lambda: _day_file().exists()
                         and len(_read_lines(_day_file())) == 4)
        for i in range(3):
            _emit_simple(payload={"b2": i})  # post-cap → discarded
        cl.close()
        lines = _read_lines(_day_file())
        assert len(lines) == 4
        marker = lines[-1]
        assert marker["category"] == "overflow"
        assert marker["payload"]["reason"] == "day_cap"
        assert not any("b2" in json.dumps(l) for l in lines)

    def test_overflow_drop_count_and_recovery_marker(self, monkeypatch):
        # no writer running — deterministic queue-side check
        monkeypatch.setattr(cl, "_max_inflight", lambda: 5)
        for i in range(8):
            _emit_simple(payload={"i": i})
        assert cl._queue.qsize() == 5      # 3 dropped
        assert cl._dropping and cl._dropped == 3
        kept = _drain()                    # pressure released
        assert [e["payload"]["i"] for e in kept] == [0, 1, 2, 3, 4]
        _emit_simple(payload={"i": 99})    # recovery → marker + line
        out = _drain()
        assert len(out) == 2
        marker, line = out
        assert marker["category"] == "overflow"
        assert marker["payload"]["reason"] == "queue_overflow"
        assert marker["payload"]["dropped"] == 3
        assert line["payload"]["i"] == 99
        assert not cl._dropping and cl._dropped == 0

    def test_conftest_guard_redirects_sink_dir_to_tmp(self, tmp_path):
        import config
        resolved = cl._resolve_sink_dir()
        assert str(tmp_path) in resolved
        assert resolved != config.CORR_LOG_DIR
