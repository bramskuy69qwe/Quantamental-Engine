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

    def test_project_version_shape(self):
        """Version must parse as v<major>.<minor>[.<patch>...] — shape pin
        only. The VALUE is deliberately unpinned here: an exact-prefix pin
        (test_task108's retired startswith('v2.4.1') assertion) failed any
        bump, and the display version in fact sat at v2.4.1.1 through the
        v2.5-v2.7 programs."""
        import re
        assert re.fullmatch(r"v\d+\.\d+(\.\d+)*", config.PROJECT_VERSION_), (
            f"PROJECT_VERSION_ {config.PROJECT_VERSION_!r} is not v<major>.<minor>[.…]"
        )

    def test_full_name_combines_both(self):
        assert config.PROJECT_NAME == f"{config.PROJECT_NAME_} {config.PROJECT_VERSION_}"

    def test_pwa_identity_constants(self):
        """PWA manifest identity lives in config (naming-hygiene task):
        short_name spec guidance is ≤ 12 chars."""
        assert isinstance(config.PROJECT_SHORT_NAME, str)
        assert 0 < len(config.PROJECT_SHORT_NAME) <= 12
        assert isinstance(config.PROJECT_DESCRIPTION, str)
        assert len(config.PROJECT_DESCRIPTION) > 0


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
    def test_no_hardcoded_version_literal(self, filepath):
        """No runtime file should contain a hardcoded 'vN.N' version string
        literal outside of the canonical config.PROJECT_VERSION_ definition.

        Naming-hygiene task: the scan was 'v2\\.'-prefixed, so it would have
        silently stopped guarding at the first v3.x bump. Now major-agnostic."""
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
            # Look for quoted version strings: "vN.N" or 'vN.N'
            matches = re.findall(r'''["']v\d+\.\d+["']''', line)
            assert len(matches) == 0, \
                f"{filepath}:{i} has hardcoded version literal: {matches}"

    def test_fastapi_version_derives_from_config(self):
        """main.py's FastAPI(version=...) must derive from config, not a
        literal. The old literal ("2.1.0") had NO leading 'v', so the quoted
        vN.N scan above could never catch this form — pin the wiring itself."""
        content = open("main.py", encoding="utf-8").read()
        assert "version=config.PROJECT_VERSION_" in content, (
            "FastAPI version must derive from config.PROJECT_VERSION_ "
            "(a numeric literal here goes stale invisibly — it read '2.1.0' "
            "while the displayed product version was v2.4.1.1)"
        )


class TestStartupOverlayUsesConfig:
    def test_overlay_no_hardcoded_version(self):
        """Startup overlay in base.html must use template vars, not literals."""
        content = open("templates/base.html", encoding="utf-8").read()
        idx = content.find("startup-overlay")
        assert idx != -1
        block = content[idx:idx+500]
        assert "project_name_" in block or "project_version_" in block, \
            "Startup overlay should use {{ project_name_ }} / {{ project_version_ }}"
        import re
        matches = re.findall(r'v\d+\.\d+', block)
        assert len(matches) == 0, \
            f"Startup overlay has hardcoded version: {matches}"


class TestLauncherReadsConfig:
    """launch-v3.bat (THE launcher — legacy launch.bat archived 2026-07-30;
    its --reload double-ran the live schedulers) reads project identity from
    config.py at runtime. Hard reads, no exists-skip: if the canonical
    launcher vanishes, this pin should say so."""

    def test_launcher_uses_python_config(self):
        content = open("launch-v3.bat", encoding="utf-8").read()
        assert "config.PROJECT_NAME" in content, \
            "launch-v3.bat should read project name from config.py"

    def test_launcher_no_hardcoded_version(self):
        content = open("launch-v3.bat", encoding="utf-8").read()
        import re
        matches = re.findall(r'v\d+\.\d+', content)
        assert len(matches) == 0, \
            f"launch-v3.bat has hardcoded version: {matches}"

    def test_launcher_never_reloads(self):
        # The archived launcher's --reload spawned workers that DOUBLE-RAN
        # all live schedulers with real API keys. Never again.
        content = open("launch-v3.bat", encoding="utf-8").read()
        assert "--reload" not in content.replace(
            "NO --reload", ""), "the launcher must never pass --reload"


class TestManifestServedDynamically:
    """manifest.json is served via route (main.py), not a static file."""

    def test_no_static_manifest(self):
        assert not os.path.exists("static/manifest.json"), \
            "static/manifest.json should be deleted — route serves dynamic JSON"

    def test_route_uses_config(self):
        content = open("main.py", encoding="utf-8").read()
        assert "config.PROJECT_NAME" in content

    def test_manifest_identity_from_config(self):
        """short_name/description were literals in the manifest route until
        the naming-hygiene task — a rename would have left them stale."""
        content = open("main.py", encoding="utf-8").read()
        assert "config.PROJECT_SHORT_NAME" in content
        assert "config.PROJECT_DESCRIPTION" in content


class TestServiceWorkerNoVersion:
    """service-worker.js comment has no hardcoded version."""

    def test_no_version_in_comment(self):
        if not os.path.exists("static/service-worker.js"):
            pytest.skip("service-worker.js not found")
        content = open("static/service-worker.js", encoding="utf-8").read()
        import re
        matches = re.findall(r'v\d+\.\d+', content)
        assert len(matches) == 0, \
            f"service-worker.js has hardcoded version: {matches}"

    def test_no_brand_name_in_display_strings(self):
        """The SW is served as a raw static file (FileResponse) and cannot
        read config — its user-visible strings are deliberately brand-free
        so a product rename can't strand them (naming-hygiene task)."""
        content = open("static/service-worker.js", encoding="utf-8").read()
        assert "Quantamental" not in content, (
            "service-worker.js hardcodes the product name; keep its display "
            "strings brand-free (it cannot read config.PROJECT_NAME)"
        )

    def test_precache_uses_manifest_route(self):
        """The manifest is served by a route (/manifest.json), not from
        /static/. The old /static/manifest.json pre-cache entry 404'd, and
        cache.addAll is atomic — one dead URL voided the entire pre-cache."""
        content = open("static/service-worker.js", encoding="utf-8").read()
        assert "'/manifest.json'" in content
        assert "/static/manifest.json" not in content
