"""P0 spike, ASSUMPTION A: the template graph is derivable from Django's own parser.

Compares A1 (parsed nodelist walk) and A2 (lexer token walk) against the fixture app, and
pins the two properties that decided the verdict: A2 needs no engine and no importable tag
libraries, and it walks an app's include closure without traversing templates the app does
not own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.spike_walkers import (
    analyze_a1,
    analyze_a2_path,
    extends_default_fallback,
    include_closure_a2,
)

FIXTURE_TEMPLATES = Path(__file__).parent / "testapp" / "templates"


def _a2(name: str):
    return analyze_a2_path(FIXTURE_TEMPLATES / name, name)


def _both(name: str):
    return {"A1": analyze_a1(name), "A2": _a2(name)}


# --------------------------------------------------------------- the happy path


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_page_graph(approach):
    """Both approaches must agree on the entry template's edges."""
    node = _both("testapp/page.html")[approach]
    assert node.extends == "base.html"
    assert node.includes == [
        "testapp/components/tile.html",
        "testapp/inc/modal.html",
    ]
    assert node.css_deps == ["testapp/htmx/fragment.html"]
    assert node.has_scope_tag is True
    assert node.dynamic_includes == []


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_tile_partial_has_scope_tag(approach):
    node = _both("testapp/components/tile.html")[approach]
    assert node.has_scope_tag is True
    assert node.extends is None
    assert node.includes == []


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_untagged_partials_have_no_scope(approach):
    for name in ("testapp/inc/modal.html", "testapp/htmx/fragment.html"):
        assert _both(name)[approach].has_scope_tag is False


# ------------------------------------------------------------- the extends chain


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_extends_chain_terminates(approach):
    """page.html -> base.html -> base_django.html -> (none), with no cycle.

    SPEC DEVIATION: the fixture's ``base.html`` says
    ``{% extends root_template|default:"base_django.html" %}`` -- a *dynamic* extends, which
    ARCHITECTURE.md's "ExtendsNode parent (literal)" rule cannot resolve. Both approaches
    report it as dynamic; the chain is only completed by reading the ``default`` filter's
    literal argument (or by falling back to SCOPED_CSS["ROOT_PARENT"]).
    """
    chain = []
    name = "testapp/page.html"
    seen = set()
    while name and name not in seen:
        seen.add(name)
        chain.append(name)
        node = _both(name)[approach]
        parent = node.extends
        if parent is None and node.extends_dynamic:
            parent = extends_default_fallback(node.extends_dynamic)
        name = parent

    assert chain == ["testapp/page.html", "base.html", "base_django.html"]
    assert _both("base.html")[approach].extends is None
    assert _both("base.html")[approach].extends_dynamic is not None
    assert _both("base_django.html")[approach].extends is None


# ----------------------------------------------------------- dynamic + commented


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_dynamic_include_is_flagged_not_swallowed(approach):
    node = _both("testapp/spike/dynamic.html")[approach]
    assert node.includes == ["testapp/inc/modal.html"]
    assert len(node.dynamic_includes) == 1
    assert "some_var" in node.dynamic_includes[0]


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_comment_and_verbatim_spans_are_skipped(approach):
    """An include inside {% comment %} or {% verbatim %} is not a real edge."""
    node = _both("testapp/spike/commented.html")[approach]
    assert node.includes == ["testapp/components/tile.html"]
    assert node.dynamic_includes == []


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_relative_include_path_is_resolved(approach):
    """``{% include "./dynamic.html" %}`` must resolve to the app-relative name."""
    node = _both("testapp/spike/relative.html")[approach]
    assert node.includes == ["testapp/spike/dynamic.html"]


@pytest.mark.parametrize("approach", ["A1", "A2"])
def test_include_options_do_not_break_target_detection(approach):
    for name in ("testapp/spike/page_only.html", "testapp/spike/page_with.html"):
        node = _both(name)[approach]
        assert node.includes == ["testapp/components/tile.html"], name
        assert node.has_scope_tag is True, name


# ------------------------------------------------------------ A1 vs A2 agreement


