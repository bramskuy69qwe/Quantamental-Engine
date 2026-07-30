"""Tests for HTMX morphing integration."""
import os

import pytest


class TestIdiomorphIncluded:
    def test_idiomorph_script_in_base(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "idiomorph" in content.lower()

    def test_idiomorph_version_pinned(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "idiomorph@0.3.0" in content

    def test_htmx_version(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "htmx.org@1.9.12" in content




