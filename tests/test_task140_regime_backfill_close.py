"""
Task 140 regression tests — FE-HIGH-008 (Regime Backfill AttributeError
on `.close()` call).

Root cause: `api/routes_regime.py:108` called `await fetcher.close()`
on a `RegimeFetcher` instance. `RegimeFetcher` has no `.close()`
method — it holds only `self._adapter` (caller-owned reference) and
each fetch_* method uses its own `async with httpx.AsyncClient(...)`
context manager which closes per-call. The orphan `.close()` call
raised AttributeError after fetch_all completed (~80% of backfill
progress, since fetch_all is the 0-80% phase), aborting the run
BEFORE the classify_range step. Net effect: BTC Market Cap +
Aggregate OI Change signals never got fully backfilled through the
UI flow.

Fix (Task 140): remove the orphan call. RegimeFetcher legitimately
has nothing to close — adding a no-op `close()` method would obscure
intent. Anchor comment in the call site explains the removal.

Investigation outcome — event-bus pattern check (per Task 140 spec):
Regime backfill does NOT share the calculator link-window race
pattern (Task 139 PENDING fix). Different shape:
  - Calculator: event_bus.publish → asyncio.Queue → separate consumer
    task → DB INSERT. Status endpoint reads DB. Race: status read may
    fire before consumer's INSERT commits.
  - Backfill: asyncio.create_task(_run) + shared in-memory
    `_regime_jobs` dict. Job dict is set BEFORE task fires
    (routes_regime.py:96 vs create_task at line 128). Status endpoint
    reads the same dict (in-memory, GIL-protected). No "row not yet
    written" window.

No new race-surface finding to file.

Run: pytest tests/test_task140_regime_backfill_close.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Source-pin: orphan .close() call removed ────────────────────────────────

class TestOrphanCloseCallRemoved:
    """The `await fetcher.close()` call at routes_regime.py:108 must
    be gone. If a future refactor adds RegimeFetcher cleanup
    semantics, do it deliberately and update this test."""

    def test_no_fetcher_close_call_in_backfill_runner(self):
        src = Path("api/routes_regime.py").read_text(encoding="utf-8")
        # Locate the _run() inner function — the orphan call lived in
        # the success path between fetch_all and classify_range.
        idx = src.find("async def _run():")
        assert idx > 0
        # Window covers the _run() body roughly
        end = src.find("\n    asyncio.create_task", idx)
        body = src[idx:end] if end > 0 else src[idx:idx + 3000]
        # Executing code should not call fetcher.close()
        for line in body.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            assert "fetcher.close()" not in line, (
                "FE-HIGH-008 regression: `fetcher.close()` call back in "
                "routes_regime.py _run(). RegimeFetcher has no close() "
                "method — orphan call raised AttributeError post-fetch."
            )

    def test_anchor_comment_explains_removal(self):
        """Anchor comment must remain so future maintainers don't
        re-add the call thinking it's a missing cleanup."""
        src = Path("api/routes_regime.py").read_text(encoding="utf-8")
        idx = src.find("async def _run():")
        end = src.find("\n    asyncio.create_task", idx)
        body = src[idx:end] if end > 0 else src[idx:idx + 3000]
        assert "FE-HIGH-008" in body or "Task 140" in body, (
            "Anchor comment missing — future maintainers may re-add "
            "the orphan .close() call."
        )


# ── Source-pin: RegimeFetcher still has no .close() (deliberate) ────────────

