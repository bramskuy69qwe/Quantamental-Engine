"""Tests for ghost interface (skeleton loading states)."""
import os

import pytest


GHOST_DIR = "templates/fragments/ghosts"
GHOST_FILES = [
    "top_ghost.html",
    "chart_ghost.html",
    "secondary_ghost.html",
    "risk_ghost.html",
    "positions_ghost.html",
    "journal_ghost.html",
]


class TestGhostTemplatesExist:
    @pytest.mark.parametrize("name", GHOST_FILES)
    def test_ghost_template_exists(self, name):
        assert os.path.exists(os.path.join(GHOST_DIR, name))

    @pytest.mark.parametrize("name", GHOST_FILES)
    def test_ghost_is_fragment(self, name):
        content = open(os.path.join(GHOST_DIR, name), encoding="utf-8").read()
        assert "<html" not in content.lower()
        assert "{% extends" not in content

    @pytest.mark.parametrize("name", GHOST_FILES)
    def test_ghost_has_ghost_class(self, name):
        content = open(os.path.join(GHOST_DIR, name), encoding="utf-8").read()
        assert "ghost" in content


class TestDashboardIncludesGhosts:
    def test_dashboard_includes_all_ghosts(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        for name in GHOST_FILES:
            assert name in content, f"Ghost {name} not included in dashboard"


class TestGhostCSS:
    def test_ghost_styles_in_base(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert ".ghost" in content
        assert "ghost-pulse" in content

    def test_reduced_motion_media_query(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "prefers-reduced-motion" in content

    def test_pulse_animation_defined(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "@keyframes ghost-pulse" in content
