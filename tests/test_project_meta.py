"""Tests for centralized project metadata."""
import os

import pytest

import config


class TestCanonicalSource:
    def test_project_name_exists(self):
        assert hasattr(config, "PROJECT_NAME_")
        assert isinstance(config.PROJECT_NAME_, str)
        assert len(config.PROJECT_NAME_) > 0

    def test_project_version_exists(self):
        assert hasattr(config, "PROJECT_VERSION_")
        assert isinstance(config.PROJECT_VERSION_, str)
        assert config.PROJECT_VERSION_.startswith("v")

    def test_full_name_combines_both(self):
        assert config.PROJECT_NAME == f"{config.PROJECT_NAME_} {config.PROJECT_VERSION_}"


class TestTemplateGlobalsWired:
    def test_helpers_registers_globals(self):
        """api/helpers.py registers project_name, project_name_, project_version_."""
        content = open("api/helpers.py", encoding="utf-8").read()
        assert 'project_name' in content
        assert 'config.PROJECT_NAME' in content
        assert 'config.PROJECT_NAME_' in content
        assert 'config.PROJECT_VERSION_' in content


class TestNoHardcodedVersionInRuntime:
    """Ensure runtime Python files don't hardcode version strings."""

    RUNTIME_FILES = [
        "main.py",
        "config.py",
        "core/schedulers.py",
        "core/risk_engine.py",
        "core/exchange.py",
        "api/helpers.py",
    ]

    @pytest.mark.parametrize("filepath", RUNTIME_FILES)
    def test_no_hardcoded_v2_dot(self, filepath):
        """No runtime file should contain a hardcoded 'v2.X' version string
        literal outside of the canonical config.PROJECT_VERSION_ definition."""
        if not os.path.exists(filepath):
            pytest.skip(f"{filepath} not found")
        lines = open(filepath, encoding="utf-8").read().split("\n")
        import re
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            # Skip comments and the canonical definition
            if stripped.startswith("#") or "PROJECT_VERSION_" in line:
                continue
            # Skip docstrings (lines inside triple-quotes are hard to detect
            # perfectly, but standalone version refs in docstrings are ok)
            if stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Look for quoted version strings: "v2.X" or 'v2.X'
            matches = re.findall(r'''["']v2\.\d+["']''', line)
            assert len(matches) == 0, \
                f"{filepath}:{i} has hardcoded version literal: {matches}"


class TestLauncherReadsConfig:
    """launch.bat reads project name from config.py at runtime."""

    def test_launch_bat_uses_python_config(self):
        if not os.path.exists("launch.bat"):
            pytest.skip("launch.bat not found")
        content = open("launch.bat", encoding="utf-8").read()
        assert "config.PROJECT_NAME" in content, \
            "launch.bat should read project name from config.py"

    def test_launch_bat_no_hardcoded_version(self):
        if not os.path.exists("launch.bat"):
            pytest.skip("launch.bat not found")
        content = open("launch.bat", encoding="utf-8").read()
        import re
        matches = re.findall(r'v2\.\d+', content)
        assert len(matches) == 0, \
            f"launch.bat has hardcoded version: {matches}"


class TestManifestServedDynamically:
    """manifest.json is served via route (main.py), not a static file."""

    def test_no_static_manifest(self):
        assert not os.path.exists("static/manifest.json"), \
            "static/manifest.json should be deleted — route serves dynamic JSON"

    def test_route_uses_config(self):
        content = open("main.py", encoding="utf-8").read()
        assert "config.PROJECT_NAME" in content


class TestServiceWorkerNoVersion:
    """service-worker.js comment has no hardcoded version."""

    def test_no_version_in_comment(self):
        if not os.path.exists("static/service-worker.js"):
            pytest.skip("service-worker.js not found")
        content = open("static/service-worker.js", encoding="utf-8").read()
        import re
        matches = re.findall(r'v2\.\d+', content)
        assert len(matches) == 0, \
            f"service-worker.js has hardcoded version: {matches}"
