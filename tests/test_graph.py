"""graph.py: the lexer token walk (P0 verdict A2) and scope resolution."""

from pathlib import Path

import pytest

from scoped_css import discovery, graph
from tests.spike_walkers import analyze_a1

FIXTURE_TEMPLATES = Path(__file__).parent / "testapp" / "templates"

PAGE_ATTR = "data-css-testapp-page"
TILE_ATTR = "data-css-testapp-components-tile"


@pytest.fixture
def app_templates(testapp):
    graph.clear_cache()
    return discovery.scan(testapp)


# ------------------------------------------------------------------ single template


def test_entry_template_edges(app_templates):
    node = graph.analyze_template("testapp/page.html", app_templates)
    assert node.extends == "base.html"
    # {% include %} and {% css_dep %} are the same kind of edge, in source order.
    assert node.includes == [
        "testapp/components/tile.html",
        "testapp/inc/modal.html",
        "testapp/htmx/fragment.html",
    ]
    assert node.css_deps == ["testapp/htmx/fragment.html"]
    assert node.has_scope_tag is True
    assert node.dynamic_includes == 0


def test_partials(app_templates):
    tile = graph.analyze_template("testapp/components/tile.html", app_templates)
    assert (tile.has_scope_tag, tile.extends, tile.includes) == (True, None, [])
    modal = graph.analyze_template("testapp/inc/modal.html", app_templates)
    assert modal.has_scope_tag is False


def test_analyze_template_without_app_templates_uses_the_loaders():
    """The build always passes an AppTemplates; the runtime may not have one."""
    node = graph.analyze_template("testapp/page.html")
    assert node.extends == "base.html"
    assert node.has_scope_tag is True


def test_comment_and_verbatim_spans_are_not_edges(app_templates):
    node = graph.analyze_template("testapp/spike/commented.html", app_templates)
    assert node.includes == ["testapp/components/tile.html"]


def test_comments_do_not_nest(app_templates):
    """Django's do_comment is skip_past("endcomment"): the FIRST endcomment closes the span."""
    node = graph.analyze_template("testapp/spike/broken/nested_comment.html", app_templates)
    assert node.includes == ["testapp/htmx/fragment.html"]


def test_relative_include_is_resolved(app_templates):
    node = graph.analyze_template("testapp/spike/relative.html", app_templates)
    assert node.includes == ["testapp/spike/dynamic.html"]


def test_include_options_do_not_hide_the_target(app_templates):
    for name in ("testapp/spike/page_only.html", "testapp/spike/page_with.html"):
        node = graph.analyze_template(name, app_templates)
        assert node.includes == ["testapp/components/tile.html"], name


def test_dynamic_includes_are_counted_and_kept(app_templates):
    node = graph.analyze_template("testapp/spike/dynamic.html", app_templates)
    assert node.includes == ["testapp/inc/modal.html"]
    assert node.dynamic_includes == 1
    assert node.dynamic_expressions == ["some_var"]


def test_a_missing_template_analyzes_to_an_empty_node():
    node = graph.analyze_template("no/such/template.html")
    assert (node.includes, node.extends, node.has_scope_tag) == ([], None, False)


# ------------------------------------------------------------------- extends chain


def test_extends_default_filter_fallback(app_templates):
    """base.html is `{% extends root_template|default:"base_django.html" %}` (P0 finding 3)."""
    node = graph.analyze_template("base.html", app_templates)
    assert node.extends is None
    assert node.extends_dynamic is not None
    assert node.has_extends is True
    assert graph.resolve_extends(node) == "base_django.html"


def test_extends_falls_back_to_root_parent(settings):
    settings.SCOPED_CSS = {"ROOT_PARENT": "custom_root.html"}
    node = graph.Node(name="x.html", extends_dynamic="some_var")
    assert graph.resolve_extends(node) == "custom_root.html"


def test_extends_chain_terminates(app_templates):
    chain, name, seen = [], "testapp/page.html", set()
    while name and name not in seen:
        seen.add(name)
        chain.append(name)
        name = graph.resolve_extends(graph.analyze_template(name, app_templates))
    assert chain == ["testapp/page.html", "base.html", "base_django.html"]


# ------------------------------------------------------- cross-check against A1


def test_lexer_walk_agrees_with_the_nodelist_walk_on_every_fixture_template():
    """P0 kept the rejected nodelist walk as a drift detector; this is that check."""
    for path in sorted(FIXTURE_TEMPLATES.rglob("*.html")):
        if "/broken/" in path.as_posix():  # deliberately unparseable for A1
            continue
        name = path.relative_to(FIXTURE_TEMPLATES).as_posix()
        a1, node = analyze_a1(name), graph.analyze_path(path, name)
        assert (a1.extends, a1.has_scope_tag) == (node.extends, node.has_scope_tag), name
        assert a1.includes + a1.css_deps == node.includes, name
        assert len(a1.dynamic_includes) == node.dynamic_includes, name


# ------------------------------------------------------------------- entry graphs


