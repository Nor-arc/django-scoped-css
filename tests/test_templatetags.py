"""P3: the three render-time tags.

The load-bearing test here is that ``{% css_scope %}`` reports the template it is *written in*
(``self.origin.template_name``), not ``context.render_context.template`` — which P0 proved is
``base_django.html`` inside a ``{% block %}`` under ``{% extends %}``, exactly where the interim
delivery places the tag. See tests/test_spike_render_context.py.
"""

from __future__ import annotations

import pytest
from django.template import Context, Engine
from django.template.base import Origin, Template
from django.template.loader import render_to_string
from django.test import RequestFactory

from scoped_css import discovery, manifest, naming
from scoped_css.templatetags import scoped_css as tags

PAGE_ATTR = "data-css-testapp-page"
TILE_ATTR = "data-css-testapp-components-tile"


@pytest.fixture
def request_obj():
    return RequestFactory().get("/")


@pytest.fixture(autouse=True)
def no_auto_compile(monkeypatch):
    """Keep {% scoped_css_links %} from shelling out to a real build in unrelated tests."""
    monkeypatch.setattr("scoped_css.dev.ensure_fresh", lambda entry: None)


def render_named(source: str, name: str, context: dict | None = None) -> str:
    """Render a string template that still answers to a loader-relative ``name``.

    Lets these tests exercise tags that key off ``context.template.name`` without adding fixture
    templates that would move the fixture app's entry list under P2's feet.
    """
    engine = Engine.get_default()
    origin = Origin(name=f"/nonexistent/{name}", template_name=name)
    template = Template(source, origin=origin, name=name, engine=engine)
    return template.render(Context(context or {}))


# ------------------------------------------------------------------ {% css_scope %}


def test_css_scope_stamps_the_entry_and_every_partial(request_obj):
    """The fixture page: one page attribute on .row, one element attribute per .col."""
    html = render_to_string("testapp/page.html", request=request_obj)

    assert f'<div class="row" {PAGE_ATTR}>' in html
    assert html.count(f'<div class="col" {TILE_ATTR}>') == 3


def test_css_scope_never_reports_the_root_of_the_extends_chain(request_obj):
    """The whole point: page.html extends base.html extends base_django.html."""
    html = render_to_string("testapp/page.html", request=request_obj)
    assert "base_django" not in html
    assert "data-css-testapp-base" not in html


def test_css_scope_is_lexical_inside_an_isolated_include(request_obj):
    """``{% include … only %}`` renders via context.new(); origin is unaffected."""
    html = render_to_string("testapp/spike/page_only.html", request=request_obj)
    assert "data-css-testapp-spike-page_only>" in html
    assert f'<div class="col" {TILE_ATTR}>' in html


def test_css_scope_is_lexical_inside_include_with_extra_context(request_obj):
    html = render_to_string("testapp/spike/page_with.html", request=request_obj)
    assert "data-css-testapp-spike-page_with>" in html
    assert f'<div class="col" {TILE_ATTR}>' in html


def test_css_scope_renders_nothing_for_a_string_template():
    """A Template built from a string has ``origin.template_name is None`` — emit nothing, not an error."""
    engine = Engine.get_default()
    out = engine.from_string("{% load scoped_css %}<i {% css_scope %}></i>").render(Context({}))
    assert out == "<i ></i>"


def test_css_scope_falls_back_to_the_first_path_segment(monkeypatch):
    """When discovery cannot place the origin, infer the app label rather than render empty."""
    monkeypatch.setattr(discovery, "template_ref_for_origin", lambda origin_name: None)
    out = render_named("{% load scoped_css %}<i {% css_scope %}></i>", "someapp/inc/thing.html")
    assert out == "<i data-css-someapp-inc-thing></i>"


