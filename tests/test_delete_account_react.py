"""H5 — Delete Account wired in React (the last disabled-in-P2 button).

THE DEFECT (wiring inventory 2026-07-30, fixed 2026-08-03): the React Config
page shipped `Delete Account` hard-`disabled` with
`title="Not wired in P2 — delete via the current /config page"` — and the
Jinja retirement then removed that page, leaving account deletion with NO
surface at all while `DELETE /accounts/{account_id}` worked the whole time.
Identical shape to the Add Account bug fixed 2026-07-30; the dialog pattern
ports from `CfgAddAccountDialog`.

Two truthfulness details carried over from the H4/M10 (false-success) work,
because delete is a WRITE and the same rules bind:

  · success is `r.ok && data.status === 'ok'` — never assumed. The
    active-account refusal arrives as a 409 with a PLAIN-TEXT body, which the
    old Jinja flow discarded outright (`hx-swap="none"`): even its refusal
    was invisible. The dialog keeps a refusal on screen instead.
  · the copy states the door's REAL blast radius: the account row (
    registration + stored credentials) — historical trade data on disk is
    NOT deleted, and claiming more would train the operator to fear a
    destructive sweep the endpoint does not perform.

Backend is DELIBERATELY untouched (H5 is a UI-only gap): the 409
active-account guard and the row-only delete are pinned here as PREMISES, so
if either changes, the dialog's claims fail loudly rather than rotting.

Run: pytest tests/test_delete_account_react.py -v
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent
_CFG = _code((_ROOT / "frontend" / "src" / "pages-config.jsx").read_text(encoding="utf-8"))


def _slice(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i)]


_DIALOG = _slice(_CFG, "const CfgDeleteAccountDialog", "const CfgAddAccountDialog")
_FORM = _slice(_CFG, "const CfgAccountForm", "const CfgDeleteAccountDialog")


# ── the button ──────────────────────────────────────────────────────────────

class TestTheButtonIsWired:
    def test_it_is_no_longer_hard_disabled(self):
        assert "Not wired in P2" not in _CFG, (
            "the placeholder title is back — the button points the operator "
            "at a Jinja page that no longer exists"
        )

    def test_it_raises_the_confirm_with_the_account(self):
        assert "onClick={() => onDelete(account)}" in _FORM, (
            "the Delete button no longer raises the confirm dialog"
        )

    def test_it_mirrors_the_backend_active_guard(self):
        """The backend 409s on the active account; the button disables for the
        same condition WITH the reason, instead of offering a click that can
        only be refused."""
        m = re.search(
            r"onClick=\{\(\) => onDelete\(account\)\}\s*"
            r"disabled=\{!!busy \|\| !!account\.is_active\}", _FORM)
        assert m, "the active-account disable (mirroring the 409 guard) is gone"
        assert "activate another account first" in _FORM

    def test_the_form_accepts_the_callback(self):
        assert re.search(
            r"const CfgAccountForm = \(\{ account, detail, onReload, onDelete \}\)",
            _FORM)


# ── the dialog ──────────────────────────────────────────────────────────────

class TestTheConfirmDialog:
    def test_it_calls_the_real_door_with_DELETE(self):
        assert re.search(
            r"_cfgPostForm\(`/accounts/\$\{account\.id\}`, \{\}, 'DELETE', \{ json: true \}\)",
            _DIALOG), "the dialog no longer calls DELETE /accounts/{id}"

    def test_success_is_checked_not_assumed(self):
        """The false-success rule (H4/M10): the branch must require both the
        HTTP ok AND the door's own status field."""
        assert "deleted = !!(r.ok && r.data && r.data.status === 'ok')" in _DIALOG, (
            "delete success is no longer verified — a refusal or error body "
            "would tear the dialog down as if the delete landed"
        )

    def test_a_post_delete_failure_cannot_report_as_a_delete_failure(self):
        """`await onDeleted()` must run OUTSIDE the try (audit): inside it, a
        throw from the post-delete reload told the operator the delete FAILED
        over a delete that landed — the H4/M10 inversion, from inside its own
        fix. Latent today (loadAccounts swallows its own errors), which is
        exactly why it needs a pin rather than a repro."""
        assert "if (deleted) { await onDeleted(); return; }" in _DIALOG
        i = _DIALOG.index("} catch (e) { setErr('delete failed")
        assert _DIALOG.index("if (deleted) { await onDeleted()") > i, (
            "onDeleted moved back inside the try"
        )

    def test_doDelete_is_reentrancy_guarded(self):
        """The sibling Add dialog opens its submit with a busy guard; this one
        relied on `disabled=` alone (audit) — a programmatic or key-repeat
        double-fire could double-POST. Idempotent SQL makes it low-stakes;
        the guard makes it zero."""
        assert "if (busy) return;" in _DIALOG

    def test_a_refusal_stays_on_screen(self):
        """The 409 body ('Cannot delete the active account…') must land in the
        dialog's err line, not vanish — the old Jinja flow discarded it."""
        assert "setErr(r.text || 'delete failed')" in _DIALOG
        assert re.search(r"\{err && \(", _DIALOG), "no err rendering in the dialog"
        assert "✗" in _DIALOG

    def test_the_unreachable_catch_is_distinct(self):
        assert "setErr('delete failed — engine unreachable?')" in _DIALOG

    def test_the_copy_states_the_real_blast_radius(self):
        """Claiming more (or less) than the door does trains the operator
        wrong on a destructive control. Whitespace-normalised: the JSX copy
        line-wraps mid-phrase, and a raw substring match went blind to it."""
        flat = re.sub(r"\s+", " ", _DIALOG)
        assert "stored API credentials" in flat
        assert "saved risk-parameter set" in flat, (
            "the copy dropped the params cascade — it under-claims again"
        )
        assert "NOT deleted" in flat
        assert "cannot be undone" in flat

    def test_the_dialog_cannot_be_dismissed_mid_flight(self):
        assert "onClose={() => { if (!busy) onClose(); }}" in _DIALOG, (
            "scrim-click during the DELETE closes the dialog and orphans the "
            "outcome — the operator never learns whether it landed"
        )

    def test_both_footer_buttons_disable_while_busy(self):
        """Scoped to the footer prop (audit: an equality count over the whole
        dialog slice fails spuriously on any third busy-disabled element and
        never proves the hits are the FOOTER's)."""
        # end at the Fragment close, not the first `}>` — that one lives
        # inside `onClick={onClose}>` and truncated the slice to one button
        footer = _slice(_DIALOG, "footer={", "</React.Fragment>}")
        assert footer.count("disabled={busy}") == 2, footer


