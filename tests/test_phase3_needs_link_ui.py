"""
Phase 3 Task 3 (P3.T3) tests — needs-link tab UI wiring.

Per CLAUDE.md "Template wiring tests": source-string grep is insufficient
(Python-in-Jinja errors slip through), so this COMPILE-AND-RENDERS the
templates via jinja2.Environment(FileSystemLoader("templates")) with a
minimal synthetic context and asserts the rendered HTML structure +
htmx wiring. Models tests/test_task122_card_primitive.py (_make_env) and
tests/test_task108_hotfix (TestAccountDetailTemplateCompiles).

Intent (Rule 8): the queue fragment must render the per-criterion diff
(green match / red miss), the choke-pointed P3.T2 action buttons
(/orders/{id}/manual_link + /mark_unplanned) targeting the per-order alert
div, and an EmptyState (not an error) when the queue is empty; the page +
fragment routes must be registered; the nav + page_meta must carry the tab.

Run: pytest tests/test_phase3_needs_link_ui.py -v
"""
from __future__ import annotations

import os
import sys

import jinja2
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    # Filters/globals the needs-link templates reference (registered on the
    # real app's templates.env in api/helpers.py).
    env.globals["fmt"] = lambda v, n=2: (
        f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    )
    env.globals["project_name"] = "TestEngine"
    return env


def _cand(calc_id="C-ABCDEF123456", entry_match=True, tp_match=True, sl_match=True):
    return {
        "calc_id": calc_id, "ticker": "BTCUSDT", "side": "long",
        "effective_entry": 50000.0, "entry_drift_pct": 0.001, "entry_match": entry_match,
        "tp_price": 55000.0, "tp_drift_pct": 0.002, "tp_match": tp_match,
        "sl_price": 48000.0, "sl_drift_pct": 0.003, "sl_match": sl_match,
        "timestamp": "2026-05-29T00:00:00+00:00", "age_hours": 1.5,
    }


def _order(oid=1, link_status="NEEDS_MANUAL_REVIEW", candidates=None):
    return {
        "id": oid, "exchange_order_id": "O%d" % oid, "symbol": "BTCUSDT",
        "side": "long", "order_type": "limit", "price": 50000.0,
        "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        "created_at_ms": 1700000000000, "link_status": link_status,
        "candidates": [_cand()] if candidates is None else candidates,
    }


def _render_queue(orders):
    return _make_env().get_template("fragments/needs_link_queue.html").render(orders=orders)


# ── queue fragment: render structure + wiring ──────────────────────────


class TestNeedsLinkQueueFragment:
    def test_renders_order_candidate_and_actions(self):
        html = _render_queue([_order()])
        assert "BTCUSDT" in html
        assert "C-ABCDEF12345" in html              # calc_id truncated (calc_id[:14])
        # choke-pointed P3.T2 action endpoints
        assert 'hx-post="/orders/1/manual_link"' in html
        assert 'hx-post="/orders/1/mark_unplanned"' in html
        assert "calc_id" in html                    # hx-vals carries the calc
        # per-criterion diff labels
        assert "Entry" in html and "TP" in html and "SL" in html
        # action result swaps into the per-order alert div
        assert 'id="nl-alert-1"' in html
        assert 'hx-target="#nl-alert-1"' in html

    def test_match_and_miss_color_both_branches(self):
        # entry matches (green), TP misses (red) → both branches must render.
        html = _render_queue([_order(candidates=[
            _cand(entry_match=True, tp_match=False, sl_match=True)
        ])])
        assert "text-green" in html
        assert "text-red" in html

    def test_empty_queue_renders_empty_state_not_error(self):
        html = _render_queue([])
        assert "es-info" in html or "class=\"es" in html
        assert "No orders need manual review" in html
        # no action buttons when the queue is empty
        assert "manual_link" not in html

    def test_order_with_no_candidates(self):
        html = _render_queue([_order(candidates=[])])
        assert "No candidate calcs within drift tolerance" in html
        # no Link buttons (no candidates) but Mark UNPLANNED still offered
        assert "manual_link" not in html
        assert 'hx-post="/orders/1/mark_unplanned"' in html

    def test_status_indicator_severity_by_link_status(self):
        nmr = _render_queue([_order(oid=1, link_status="NEEDS_MANUAL_REVIEW")])
        unl = _render_queue([_order(oid=2, link_status="UNLINKED")])
        assert "si-warning" in nmr      # NEEDS_MANUAL_REVIEW → warning
        assert "si-neutral" in unl      # UNLINKED → neutral

    def test_multiple_orders_each_get_own_targets(self):
        html = _render_queue([_order(oid=1), _order(oid=2)])
        assert 'id="nl-alert-1"' in html and 'id="nl-alert-2"' in html
        assert 'hx-post="/orders/2/manual_link"' in html


# ── page template compiles (catches Jinja syntax / nested-comment) ─────


class TestNeedsLinkPageCompiles:
    def test_page_template_compiles(self):
        # get_template compiles the child's own syntax (extends is resolved at
        # render); this catches a Jinja syntax error / nested-comment gotcha in
        # the page's content block without needing base.html's full context.
        _make_env().get_template("orders/needs_link.html")

    def test_page_lazy_loads_the_fragment(self):
        with open("templates/orders/needs_link.html", encoding="utf-8") as fh:
            src = fh.read()
        assert 'hx-get="/fragments/needs_link"' in src
        assert 'id="nl-queue"' in src
        # auto-refresh script targets the action endpoints
        assert "manual_link|mark_unplanned" in src


# ── route + nav registration (no TestClient — gotcha #9) ───────────────


class TestNeedsLinkRoutesAndNav:
    def test_routes_registered(self):
        import api.routes_orders as ro

        def _has(path, method):
            return any(
                getattr(r, "path", None) == path
                and method in getattr(r, "methods", set())
                for r in ro.router.routes
            )

        assert _has("/orders/needs_link", "GET")
        assert _has("/fragments/needs_link", "GET")

    def test_nav_and_page_meta_registered(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            base = fh.read()
        # nav tab tuple + page_meta entry both present
        assert "('needs_link', '/orders/needs_link')" in base
        assert "'needs_link':" in base
        # multi-word nav labels humanized (so "needs_link" renders "Needs Link")
        assert "page_key|replace('_', ' ')|title" in base
