"""Build verification for ``examples/example_app`` — WITHOUT Nautobot installed.

The example app is a real Nautobot app: importing it needs ``nautobot.apps``, which this library
does not depend on and CI does not install. It is never imported here. Instead these tests lean on
the property P0 proved and the whole build is designed around (ARCHITECTURE.md § Spike findings 1):
**the graph is a lexer walk over raw template source**, so it needs no engine, no tag libraries and
no app registry. A ``SimpleNamespace`` with a ``label`` and a ``path`` is all ``discovery`` and
``bundler`` ever ask of an ``AppConfig``, so the example app's real templates and real stylesheets
can be scanned, graphed and bundled exactly as a deployment would — from this repository's own
test suite, in one second, with nothing installed.

That is also the honest test of the claim: if this passes, ``nautobot-server compile_css --app
example_app`` produces the same bundles.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scoped_css import bundler, discovery, graph

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "example_app"

pytestmark = pytest.mark.skipif(not EXAMPLES.is_dir(), reason="examples/example_app is not present")

LIST_ENTRY = "example_app/widget_list.html"
RETRIEVE_ENTRY = "example_app/widget_retrieve.html"
PANEL_ENTRY = "example_app/panels/device_widgets.html"

RETRIEVE_ATTR = "data-css-example_app-widget_retrieve"
PANEL_ATTR = "data-css-example_app-panels-device_widgets"


@pytest.fixture
def example_app(tmp_path, scoped_css_settings, _clear_caches):
    """A stand-in AppConfig pointed at examples/example_app, building into this test's tmp_path."""
    scoped_css_settings(OUTPUT_DIR=str(tmp_path / "out"))
    return SimpleNamespace(label="example_app", path=str(EXAMPLES))


@pytest.fixture
def scanned(example_app):
    return discovery.scan(example_app)


def build(scanned, entry: str) -> tuple[graph.EntryGraph, str]:
    """Graph and bundle one entry; return the graph and the bundle's text."""
    entry_graph = graph.build_entry_graph(scanned, entry)
    record = bundler.build_entry(scanned, entry_graph)
    assert record is not None, f"{entry} produced no bundle"
    assert record.path is not None and record.path.is_file()
    return entry_graph, record.path.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------ entries


def test_the_example_app_has_exactly_three_entries(scanned):
    """Two pages ({% extends %}) and one self-declaring panel — and nothing else."""
    assert scanned.entries == [PANEL_ENTRY, LIST_ENTRY, RETRIEVE_ENTRY]


def test_the_panel_is_an_entry_because_it_names_itself(scanned):
    """It extends nothing; `{% scoped_css_links "<itself>" %}` is what makes it an entry."""
    node = graph.analyze_template(PANEL_ENTRY, scanned)
    assert node.has_extends is False
    assert node.declares_self_entry is True
    assert node.link_targets == [PANEL_ENTRY]


def test_the_partials_are_not_entries(scanned):
    for partial in (
        "example_app/components/widget_tile.html",
        "example_app/inc/add_widget_modal.html",
        "example_app/htmx/widget_table.html",
    ):
        assert partial not in scanned.entries


def test_the_core_parents_are_edges_never_sources(scanned):
    """`generic/object_list.html` lives in Nautobot, not here: recorded, never scanned."""
    list_graph = graph.build_entry_graph(scanned, LIST_ENTRY)
    retrieve_graph = graph.build_entry_graph(scanned, RETRIEVE_ENTRY)
    assert list_graph.external == ["generic/object_list.html"]
    assert retrieve_graph.external == ["generic/object_retrieve.html"]
    assert all("generic/" not in name for name, _s, _k in retrieve_graph.ordered_sources)


# ------------------------------------------------------------------------ hygiene


def test_no_dynamic_includes_anywhere_in_the_app(scanned):
    """Every {% include %} target is a literal, so the graph sees the whole app. No W002."""
    for name in scanned.templates:
        node = graph.analyze_template(name, scanned)
        assert node.dynamic_includes == 0, f"{name}: {node.dynamic_expressions}"


def test_every_stylesheet_is_reachable_from_an_entry(scanned):
    """No W003 orphans: each of the seven colocated files lands in at least one bundle."""
    reached: set[str] = set()
    for entry in scanned.entries:
        entry_graph = graph.build_entry_graph(scanned, entry)
        for name, _scope, _kind in entry_graph.ordered_sources:
            reached.update(str(p) for p in scanned.templates[name].stylesheets)

    owned = {str(p) for ref in scanned.templates.values() for p in ref.stylesheets}
    assert owned - reached == set()
    assert discovery.orphan_stylesheets(scanned) == []
    assert len(owned) == 7


# --------------------------------------------------------------- the retrieve bundle


def test_the_tile_compiles_under_the_page_attribute_in_descendant_form_only(scanned):
    """No {% css_scope %} in widget_tile.html, so it inherits the page's scope — the default.

    And because a page's scope root is the content wrapper (core's <main> after the core change),
    which never carries this app's classes, the self-match form is skipped.
    """
    entry_graph, css = build(scanned, RETRIEVE_ENTRY)

    assert ("example_app/components/widget_tile.html", RETRIEVE_ATTR, graph.KIND_PAGE) in entry_graph.ordered_sources
    assert f"/* source: example_app/components/widget_tile.module.css [scope: {RETRIEVE_ATTR}] */" in css
    assert f"[{RETRIEVE_ATTR}] .widget-tile {{" in css
    assert f"[{RETRIEVE_ATTR}].widget-tile" not in css  # self-match: absent, on purpose
    # The tile's own attribute is never minted: it has no {% css_scope %}.
    assert "data-css-example_app-components-widget_tile" not in css