# ── the mount + the aftermath ───────────────────────────────────────────────

class TestMountAndAftermath:
    def test_the_dialog_mounts_outside_the_grid(self):
        """Same clipping trap as the Add/DD-override dialogs: ModelDialog is
        position:absolute, Pane is position:relative — inside a tile it clips.
        Asserts the mount sits AFTER </GridWorkspace>. NB (audit): that proves
        'not inside the grid', not 'unclipped' — a Pane wrapper OUTSIDE the
        grid would still clip and still pass here. The realistic regression
        (moving the mount back into a tile) is what this bites."""
        pane = _slice(_CFG, "const CfgAccountsTab", "const CfgConnectionsTab")
        assert pane.index("</GridWorkspace>") < pane.index("<CfgDeleteAccountDialog"), (
            "the delete dialog is mounted inside the grid and will clip to "
            "its tile"
        )

    def test_deletion_reloads_the_accounts_list(self):
        """loadAccounts(true) is THE funnel: it refreshes the pane list, syncs
        QE_CHROME (nav picker + EXCH cell app-wide), and its setAcct updater
        migrates a vanished selection to active-or-first — which is exactly
        the deleted-account case. Anything less leaves the app naming an
        account that no longer exists."""
        pane = _slice(_CFG, "const CfgAccountsTab", "const CfgConnectionsTab")
        m = re.search(
            r"onDeleted=\{async \(\) => \{ setDeleting\(null\); await loadAccounts\(true\); \}\}",
            pane)
        assert m, "onDeleted no longer routes through loadAccounts(true)"

    def test_the_selection_migration_premise_holds(self):
        """The test above leans on loadAccounts' updater dropping dead ids —
        pin the premise so a refactor of that updater fails HERE with the
        delete-flow consequence named, not just in whatever file owns it."""
        assert "rows.some((a) => a.id === cur)" in _CFG, (
            "loadAccounts no longer checks the current selection against the "
            "fresh rows — after a delete, the dead account stays selected and "
            "the detail pane fetches a 404 forever"
        )


# ── backend premises (deliberately untouched — pinned so drift is loud) ─────

