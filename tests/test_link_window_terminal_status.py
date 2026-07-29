"""E2E-P5-002 regression pins â€” the countdown chip lied about cancelled calcs.

Found by the Phase-5 live-mutation sweep: after cancelling a calc through the
Linkage dialog (server answered "Calc cancelled.", Active Calcs emptied), the
status door still reported:

    {"status":"LINKABLE","remaining_s":21498,...}

Mechanism: `GET /calculator/link-window-status/{calc_id}` special-cased only
`matched`/`linked` â†’ LINKED; EVERY other status fell through to the bare
time-window countdown. But the matcher's candidate set is
`status IN ('active','released')` (core/calc_correlation.py:389), so a
cancelled / superseded / expired / completed calc can NEVER link. The chip
asserted `âœ“ LINKABLE` for a dead plan â€” and contradicted the cancel dialog's
own copy ("A fill after this lands UNPLANNED unless a fresh calc is run").

Fix: terminal non-linkable statuses return EXPIRED â€” the existing terminal chip
bucket, whose copy is the correct instruction ("recalculate to link new fills")
and which stops the 5 s poller (pages-pretrade.jsx:386-388).
"""
import pytest

import api.routes_calculator as rc


TERMINAL_NON_LINKABLE = [
    "cancelled_by_operator",
    "superseded",
    "expired",
    "completed_via_position",
]


class TestTerminalStatusMapping:
    @pytest.mark.parametrize("status", TERMINAL_NON_LINKABLE)
    def test_terminal_statuses_are_handled(self, status):
        src = rc.calculator_link_window_status.__doc__ or ""
        route_src = __import__("inspect").getsource(rc.calculator_link_window_status)
        assert status in route_src, (
            f"{status!r} must map to a terminal chip state â€” falling through to the "
            "countdown reports LINKABLE for a calc the matcher will never consider"
        )

    def test_terminal_statuses_map_to_expired_not_linkable(self):
        route_src = __import__("inspect").getsource(rc.calculator_link_window_status)
        idx = route_src.find("cancelled_by_operator")
        assert idx > 0
        tail = route_src[idx: idx + 400]
        assert '"EXPIRED"' in tail, "terminal statuses must return EXPIRED (stops the poller)"

    def test_matched_and_linked_still_map_to_LINKED(self):
        route_src = __import__("inspect").getsource(rc.calculator_link_window_status)
        assert '("matched", "linked")' in route_src
        assert '"LINKED"' in route_src

    def test_status_is_fetched_once(self):
        """The fix must not add a second get_calc_status round-trip per poll."""
        route_src = __import__("inspect").getsource(rc.calculator_link_window_status)
        assert route_src.count("get_calc_status(") == 1, (
            "poller runs at 1-5 s; keep it to one status read"
        )

    def test_matcher_candidate_statuses_are_the_contract(self):
        """Pins WHY the mapping is what it is: only these two can ever link."""
        import core.calc_correlation as cc
        import inspect

        src = inspect.getsource(cc.find_candidate_calcs)
        assert "'active','released'" in src.replace(" ", "") or \
               '"active","released"' in src.replace(" ", ""), \
            "matcher candidate set changed â€” revisit the terminal-status mapping"

