"""H4 + M10 — the FALSE-SUCCESS class: no write may report success it didn't earn.

Two filings, one mechanism (wiring inventory 2026-07-30, fixed 2026-08-03):

H4 · `POST /accounts/{id}/update` wrapped its `update_account_settings` call in
    `except Exception: pass`, then returned the unconditional green `Saved.`
    span the React Config page keys success on. A failed preferences write
    reported success — silent data loss with positive confirmation, on the
    page that edits risk posture. Same site, second lane: an UNKNOWN timezone
    (or analytics period) was silently dropped (`ZoneInfoNotFoundError →
    pass`) and still answered `Saved.`.

M10 · Linkage's cancel-calc dialog discarded `res.ok` and flashed every
    outcome — including engine refusals and its own "cancel failed" catch —
    under a hardcoded green ✓ toast. `_lkForm` had already body-sniffed the
    truth into `ok` (the cancel door answers 200 for every outcome with the
    outcome in the alert class); the handler threw it away at the last hop.

CLASS INVENTORY (broad re-grep, both sides, before fixing — a finding list is
a sample): AST-walked every api/ handler for except-pass-then-succeed — the
two `update_account_detail` lanes are the only members (activate_account's
swallow is a benign per-position OHLCV prefetch whose outer failure rolls back
with a 500; the rest are read-path). Walked every `_lkForm`/`_cfgPostForm`/
`_cfgPostJson`/`_dashPostJson`/`_rgPost` caller for a discarded `ok` — the
cancel handler was the only one.

Fix shape, and one deviation worth naming: the preference VALIDATION moved to
the TOP of the handler (beside the link_window precedent) instead of erroring
at the write site — a rejected preference no longer costs a partial save.
The WRITE failure lane cannot move up (the write is the thing that fails), so
it returns an err span naming the split: everything above it HAS been written.

THE LOAD-BEARING CONTRACT: the React doSave keys success on `/saved/i` over
the response text. Every failure lane must therefore avoid the word in ANY
casing, and the success span must keep it. That contract spans two files and
nothing but this test holds it together.

Run: pytest tests/test_false_success_class.py -v
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_LK = _code((_ROOT / "frontend" / "src" / "pages-linkage.jsx").read_text(encoding="utf-8"))
_CFG = _code((_ROOT / "frontend" / "src" / "pages-config.jsx").read_text(encoding="utf-8"))


# ── the direct-call harness ─────────────────────────────────────────────────
# A direct handler call bypasses FastAPI DI, so an OMITTED argument would be a
# `Form(None)` sentinel, not None — the add-account precedent. Every parameter
# is therefore passed explicitly; `_call` centralises that so a signature
# change breaks ONE place loudly (TypeError) instead of poisoning every test.

def _call(**over):
    from api.routes_accounts import update_account_detail
    kwargs = dict(
        account_id=over.pop("account_id", 999),
        request=None,
        exchange=None, market_type=None, environment=None,
        api_key=None, api_secret=None, broker_account_id=None,
        maker_fee=None, taker_fee=None,
        individual_risk_per_trade=None, max_w_loss_percent=None,
        max_dd_percent=None, max_exposure=None, max_position_count=None,
        max_correlated_exposure=None, auto_export_hours=None,
        weekly_loss_warning_pct=None, weekly_loss_limit_pct=None,
        max_dd_warning_pct=None, max_dd_limit_pct=None,
        timezone=None, analytics_default_period=None,
        week_start_dow=None,
        link_window_seconds=None,
    )
    kwargs.update(over)
    return asyncio.run(update_account_detail(**kwargs))


@pytest.fixture
def settings_writer(monkeypatch):
    """Records calls to the REAL write target; `.boom = True` makes it raise.

    The handler imports `update_account_settings` INSIDE its body from
    `core.db_account_settings`, so patching that module attribute intercepts
    every call — no app, no TestClient, no live DB (the
    no-write-tests-through-TestClient rule)."""
    import core.db_account_settings as mod
    calls = []

    def stub(account_id, **kw):
        if getattr(stub, "boom", False):
            raise RuntimeError("disk on fire")
        calls.append((account_id, kw))

    stub.calls = calls
    stub.boom = False
    monkeypatch.setattr(mod, "update_account_settings", stub)
    return stub


# ── H4: behaviour, executed against the real handler ───────────────────────

class TestH4SettingsWriteFailure:
    def test_a_failed_write_is_not_reported_as_saved(self, settings_writer):
        """THE defect. Before the fix this exact call returned the green
        `Saved.` span with the exception swallowed."""
        settings_writer.boom = True
        r = _call(timezone="UTC")
        body = r.body.decode()
        assert not re.search(r"saved", body, re.I), (
            f"a failed preferences write still answers with the success "
            f"discriminator: {body!r}"
        )
        assert "Preferences write failed" in body
        assert "var(--red)" in body, "the failure span must not render green"

    def test_the_failure_text_names_the_split_truthfully(self, settings_writer,
                                                         monkeypatch):
        """Fields written before this lane fails must be reported as landed —
        erring the whole save would send the operator re-entering fields that
        stored fine. Exercised with a REAL split (a param submitted alongside,
        its writer observed running) — the first draft asserted the wording on
        a preference-only submit, the one input where the claim is false
        (audit finding). Hence 'any other SUBMITTED fields': universally true,
        vacuously so when nothing else was sent."""
        from api.routes_accounts import account_registry
        wrote = []

        async def params_stub(*a, **kw):
            wrote.append(a)

        monkeypatch.setattr(account_registry, "update_account_params", params_stub)
        monkeypatch.setattr(account_registry, "get_account_params", lambda _aid: {})
        settings_writer.boom = True
        # 0.01, not 1.0: the field is a FRACTION bounded 0.0001-0.1, and an
        # out-of-bounds value returns at the params-validation span — the
        # `assert wrote` below caught this test's own first draft doing that.
        body = _call(timezone="UTC", individual_risk_per_trade=0.01).body.decode()
        assert wrote, "the param writer never ran — this no longer tests the split"
        assert "any other submitted fields were stored" in body
        assert not re.search(r"saved", body, re.I)

    def test_a_successful_write_still_says_saved(self, settings_writer):
        r = _call(timezone="UTC")
        assert re.search(r"saved", r.body.decode(), re.I)
        assert settings_writer.calls == [(999, {"timezone": "UTC"})]

    def test_a_no_settings_save_still_says_saved(self, settings_writer):
        """The pure no-op lane (nothing submitted) keeps the green span and
        never touches the writer.

        NB this DOCUMENTS pre-existing behaviour rather than endorsing it: an
        empty submit answers `Saved.` having written nothing. Against this
        file's thesis that is a (harmless) success report for zero writes —
        the operator clicked Save on an unchanged form and nothing was lost.
        If that lane is ever tightened, update this pin deliberately."""
        r = _call()
        assert re.search(r"saved", r.body.decode(), re.I)
        assert settings_writer.calls == []

    def test_a_valueerror_timezone_is_rejected_not_a_500(self, settings_writer):
        """ZoneInfo('') and path-shaped keys ('/etc/UTC') raise ValueError,
        NOT ZoneInfoNotFoundError — with the original two-member except tuple
        those were unhandled 500s (audit finding; the OLD code 500'd there
        too, just after writing everything).

        Live-verified against the running engine (2026-08-03), which also
        CORRECTED this test's first docstring: through the real door a blank
        `timezone=` arrives as None (FastAPI coerces the empty form value for
        Form(None)), so the '' lane below is direct-call-only defense-in-depth
        — the door-reachable ValueError trigger is the path-shaped key, which
        returned the 400 red span live."""
        for bad in ("", "/etc/UTC"):
            r = _call(timezone=bad)
            assert r.status_code == 400, f"timezone={bad!r} did not 400"
            assert not re.search(r"saved", r.body.decode(), re.I)
        assert settings_writer.calls == []


class TestH4InvalidPreferenceRejected:
    """The second lane at the same site: invalid input used to be silently
    DROPPED and the handler still answered `Saved.` — the operator's timezone
    edit vanished with a green confirmation."""

    def test_unknown_timezone_is_rejected_not_dropped(self, settings_writer):
        r = _call(timezone="Not/AZone")
        body = r.body.decode()
        assert r.status_code == 400
        assert "Not/AZone" in body, "the rejection must name the bad input"
        assert not re.search(r"saved", body, re.I)
        assert settings_writer.calls == []

    def test_unknown_period_is_rejected_not_dropped(self, settings_writer):
        r = _call(analytics_default_period="fortnightly")
        assert r.status_code == 400
        assert "fortnightly" in r.body.decode()
        assert settings_writer.calls == []

    def test_valid_period_still_writes(self, settings_writer):
        from core.period_resolver import VALID_PERIODS
        period = sorted(VALID_PERIODS)[0]
        r = _call(analytics_default_period=period)
        assert re.search(r"saved", r.body.decode(), re.I)
        assert settings_writer.calls == [(999, {"analytics_default_period": period})]

    def test_rejection_happens_before_any_write(self, settings_writer, monkeypatch):
        """The deviation's justification, executed: validation was HOISTED
        above every writer, so a bad preference no longer costs a partial
        save. Submit a bad timezone TOGETHER with a credential edit and a
        param edit; neither writer may run."""
        from api.routes_accounts import account_registry
        reg_calls = []

        async def reg_stub(*a, **kw):
            reg_calls.append(a)

        monkeypatch.setattr(account_registry, "update_account", reg_stub)
        monkeypatch.setattr(account_registry, "update_account_params", reg_stub)
        r = _call(timezone="Not/AZone", api_key="k", individual_risk_per_trade=1.0)
        assert r.status_code == 400
        assert reg_calls == [], (
            "a rejected preference still cost a partial write — the "
            "validation is no longer hoisted above the writers"
        )
        assert settings_writer.calls == []


class TestM3WeekStartDowValidation:
    """M3 (dead-settings batch, 2026-08-04): week_start_dow joined the
    preference lane — same site, same H4 hoist discipline, same failure
    modes to pin: an invalid value must be REJECTED (never dropped-then-
    'Saved.'), a valid one must reach the settings writer."""

    def test_out_of_range_rejected_not_dropped(self, settings_writer):
        for bad in (0, 8, -1):
            r = _call(week_start_dow=bad)
            body = r.body.decode()
            assert r.status_code == 400, f"week_start_dow={bad} did not 400"
            assert str(bad) in body, "the rejection must name the bad input"
            assert not re.search(r"saved", body, re.I)
        assert settings_writer.calls == []

    def test_both_boundaries_write(self, settings_writer):
        for ok_dow in (1, 7):
            settings_writer.calls.clear()
            r = _call(week_start_dow=ok_dow)
            assert re.search(r"saved", r.body.decode(), re.I)
            assert settings_writer.calls == [
                (999, {"week_start_dow": ok_dow})
            ]

    def test_rejection_happens_before_any_write(self, settings_writer,
                                                monkeypatch):
        """The hoist, exercised for THIS field: a bad dow submitted with a
        credential edit must cost nothing."""
        from api.routes_accounts import account_registry
        reg_calls = []

        async def reg_stub(*a, **kw):
            reg_calls.append(a)

        monkeypatch.setattr(account_registry, "update_account", reg_stub)
        r = _call(week_start_dow=9, api_key="k")
        assert r.status_code == 400
        assert reg_calls == []
        assert settings_writer.calls == []


# ── H4: the cross-file /saved/i contract ───────────────────────────────────

class TestTheSavedDiscriminatorContract:
    """doSave: `const ok = r.ok && /saved/i.test(r.text)`. The word "saved" in
    a failure body flips the React tone to success; its absence from the
    success body flips success to failure. Both sides pinned FROM SOURCE."""

    def _handler_src(self) -> str:
        from api.routes_accounts import update_account_detail
        return inspect.getsource(update_account_detail)

    def test_the_frontend_still_keys_on_saved(self):
        assert re.search(r"r\.ok && /saved/i\.test\(r\.text\)", _CFG), (
            "doSave no longer discriminates on /saved/i — this contract "
            "class needs re-deriving from whatever replaced it"
        )

    def test_every_failure_string_avoids_the_discriminator(self):
        """Extract every string literal returned by the handler and check the
        red-span ones against the regex the frontend actually runs."""
        tree = ast.parse(self._handler_src())
        reds, greens = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "var(--red)" in node.value:
                    reds.append(node.value)
                if "var(--green)" in node.value:
                    greens.append(node.value)
            if isinstance(node, ast.JoinedStr):
                flat = "".join(v.value for v in node.values
                               if isinstance(v, ast.Constant))
                if "var(--red)" in flat:
                    reds.append(flat)
        assert reds, "no failure spans parsed — the handler shape changed"
        for s in reds:
            assert not re.search(r"saved", s, re.I), (
                f"a FAILURE span contains the success discriminator and the "
                f"React page will paint it green: {s!r}"
            )
        assert any(re.search(r"saved", s, re.I) for s in greens), (
            "the success span dropped the discriminator — every successful "
            "save now renders as a failure"
        )

    def test_the_swallow_is_gone_from_the_handler(self):
        """No except-handler inside update_account_detail may be a bare pass
        anymore — that shape IS the bug."""
        tree = ast.parse(self._handler_src())
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                assert not (len(node.body) == 1 and isinstance(node.body[0], ast.Pass)), (
                    f"an except-pass is back in update_account_detail at "
                    f"line {node.lineno} — a swallowed failure under an "
                    f"unconditional success span is the H4 mechanism verbatim"
                )

    def test_the_write_failure_is_logged(self):
        assert "log.error" in self._handler_src(), (
            "the settings-write failure is no longer logged — the operator "
            "span says 'check engine logs', which would then show nothing"
        )


# ── M10: the toast carries the outcome ─────────────────────────────────────

class TestM10CancelTone:
    def test_flash_takes_a_tone(self):
        m = re.search(r"const flash = \(m, tone = 'ok'\) => \{(.*?)\};", _LK, re.S)
        assert m, "flash no longer takes a tone — every caller is green again"
        assert "setToast({ text: m, tone })" in m.group(1)

    def test_err_toasts_dwell_longer(self):
        """2.6 s was sized for reading 'done'; a refusal is a sentence."""
        m = re.search(r"tone === 'ok' \? 2600 : (\d+)", _LK)
        assert m and int(m.group(1)) > 2600, (
            "err toasts no longer outlive ok toasts — a refusal sentence "
            "gets the 'done' dwell time"
        )

    def test_the_toast_render_derives_from_the_tone(self):
        seg = _LK[_LK.index("{toast && ("):]
        seg = seg[:seg.index(")}")]
        assert "toast.tone === 'ok' ? 'var(--qe-green)' : 'var(--qe-red)'" in seg, (
            "the toast border/glyph colour no longer derives from the tone"
        )
        assert "toast.tone === 'ok' ? '✓' : '✗'" in seg, (
            "the glyph is fixed again — an error message under a ✓ is the "
            "exact incoherence M10 filed"
        )
        assert "'var(--qe-green)' }}>✓" not in seg, "a hardcoded green ✓ is back"

    def test_cancel_threads_res_ok_into_the_tone(self):
        i = _LK.index("/calculator/cancel/")
        seg = _LK[i:i + 700]
        assert re.search(r"res\.ok \? 'ok' : 'err'", seg), (
            "the cancel handler discards res.ok again — engine refusals "
            "flash as success"
        )
        assert "res.ok ? 'cancel sent' : 'cancel failed'" in seg

    def test_the_unreachable_catch_is_err_toned(self):
        assert "flash('cancel failed — engine unreachable?', 'err')" in _LK, (
            "the catch lane flashes without a tone — 'cancel failed' under "
            "a green ✓"
        )

    def test_the_premise_lkform_still_body_sniffs_ok(self):
        """cancel's `res.ok` is only meaningful because _lkForm derives it
        from the alert class (the door answers 200 for every outcome). If
        this derivation goes, the tone above goes blind with it."""
        assert re.search(r"ok: r\.ok && !/alert-\(error\|warning\)/\.test\(raw\)", _LK), (
            "_lkForm no longer body-sniffs the alert class into ok"
        )

    def test_the_other_posters_still_check_ok_themselves(self):
        """The class sweep found cancel to be the ONLY discard; keep the
        others honest so the inventory stays closed."""
        for site, frag in (
            ("manual_link/mark_unplanned", "setMsg({ text: r.text || (r.ok ? 'done' : 'failed'), ok: r.ok })"),
            ("close_reason", "setMsg({ text: r.ok ? 'reason saved' : (r.text || 'save failed'), ok: r.ok })"),
        ):
            assert frag in _LK, f"{site} no longer folds r.ok into its message"


# ── the class stays closed ─────────────────────────────────────────────────

class TestTheClassStaysClosed:
    def test_no_api_write_handler_swallows_then_succeeds(self):
        """The backend inventory, re-run forever: inside any api/ router
        handler, an except-pass wrapping a call whose name says it writes is
        the H4 shape regardless of which endpoint hosts it."""
        WRITE = re.compile(r"update_|insert_|delete_|upsert_|set_|write_", re.I)
        offenders = []
        for f in sorted((_ROOT / "api").glob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                calls = [n.func.attr if isinstance(n.func, ast.Attribute) else
                         getattr(n.func, "id", "")
                         for n in ast.walk(node) if isinstance(n, ast.Call)]
                writes = [c for c in calls if WRITE.match(c or "")]
                for h in node.handlers:
                    if writes and len(h.body) == 1 and isinstance(h.body[0], ast.Pass):
                        offenders.append(f"{f.name}:{h.lineno} swallows {writes}")
        # No exemptions. The first draft exempted any offender-line mentioning
        # set_calculator_symbol, "knowing" api_price's swallow contained it —
        # it does not (the swallow wraps fetch_orderbook, which the WRITE
        # regex never matched), so the filter excluded nothing today while
        # blinding the sweep to any future swallow co-located with that call
        # (audit mutation M4 proved it: a planted update_* swallow sharing a
        # try with set_calculator_symbol passed). Zero raw offenders exist;
        # if this ever fires, fix the handler, don't add a filter.
        assert not offenders, (
            "an api/ handler swallows a write and continues — if it then "
            "reports success it is H4 again:\n  " + "\n  ".join(offenders)
        )

    def test_the_bundle_carries_both_fixes(self):
        import json
        man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
        flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
        for token in ('res.ok?"ok":"err"', 'toast.tone==="ok"?"\\u2713":"\\u2717"'):
            assert token in flat, (
                f"`{token}` exists in source but not in the emitted bundle — "
                f"rebuild frontend/ (node build.mjs)"
            )