class TestBackendPremises:
    def _src(self) -> str:
        from api.routes_accounts import delete_account
        return inspect.getsource(delete_account)

    def test_the_active_account_guard_still_409s(self):
        src = self._src()
        assert "account_id == app_state.active_account_id" in src
        assert "status_code=409" in src, (
            "the active-account guard changed shape — the dialog's disable "
            "title and refusal handling were written against a 409"
        )

    def test_success_still_answers_status_ok(self):
        """Asserted on the handler's FINAL statement, not a substring — a
        substring survives an early `return {"deleted": True}` that leaves the
        old literal in dead code below it (this pin's first draft did exactly
        that, caught by its own mutation check)."""
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(self._src()))
        fn = tree.body[0]
        last = fn.body[-1]
        assert isinstance(last, ast.Return), "the handler no longer ends in a return"
        src_last = ast.unparse(last)
        assert "'status': 'ok'" in src_last or '"status": "ok"' in src_last, (
            f"the success return changed to `{src_last}` — the dialog's "
            f"success check (data.status === 'ok') is now never true and "
            f"every delete reports failure while having deleted"
        )
        # and no OTHER return in the success path answers first: every earlier
        # return must be inside the guard (a Return under an If), never bare
        for node in fn.body[:-1]:
            assert not isinstance(node, ast.Return), (
                "an unconditional return precedes the status-ok one — the "
                "final return is dead code and this pin is checking a corpse"
            )

    def test_the_deletes_blast_radius_matches_the_copy(self):
        """The dialog promises: registration + credentials + risk-parameter
        set go; historical trade data survives. DERIVED from the schema, not
        grepped from a wrapper — the first draft of this pin read the
        7-line registry wrapper for strings like `rmtree` that could never
        appear there, and its 'row-only' premise was ALREADY false: the audit
        found `account_params` rides `ON DELETE CASCADE` off accounts(id)
        with `foreign_keys=ON` on the very connection the delete runs on
        (verified live in risk_engine.db). So: compute the actual cascade
        set and hold BOTH sides of the copy against it."""
        import re as _re
        schema = (_ROOT / "core" / "database.py").read_text(encoding="utf-8")
        cascade = set()
        for m in _re.finditer(
                r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", schema, _re.S):
            name, body = m.groups()
            if _re.search(r"REFERENCES accounts\s*\(id\)\s*ON DELETE CASCADE", body):
                cascade.add(name)
        assert cascade == {"account_params"}, (
            f"the accounts cascade set changed to {sorted(cascade)} — the "
            f"dialog copy's blast-radius claim must change in the same commit"
        )
        # the copy's survival claim: no trade-data table may join the cascade
        for t in ("exchange_history", "closed_positions", "fills", "orders",
                  "trade_history", "pre_trade_log"):
            assert t not in cascade, (
                f"{t} now cascades off accounts — 'Historical trade data on "
                f"disk is NOT deleted' is a lie on a destructive control"
            )
        # and the SQL layer (the real delete, not the wrapper) is one
        # accounts-row DELETE — anything more must update the copy
        from core.db_settings import SettingsMixin
        sql_src = inspect.getsource(SettingsMixin.delete_account)
        deletes = _re.findall(r"DELETE FROM (\w+)", sql_src)
        assert deletes == ["accounts"], (
            f"db.delete_account now issues DELETEs against {deletes} — "
            f"re-derive the dialog copy"
        )
        # the pragma premise: the cascade only fires because FKs are ON
        assert 'PRAGMA foreign_keys=ON' in schema

    def test_the_dialog_copy_names_the_cascade(self):
        """The frontend half of the same contract: the copy must claim the
        params deletion (it cascades) and the data survival (nothing else
        references accounts). Two files, one truth."""
        assert "risk-parameter set" in _DIALOG
        assert "NOT deleted" in _DIALOG


# ── it reaches the shipped bundle ──────────────────────────────────────────

def test_the_fix_reaches_the_emitted_bundle():
    man = json.loads((_ROOT / "static" / "v3" / "manifest.json").read_text(encoding="utf-8"))
    flat = re.sub(r"\s+", "", (_ROOT / "static" / "v3" / man["app"]).read_text(encoding="utf-8"))
    for token in (
        "CfgDeleteAccountDialog",
        'r.ok&&r.data&&r.data.status==="ok"',
        '"DELETE",{json:true}',
    ):
        assert token in flat, (
            f"`{token}` exists in source but not in the emitted bundle — "
            f"rebuild frontend/ (node build.mjs)"
        )
    assert "NotwiredinP2" not in flat.replace(" ", ""), (
        "the emitted bundle still carries the disabled-button placeholder"
    )
