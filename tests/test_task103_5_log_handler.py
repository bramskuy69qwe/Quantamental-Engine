"""
Task 103.5 regression tests for MED-045.

MED-045 — main.py's primary log handler must be ConcurrentRotatingFileHandler
(not the stdlib RotatingFileHandler). The stdlib version uses os.rename for
rotation, which fails on Windows under multi-process setups
(uvicorn workers etc.) with PermissionError [WinError 32].

Cross-process rotation is genuinely hard to unit-test (would require
spawning real processes that share the file handle). The pins below cover:
1. Source-pin: main.py imports + instantiates ConcurrentRotatingFileHandler.
2. Config-preservation: maxBytes / backupCount / encoding match prior values.
3. Single-process rotation smoke: trigger a real rollover and confirm the
   .1 file appears (catches a swap that broke basic rotation).

Run: pytest tests/test_task103_5_log_handler.py -v
"""
from __future__ import annotations

import inspect
import logging
import os
import tempfile

import pytest


# ── MED-045 source-pin: main.py uses ConcurrentRotatingFileHandler ───────────

class TestLogHandlerClass:
    def test_main_imports_concurrent_rotating_file_handler(self):
        """Source-pin: the import line must reference the concurrent variant.
        Catches an accidental revert to `from logging.handlers import
        RotatingFileHandler`."""
        import main
        src = inspect.getsource(main)
        assert "from concurrent_log_handler import ConcurrentRotatingFileHandler" in src, (
            "MED-045 regression: main.py no longer imports "
            "ConcurrentRotatingFileHandler. Rotation will fail on Windows "
            "multi-process setups."
        )

    def test_main_does_not_import_stdlib_rotating_file_handler(self):
        """Anti-revert pin: the old import must NOT be present. A reviewer
        who adds back the stdlib import without noticing the swap should
        be caught here."""
        import main
        src = inspect.getsource(main)
        assert "from logging.handlers import RotatingFileHandler" not in src, (
            "MED-045 regression: main.py reintroduced the stdlib "
            "RotatingFileHandler import. The cross-process rotation bug "
            "comes back with it."
        )

    def test_instantiation_uses_concurrent_handler_class(self):
        """The handler instance attached to the root logger must be a
        ConcurrentRotatingFileHandler. Source-pin above proves the
        import; this asserts the instance actually used was the right
        class (catches an import that aliases to something else)."""
        import main
        from concurrent_log_handler import ConcurrentRotatingFileHandler

        # The handler is created at module-load time as _json_handler.
        assert isinstance(main._json_handler, ConcurrentRotatingFileHandler), (
            f"MED-045 regression: main._json_handler is "
            f"{type(main._json_handler).__name__}, not "
            f"ConcurrentRotatingFileHandler."
        )


# ── MED-045 config-preservation: rotation thresholds unchanged ───────────────

class TestLogHandlerConfigPreserved:
    """The handler-class swap must NOT change rotation behavior. maxBytes,
    backupCount, and encoding all need to match the prior config exactly."""

    def test_max_bytes_unchanged(self):
        import main
        assert main._json_handler.maxBytes == 10 * 1024 * 1024, (
            f"MED-045 sanity: maxBytes drifted from 10 MB during handler "
            f"swap; got {main._json_handler.maxBytes}."
        )

    def test_backup_count_unchanged(self):
        import main
        assert main._json_handler.backupCount == 5, (
            f"MED-045 sanity: backupCount drifted from 5 during handler "
            f"swap; got {main._json_handler.backupCount}."
        )

    def test_encoding_unchanged(self):
        import main
        assert main._json_handler.encoding == "utf-8", (
            f"MED-045 sanity: encoding drifted from utf-8 during handler "
            f"swap; got {main._json_handler.encoding!r}."
        )


# ── MED-045 smoke: rotation actually happens (single-process) ────────────────

class TestSingleProcessRotationSmoke:
    """Multi-process rotation can't be unit-tested cheaply. At minimum,
    confirm the swap didn't break single-process rotation — write enough
    bytes to trigger a rollover, then verify the .1 file appears."""

    def test_rotation_produces_backup_file(self, tmp_path):
        from concurrent_log_handler import ConcurrentRotatingFileHandler

        log_file = tmp_path / "smoke.log"
        # Small maxBytes so rotation triggers after a couple of records.
        handler = ConcurrentRotatingFileHandler(
            str(log_file),
            maxBytes=200,
            backupCount=2,
            encoding="utf-8",
            use_gzip=False,
        )
        logger = logging.getLogger("med045_smoke_test")
        # Defensive: clear any handlers from a prior test invocation
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Write enough records to force rotation
        for i in range(10):
            logger.info(
                "padding-record-%d %s", i, "x" * 50,
            )
        handler.flush()
        handler.close()

        # Either the rotated .1 exists OR the current file is small
        # (post-rotation state). Both signal that rotation ran.
        rotated = log_file.with_suffix(".log.1")
        assert rotated.exists(), (
            f"MED-045 regression: rotation did not produce {rotated.name}. "
            f"Listing: {[p.name for p in tmp_path.iterdir()]}"
        )

    def test_handler_close_does_not_raise(self, tmp_path):
        """Anti-over-correction: closing the handler must be clean —
        important because lifespan shutdown does this."""
        from concurrent_log_handler import ConcurrentRotatingFileHandler

        log_file = tmp_path / "close.log"
        handler = ConcurrentRotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
            use_gzip=False,
        )
        # Closing without writing anything should be a no-op
        handler.close()
