"""P0 spike, ASSUMPTION B: an argument-free {% css_scope %} can learn its own template.

ARCHITECTURE.md claims ``context.render_context.template`` is the currently rendering template.
That is TRUE for ``{% include %}`` (every variant) but FALSE inside ``{% block %}`` of a
template that uses ``{% extends %}``: ``ExtendsNode.render`` calls
``render_context.push_state(compiled_parent)``, so while the leaf's block body runs, the
render_context template is the ROOT of the extends chain.

These tests pin both behaviours, and prove the mechanism that is correct everywhere:
``Node.origin`` -- set at parse time by ``Parser.extend_nodelist`` on every node.
"""

from __future__ import annotations

import pytest
from django.template import Context, Engine
from django.template.loader import render_to_string
from django.test import RequestFactory

from scoped_css.templatetags.scoped_css import CSSScopeNode


@pytest.fixture
def records(monkeypatch):
    """Replace CSSScopeNode.render with a recorder; returns the list it fills."""
    collected: list[dict] = []

    def fake_render(self, context):
        collected.append(
            {
                "render_context_template": context.render_context.template.name,
                "context_template": context.template.name,
                "node_origin_template_name": self.origin.template_name,
                "node_origin_name": self.origin.name,
                "rc_origin_name": context.render_context.template.origin.name,
            }
        )
        return ""

    monkeypatch.setattr(CSSScopeNode, "render", fake_render)
    return collected


@pytest.fixture
def request_obj():
    return RequestFactory().get("/")


def _rc(records):
    return [r["render_context_template"] for r in records]


def _origin(records):
    return [r["node_origin_template_name"] for r in records]


# ------------------------------------------- the claim holds for {% include %} ...


def test_render_context_template_tracks_the_included_template(records, request_obj):
    """Inside {% include %}, render_context.template IS the included template (claim holds).

    page.html loops the tile include three times.
    """
    render_to_string("testapp/page.html", request=request_obj)
    assert _rc(records)[1:] == ["testapp/components/tile.html"] * 3


def test_context_template_is_the_entry_for_the_whole_render(records, request_obj):
    """context.template.name is the top-level entry everywhere -- the manifest key."""
    render_to_string("testapp/page.html", request=request_obj)
    assert len(records) == 4
    assert {r["context_template"] for r in records} == {"testapp/page.html"}


# ------------------------------------ ... and BREAKS inside {% extends %} + block


def test_render_context_template_is_wrong_inside_an_extended_block(records, request_obj):
    """SPEC DEVIATION, load-bearing.

    The {% css_scope %} written in page.html's {% block content %} reports
    ``base_django.html`` -- the root of the extends chain -- not ``testapp/page.html``.
    Using render_context.template would scope every page's own CSS under the *host root
    template's* attribute, collapsing all pages into one scope.
    """
    render_to_string("testapp/page.html", request=request_obj)
    assert records[0]["render_context_template"] == "base_django.html"
    assert records[0]["render_context_template"] != "testapp/page.html"
    # ... and this is exactly the interim placement ARCHITECTURE.md prescribes
    # ("the author places {% css_scope %} on the outermost element of {% block content %}").


def test_node_origin_is_correct_in_every_position(records, request_obj):
    """``self.origin.template_name`` -- the template the tag is literally written in."""
    render_to_string("testapp/page.html", request=request_obj)
    assert _origin(records) == [
        "testapp/page.html",
        "testapp/components/tile.html",
        "testapp/components/tile.html",
        "testapp/components/tile.html",
    ]


# ------------------------------------------------------------ {% include %} variants


def test_include_with_only(records, request_obj):
    """``only`` renders via ``context.new()``; render_context is shared by the shallow copy."""
    render_to_string("testapp/spike/page_only.html", request=request_obj)
    assert _rc(records) == ["testapp/spike/page_only.html", "testapp/components/tile.html"]
    assert _origin(records) == _rc(records)
    assert {r["context_template"] for r in records} == {"testapp/spike/page_only.html"}


def test_include_with_extra_context(records, request_obj):
    """``with x=1`` renders via ``context.push()`` -- same answer."""
    render_to_string("testapp/spike/page_with.html", request=request_obj)
    assert _rc(records) == ["testapp/spike/page_with.html", "testapp/components/tile.html"]
    assert _origin(records) == _rc(records)
    assert {r["context_template"] for r in records} == {"testapp/spike/page_with.html"}


def test_only_and_with_agree_with_the_plain_include(records, request_obj):
    render_to_string("testapp/spike/page_only.html", request=request_obj)
    render_to_string("testapp/spike/page_with.html", request=request_obj)
    assert [r for r in _origin(records) if "tile" in r] == ["testapp/components/tile.html"] * 2


def test_no_request_behaves_identically(records):
    """Not RequestContext-specific: no request, no context processors, same answers."""
    render_to_string("testapp/page.html")
    assert _origin(records)[0] == "testapp/page.html"
    assert _rc(records)[0] == "base_django.html"


# ------------------------------------------------------------------ origin details


def test_origin_name_is_an_absolute_path_for_app_discovery(records, request_obj):
    """discovery maps origin.name (absolute path) -> owning app; template_name is the key."""
    render_to_string("testapp/page.html", request=request_obj)
    page, tile = records[0], records[1]

    assert page["node_origin_name"].startswith("/")
    assert page["node_origin_name"].endswith("/tests/testapp/templates/testapp/page.html")
    assert page["node_origin_template_name"] == "testapp/page.html"
    assert tile["node_origin_name"].endswith("/tests/testapp/templates/testapp/components/tile.html")

    # render_context's origin points at the wrong file for the same tag.
    assert page["rc_origin_name"].endswith("/tests/testapp/templates/base_django.html")


def test_origin_is_degenerate_for_string_templates(monkeypatch):
    """A Template built from a string has no template_name -- {% css_scope %} must not raise."""
    seen: list[tuple] = []
    monkeypatch.setattr(
        CSSScopeNode,
        "render",
        lambda self, context: seen.append((self.origin.template_name, self.origin.name)) or "",
    )
    engine = Engine.get_default()
    engine.from_string("{% load scoped_css %}<i {% css_scope %}></i>").render(Context({}))

    assert len(seen) == 1
    template_name, name = seen[0]
    assert template_name is None
    assert name == "<unknown source>"


def test_scope_tag_never_needs_the_context(records, request_obj):
    """self.origin is fixed at parse time, so the tag can answer with no context at all."""
    render_to_string("testapp/page.html", request=request_obj)
    assert all(r["node_origin_template_name"] for r in records)