def test_css_scope_prefers_discovery_over_the_fallback(monkeypatch, testapp):
    """A template whose path segment differs from the owning app label follows discovery."""
    ref = discovery.TemplateRef(app=testapp, name="testapp/components/tile.html", path="/x")
    monkeypatch.setattr(discovery, "template_ref_for_origin", lambda origin_name: ref)
    out = render_named("{% load scoped_css %}<i {% css_scope %}></i>", "vendored/thing.html")
    assert out == f"<i {TILE_ATTR}></i>"


def test_css_scope_renders_nothing_for_a_root_level_template(monkeypatch):
    """No path segment means no app label to infer."""
    monkeypatch.setattr(discovery, "template_ref_for_origin", lambda origin_name: None)
    assert render_named("{% load scoped_css %}<i {% css_scope %}></i>", "toplevel.html") == "<i ></i>"


@pytest.mark.parametrize("boom", ["discovery", "naming"])
def test_css_scope_never_raises(monkeypatch, boom, request_obj):
    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    if boom == "discovery":
        monkeypatch.setattr(discovery, "template_ref_for_origin", explode)
    else:
        monkeypatch.setattr(naming, "scope_attr", explode)

    html = render_to_string("testapp/page.html", request=request_obj)
    assert '<div class="row" >' in html or '<div class="row" data-css' in html


def test_css_scope_output_is_marked_safe(monkeypatch):
    """The attribute must not be autoescaped into &quot;-soup."""
    monkeypatch.setattr(naming, "scope_attr", lambda label, key: 'data-css-x"y')
    assert "&quot;" not in render_named("{% load scoped_css %}<i {% css_scope %}></i>", "a/b.html")


# ------------------------------------------------------------- {% css_scope_page %}


def test_css_scope_page_stamps_main_with_the_entry_attribute(request_obj):
    """base_django.html carries {% css_scope_page %} — mirrors the eventual Nautobot core change."""
    html = render_to_string("testapp/page.html", request=request_obj)
    assert f'<main class="container-fluid wrapper" id="main-content" {PAGE_ATTR}>' in html


def test_css_scope_page_uses_the_entry_not_the_template_it_sits_in(request_obj):
    """It is written in base_django.html but must report context.template.name."""
    html = render_to_string("testapp/spike/page_only.html", request=request_obj)
    assert 'id="main-content"' not in html  # page_only.html does not extend anything
    out = render_named("{% load scoped_css %}<main {% css_scope_page %}>", "testapp/page.html")
    assert out == f"<main {PAGE_ATTR}>"


def test_css_scope_page_is_empty_for_a_nameless_template():
    engine = Engine.get_default()
    assert engine.from_string("{% load scoped_css %}<main {% css_scope_page %}>").render(Context({})) == "<main >"


# ------------------------------------------------------------ {% scoped_css_links %}


SOURCE = "{% load scoped_css %}{% scoped_css_links %}"


def test_scoped_css_links_emits_one_link_from_the_manifest(monkeypatch):
    monkeypatch.setattr(manifest, "lookup", lambda name: {"bundle": "testapp/scoped_css/page.abc12345.css"})
    out = render_named(SOURCE, "testapp/page.html")
    assert out == '<link rel="stylesheet" href="/static/testapp/scoped_css/page.abc12345.css">'


def test_scoped_css_links_looks_up_by_the_entry_template_name(monkeypatch):
    seen = []
    monkeypatch.setattr(manifest, "lookup", lambda name: seen.append(name) or None)
    render_named(SOURCE, "testapp/page.html")
    assert seen == ["testapp/page.html"]


def test_scoped_css_links_is_empty_when_the_entry_has_no_bundle(monkeypatch):
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    assert render_named(SOURCE, "testapp/page.html") == ""


def test_scoped_css_links_is_empty_when_the_record_has_no_bundle_key(monkeypatch):
    monkeypatch.setattr(manifest, "lookup", lambda name: {"attr": "data-css-testapp-page", "sources": []})
    assert render_named(SOURCE, "testapp/page.html") == ""


def test_scoped_css_links_supports_a_multi_bundle_record(monkeypatch):
    monkeypatch.setattr(manifest, "lookup", lambda name: {"bundles": ["a/one.css", "a/two.css"]})
    out = render_named(SOURCE, "testapp/page.html")
    assert out.count("<link ") == 2
    assert 'href="/static/a/two.css"' in out


