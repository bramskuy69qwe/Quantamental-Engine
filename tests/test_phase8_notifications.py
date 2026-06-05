"""
Phase 8 Task 7 (P8.T7) — in-app notification system (spec §12.5).

An event_bus catch-all routes the notifiable event subset into a per-account
ring buffer; GET /notifications/poll returns new entries filtered by the
account's config_json.notification_subscriptions; base.html toasts them + shows
an unseen-count bell badge. The T8 settings page now carries the subscriptions.

Intent (Rule 8):
  - event_bus.subscribe_all delivers EVERY event (channel+payload), isolated;
  - NotificationCenter buffers ONLY the notifiable subset, monotonic-id'd,
    bounded; poll returns >since filtered by subscriptions;
  - AccountConfig.notification_subscriptions parses strict bools (default ON);
  - the poll endpoint inits without backlog replay + applies the filter;
  - the settings save persists the subscriptions; the UI is wired.

Run: pytest tests/test_phase8_notifications.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.event_bus import EventBus  # noqa: E402
from core.notifications import NotificationCenter  # noqa: E402
from core.account_config import _parse_config_json, NOTIFICATION_TYPES  # noqa: E402


# ── event_bus.subscribe_all ───────────────────────────────────────────────────


class TestSubscribeAll:
    @pytest.mark.asyncio
    async def test_receives_every_event_with_channel(self):
        bus = EventBus()
        got = []
        async def gh(ch, p): got.append((ch, p))
        bus.subscribe_all(gh)
        await bus._dispatch("engine:account:2:calc:expired", {"ticker": "BTC"})
        await bus._dispatch("risk:account_updated", {"x": 1})
        assert got == [
            ("engine:account:2:calc:expired", {"ticker": "BTC"}),
            ("risk:account_updated", {"x": 1}),
        ]

    @pytest.mark.asyncio
    async def test_global_handler_error_isolated(self):
        bus = EventBus()
        ok = []
        async def boom(ch, p): raise RuntimeError("x")
        async def fine(ch, p): ok.append(ch)
        bus.subscribe_all(boom)
        bus.subscribe_all(fine)
        await bus._dispatch("engine:account:1:order:duplicate_detected", {})  # must not raise
        assert ok == ["engine:account:1:order:duplicate_detected"]

    def test_subscribe_all_idempotent(self):
        bus = EventBus()
        async def gh(ch, p): pass
        bus.subscribe_all(gh); bus.subscribe_all(gh)
        assert bus._global_handlers.count(gh) == 1


# ── NotificationCenter ────────────────────────────────────────────────────────


class TestNotificationCenter:
    @pytest.mark.asyncio
    async def test_routes_notifiable_events(self):
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:calc:expired", {"ticker": "ETH", "direction": "long"})
        await nc.on_event("engine:account:1:position:liquidated", {"position_id": "P1"})
        await nc.on_event("engine:account:1:order:duplicate_detected", {"order_ids": [1, 2]})
        items, latest = nc.poll(1, 0)
        types = [i["type"] for i in items]
        assert types == ["calc_expired", "position_liquidated", "duplicate_order_detected"]
        assert latest == 3
        assert "ETH" in items[0]["message"]

    @pytest.mark.asyncio
    async def test_ignores_non_notifiable_and_bad_channels(self):
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:calc:linked", {})       # not notifiable
        await nc.on_event("risk:account_updated", {})               # not a Phase-6 topic
        await nc.on_event("garbage", {})
        assert nc.poll(1, 0)[0] == []

    @pytest.mark.asyncio
    async def test_account_scoped_and_since_filter(self):
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:calc:expired", {})       # id 1, acct 1
        await nc.on_event("engine:account:2:calc:expired", {})       # id 2, acct 2
        await nc.on_event("engine:account:1:position:liquidated", {})# id 3, acct 1
        a1, _ = nc.poll(1, 0)
        assert [i["id"] for i in a1] == [1, 3]                        # acct-2 excluded
        a1_since1, _ = nc.poll(1, 1)
        assert [i["id"] for i in a1_since1] == [3]                    # > since

    @pytest.mark.asyncio
    async def test_subscription_filter(self):
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:calc:expired", {})
        await nc.on_event("engine:account:1:position:liquidated", {})
        items, _ = nc.poll(1, 0, subscribed={"position_liquidated"})
        assert [i["type"] for i in items] == ["position_liquidated"]

    @pytest.mark.asyncio
    async def test_ring_buffer_bounded(self):
        nc = NotificationCenter()
        for _ in range(250):
            await nc.on_event("engine:account:1:calc:expired", {})
        items, latest = nc.poll(1, 0)
        assert len(items) == 200                                     # oldest dropped
        assert latest == 250                                         # id still monotonic

    def test_latest_id_empty(self):
        assert NotificationCenter().latest_id(99) == 0

    @pytest.mark.asyncio
    async def test_poll_cursor_never_regresses(self):
        # Audit P8.T7 MED: ids are global-monotonic; the active account's newest
        # buffered id can be < the client cursor (carried across a reload-less
        # account switch). poll's returned cursor must clamp to >= since_id so a
        # switch-back doesn't replay already-seen entries.
        nc = NotificationCenter()
        await nc.on_event("engine:account:2:calc:expired", {})       # id 1, acct 2 only
        _, latest = nc.poll(2, 5)                                     # cursor 5 > acct-2 newest (1)
        assert latest == 5                                           # clamped, NOT 1
        assert nc.poll(2, 5)[0] == []                                # and nothing replayed


# ── AccountConfig.notification_subscriptions ──────────────────────────────────


class TestAccountConfigSubscriptions:
    def test_default_all_subscribed(self):
        cfg = _parse_config_json(None)
        assert cfg.notification_subscriptions == {t: True for t in NOTIFICATION_TYPES}

    def test_explicit_false_parsed(self):
        cfg = _parse_config_json(json.dumps(
            {"notification_subscriptions": {"calc_expired": False, "position_liquidated": True}}))
        assert cfg.notification_subscriptions["calc_expired"] is False
        assert cfg.notification_subscriptions["position_liquidated"] is True
        assert cfg.notification_subscriptions["position_size_drift"] is True   # missing -> default True

    def test_strict_bool(self):
        # a non-bool value (string "false") must NOT disable — defaults to True
        cfg = _parse_config_json(json.dumps(
            {"notification_subscriptions": {"calc_expired": "false"}}))
        assert cfg.notification_subscriptions["calc_expired"] is True


# ── poll endpoint + settings round-trip ───────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.commit()
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


class TestPollEndpoint:
    @pytest.mark.asyncio
    async def test_init_returns_cursor_no_backlog(self, db, monkeypatch):
        import api.routes_notifications as rn
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:calc:expired", {})
        monkeypatch.setattr(rn, "notification_center", nc)
        monkeypatch.setattr(rn, "db", db)
        monkeypatch.setattr(rn, "app_state", SimpleNamespace(active_account_id=1))
        resp = await rn.notifications_poll(since=-1)
        body = json.loads(resp.body)
        assert body["notifications"] == [] and body["latest_id"] == 1

    @pytest.mark.asyncio
    async def test_poll_filters_by_subscription(self, db, monkeypatch):
        import api.routes_notifications as rn
        # subscribe OFF for calc_expired
        await db._conn.execute(
            "UPDATE accounts SET config_json=? WHERE id=1",
            (json.dumps({"notification_subscriptions": {"calc_expired": False}}),))
        await db._conn.commit()
        nc = NotificationCenter()
        await nc.on_event("engine:account:1:calc:expired", {})
        await nc.on_event("engine:account:1:position:liquidated", {})
        monkeypatch.setattr(rn, "notification_center", nc)
        monkeypatch.setattr(rn, "db", db)
        monkeypatch.setattr(rn, "app_state", SimpleNamespace(active_account_id=1))
        body = json.loads((await rn.notifications_poll(since=0)).body)
        assert [n["type"] for n in body["notifications"]] == ["position_liquidated"]


class TestSettingsWritesSubscriptions:
    @pytest.mark.asyncio
    async def test_save_persists_subscriptions(self, db, monkeypatch):
        import api.routes_config as rc
        from core.account_config import read_account_config_async
        monkeypatch.setattr(rc, "db", db)
        monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))
        await rc.save_account_config(
            window_seconds="300", clock_skew_tolerance_sec="10",
            entry_tolerance_pct="0.25", snapshot_drift_tolerance_pct="0.5",
            yellow_pct="5", red_pct="15", size_deviation_threshold_pct="10",
            webhook_url="", webhook_enabled="", snapshot_wins_drift="",
            notif_calc_expired="on", notif_position_liquidated="",
            notif_position_size_drift="on", notif_duplicate_order_detected="on",
            notif_near_replacement_match="",
        )
        cfg = await read_account_config_async(db, 1)
        assert cfg.notification_subscriptions == {
            "calc_expired": True, "position_liquidated": False,
            "position_size_drift": True, "duplicate_order_detected": True,
            "near_replacement_match": False,
        }


# ── wiring ────────────────────────────────────────────────────────────────────


class TestWiring:
    def test_poll_route_registered(self):
        import api.routes_notifications as rn
        assert any(getattr(r, "path", None) == "/notifications/poll" for r in rn.router.routes)
        import api.router as r
        assert "/notifications/poll" in {getattr(rt, "path", None) for rt in r.router.routes}

    def test_base_html_bell_and_poll(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            src = fh.read()
        assert 'id="notif-count"' in src
        assert "/notifications/poll?since=" in src
        assert "ackNotifications" in src            # bell click acks the unseen count
        assert "/notifications/poll?since=-1" in src  # init establishes cursor (no backlog replay)
        assert "htmx:afterSettle" in src            # repaint badge after boosted-nav body swap (audit fix)

    def test_settings_renders_notif_checkboxes_prefilled(self):
        # Compile-render (CLAUDE.md template discipline): the checkbox names are
        # templated (name="notif_{{ t }}"), so a raw-source grep can't see them;
        # render with a known subscription map and assert the names + prefill.
        import jinja2
        from core.account_config import AccountConfig
        env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"), autoescape=True)
        tmpl = env.get_template("fragments/account_config.html")
        cfg = AccountConfig(                       # all flags off -> isolate notif prefill
            snapshot_wins_drift=False, webhook_enabled=False,
            notification_subscriptions={
                "calc_expired": True, "position_liquidated": False,
                "position_size_drift": False, "duplicate_order_detected": False,
                "near_replacement_match": False,
            },
        )
        html = tmpl.render(cfg=cfg)
        for t in ("calc_expired", "position_liquidated", "position_size_drift",
                  "duplicate_order_detected", "near_replacement_match"):
            assert f'name="notif_{t}"' in html
        # exactly the one subscribed type renders a checked attribute
        assert html.count(" checked") == 1

    def test_schedulers_wires_center(self):
        with open("core/schedulers.py", encoding="utf-8") as fh:
            src = fh.read()
        assert "start_notification_center(event_bus)" in src