def test_a1_and_a2_agree_on_every_fixture_template():
    for path in sorted(FIXTURE_TEMPLATES.rglob("*.html")):
        if "/broken/" in path.as_posix():  # deliberately unparseable, see below
            continue
        name = path.relative_to(FIXTURE_TEMPLATES).as_posix()
        a1, a2 = analyze_a1(name), analyze_a2_path(path, name)
        assert (a1.extends, a1.includes, a1.css_deps, a1.has_scope_tag) == (
            a2.extends,
            a2.includes,
            a2.css_deps,
            a2.has_scope_tag,
        ), name
        assert len(a1.dynamic_includes) == len(a2.dynamic_includes), name


# ---------------------------------------------------- divergence: broken templates


def test_a1_raises_and_a2_degrades_on_an_unparseable_template():
    """{% comment %} does NOT nest in Django, so the fixture in broken/ is a syntax error.

    A1 propagates TemplateSyntaxError (the build must catch it per template); A2 still returns
    edges, and matches Django's comment semantics -- the first {% endcomment %} closes the span.
    """
    from django.template import TemplateSyntaxError

    name = "testapp/spike/broken/nested_comment.html"
    with pytest.raises(TemplateSyntaxError):
        analyze_a1(name)

    node = _a2(name)
    assert node.includes == ["testapp/htmx/fragment.html"]


# ------------------------------------------- why A2 won: no engine, no tag libraries

#: What a Nautobot app's page template looks like to the walkers: it `{% load %}`s a tag
#: library that only exists inside the host, so A1 cannot parse it without booting the host.
HOST_LIBRARY_TEMPLATE = """{% extends "generic/object_retrieve.html" %}
{% load helpers %}
{% load scoped_css %}

{% block content %}
<div class="row" {% css_scope %}>
  {% include "example_app/inc/add_widget_modal.html" %}
  {% include "example_app/components/widget_tile.html" with widget=object only %}
</div>
{% endblock %}
"""


def test_a1_cannot_run_when_a_loaded_tag_library_is_unavailable(tmp_path):
    """A1 needs every {% load %}ed library importable, transitively through {% extends %}.

    Point a real Engine straight at the template -- the file is found, and parsing still fails
    on ``{% load helpers %}``, a library the host app would provide and this process does not.
    A2 reads the same file with no engine at all.
    """
    from django.template import Engine, TemplateSyntaxError
    from django.template.backends.django import get_installed_libraries

    path = tmp_path / "example_app" / "widget_retrieve.html"
    path.parent.mkdir(parents=True)
    path.write_text(HOST_LIBRARY_TEMPLATE, encoding="utf-8")

    # Every tag library the *current* project provides is available; `helpers` still is not.
    engine = Engine(dirs=[str(tmp_path)], libraries=get_installed_libraries())
    with pytest.raises(TemplateSyntaxError) as excinfo:
        engine.get_template("example_app/widget_retrieve.html")
    assert "helpers" in str(excinfo.value)

    node = analyze_a2_path(path, "example_app/widget_retrieve.html")
    assert node.extends == "generic/object_retrieve.html"
    assert node.includes == [
        "example_app/inc/add_widget_modal.html",
        "example_app/components/widget_tile.html",
    ]
    assert node.has_scope_tag is True


# ------------------------------------------------------ closure over the fixture app


def test_a2_include_closure_stops_at_templates_the_app_does_not_own():
    """The closure scans what the app ships and records the rest as edges.

    ``resolve`` models discovery: a template under the app's own ``templates/`` dir is read,
    anything else (a host base template, another app's partial) is an edge and is never
    traversed. The fixture's ``base.html`` stands in for that host parent.
    """

    def resolve(name: str) -> Path | None:
        if not name.startswith("testapp/"):
            return None  # outside the app's own templates/ dir
        candidate = FIXTURE_TEMPLATES / name
        return candidate if candidate.is_file() else None

    nodes, unresolved = include_closure_a2("testapp/page.html", resolve)

    assert sorted(nodes) == [
        "testapp/components/tile.html",
        "testapp/htmx/fragment.html",  # reached only via {% css_dep %}
        "testapp/inc/modal.html",
        "testapp/page.html",
    ]
    assert unresolved == ["base.html"]
    assert nodes["testapp/page.html"].has_scope_tag is True
    # Nothing in the closure is a dynamic include: every edge was resolvable statically.
    assert [n for n in nodes.values() if n.dynamic_includes] == []
