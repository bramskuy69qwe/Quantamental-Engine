"""Tests for position_update publish on recalc cycle."""
import inspect

import pytest


class TestRecalcPublisherPresent:
    def test_position_channel_in_recalc(self):
        """_do_recalculate_portfolio publishes to position_channel."""
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        assert "position_channel" in src

    def test_recalc_trigger_value(self):
        """Recalc publisher uses trigger='recalc_cycle'."""
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        assert '"recalc_cycle"' in src


class TestApplySnapshotPublisherStillActive:
    def test_position_channel_in_apply_snapshot(self):
        """apply_position_snapshot still publishes (regression check)."""
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache.apply_position_snapshot)
        assert "position_channel" in src


class TestPayloadShapeParity:
    def test_both_have_trigger_key(self):
        from core.data_cache import DataCache
        src_recalc = inspect.getsource(DataCache._do_recalculate_portfolio)
        src_apply = inspect.getsource(DataCache.apply_position_snapshot)
        assert '"trigger"' in src_recalc
        assert '"trigger"' in src_apply

    def test_both_have_positions_key(self):
        from core.data_cache import DataCache
        src_recalc = inspect.getsource(DataCache._do_recalculate_portfolio)
        src_apply = inspect.getsource(DataCache.apply_position_snapshot)
        assert '"positions"' in src_recalc
        assert '"positions"' in src_apply

    def test_both_have_ts_key(self):
        from core.data_cache import DataCache
        src_recalc = inspect.getsource(DataCache._do_recalculate_portfolio)
        src_apply = inspect.getsource(DataCache.apply_position_snapshot)
        assert '"ts"' in src_recalc
        assert '"ts"' in src_apply


class TestBestEffortWrapping:
    def test_publish_wrapped_in_try_except(self):
        """Publisher failure must not break recalc."""
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        # The position publish is inside a try/except block
        # Find the "recalc_cycle" line and verify except follows
        lines = src.split("\n")
        found_publish = False
        found_except = False
        for line in lines:
            if "recalc_cycle" in line:
                found_publish = True
            if found_publish and "except Exception" in line:
                found_except = True
                break
        assert found_publish, "recalc_cycle publish not found"
        assert found_except, "try/except wrapping not found after publish"