def test_entry_graph_scopes_and_dfs_order(app_templates):
    entry_graph = graph.build_entry_graph(app_templates, "testapp/page.html")

    assert entry_graph.attr == PAGE_ATTR
    assert entry_graph.ordered_sources == [
        # In-app {% extends %} parents are sources too, outermost first, so the child can override
        # them. Neither fixture host owns a stylesheet, so neither contributes bytes here.
        ("base_django.html", PAGE_ATTR, "page"),
        ("base.html", PAGE_ATTR, "page"),
        # The entry is its own scope root and follows its parents.
        ("testapp/page.html", PAGE_ATTR, "page"),
        # tile.html carries {% css_scope %}: it compiles under its OWN attribute.
        ("testapp/components/tile.html", TILE_ATTR, "element"),
        # modal.html has no tag: it inherits its includer's scope, which is the page.
        ("testapp/inc/modal.html", PAGE_ATTR, "page"),
        # reached through {% css_dep %} -- an edge exactly like an include.
        ("testapp/htmx/fragment.html", PAGE_ATTR, "page"),
    ]
    assert entry_graph.warnings == []
    assert entry_graph.external == []
    assert set(entry_graph.nodes) == {name for name, _scope, _kind in entry_graph.ordered_sources}


def test_an_in_app_extends_parent_is_a_source_before_its_child(app_templates):
    """GAP 1: page2.html extends testapp/base_app.html, which lives in the same app."""
    entry_graph = graph.build_entry_graph(app_templates, "testapp/page2.html")
    assert entry_graph.ordered_sources == [
        ("base_django.html", "data-css-testapp-page2", "page"),
        ("base.html", "data-css-testapp-page2", "page"),
        # The in-app parent, under the CHILD's page scope...
        ("testapp/base_app.html", "data-css-testapp-page2", "page"),
        # ...and the parent's own includes come with it.
        ("testapp/inc/modal.html", "data-css-testapp-page2", "page"),
        # The child is last, so its rules win ties against the base it extends.
        ("testapp/page2.html", "data-css-testapp-page2", "page"),
    ]


def test_an_extends_parent_outside_the_app_stays_an_edge(app_templates):
    """A Nautobot-core parent (generic/object_list.html) is recorded, never scanned or bundled."""
    del app_templates.templates["base.html"]
    entry_graph = graph.build_entry_graph(app_templates, "testapp/page.html")
    assert entry_graph.external == ["base.html"]
    assert "base.html" not in entry_graph.nodes
    assert [name for name, _s, _k in entry_graph.ordered_sources][0] == "testapp/page.html"


def test_a_template_that_is_only_ever_extended_is_still_an_entry(app_templates):
    """base_app.html contains {% extends %}, so it is an entry and gets a bundle of its own.

    Accepted, not a bug: it costs one extra bundle nobody links, and keeps entry detection to a
    single rule. See ARCHITECTURE.md § Vocabulary.
    """
    assert "testapp/base_app.html" in app_templates.entries
    entry_graph = graph.build_entry_graph(app_templates, "testapp/base_app.html")
    assert entry_graph.attr == "data-css-testapp-base_app"


def test_a_partial_reached_under_two_scopes_is_recorded_twice(app_templates, monkeypatch):
    """A partial reached from includers with different scopes compiles once per distinct scope."""
    nodes = {
        "testapp/page.html": graph.Node(
            "testapp/page.html",
            includes=["testapp/components/tile.html", "testapp/inc/modal.html"],
            has_scope_tag=True,
        ),
        # The tagged partial now includes modal.html too, so modal is reached under both scopes.
        "testapp/components/tile.html": graph.Node(
            "testapp/components/tile.html",
            includes=["testapp/inc/modal.html"],
            has_scope_tag=True,
        ),
        "testapp/inc/modal.html": graph.Node("testapp/inc/modal.html"),
    }
    monkeypatch.setattr(graph, "analyze_path", lambda path, name: nodes[name])

    entry_graph = graph.build_entry_graph(app_templates, "testapp/page.html")
    assert entry_graph.ordered_sources == [
        ("testapp/page.html", PAGE_ATTR, "page"),
        ("testapp/components/tile.html", TILE_ATTR, "element"),
        # Below the tagged partial the scope is inherited from it, not from the page.
        ("testapp/inc/modal.html", TILE_ATTR, "element"),
        ("testapp/inc/modal.html", PAGE_ATTR, "page"),
    ]


def test_a_template_is_visited_once_per_distinct_scope(app_templates):
    """Dedupe is by (template, scope): three includes of one tile are one source."""
    entry_graph = graph.build_entry_graph(app_templates, "testapp/page.html")
    names = [name for name, _scope, _kind in entry_graph.ordered_sources]
    assert names.count("testapp/components/tile.html") == 1


def test_templates_outside_the_app_are_edges_not_sources(app_templates):
    """A Nautobot-core template is recorded and never scanned (P0: generic/object_retrieve.html)."""
    del app_templates.templates["testapp/inc/modal.html"]
    entry_graph = graph.build_entry_graph(app_templates, "testapp/page.html")
    assert entry_graph.external == ["testapp/inc/modal.html"]
    assert "testapp/inc/modal.html" not in entry_graph.nodes
    assert all(name != "testapp/inc/modal.html" for name, _s, _k in entry_graph.ordered_sources)