def test_scoped_css_links_calls_ensure_fresh_when_auto_compile(monkeypatch, settings):
    settings.SCOPED_CSS = {"AUTO_COMPILE": True}
    seen = []
    monkeypatch.setattr("scoped_css.dev.ensure_fresh", lambda entry: seen.append(entry))
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    render_named(SOURCE, "testapp/page.html")
    assert seen == ["testapp/page.html"]


def test_scoped_css_links_skips_ensure_fresh_when_auto_compile_is_off(monkeypatch, settings):
    settings.SCOPED_CSS = {"AUTO_COMPILE": False}
    seen = []
    monkeypatch.setattr("scoped_css.dev.ensure_fresh", lambda entry: seen.append(entry))
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    render_named(SOURCE, "testapp/page.html")
    assert seen == []


def test_scoped_css_links_never_raises(monkeypatch):
    def explode(name):
        raise RuntimeError("manifest is on fire")

    monkeypatch.setattr(manifest, "lookup", explode)
    assert render_named(SOURCE, "testapp/page.html") == ""


def test_scoped_css_links_is_empty_for_a_nameless_template(monkeypatch):
    monkeypatch.setattr(manifest, "lookup", lambda name: {"bundle": "a/b.css"})
    assert Engine.get_default().from_string(SOURCE).render(Context({})) == ""


# --------------------------------------------------------------------- {% css_dep %}


def test_css_dep_renders_nothing_but_parses(request_obj):
    """page.html carries {% css_dep "testapp/htmx/fragment.html" %}."""
    html = render_to_string("testapp/page.html", request=request_obj)
    assert "fragment" not in html


def test_css_dep_rejects_a_dynamic_target():
    from django.template import TemplateSyntaxError

    with pytest.raises(TemplateSyntaxError):
        Engine.get_default().from_string("{% load scoped_css %}{% css_dep some_var %}")


def test_node_classes_are_public_for_the_a1_cross_check_walk():
    """graph.py recognises the tags by NAME (lexer walk); only the A1 drift check uses isinstance."""
    assert issubclass(tags.CSSScopeNode, __import__("django").template.Node)
    assert tags.CSSDepNode("x.html").path == "x.html"


# ------------------------------- {% scoped_css_links "entry" %} + per-request dedupe (Part A.1)
#
# A TemplateExtension panel renders inside a CORE view: neither ScopedCSSMixin nor the page's
# scope root is the app's, and context.template.name is a core template with no bundle. So the
# panel names its own entry and delivers its <link> in-body — and, because one page can render
# the same panel many times, the tag emits it at most once per request per entry.

PANEL_ENTRY = "testapp/panels/self_entry.html"
PANEL_BUNDLE = "testapp/scoped_css/panels-self_entry.abc12345.css"
PANEL_LINK = f'<link rel="stylesheet" href="/static/{PANEL_BUNDLE}">'
EXPLICIT = '{% load scoped_css %}{% scoped_css_links "' + PANEL_ENTRY + '" %}'


@pytest.fixture
def panel_manifest(monkeypatch):
    """Every entry has a bundle named after it, so the emitted href identifies the lookup key."""
    monkeypatch.setattr(
        manifest,
        "lookup",
        lambda name: {"bundle": f"testapp/scoped_css/{naming.template_key('testapp', name)}.abc12345.css"},
    )


def render_with_request(source: str, name: str, request) -> str:
    """Render a named string template with ``request`` in the context, as a real view would."""
    engine = Engine.get_default()
    origin = Origin(name=f"/nonexistent/{name}", template_name=name)
    template = Template(source, origin=origin, name=name, engine=engine)
    return template.render(Context({"request": request}))


def test_an_explicit_entry_argument_overrides_the_rendering_template(panel_manifest):
    """The point of the argument: the page being rendered is a core template, not the app's."""
    out = render_named(EXPLICIT, "generic/object_retrieve.html")
    assert out == PANEL_LINK


