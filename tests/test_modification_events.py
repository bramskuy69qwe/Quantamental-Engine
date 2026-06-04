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


class TestHasTpslModification:
    """``routes_orders._has_tpsl_modification`` is the migrated consumer: it
    derives "this fill's calc had a TP/SL change" from position_amended rows
    (forward) and the legacy types (historical)."""

    def _h(self, events):
        from api.routes_orders import _has_tpsl_modification
        return _has_tpsl_modification(events)

    def test_position_amended_tp_price_counts(self):
        assert self._h([{"event_type": "position_amended",
                         "payload_json": '{"field": "tp_price", "old": 1, "new": 2}'}])

    def test_position_amended_sl_price_counts(self):
        assert self._h([{"event_type": "position_amended",
                         "payload_json": '{"field": "sl_price"}'}])

    def test_position_amended_entry_price_does_not_count(self):
        # entry/size amendments are not "TP/SL modifications" — the migrated
        # predicate must scope to tp_price/sl_price, mirroring the old
        # tp_modified/sl_modified semantics exactly.
        assert not self._h([{"event_type": "position_amended",
                             "payload_json": '{"field": "entry_price"}'}])

    def test_position_amended_size_does_not_count(self):
        assert not self._h([{"event_type": "position_amended",
                             "payload_json": '{"field": "size"}'}])

    def test_legacy_tp_modified_counts(self):
        # historical rows (no live producer) still register.
        assert self._h([{"event_type": "tp_modified", "payload_json": "{}"}])

    def test_legacy_sl_modified_counts(self):
        assert self._h([{"event_type": "sl_modified", "payload_json": "{}"}])

    def test_unrelated_events_do_not_count(self):
        assert not self._h([
            {"event_type": "order_filled", "payload_json": "{}"},
            {"event_type": "position_opened", "payload_json": "{}"},
        ])

    def test_empty_is_false(self):
        assert not self._h([])

    def test_malformed_payload_json_does_not_raise(self):
        # a corrupt payload must be treated as "no field", not crash the panel.
        assert not self._h([{"event_type": "position_amended",
                             "payload_json": "{not json"}])
        # missing payload_json key entirely
        assert not self._h([{"event_type": "position_amended"}])