def test_dynamic_include_raises_a_w002_warning(settings, testapp):
    settings.SCOPED_CSS = {"ENTRIES": {"testapp": ["testapp/spike/dynamic.html"]}}
    app_templates = discovery.scan(testapp)
    assert "testapp/spike/dynamic.html" in app_templates.entries

    entry_graph = graph.build_entry_graph(app_templates, "testapp/spike/dynamic.html")
    assert len(entry_graph.warnings) == 1
    warning = entry_graph.warnings[0]
    assert warning.startswith("scoped_css.W002")
    assert "testapp/spike/dynamic.html" in warning
    assert "some_var" in warning  # the raw expression is never silently dropped
    assert "css_dep" in warning
    # The literal include next to it is still followed.
    assert ("testapp/inc/modal.html", "data-css-testapp-spike-dynamic", "page") in entry_graph.ordered_sources


def test_an_entry_without_a_scope_tag_still_owns_the_page_scope(app_templates):
    """scope(entry) = attr(entry) whether or not the entry writes {% css_scope %}."""
    entry_graph = graph.build_entry_graph(app_templates, "testapp/spike/page_only.html")
    assert entry_graph.ordered_sources[0] == (
        "testapp/spike/page_only.html",
        "data-css-testapp-spike-page_only",
        "page",
    )


# ----------------------------------------------------- self-declaring entries (Part A.2)
#
# A template containing {% scoped_css_links "<its own name>" %} declares itself an entry: a
# self-contained styled unit that delivers its own <link>. This is what a Nautobot
# TemplateExtension panel needs — it renders inside a CORE view, so it cannot ride on any page's
# bundle. See graph.Node.is_entry.

SELF_ENTRY = "testapp/panels/self_entry.html"
SELF_ATTR = "data-css-testapp-panels-self_entry"


def test_a_template_naming_itself_in_scoped_css_links_is_an_entry(app_templates):
    node = graph.analyze_template(SELF_ENTRY, app_templates)
    assert node.link_targets == [SELF_ENTRY]
    assert node.declares_self_entry is True
    assert node.has_extends is False  # no {% extends %} anywhere in it
    assert node.is_entry is True


def test_argument_free_scoped_css_links_declares_nothing(app_templates):
    """base_django.html's host usage keys off context.template.name; it is not an entry."""
    node = graph.analyze_template("base_django.html", app_templates)
    assert node.link_targets == []
    assert node.declares_self_entry is False
    assert node.is_entry is False


def test_scoped_css_links_naming_another_template_is_not_a_self_declaration():
    node = graph.analyze_source(
        '{% load scoped_css %}{% scoped_css_links "testapp/other.html" %}',
        "testapp/panels/thing.html",
    )
    assert node.link_targets == ["testapp/other.html"]
    assert node.declares_self_entry is False
    assert node.is_entry is False


def test_a_dynamic_scoped_css_links_argument_is_not_a_self_declaration():
    node = graph.analyze_source("{% scoped_css_links some_var %}", "testapp/panels/thing.html")
    assert node.link_targets == []
    assert node.is_entry is False


def test_a_relative_self_link_resolves_like_do_include():
    """`"./self_entry.html"` is the same template as `testapp/panels/self_entry.html`."""
    node = graph.analyze_source('{% scoped_css_links "./self_entry.html" %}', SELF_ENTRY)
    assert node.link_targets == [SELF_ENTRY]
    assert node.declares_self_entry is True


def test_self_declaration_inside_a_comment_is_not_an_entry():
    """Entry detection is a lexer walk, so a commented-out tag declares nothing."""
    source = "{% comment %}{% scoped_css_links " + f'"{SELF_ENTRY}"' + "%}{% endcomment %}"
    assert graph.analyze_source(source, SELF_ENTRY).is_entry is False


def test_a_self_declaring_entry_compiles_at_element_scope(app_templates):
    """It owns its scope root ({% css_scope %} on its own element), so self-match forms are live.

    A page's scope root is core's <main>, which never carries the app's classes — hence "page".
    """
    entry_graph = graph.build_entry_graph(app_templates, SELF_ENTRY)
    assert entry_graph.attr == SELF_ATTR
    assert entry_graph.ordered_sources[0] == (SELF_ENTRY, SELF_ATTR, graph.KIND_ELEMENT)
    # Its include still resolves normally, and the tagged partial keeps its own attribute.
    assert ("testapp/components/tile.html", TILE_ATTR, graph.KIND_ELEMENT) in entry_graph.ordered_sources


def test_an_entry_declared_only_through_the_settings_stays_page_scoped(settings, testapp):
    """SCOPED_CSS["ENTRIES"] keeps working and is unaffected by the new rule."""
    settings.SCOPED_CSS = {"ENTRIES": {"testapp": ["testapp/htmx/fragment.html"]}}
    app_templates = discovery.scan(testapp)
    entry_graph = graph.build_entry_graph(app_templates, "testapp/htmx/fragment.html")
    assert entry_graph.ordered_sources[0][2] == graph.KIND_PAGE