def test_the_explicit_argument_is_what_gets_looked_up(monkeypatch):
    seen = []
    monkeypatch.setattr(manifest, "lookup", lambda name: seen.append(name) or None)
    render_named(EXPLICIT, "generic/object_retrieve.html")
    assert seen == [PANEL_ENTRY]


def test_an_explicit_entry_with_no_bundle_emits_nothing(monkeypatch):
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    assert render_named(EXPLICIT, "generic/object_retrieve.html") == ""


def test_an_explicit_entry_still_calls_ensure_fresh(monkeypatch, settings):
    settings.SCOPED_CSS = {"AUTO_COMPILE": True}
    seen = []
    monkeypatch.setattr("scoped_css.dev.ensure_fresh", lambda entry: seen.append(entry))
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    render_named(EXPLICIT, "generic/object_retrieve.html")
    assert seen == [PANEL_ENTRY]


def test_the_link_is_emitted_once_per_request_per_entry(panel_manifest, request_obj):
    """Three panels on one page — one <link>. This is the whole reason for the dedupe."""
    out = "".join(render_with_request(EXPLICIT, "generic/object_retrieve.html", request_obj) for _ in range(3))
    assert out.count("<link ") == 1
    assert out == PANEL_LINK


def test_two_different_entries_each_get_their_own_link(panel_manifest, request_obj):
    """Deduped per ENTRY, not per request: the page's own bundle and the panel's both land."""
    page = render_with_request(SOURCE, "testapp/page.html", request_obj)
    panel = render_with_request(EXPLICIT, "testapp/page.html", request_obj)
    assert page == '<link rel="stylesheet" href="/static/testapp/scoped_css/page.abc12345.css">'
    assert panel == PANEL_LINK


def test_a_later_request_gets_the_link_again(panel_manifest):
    """The set lives on the request, so it dies with the response — nothing leaks between them."""
    factory = RequestFactory()
    first = render_with_request(EXPLICIT, "generic/object_retrieve.html", factory.get("/"))
    second = render_with_request(EXPLICIT, "generic/object_retrieve.html", factory.get("/"))
    assert first == second == PANEL_LINK


def test_without_a_request_there_is_nothing_to_dedupe_against(panel_manifest):
    """A bare render (management command, a Template built by hand) keeps the old behaviour."""
    out = "".join(render_named(EXPLICIT, "generic/object_retrieve.html") for _ in range(2))
    assert out.count("<link ") == 2


def test_the_dedupe_reaches_the_request_through_a_request_context(panel_manifest, request_obj):
    """render_to_string(request=…) supplies `request` via the context processor, not context.get."""
    from django.template.loader import render_to_string as rts

    first = rts("testapp/panels/self_entry.html", request=request_obj)
    second = rts("testapp/panels/self_entry.html", request=request_obj)
    assert first.count("<link ") == 1
    assert second.count("<link ") == 0


def test_the_dedupe_marks_the_entry_even_when_there_is_no_bundle(monkeypatch, request_obj):
    """Marked before the lookup, so a bundle-less panel does not re-run ensure_fresh per render."""
    calls = []
    monkeypatch.setattr(manifest, "lookup", lambda name: calls.append(name) or None)
    for _ in range(3):
        render_with_request(EXPLICIT, "generic/object_retrieve.html", request_obj)
    assert calls == [PANEL_ENTRY]


def test_the_dedupe_never_raises_on_a_request_that_rejects_attributes(panel_manifest):
    """A stand-in request with __slots__ cannot carry the set; emit rather than fail."""

    class Frozen:
        __slots__ = ()

    engine = Engine.get_default()
    origin = Origin(name="/nonexistent/x.html", template_name="x.html")
    template = Template(EXPLICIT, origin=origin, name="x.html", engine=engine)
    out = "".join(template.render(Context({"request": Frozen()})) for _ in range(2))
    assert out.count("<link ") == 2