def test_the_htmx_fragment_joins_the_page_through_css_dep(scanned):
    """It arrives by hx-get; only {% css_dep %} puts its stylesheet in this page's bundle."""
    entry_graph, css = build(scanned, RETRIEVE_ENTRY)

    node = entry_graph.nodes[RETRIEVE_ENTRY]
    assert node.css_deps == ["example_app/htmx/widget_table.html"]
    assert ("example_app/htmx/widget_table.html", RETRIEVE_ATTR, graph.KIND_PAGE) in entry_graph.ordered_sources
    assert f"[{RETRIEVE_ATTR}] .widget-table-empty" in css


def test_the_plain_css_companion_is_copied_in_verbatim(scanned):
    """widget_retrieve.css holds the popover rule Bootstrap moves outside the page scope."""
    _graph, css = build(scanned, RETRIEVE_ENTRY)
    assert "/* source: example_app/widget_retrieve.css */" in css
    assert ".popover-body .widget-preview-img {" in css  # unscoped, deliberately
    # ...while its .module.css sibling is scoped like everything else.
    assert f"[{RETRIEVE_ATTR}] .widget-card {{" in css


def test_the_modal_inherits_the_page_scope(scanned):
    _graph, css = build(scanned, RETRIEVE_ENTRY)
    assert f"[{RETRIEVE_ATTR}] .add-widget-modal {{" in css
    # The prefix anti-pattern is retired: no COMPILED selector carries one. (The file's header
    # comment still names `.acme-` — explaining what the attribute replaced is the point of it.)
    assert f"[{RETRIEVE_ATTR}] .acme-" not in css
    assert f"[{RETRIEVE_ATTR}].acme-" not in css


def test_the_theme_attribute_keeps_its_place_ahead_of_the_scope(scanned):
    """[data-bs-theme] is on <html>, above the scope root: the attribute goes AFTER it."""
    _graph, css = build(scanned, RETRIEVE_ENTRY)
    assert f'[data-bs-theme="dark"] [{RETRIEVE_ATTR}] .widget-card {{' in css


# ----------------------------------------------------------------- the panel bundle


def test_the_panel_compiles_under_its_own_attribute_with_self_match_forms(scanned):
    """It owns its scope root ({% css_scope %} on its <section>), so both forms are emitted."""
    entry_graph, css = build(scanned, PANEL_ENTRY)

    assert entry_graph.attr == PANEL_ATTR
    assert entry_graph.ordered_sources == [(PANEL_ENTRY, PANEL_ATTR, graph.KIND_ELEMENT)]
    # Both forms, on one prelude: the descendant form for markup inside the panel, the self-match
    # form for the scope root itself — which here IS `<div class="device-widgets">`.
    assert f"[{PANEL_ATTR}] .device-widgets, [{PANEL_ATTR}].device-widgets {{" in css
    # A leading type selector still gets the descendant form only.
    assert f"[{PANEL_ATTR}] li.device-widgets-item + li.device-widgets-item {{" in css
    assert f"[{PANEL_ATTR}]li." not in css
    # The theme attribute lives above the scope root, so the attribute goes after that compound.
    assert f'[data-bs-theme="dark"] [{PANEL_ATTR}] .device-widgets {{' in css


def test_the_panel_boxes_in_its_bare_bootstrap_override(scanned):
    """`.list-group-item { background: transparent }` — the rule that used to leak deployment-wide."""
    _graph, css = build(scanned, PANEL_ENTRY)
    assert f"[{PANEL_ATTR}] .list-group-item, [{PANEL_ATTR}].list-group-item {{" in css
    # No page's attribute appears in the panel's bundle: it belongs to no page of ours.
    assert RETRIEVE_ATTR not in css


def test_the_panel_bundle_is_independent_of_the_pages(scanned):
    """It is a separate entry, so it is a separate bundle with a separate <link>."""
    _retrieve_graph, retrieve_css = build(scanned, RETRIEVE_ENTRY)
    _panel_graph, panel_css = build(scanned, PANEL_ENTRY)
    assert PANEL_ATTR not in retrieve_css
    assert ".device-widgets-title" not in retrieve_css
    assert ".widget-tile" not in panel_css


# ------------------------------------------------------------------- the list bundle


def test_the_list_page_scopes_its_bare_framework_resets(scanned):
    """`.card { border: none }` is the motivating bug; page-scoped it reaches this page only."""
    entry_graph, css = build(scanned, LIST_ENTRY)
    attr = "data-css-example_app-widget_list"
    assert entry_graph.attr == attr
    assert f"[{attr}] .card {{" in css
    assert f"[{attr}] .table-responsive {{" in css
    # @keyframes selectors are never rewritten.
    assert "@keyframes widget-list-fade-in" in css
    assert f"[{attr}] 0%" not in css


def test_every_entry_builds_without_a_warning(scanned):
    """A clean app compiles clean: no W002, no compiler warnings, on any entry."""
    for entry in scanned.entries:
        entry_graph = graph.build_entry_graph(scanned, entry)
        record = bundler.build_entry(scanned, entry_graph)
        assert record is not None
        assert record.warnings == [], f"{entry}: {record.warnings}"