class TestRegimeFetcherHasNoCloseMethod:
    """RegimeFetcher legitimately holds no persistent resources.
    Adding a no-op .close() to silence the call would obscure intent.
    Pinned: the class still has no .close() method."""

    def test_no_close_method_defined(self):
        from core.regime_fetcher import RegimeFetcher
        assert not hasattr(RegimeFetcher, "close"), (
            "RegimeFetcher gained a .close() method. If this is "
            "deliberate (e.g., a new persistent resource was added), "
            "update this test to match the new contract. Otherwise "
            "remove the method — Task 140 deliberately did NOT add a "
            "no-op close to silence the call site."
        )

    def test_instance_has_only_adapter_attr(self):
        """The class holds only `self._adapter` — no httpx client,
        no DB connection, no file handle. If state expands, audit
        cleanup needs."""
        from core.regime_fetcher import RegimeFetcher
        f = RegimeFetcher()
        # Defensive set check: only _adapter as instance state
        state = {k for k in vars(f) if not k.startswith("__")}
        assert state == {"_adapter"}, (
            f"RegimeFetcher instance state changed: {state}. If a "
            f"persistent resource was added (httpx client, DB conn, "
            f"file handle), cleanup semantics need re-evaluation — "
            f"the Task-140 'no close() needed' rationale assumes only "
            f"_adapter is held."
        )


# ── FBF-style: reproduce the original AttributeError ────────────────────────

class TestOriginalAttributeErrorReproducible:
    """If you call `.close()` on a RegimeFetcher directly, it still
    raises AttributeError. This documents the pre-fix failure mode —
    if a maintainer ever re-adds .close() in routes_regime, this
    test still demonstrates why it would crash."""

    @pytest.mark.asyncio
    async def test_close_raises_attribute_error(self):
        from core.regime_fetcher import RegimeFetcher
        fetcher = RegimeFetcher()
        with pytest.raises(AttributeError) as exc:
            await fetcher.close()  # type: ignore[attr-defined]
        # The pre-fix error message was specifically this shape:
        msg = str(exc.value)
        assert "close" in msg
        assert "RegimeFetcher" in msg


# ── Event-bus-pattern investigation pin (Task 140 step 3) ───────────────────

class TestBackfillUsesInMemoryJobDictNotEventBus:
    """Document the investigation outcome in test form: Regime
    backfill does NOT use the calculator event-bus-then-poll pattern.
    If a future refactor moves backfill onto the event_bus, this
    test will fail and trigger a re-evaluation of whether the Task
    139 PENDING approach should generalize."""

    def test_backfill_uses_create_task_not_event_bus(self):
        src = Path("api/routes_regime.py").read_text(encoding="utf-8")
        idx = src.find("async def api_regime_backfill")
        assert idx > 0
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        # Backfill spawns its own task via create_task
        assert "asyncio.create_task(_run())" in body, (
            "Backfill no longer uses create_task — re-evaluate "
            "whether the calculator event-bus race pattern now "
            "applies. See Task 139 for the PENDING-state pattern."
        )
        # And does NOT publish to event_bus
        assert "event_bus.publish" not in body, (
            "Backfill is now publishing to event_bus — same race "
            "surface as Task 139's calculator countdown. Consider "
            "generalizing the PENDING approach."
        )

    def test_status_endpoint_reads_in_memory_dict(self):
        """The status endpoint reads from _regime_jobs (in-memory
        dict), not from a DB table. This is why the race doesn't
        apply — no DB write-after-read window."""
        src = Path("api/routes_regime.py").read_text(encoding="utf-8")
        idx = src.find("async def api_regime_backfill_status")
        assert idx > 0
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        assert "_regime_jobs.get(" in body or "_regime_jobs[" in body, (
            "Status endpoint no longer reads from _regime_jobs — "
            "shape may have changed; re-investigate event-bus race "
            "surface."
        )

    def test_job_dict_set_before_task_fires(self):
        """The job dict is registered in _regime_jobs BEFORE
        asyncio.create_task fires. This ordering is what closes the
        'job not found' window — no equivalent to calculator's
        'calc_id not in DB yet' transient state."""
        src = Path("api/routes_regime.py").read_text(encoding="utf-8")
        idx = src.find("async def api_regime_backfill")
        end = src.find("\n@router", idx)
        body = src[idx:end] if end > 0 else src[idx:]
        # The registration line must appear before the create_task line
        reg_idx = body.find("_regime_jobs[job_id] = job")
        task_idx = body.find("asyncio.create_task(_run())")
        assert reg_idx > 0 and task_idx > 0
        assert reg_idx < task_idx, (
            "Job dict registered AFTER task fires — would re-open "
            "the 'job_id not found' race window. Re-order required."
        )
