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
    yield
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

    def test_nine_attr_categories_registered(self):
        attr = [c for c, g in cl.registry().items() if g == cl.GROUP_ATTR]
        assert len(attr) == 9

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
