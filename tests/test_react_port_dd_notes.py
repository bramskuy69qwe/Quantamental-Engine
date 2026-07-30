"""
React port of the two UI-orphaned endpoint families (2026-07-30).

The Jinja retirement + fragments slim-down deleted every caller of
`POST /account/{id}/dd_override` and the three `PUT /history/notes/*`
routes, leaving them live-but-unreachable — and worse, the notes routes
answered with `<span onclick="editNote(...)">` markup calling a function
that the slim-down had deleted from base.html. Both families are now
JSON-in/JSON-out with React surfaces:

  · dd_override  → Dashboard Risk Monitor "Override" button + reason dialog
                   (the surface Pre-Trade's halt banner already pointed at
                   with "override via Dashboard")
  · notes/pre_trade → History ▸ Pre-Trade Log NOTES cell (click-to-edit)

Route logic is exercised by DIRECT handler calls with the module `db` /
`log_event` patched — never a second TestClient (LOW-023 hang) and never a
write through the shared client (F5 live-data discipline: `log_event`
resolves config.DATA_DIR, so it is stubbed here).

SURFACE NOTE pinned below: `notes/trade_history` and `notes/position` have
NO React consumer because the tables they annotate lost their last reader
in the slim-down (`db.query_trade_history` / `db.get_position_notes` are
caller-less). They are pinned JSON-correct, not ported.

Run: pytest tests/test_react_port_dd_notes.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_SRC = Path(__file__).parent.parent / "frontend" / "src"


def _code(src: str) -> str:
    """Executable source only — BOTH `/* … */` and `//` comment bodies stripped.

    Source pins must never be satisfiable (or broken) by prose: these files
    carry comments that NAME the very endpoints and components being pinned, so
    a naive substring search matches the comment instead of the call site (the
    `786b610` comment-trap class). Stripping only `//` is NOT enough — these
    modules are commented predominantly with `/* */` block headers, and an
    earlier version of this helper let three pins survive deletion of the code
    they claimed to protect.

    Order matters: block comments first (they can contain `//`), then line
    comments. Crude but sufficient — neither delimiter appears inside a string
    literal in these modules, which is asserted by
    `TestCodeStripper::test_stripper_removes_both_comment_forms`.
    """
    out, i, n = [], 0, len(src)
    while i < n:
        j = src.find("/*", i)
        if j < 0:
            out.append(src[i:])
            break
        out.append(src[i:j])
        k = src.find("*/", j + 2)
        if k < 0:
            break
        # keep newlines so line-oriented reasoning still works
        out.append("\n" * src.count("\n", j, k))
        i = k + 2
    stripped = "".join(out)
    return "\n".join(
        (ln if ln.find("//") < 0 else ln[:ln.find("//")])
        for ln in stripped.splitlines()
    )


class TestCodeStripper:
    """The pins are only as good as this helper — it earned its own tests after
    a weaker version made three of them deletion-proof."""

    def test_stripper_removes_both_comment_forms(self):
        src = "/* PUT /a/b hidden */\nreal = 1;  // PUT /c/d hidden\nkeep('/e/f');"
        code = _code(src)
        assert "/a/b" not in code and "/c/d" not in code
        assert "keep('/e/f')" in code and "real = 1;" in code

    def test_real_sources_have_no_delimiters_inside_strings(self):
        """The stripper is textual, so a `//` or `/*` inside a string literal
        would silently eat real code. Pinned for the three files it runs on."""
        import re
        for name in ("dash-tiled.jsx", "pages-history.jsx", "pages-linkage.jsx"):
            src = (_SRC / name).read_text(encoding="utf-8")
            for lit in re.findall(r"'[^'\n]*'|\"[^\"\n]*\"", src):
                assert "//" not in lit, f"{name}: {lit}"
                assert "/*" not in lit, f"{name}: {lit}"

    def test_stripper_defeats_a_deleted_call(self):
        """The exact mutation that beat the previous version: the block-comment
        header names the endpoint, so deleting the real call must still fail."""
        src = (_SRC / "pages-history.jsx").read_text(encoding="utf-8")
        mutated = "\n".join(
            ln for ln in src.splitlines()
            if "_lkForm(`/history/notes/pre_trade/" not in ln
        )
        assert "/history/notes/pre_trade/" not in _code(mutated)


def _json_req(payload) -> Request:
    """A Request whose .json() resolves to *payload* (raw string allowed)."""
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": "/x", "raw_path": b"/x", "root_path": "", "scheme": "http",
        "query_string": b"", "headers": [(b"content-type", b"application/json")],
        "client": ("test", 0), "server": ("test", 80),
    }, receive)


def _req_get() -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "path": "/x", "raw_path": b"/x", "root_path": "", "scheme": "http",
        "query_string": b"", "headers": [],
        "client": ("test", 0), "server": ("test", 80),
    })


def _body(resp) -> dict:
    return json.loads(resp.body.decode("utf-8"))


# ── dd_override: the JSON contract ───────────────────────────────────────────

class TestDdOverrideJsonContract:
    """Every lane answers JSON with a real status code. Before the port these
    were HTML alert <div>s — unusable from React and unstyled by the v3
    design system."""

    @pytest.fixture(autouse=True)
    def _env(self, monkeypatch):
        import api.routes_accounts as ra
        # F5: the route's event log resolves config.DATA_DIR (LIVE). Stub it and
        # record the calls so the payload contract is pinned too.
        self.logged = []
        # raising=True on purpose: if log_event is ever renamed the patch must
        # FAIL, not silently no-op and let the real writer hit live data/.
        monkeypatch.setattr(
            "core.event_log.log_event",
            lambda *a, **k: self.logged.append((a, k)),
            raising=True,
        )
        self.state = SimpleNamespace(
            active_account_id=1,
            portfolio=SimpleNamespace(dd_state="limit", drawdown=0.091),
            account_state=SimpleNamespace(total_equity=9100.0),
            dd_manually_unblocked=set(),
        )
        monkeypatch.setattr(ra, "app_state", self.state)
        self.ra = ra

    @pytest.mark.asyncio
    async def test_non_active_account_is_refused(self):
        """THE audit's HIGH: every gate reads app_state.portfolio (ACTIVE-account
        state) while the write and the event log take the PATH id. A mismatch
        validated one account's drawdown, unblocked ANOTHER (persisting an
        un-approved future bypass) and logged the wrong account's drawdown —
        all behind a 200. The route must refuse instead."""
        resp = await self.ra.dd_override(
            7, _json_req({"reason": "override the wrong account"}))
        assert resp.status_code == 409
        assert "active account" in _body(resp)["error"]
        assert self.state.dd_manually_unblocked == set(), "no foreign id written"
        assert self.logged == [], "no event logged against the wrong account"

    @pytest.mark.asyncio
    async def test_exactly_min_length_reason_is_accepted(self):
        """The accept side of the >=10 boundary (the reject side is below)."""
        resp = await self.ra.dd_override(1, _json_req({"reason": "x" * 10}))
        assert resp.status_code == 200
        assert 1 in self.state.dd_manually_unblocked

    @pytest.mark.asyncio
    async def test_happy_path_returns_ok_and_sets_override(self):
        resp = await self.ra.dd_override(
            1, _json_req({"reason": "Strategy intact, one bad news day"}))
        assert resp.status_code == 200
        assert _body(resp)["status"] == "ok"
        assert 1 in self.state.dd_manually_unblocked

    @pytest.mark.asyncio
    async def test_short_reason_is_400_json_and_writes_nothing(self):
        resp = await self.ra.dd_override(1, _json_req({"reason": "too short"}))
        assert resp.status_code == 400
        assert "10 characters" in _body(resp)["error"]
        assert self.state.dd_manually_unblocked == set()

    @pytest.mark.asyncio
    async def test_whitespace_reason_is_400(self):
        """The length check runs on the STRIPPED reason."""
        resp = await self.ra.dd_override(1, _json_req({"reason": " " * 20}))
        assert resp.status_code == 400
        assert self.state.dd_manually_unblocked == set()

    @pytest.mark.asyncio
    async def test_not_in_limit_is_400(self):
        self.state.portfolio.dd_state = "ok"
        resp = await self.ra.dd_override(
            1, _json_req({"reason": "no limit breached right now"}))
        assert resp.status_code == 400
        assert "not in limit state" in _body(resp)["error"]
        assert self.state.dd_manually_unblocked == set()

    @pytest.mark.asyncio
    async def test_already_active_is_409_with_an_error(self):
        """409, not 200: the client treats any 2xx as success, so a 200 closed
        the dialog on a no-op and silently dropped the typed reason."""
        self.state.dd_manually_unblocked.add(1)
        resp = await self.ra.dd_override(
            1, _json_req({"reason": "second override attempt here"}))
        assert resp.status_code == 409
        body = _body(resp)
        assert body["status"] == "already_active"
        assert "already active" in body["error"].lower()

    @pytest.mark.asyncio
    async def test_malformed_body_degrades_to_400_not_500(self):
        """Non-dict + unparseable bodies fall through the reason guard."""
        for payload in (b"{not json", json.dumps([1, 2]).encode(),
                        json.dumps("a string").encode()):
            resp = await self.ra.dd_override(1, _json_req(payload))
            assert resp.status_code == 400, payload
        assert self.state.dd_manually_unblocked == set()

    @pytest.mark.asyncio
    async def test_event_log_payload_carries_reason_and_drawdown(self):
        await self.ra.dd_override(
            1, _json_req({"reason": "Strategy intact, one bad news day"}))
        assert len(self.logged) == 1
        args, kwargs = self.logged[0]
        assert args[0] == 1 and args[1] == "manual_override"
        assert args[2]["reason"] == "Strategy intact, one bad news day"
        assert args[2]["drawdown"] == pytest.approx(0.091)
        assert kwargs.get("source") == "api_override"

    @pytest.mark.asyncio
    async def test_no_html_alert_markup_in_any_lane(self):
        """Anti-regression: every pre-port response was an alert <div>. All five
        lanes, and each must be JSON-parseable."""
        lanes = [
            await self.ra.dd_override(7, _json_req({"reason": "wrong account here"})),
            await self.ra.dd_override(1, _json_req({"reason": "x"})),
            await self.ra.dd_override(1, _json_req({"reason": "a valid override reason"})),
            await self.ra.dd_override(1, _json_req({"reason": "a second attempt now"})),
        ]
        self.state.portfolio.dd_state = "ok"
        lanes.append(
            await self.ra.dd_override(1, _json_req({"reason": "not at limit now"})))
        for resp in lanes:
            raw = resp.body.decode("utf-8")
            assert "<div" not in raw and "alert-" not in raw
            json.loads(raw)   # every lane is valid JSON


# ── notes: the JSON contract ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def ndb(monkeypatch):
    """Temp DatabaseManager wired as routes_history's module `db`, with the
    active account pinned to 1 (the notes writer is account-scoped)."""
    from core.database import DatabaseManager
    import api.routes_history as rh
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (2, 'Other')")
    await d._conn.commit()
    monkeypatch.setattr(rh, "db", d)
    monkeypatch.setattr(rh, "app_state", SimpleNamespace(active_account_id=1))
    yield d
    await d.close()
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp.name + ext)
        except OSError:
            pass


class TestNotesJsonContract:
    @pytest.mark.asyncio
    async def test_pre_trade_note_persists_and_returns_json(self, ndb):
        import api.routes_history as rh
        cur = await ndb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, notes) "
            "VALUES (1, '2026-07-30T10:00:00', 'BTCUSDT', 'long', '')")
        await ndb._conn.commit()
        row_id = cur.lastrowid

        resp = await rh.update_pre_trade_note(row_id, notes="sized down, thin book")
        assert resp.status_code == 200
        body = _body(resp)
        assert body == {"status": "ok", "row_id": row_id,
                        "notes": "sized down, thin book"}

        async with ndb._conn.execute(
            "SELECT notes FROM pre_trade_log WHERE id=?", (row_id,)) as c:
            assert (await c.fetchone())["notes"] == "sized down, thin book"

    @pytest.mark.asyncio
    async def test_pre_trade_note_clears_to_empty(self, ndb):
        """Blank submit is a DELETE-by-emptying, not a no-op."""
        import api.routes_history as rh
        cur = await ndb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, notes) "
            "VALUES (1, '2026-07-30T10:00:00', 'ETHUSDT', 'short', 'old text')")
        await ndb._conn.commit()
        row_id = cur.lastrowid
        await rh.update_pre_trade_note(row_id, notes="")
        async with ndb._conn.execute(
            "SELECT notes FROM pre_trade_log WHERE id=?", (row_id,)) as c:
            assert (await c.fetchone())["notes"] == ""

    @pytest.mark.asyncio
    async def test_unknown_row_is_404_not_a_false_success(self, ndb):
        """An unscoped UPDATE by bare id matched nothing yet reported success, so
        the cell closed on a write that never landed and the text then reverted
        with no error (2026-07-30 audit)."""
        import api.routes_history as rh
        resp = await rh.update_pre_trade_note(999999, notes="into the void")
        assert resp.status_code == 404
        assert "not found" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_write_is_account_scoped(self, ndb):
        """A row belonging to another account must not be writable by id."""
        import api.routes_history as rh
        cur = await ndb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, notes) "
            "VALUES (2, '2026-07-30T10:00:00', 'BTCUSDT', 'long', 'theirs')")
        await ndb._conn.commit()
        foreign = cur.lastrowid
        resp = await rh.update_pre_trade_note(foreign, notes="mine now")
        assert resp.status_code == 404
        async with ndb._conn.execute(
            "SELECT notes FROM pre_trade_log WHERE id=?", (foreign,)) as c:
            assert (await c.fetchone())["notes"] == "theirs"

    @pytest.mark.asyncio
    async def test_pre_trade_door_carries_id_and_notes(self, ndb):
        """The whole cell rests on these two fields reaching the client —
        `row.id` builds the PUT url and `row.notes` is the displayed text. The
        door is `SELECT *` today; an explicit projection would break it and
        every save would PUT to /…/undefined."""
        import api.routes_history as rh
        await ndb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, notes) "
            "VALUES (1, '2026-07-30T10:00:00', 'BTCUSDT', 'long', 'hello')")
        await ndb._conn.commit()
        resp = await rh.frag_history_pre_trade(_req_get(), format="json")
        rows = json.loads(resp.body.decode("utf-8"))["rows"]
        assert rows and "id" in rows[0] and "notes" in rows[0]
        assert rows[0]["notes"] == "hello"

    @pytest.mark.asyncio
    async def test_position_and_trade_history_notes_answer_json(self, ndb):
        """Kept JSON-correct even though no React table reads them back."""
        import api.routes_history as rh
        r1 = await rh.update_position_note(trade_key="BTCUSDT|1", notes="scaled in")
        assert _body(r1) == {"status": "ok", "trade_key": "BTCUSDT|1",
                             "notes": "scaled in"}
        r2 = await rh.update_trade_history_note(7, notes="legacy row")
        assert _body(r2) == {"status": "ok", "row_id": 7, "notes": "legacy row"}

    @pytest.mark.asyncio
    async def test_no_editnote_markup_in_any_notes_response(self, ndb):
        """THE port's load-bearing anti-regression: these responses used to
        emit onclick="editNote(...)" — a call into a function the fragments
        slim-down deleted from base.html."""
        import api.routes_history as rh
        cur = await ndb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side) "
            "VALUES (1, '2026-07-30T10:00:00', 'SOLUSDT', 'long')")
        await ndb._conn.commit()
        for resp in (
            await rh.update_pre_trade_note(cur.lastrowid, notes="a"),
            await rh.update_trade_history_note(1, notes="b"),
            await rh.update_position_note(trade_key="k", notes="c"),
        ):
            raw = resp.body.decode("utf-8")
            assert "editNote" not in raw
            assert "<span" not in raw

    @pytest.mark.asyncio
    async def test_note_text_containing_alert_class_still_reads_as_success(self, ndb):
        """The echo + the client's jsonOk mode: a note whose TEXT contains
        'alert-error' must not be mistaken for a failed save (the body-sniffing
        `_lkForm` default would have)."""
        import api.routes_history as rh
        cur = await ndb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side) "
            "VALUES (1, '2026-07-30T10:00:00', 'XRPUSDT', 'long')")
        await ndb._conn.commit()
        resp = await rh.update_pre_trade_note(
            cur.lastrowid, notes="saw an alert-error in the log")
        assert resp.status_code == 200
        assert _body(resp)["notes"] == "saw an alert-error in the log"


# ── React wiring (source pins) ───────────────────────────────────────────────

class TestDashboardOverrideWiring:
    def _src(self) -> str:
        return (_SRC / "dash-tiled.jsx").read_text(encoding="utf-8")

    def test_dialog_posts_the_override_endpoint(self):
        code = _code(self._src())
        assert "DdOverrideDialog" in code
        assert "/dd_override" in code

    def test_min_reason_matches_the_engine_rule(self):
        """Both SIDES asserted, not just the client constant: a server-side
        retune would otherwise drift silently and send every reason into a
        guaranteed 400."""
        import re
        client = re.search(r"DD_OVERRIDE_MIN_REASON = (\d+)", _code(self._src()))
        assert client, "client min-reason constant missing"
        route = Path("api/routes_accounts.py").read_text(encoding="utf-8")
        body = route[route.index("async def dd_override"):]
        server = re.search(r"len\(reason\) < (\d+)", body)
        assert server, "server min-reason guard missing"
        assert client.group(1) == server.group(1), (
            f"client requires {client.group(1)} chars, engine requires "
            f"{server.group(1)} — the client would submit rejectable reasons"
        )

    def test_trigger_is_gated_on_limit_enforced_and_not_overridden(self):
        """Structure, not substrings: `ddState === 'limit'` alone predates this
        change (the HALTED badge uses it), so a substring pin would survive
        deleting the whole control."""
        code = _code(self._src())
        assert "const canOverride = ddState === 'limit' && enforced" in code
        # the ternary must put the BADGE on overridden and the BUTTON on
        # canOverride — an inverted ternary is a real regression shape
        seg = code[code.index("{ddOverridden"):]
        seg = seg[:seg.index("</div>")]
        assert seg.index("OVERRIDDEN") < seg.index("canOverride")
        assert "setUi({ ddOverride: true })" in seg

    def test_dialog_is_hosted_at_page_level_not_inside_the_tile(self):
        """ModelDialog is position:absolute and Pane is position:relative, so
        a dialog rendered inside RiskMonitorPane would be CLIPPED to that
        tile. The host must be a sibling of TiledGrid."""
        code = _code(self._src())
        assert "DdOverrideHost" in code
        grid = code.index("<TiledGrid />")
        host = code.index("<DdOverrideHost />")
        assert host > grid, "the dialog host must sit outside the grid"
        pane_start = code.index("const RiskMonitorPane")
        pane_end = code.index("const DdOverrideHost")
        assert "<DdOverrideDialog" not in code[pane_start:pane_end]

    def test_page_root_anchors_the_overlay(self):
        """The overlay's containing block must be the page root, not whichever
        positioned ancestor happens to exist above it."""
        code = _code(self._src())
        root = code.index('data-screen-label="01 Dashboard"')
        assert "position: 'relative'" in code[root:root + 500]

    def test_state_refreshes_after_a_successful_override(self):
        """Both halves of the wiring — the store must EXPOSE refreshState and
        the dialog must CALL it (a comment mentioning it is not wiring)."""
        code = _code(self._src())
        assert "refreshState: loadState" in code
        assert "onDone={() => QE_DASH.refreshState()}" in code

    def test_account_id_comes_from_live_state_not_the_boot_snapshot(self):
        """THE highest-severity trap of this port: QE_BOOTSTRAP.activeAccountId
        is baked at page load and goes stale when an account is activated from
        the Config page (which refetches without reloading), so a write keyed to
        it targets the WRONG account behind a 200. And no `|| 1` fallback —
        account 1 is the one that exists live."""
        code = _code(self._src())
        host = code.index("const DdOverrideHost")
        seg = code[host:host + 900]
        assert "accountId={d.st.account_id}" in seg
        assert "QE_BOOTSTRAP" not in seg, "the boot snapshot can be stale"
        assert "d.st.account_id == null) return null" in seg

    def test_dialog_flag_is_reset_on_dashboard_unmount(self):
        """`ui` is module-level; a dialog left open would re-raise itself on the
        next visit to the Dashboard."""
        code = _code(self._src())
        stop = code.index("function stop()")
        assert "ui = { ddOverride: false }" in code[stop:stop + 400]


class TestHistoryNoteCellWiring:
    def _src(self) -> str:
        return (_SRC / "pages-history.jsx").read_text(encoding="utf-8")

    def test_note_cell_puts_the_pre_trade_notes_endpoint(self):
        code = _code(self._src())
        assert "HNoteCell" in code
        assert "/history/notes/pre_trade/" in code

    def test_notes_column_is_wired_into_the_pretrade_tab(self):
        src = self._src()
        pre = src.index("pretrade: [")
        tail = src.index("};", pre)
        assert "HNoteCell" in src[pre:tail]

    def test_note_save_uses_json_ok_not_body_sniffing(self):
        code = _code(self._src())
        idx = code.index("_lkForm(`/history/notes/pre_trade/")
        assert "jsonOk" in code[idx:idx + 200]

    def test_commit_guard_is_a_ref_and_is_consulted(self):
        """Enter can fire blur in the same tick; a state flag would not have
        flipped yet and commit would run twice. Pin the declaration AND the
        early return — the declaration alone is a spelling test."""
        code = _code(self._src())
        assert "const guard = React.useRef(false)" in code
        commit = code.index("const commit = async ()")
        seg = code[commit:commit + 400]
        assert "if (guard.current) return;" in seg
        assert "guard.current = true;" in seg

    def test_untouched_cell_never_writes(self):
        """Opening a cell and clicking away must not PUT the open-time snapshot
        — that silently clobbers a concurrent update with stale text."""
        code = _code(self._src())
        assert "openedWith" in code
        commit = code.index("const commit = async ()")
        seg = code[commit:commit + 700]
        assert "openedWith.current" in seg

    def test_failed_save_stays_in_edit_mode_with_a_visible_error(self):
        """A silent failure loses the operator's text: on error the cell must
        keep the input (text intact) AND show something."""
        code = _code(self._src())
        commit = code.index("const commit = async ()")
        seg = code[commit:code.index("if (editing)")]
        assert "setPhase('err')" in seg
        assert "done()" not in seg.split("setPhase('err')")[-1], (
            "the error path must NOT close the editor"
        )
        editing = code.index("if (editing)")
        body = code[editing:editing + 1600]
        assert "save failed" in body, "no visible error surface in edit mode"

    def test_no_change_return_clears_the_error_phase(self):
        """Otherwise a healthy row keeps rendering a stale failure badge."""
        code = _code(self._src())
        commit = code.index("const commit = async ()")
        seg = code[commit:commit + 700]
        idx = seg.index("=== stored")
        assert "setPhase(null)" in seg[idx:idx + 120]

    def test_successful_save_paints_optimistically(self):
        """Otherwise the cell shows the OLD text for the whole reload round trip
        — and forever if the reload fails (load keeps last-good)."""
        code = _code(self._src())
        assert "setSaved(next)" in code
        assert "saved != null ? saved : stored" in code

    def test_autorefresh_pauses_while_a_note_is_open(self):
        """This table is server-paged and newest-first: a refresh mid-edit can
        drop the edited row off the page and unmount the input."""
        code = _code(self._src())
        assert "HNOTE_EDITING" in code
        idx = code.index("setInterval(")
        assert "HNOTE_EDITING.size === 0" in code[idx:idx + 200]


class TestLkFormJsonOkMode:
    def test_json_ok_skips_the_alert_regex(self):
        code = _code((_SRC / "pages-linkage.jsx").read_text(encoding="utf-8"))
        assert "opts.jsonOk" in code
        idx = code.index("if (opts.jsonOk)")
        # the jsonOk branch only — up to the closing brace of that block
        seg = code[idx:code.index("\n  }", idx)]
        assert "r.ok" in seg
        assert "alert-" not in seg, "jsonOk must not body-sniff"

    def test_close_reason_callers_opt_into_json_ok(self):
        """close_reason echoes `close_note`, so it has the same
        operator-text-in-the-body hazard as notes."""
        for name in ("pages-history.jsx", "pages-linkage.jsx"):
            code = _code((_SRC / name).read_text(encoding="utf-8"))
            idx = code.index("_lkForm(`/history/close_reason/")
            assert "jsonOk" in code[idx:idx + 200], name

    def test_alert_sniffing_sites_have_NOT_opted_in(self):
        """The inverse guard, and the more dangerous direction: manual_link /
        mark_unplanned / calculator-cancel answer 200 for EVERY outcome with an
        `alert-*` body. Putting them on jsonOk would report every failure as a
        success — a silent operator lie with a green suite."""
        code = _code((_SRC / "pages-linkage.jsx").read_text(encoding="utf-8"))
        for ep in ("/manual_link", "/mark_unplanned", "/calculator/cancel/"):
            idx = code.index(ep)
            seg = code[idx:idx + 160]
            assert "jsonOk" not in seg, (
                f"{ep} answers 200-for-every-outcome; it MUST keep body-sniffing"
            )

    def test_default_path_still_sniffs(self):
        code = _code((_SRC / "pages-linkage.jsx").read_text(encoding="utf-8"))
        tail = code[code.index("if (opts.jsonOk)"):]
        assert "alert-(error|warning)" in tail, (
            "the default (non-jsonOk) path must still treat an alert-* body as "
            "failure"
        )
