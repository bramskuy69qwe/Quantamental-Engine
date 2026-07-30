"""TP/SL modification tracking — post-migration to the amendment path.

The legacy ``_detect_modification_events`` (emitter of ``tp_modified`` /
``sl_modified`` trade events) was DELETED: it ran post-gate in
``process_order_update``, but a TP/SL price change arrives as a ``new→new``
self-transition that the SR-1 gate rejects first, so it never fired live. TP/SL
modifications now flow through the P4.T1 amendment path (pre-gate
``detect_and_persist_amendment`` → ``position_amended`` with
``field=tp_price/sl_price``). These tests pin that migration.
"""
from core.trade_event_log import _VALID_TRADE_EVENT_TYPES


class TestLegacyDetectorRemoved:
    def test_detect_modification_events_method_gone(self):
        """The dead detector must not exist — its presence would re-introduce a
        producer for the superseded event types (and a post-gate dead path)."""
        from core.order_manager import OrderManager
        assert not hasattr(OrderManager, "_detect_modification_events")


class TestModificationEventTypesRetained:
    """The legacy types stay VALID (no producer) so historical rows in older
    per-account DBs still read + render; position_amended is the live signal."""

    def test_tp_modified_still_valid_for_history(self):
        assert "tp_modified" in _VALID_TRADE_EVENT_TYPES

    def test_sl_modified_still_valid_for_history(self):
        assert "sl_modified" in _VALID_TRADE_EVENT_TYPES

    def test_position_amended_is_the_live_type(self):
        assert "position_amended" in _VALID_TRADE_EVENT_TYPES


