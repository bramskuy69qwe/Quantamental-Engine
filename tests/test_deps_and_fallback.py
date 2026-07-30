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


