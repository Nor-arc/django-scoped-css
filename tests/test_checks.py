"""P3: the system checks — W001 missing bundle, W002 dynamic include, W003 orphan stylesheet."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scoped_css import checks, discovery, graph, manifest
from scoped_css.graph import KIND_ELEMENT, KIND_PAGE, EntryGraph, Node


def ref(name, *, css=None, module_css=None):
    return SimpleNamespace(name=name, css=css, module_css=module_css, stylesheets=[p for p in (css, module_css) if p])


def app_templates(templates, entries, *, label="testapp"):
    return SimpleNamespace(
        app=SimpleNamespace(label=label, path="/nonexistent/testapp"),
        templates_dir=Path("/nonexistent/testapp/templates"),
        output_dir=Path("/nonexistent/testapp/static/testapp/scoped_css"),
        templates=templates,
        entries=entries,
    )


@pytest.fixture
def wire(monkeypatch):
    """Install fake discovery/graph/manifest; returns a setup callable."""

    def setup(app_templates_obj, graphs, *, bundles=(), auto_compile=False, orphans=()):
        monkeypatch.setattr(discovery, "participating_apps", lambda: [app_templates_obj.app])
        monkeypatch.setattr(discovery, "scan", lambda app: app_templates_obj)
        monkeypatch.setattr(discovery, "orphan_stylesheets", lambda at: list(orphans))
        monkeypatch.setattr(graph, "build_entry_graph", lambda at, entry: graphs[entry])
        monkeypatch.setattr(manifest, "lookup", lambda entry: {"bundle": "x.css"} if entry in bundles else None)
        monkeypatch.setattr("scoped_css.conf.get", lambda key: auto_compile if key == "AUTO_COMPILE" else None)

    return setup


def ids(messages):
    return sorted(m.id for m in messages)


PAGE_CSS = Path("/nonexistent/testapp/templates/testapp/page.css")
TILE_CSS = Path("/nonexistent/testapp/templates/testapp/components/tile.module.css")


def page_setup(*, dynamic=0, extra_templates=None):
    templates = {
        "testapp/page.html": ref("testapp/page.html", css=PAGE_CSS),
        "testapp/components/tile.html": ref("testapp/components/tile.html", module_css=TILE_CSS),
    }
    templates.update(extra_templates or {})
    at = app_templates(templates, ["testapp/page.html"])
    entry_graph = EntryGraph(
        entry="testapp/page.html",
        nodes={
            "testapp/page.html": Node(name="testapp/page.html", dynamic_includes=dynamic),
            "testapp/components/tile.html": Node(name="testapp/components/tile.html"),
        },
        ordered_sources=[
            ("testapp/page.html", "data-css-testapp-page", KIND_PAGE),
            ("testapp/components/tile.html", "data-css-testapp-components-tile", KIND_ELEMENT),
        ],
        warnings=[],
    )
    return at, {"testapp/page.html": entry_graph}


# ------------------------------------------------------------------------------ W001


def test_w001_when_an_entry_with_css_has_no_bundle(wire):
    at, graphs = page_setup()
    wire(at, graphs, bundles=(), auto_compile=False)
    messages = checks.check_scoped_css(None)
    assert ids(messages) == ["scoped_css.W001"]
    assert "testapp/page.html" in messages[0].msg
    assert messages[0].obj == "testapp"


def test_no_w001_once_the_bundle_exists(wire):
    at, graphs = page_setup()
    wire(at, graphs, bundles=("testapp/page.html",))
    assert ids(checks.check_scoped_css(None)) == []


def test_no_w001_under_auto_compile(wire):
    """In dev the bundle is built on demand; a missing one is not a problem."""
    at, graphs = page_setup()
    wire(at, graphs, bundles=(), auto_compile=True)
    assert ids(checks.check_scoped_css(None)) == []


def test_no_w001_for_an_entry_with_no_stylesheets_anywhere(wire):
    at = app_templates({"testapp/bare.html": ref("testapp/bare.html")}, ["testapp/bare.html"])
    graphs = {
        "testapp/bare.html": EntryGraph(
            entry="testapp/bare.html",
            nodes={"testapp/bare.html": Node(name="testapp/bare.html")},
            ordered_sources=[("testapp/bare.html", "data-css-testapp-bare", KIND_PAGE)],
            warnings=[],
        )
    }
    wire(at, graphs)
    assert ids(checks.check_scoped_css(None)) == []


# ------------------------------------------------------------------------------ W002


def test_w002_for_a_dynamic_include(wire):
    at, graphs = page_setup(dynamic=2)
    wire(at, graphs, bundles=("testapp/page.html",))
    messages = checks.check_scoped_css(None)
    assert ids(messages) == ["scoped_css.W002"]
    assert "testapp/page.html" in messages[0].msg
    assert "2 occurrence" in messages[0].msg
    assert "css_dep" in messages[0].hint


def test_w002_is_reported_once_per_template(wire):
    """The same partial reached from two entries must not warn twice."""
    at, graphs = page_setup(dynamic=1)
    at.entries = ["testapp/page.html", "testapp/other.html"]
    graphs["testapp/other.html"] = graphs["testapp/page.html"]
    wire(at, graphs, bundles=("testapp/page.html", "testapp/other.html"))
    assert ids(checks.check_scoped_css(None)) == ["scoped_css.W002"]


# ------------------------------------------------------------------------------ W003


def test_w003_for_a_stylesheet_no_entry_can_reach(wire):
    stray = Path("/nonexistent/testapp/templates/testapp/htmx/fragment.module.css")
    at, graphs = page_setup(
        extra_templates={"testapp/htmx/fragment.html": ref("testapp/htmx/fragment.html", module_css=stray)}
    )
    wire(at, graphs, bundles=("testapp/page.html",))
    messages = checks.check_scoped_css(None)
    assert ids(messages) == ["scoped_css.W003"]
    assert "fragment.module.css" in messages[0].msg


def test_w003_for_a_stylesheet_with_no_template_beside_it(wire):
    at, graphs = page_setup()
    stray = Path("/nonexistent/testapp/templates/testapp/leftover.module.css")
    wire(at, graphs, bundles=("testapp/page.html",), orphans=[stray])
    messages = checks.check_scoped_css(None)
    assert ids(messages) == ["scoped_css.W003"]
    assert "leftover.module.css" in messages[0].msg


def test_no_w003_when_every_stylesheet_is_reachable(wire):
    at, graphs = page_setup()
    wire(at, graphs, bundles=("testapp/page.html",))
    assert ids(checks.check_scoped_css(None)) == []


# ------------------------------------------------------------------------ plumbing


def test_app_configs_filters_the_apps_checked(wire):
    at, graphs = page_setup()
    wire(at, graphs)
    other = SimpleNamespace(label="someoneelse")
    assert checks.check_scoped_css([other]) == []
    assert ids(checks.check_scoped_css([at.app])) == ["scoped_css.W001"]


def test_a_broken_app_does_not_abort_the_check(monkeypatch):
    monkeypatch.setattr(discovery, "participating_apps", lambda: [SimpleNamespace(label="boom")])

    def explode(app):
        raise RuntimeError("unreadable templates dir")

    monkeypatch.setattr(discovery, "scan", explode)
    assert checks.check_scoped_css(None) == []


def test_a_broken_entry_graph_does_not_abort_the_app(monkeypatch, wire):
    at, graphs = page_setup()
    wire(at, graphs)

    def explode(app_templates_obj, entry):
        raise RuntimeError("unparseable")

    monkeypatch.setattr(graph, "build_entry_graph", explode)
    # No W001 (the entry could not be analysed) but W003 for both now-unreachable stylesheets.
    assert ids(checks.check_scoped_css(None)) == ["scoped_css.W003", "scoped_css.W003"]


def test_check_is_registered_with_django(monkeypatch):
    from django.core.checks import registry

    assert checks.check_scoped_css in registry.registry.get_checks()


def test_the_real_fixture_app_checks_cleanly(settings):
    """No mocks: the real fixture app through real discovery/graph/manifest.

    AUTO_COMPILE is forced on because pytest-django sets ``DEBUG = False`` for tests, which would
    otherwise make this assert W001 or not depending on whether some earlier test happened to
    leave a built bundle on disk. Every fixture stylesheet is reachable — ``htmx/fragment.html``
    only by ``{% css_dep %}``, which is the whole point of that tag — so no W003 either.
    """
    settings.SCOPED_CSS = {"AUTO_COMPILE": True}
    assert ids(checks.check_scoped_css(None)) == []


def test_the_real_fixture_app_reports_w001_in_production_without_a_build(settings, tmp_path, monkeypatch):
    """Same app, AUTO_COMPILE off and no manifest: the entry with colocated css is flagged."""
    settings.SCOPED_CSS = {"AUTO_COMPILE": False}
    monkeypatch.setattr(manifest, "lookup", lambda entry: None)
    messages = checks.check_scoped_css(None)
    assert set(ids(messages)) == {"scoped_css.W001"}
    # One per entry whose closure owns a stylesheet; base.html owns none and is not flagged.
    flagged = sorted(m.msg.split("'")[1] for m in messages)
    assert flagged == [
        "testapp/base_app.html",
        "testapp/page.html",
        "testapp/page2.html",
        "testapp/page3.html",
        # A self-declaring entry ({% scoped_css_links "<itself>" %}) is an entry like any other.
        "testapp/panels/self_entry.html",
    ]
