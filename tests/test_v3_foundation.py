"""P0 foundation contract tests (v3.0 UI rebuild).

Track-2 doctrine (docs/design/v3.0_ui_rebuild_plan.md §8): the new React DOM is
NOT frozen yet, so there are no Playwright/DOM assertions here. These pin the
serving + build-output contract at stable seams — the manifest, the vendored
(offline) assets, the shell template's compile-render, and the /v3 route
registration. Expand to DOM assertions only after the v3 DOM settles.

No TestClient is used (LOW-023 + the F5 live-DB lifespan gap): the route is
verified by inspecting the router and calling the manifest loader / rendering the
template directly with a synthetic context.
"""
import json
import pathlib
import re

from jinja2 import Environment, FileSystemLoader

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_STATIC_V3 = _ROOT / "static" / "v3"
_VENDOR = _ROOT / "static" / "vendor"


def _manifest() -> dict:
    return json.loads((_STATIC_V3 / "manifest.json").read_text(encoding="utf-8"))


class TestV3BuildOutput:
    def test_manifest_exists_and_complete(self):
        m = _manifest()
        for k in ("hash", "app", "tokens", "shell", "modules"):
            assert k in m, f"manifest missing {k}"
        for key in ("app", "tokens", "shell"):
            assert (_STATIC_V3 / m[key]).exists(), f"{m[key]} missing on disk"
        assert m["hash"] in m["app"], "app filename must carry the build hash"

    def test_app_shell_builds_last(self):
        # load order is load-bearing (window-sharing); app-shell mounts React root
        assert _manifest()["modules"][-1] == "app-shell.jsx"

    def test_vendored_assets_present(self):
        for f in (
            "react.production.min.js",
            "react-dom.production.min.js",
            "echarts.min.js",
            "gridstack-all.js",
            "gridstack.min.css",
        ):
            assert (_VENDOR / f).exists(), f"vendored {f} missing"
        assert (_VENDOR / "fonts" / "fonts.css").exists()
        assert (_VENDOR / "fonts" / "space-grotesk-latin-400-normal.woff2").exists()
        assert (_VENDOR / "fonts" / "jetbrains-mono-latin-400-normal.woff2").exists()

    def test_bundle_is_offline_precompiled(self):
        app = (_STATIC_V3 / _manifest()["app"]).read_text(encoding="utf-8")
        for host in ("unpkg.com", "cdn.jsdelivr.net", "fonts.googleapis.com",
                     "fonts.gstatic.com"):
            assert host not in app, f"CDN host {host} leaked into the bundle"
        assert 'type="text/babel"' not in app  # no in-browser Babel survives
        # no network URLs at all beyond the inert SVG namespace (w3.org)
        external = [u for u in re.findall(r"https?://[^\s'\"()]+", app)
                    if "www.w3.org" not in u]
        assert not external, f"unexpected external URL(s) in bundle: {external[:3]}"

    def test_shell_and_fonts_reference_only_local_assets(self):
        shell = (_ROOT / "templates" / "v3.html").read_text(encoding="utf-8")
        for host in ("unpkg", "jsdelivr", "googleapis", "gstatic", "cdn."):
            assert host not in shell, f"{host} leaked into templates/v3.html"
        fonts = (_VENDOR / "fonts" / "fonts.css").read_text(encoding="utf-8")
        assert "/static/vendor/fonts/" in fonts
        for host in ("googleapis", "gstatic", "http"):
            assert host not in fonts, f"fonts.css references remote {host}"


class TestV3TemplateContract:
    def _render(self, v3=None) -> str:
        env = Environment(loader=FileSystemLoader(str(_ROOT / "templates")))
        return env.get_template("v3.html").render(
            project_name_="TEST ENGINE",
            project_short_name="TE",
            project_version_="v9.9",
            active_account_id=7,
            v3=(_manifest() if v3 is None else v3),
        )

    def test_renders_bundle_deps_and_bootstrap(self):
        html = self._render()
        m = _manifest()
        assert f"/static/v3/{m['app']}" in html
        assert f"/static/v3/{m['tokens']}" in html
        assert "/static/vendor/react.production.min.js" in html
        assert "/static/vendor/echarts.min.js" in html
        assert "/static/vendor/gridstack-all.js" in html
        assert "window.QE_BOOTSTRAP" in html
        assert '"TE"' in html          # projectShortName via tojson
        assert "7" in html             # activeAccountId via tojson
        assert "v3 bundle not built" not in html

    def test_missing_build_shows_error_not_500(self):
        # empty manifest → {% if v3.app %} is false → loud in-page error, no crash
        html = self._render(v3={})
        assert "v3 bundle not built" in html
        assert "/static/v3/" not in html          # no asset tags emitted
        assert "/static/vendor/" not in html


class TestV3RouteWiring:
    def test_v3_route_registered(self):
        from api.router import router
        paths = {getattr(r, "path", None) for r in router.routes}
        assert "/v3" in paths

    def test_load_manifest_returns_dict(self):
        from api.routes_v3 import _load_manifest
        m = _load_manifest()
        assert isinstance(m, dict) and m.get("app")

    def test_load_manifest_soft_fails_on_missing(self, tmp_path, monkeypatch):
        import api.routes_v3 as v3
        monkeypatch.setattr(v3, "_MANIFEST_PATH", str(tmp_path / "nope.json"))
        assert v3._load_manifest() == {}
