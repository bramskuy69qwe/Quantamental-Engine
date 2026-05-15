"""Tests for dependency pinning + fallback polling tightening."""
import pytest


class TestDependencyImports:
    def test_sse_starlette_importable(self):
        import sse_starlette
        assert hasattr(sse_starlette, "sse")

    def test_redis_asyncio_importable(self):
        import redis.asyncio
        assert hasattr(redis.asyncio, "Redis")

    def test_fakeredis_importable(self):
        import fakeredis
        assert hasattr(fakeredis, "aioredis")

    def test_routes_streams_importable(self):
        from api.routes_streams import router
        assert router is not None


class TestRequirementsTxt:
    def test_sse_starlette_in_requirements(self):
        content = open("requirements.txt", encoding="utf-8").read()
        assert "sse-starlette" in content

    def test_redis_in_requirements(self):
        content = open("requirements.txt", encoding="utf-8").read()
        assert "redis>=" in content

    def test_fakeredis_in_requirements(self):
        content = open("requirements.txt", encoding="utf-8").read()
        assert "fakeredis>=" in content


class TestFallbackPolling:
    def test_sse_fragments_use_10s_fallback(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        # All SSE-driven fragments should have "every 10s"
        sse_lines = [
            line for line in content.split("\n")
            if "sse:" in line and "hx-trigger" in line
        ]
        for line in sse_lines:
            assert "every 10s" in line, f"Expected 10s fallback in: {line.strip()}"

    def test_journal_stats_stays_30s(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if "journal_stats" in line:
                # Find the hx-trigger on the next few lines
                for j in range(max(0, i-2), min(len(lines), i+3)):
                    if "hx-trigger" in lines[j]:
                        assert "every 30s" in lines[j], "journal_stats should stay at 30s"
                        break

    def test_no_every_1s_or_2s_remaining(self):
        """No pre-SSE polling intervals should remain on SSE fragments."""
        content = open("templates/dashboard.html", encoding="utf-8").read()
        # Check that "every 1s" and "every 2s" are gone from SSE fragments
        assert "every 1s" not in content
        assert "every 2s" not in content
