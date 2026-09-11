"""P4: the two delivery stories, proven separately against two host fixtures.

``tests/testapp/templates/base_django.html`` is the host **after** the core PR: it emits
``{% scoped_css_links %}`` before ``{% block extra_styles %}`` and stamps ``<main>`` with
``{% css_scope_page %}``. ``tests/testapp/templates/legacy_host.html`` is the host **before** it:
neither tag. The interim tests point ``SCOPED_CSS["ROOT_PARENT"]`` at the legacy host, so the two
stories never double-emit a ``<link>`` and each is proven on its own. See ARCHITECTURE.md
§ Delivery and § Test fixtures model both host states.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.template import Context, Engine
from django.template.base import Origin, Template
from django.template.loader import render_to_string

from scoped_css import build, manifest
from scoped_css.nautobot import ScopedCSSMixin

BUNDLE = "testapp/scoped_css/page.abc12345.css"
LINK = f'<link rel="stylesheet" href="/static/{BUNDLE}">'


class FakeNautobotView:
    """Stand-in for NautobotUIViewSet: same get_extra_context signature, nothing else."""

    def get_extra_context(self, request, instance=None):
        return {"object": instance, "verbose_name": "widget"}


class ScopedView(ScopedCSSMixin, FakeNautobotView):
    pass


def render_named(source: str, name: str, context: dict) -> str:
    engine = Engine.get_default()
    origin = Origin(name=f"/nonexistent/{name}", template_name=name)
    return Template(source, origin=origin, name=name, engine=engine).render(Context(context))


# ------------------------------------------------------------------------ HTML parsing


class _Harvest(HTMLParser):
    """The three things every delivery story is judged on."""

    def __init__(self):
        super().__init__()
        self.stylesheet_hrefs: list[str] = []
        self.main_attrs: dict[str, str | None] = {}
        self.row_attrs: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.stylesheet_hrefs.append(attributes.get("href"))
        elif tag == "main":
            self.main_attrs = attributes
        elif tag == "div" and "row" in (attributes.get("class") or "").split():
            self.row_attrs.append(attributes)


def parse(html: str) -> _Harvest:
    harvest = _Harvest()
    harvest.feed(html)
    return harvest


def scoped_attributes(attributes) -> list[str]:
    return sorted(key for key in attributes if key.startswith("data-css-"))


# --------------------------------------------------------------------- interim fixtures


@pytest.fixture
def legacy_host(scoped_css_settings):
    """The host before the core PR: root.html must supply the links itself."""
    scoped_css_settings(ROOT_PARENT="legacy_host.html")


@pytest.fixture
def fake_bundle(monkeypatch):
    """A manifest entry without a build, for the unit-level interim assertions."""
    monkeypatch.setattr(manifest, "lookup", lambda name: {"bundle": BUNDLE} if name.startswith("testapp/") else None)
    monkeypatch.setattr("scoped_css.dev.ensure_fresh", lambda entry: None)


# ------------------------------------------------------------------------- the mixin


def test_mixin_sets_root_template_and_the_root_parent():
    context = ScopedView().get_extra_context(None)
    assert context["root_template"] == "scoped_css/root.html"
    assert context["scoped_css_root_parent"] == "base_django.html"


def test_mixin_preserves_the_view_s_own_context():
    context = ScopedView().get_extra_context(None, instance="obj")
    assert context["object"] == "obj"
    assert context["verbose_name"] == "widget"


def test_root_parent_follows_the_setting(scoped_css_settings):
    scoped_css_settings(ROOT_PARENT="nautobot/other_base.html")
    assert ScopedView().get_extra_context(None)["scoped_css_root_parent"] == "nautobot/other_base.html"


def test_mixin_tolerates_a_view_returning_none():
    class NoneView:
        def get_extra_context(self, request, instance=None):
            return None

    class V(ScopedCSSMixin, NoneView):
        pass

    assert V().get_extra_context(None)["root_template"] == "scoped_css/root.html"


# ------------------------------------------------- the interim, against the legacy host


def test_the_link_lands_in_the_head(legacy_host, fake_bundle):
    """page.html -> base.html -> scoped_css/root.html -> legacy_host.html."""
    html = render_to_string("testapp/page.html", ScopedView().get_extra_context(None))
    assert LINK in html.split("</head>")[0]


def test_without_the_mixin_the_legacy_host_emits_no_link(legacy_host, fake_bundle):
    """The whole reason the interim exists: the pre-PR host has nowhere to put the <link>."""
    html = render_to_string("testapp/page.html", {"root_template": "legacy_host.html"})
    assert parse(html).stylesheet_hrefs == []


def test_the_page_attribute_comes_from_css_scope_not_the_mixin(legacy_host, fake_bundle):
    """The interim cannot stamp <main>: the author writes {% css_scope %} on the content wrapper."""
    harvest = parse(render_to_string("testapp/page.html", ScopedView().get_extra_context(None)))
    assert scoped_attributes(harvest.main_attrs) == []
    assert scoped_attributes(harvest.row_attrs[0]) == ["data-css-testapp-page"]


def test_a_page_can_still_add_its_own_styles_via_app_extra_styles(legacy_host, fake_bundle):
    """root.html leaves {% block app_extra_styles %} for the page, so both survive."""
    source = (
        "{% extends 'base.html' %}"
        "{% block app_extra_styles %}<style>mine</style>{% endblock %}"
        "{% block content %}<p>x</p>{% endblock %}"
    )
    html = render_named(source, "testapp/page.html", ScopedView().get_extra_context(None))
    assert LINK in html
    assert "<style>mine</style>" in html


def test_interim_extra_styles_override_drops_links(legacy_host, fake_bundle):
    """KNOWN LIMITATION of the interim, expected behaviour — not a bug to fix here.

    ``scoped_css/root.html`` emits the links inside ``{% block extra_styles %}``. A leaf page that
    overrides that same block without ``{{ block.super }}`` wins, and the links vanish. Every app
    that overrides ``extra_styles`` today does so without ``block.super``, because the block is
    empty in Nautobot core.

    This is exactly why ARCHITECTURE.md § Delivery requires the core PR to emit
    ``{% scoped_css_links %}`` *before* ``{% block extra_styles %}`` rather than inside it — and
    ``base_django.html``, the post-PR host fixture, shows that placement working. Until then, such
    a page must use ``{% block app_extra_styles %}`` (above) or call ``{{ block.super }}``.
    """
    override = (
        "{% extends 'base.html' %}"
        "{% block extra_styles %}<style>mine</style>{% endblock %}"
        "{% block content %}<p>x</p>{% endblock %}"
    )
    html = render_named(override, "testapp/page.html", ScopedView().get_extra_context(None))
    assert "<style>mine</style>" in html
    assert LINK not in html  # <- the limitation

    with_super = override.replace("{% block extra_styles %}", "{% block extra_styles %}{{ block.super }}")
    rescued = render_named(with_super, "testapp/page.html", ScopedView().get_extra_context(None))
    assert LINK in rescued
    assert "<style>mine</style>" in rescued


def test_root_html_falls_back_when_the_parent_is_not_in_the_context(fake_bundle):
    """Rendered without the mixin (e.g. a hand-set root_template), root.html still resolves."""
    html = render_to_string("testapp/page.html", {"root_template": "scoped_css/root.html"})
    assert LINK in html


# ------------------------------------------------------------------------- end to end
#
# One true end-to-end test per delivery story: build the real bundle, render the real page, parse
# the HTML, resolve the <link> href back to the manifest record and the bundle on disk, and read
# the compiled rule out of that file.


def bundle_on_disk(output_dir: Path, entry: str) -> tuple[dict, str]:
    """The manifest record for ``entry`` and the text of the bundle it points at."""
    record = manifest.lookup(entry)
    assert record is not None, f"no manifest record for {entry}"
    path = output_dir / Path(record["bundle"]).name
    assert path.is_file(), f"{record['bundle']} is not on disk"
    return record, path.read_text(encoding="utf-8")


def test_story_core_after_pr_needs_no_mixin_and_no_template_edit(testapp, output_dir):
    """page3.html has no {% css_scope %} and the view has no mixin: the zero-edit state.

    The post-PR host does everything — the <link> from {% scoped_css_links %}, the page attribute
    from {% css_scope_page %} on <main> — so the app ships stylesheets and nothing else.
    """
    build.build_app(testapp)
    record, css = bundle_on_disk(output_dir, "testapp/page3.html")

    harvest = parse(render_to_string("testapp/page3.html", {}))

    # Exactly one <link>, and it resolves to this entry's bundle.
    assert harvest.stylesheet_hrefs == [f"/static/{record['bundle']}"]
    # The page attribute is on <main>, stamped by the host, with no tag in the page.
    assert scoped_attributes(harvest.main_attrs) == ["data-css-testapp-page3"]
    assert "{% css_scope %}" not in (Path(testapp.path) / "templates/testapp/page3.html").read_text()
    assert scoped_attributes(harvest.row_attrs[0]) == []
    # ...and the rule from page3.module.css is compiled under exactly that attribute.
    assert "[data-css-testapp-page3] .zero-edit" in css
    assert record["attr"] == "data-css-testapp-page3"


def test_story_core_after_pr_tolerates_a_page_that_still_carries_css_scope(testapp, output_dir):
    """page.html keeps its interim {% css_scope %}: still ONE link, and the two attrs agree."""
    build.build_app(testapp)
    record, css = bundle_on_disk(output_dir, "testapp/page.html")

    harvest = parse(render_to_string("testapp/page.html", {}))

    assert harvest.stylesheet_hrefs == [f"/static/{record['bundle']}"]
    # <main> (host) and .row (the leftover interim tag) carry the same page attribute: harmless.
    assert scoped_attributes(harvest.main_attrs) == ["data-css-testapp-page"]
    assert scoped_attributes(harvest.row_attrs[0]) == ["data-css-testapp-page"]
    assert "[data-css-testapp-page] .modal-body" in css
    # The {% css_scope %}-tagged partial still compiles under its own attribute.
    assert "[data-css-testapp-components-tile] .tile" in css


def test_story_interim_legacy_host_plus_mixin(testapp, output_dir, legacy_host):
    """Before the core PR: the mixin supplies the link, {% css_scope %} supplies the attribute."""
    build.build_app(testapp)
    record, css = bundle_on_disk(output_dir, "testapp/page.html")

    harvest = parse(render_to_string("testapp/page.html", ScopedView().get_extra_context(None)))

    # Still exactly one link — the legacy host emits none of its own.
    assert harvest.stylesheet_hrefs == [f"/static/{record['bundle']}"]
    # The legacy <main> is bare; the attribute comes from the page's own tag.
    assert scoped_attributes(harvest.main_attrs) == []
    assert scoped_attributes(harvest.row_attrs[0]) == ["data-css-testapp-page"]
    assert "[data-css-testapp-page] .modal-body" in css


def test_story_in_app_base_stylesheet_joins_the_child_s_bundle(testapp, output_dir):
    """GAP 1: page2 extends an in-app base, so base_app.css is part of page2's bundle — first."""
    build.build_app(testapp)
    _record, page2_css = bundle_on_disk(output_dir, "testapp/page2.html")
    _record, page_css = bundle_on_disk(output_dir, "testapp/page.html")

    assert "/* source: testapp/base_app.css */" in page2_css
    assert ".app-shell" in page2_css
    # The parent's stylesheet precedes the child's so the child can override it.
    assert page2_css.index("base_app.css") < page2_css.index("page2.module.css")
    assert "[data-css-testapp-page2] .panel" in page2_css
    # page.html extends base.html, which owns no stylesheet: nothing leaks in.
    assert "base_app.css" not in page_css
    assert ".app-shell" not in page_css
