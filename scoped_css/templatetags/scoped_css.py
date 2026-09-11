"""The four render-time template tags.

``graph.py`` does **not** see these Node classes: it is a lexer walk over raw template source
(P0 verdict A2) and recognises ``css_scope`` / ``css_dep`` by tag name. The classes stay public
for the A1 nodelist walk that ``tests/spike_walkers.py`` keeps as a drift cross-check, which does
match them with ``isinstance``.
"""

import logging

from django import template
from django.templatetags.static import static
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe

logger = logging.getLogger("scoped_css")

register = template.Library()


def _app_label_from_template_name(template_name: str) -> str:
    """Fallback app label: the first path segment of a loader-relative template name.

    ``"testapp/page.html"`` -> ``"testapp"``; a template at the loader root (``"base.html"``)
    has no app segment and yields ``""``.
    """
    head, sep, _rest = (template_name or "").partition("/")
    return head if sep else ""


def _attr_for(template_name: str | None, origin_name: str | None = None) -> str:
    """``attr(T)`` for a loader-relative template name.

    ``origin_name`` (the absolute path) is the authoritative way to find the owning app, via
    ``discovery.template_ref_for_origin``. When discovery cannot answer -- it is not built yet,
    the app is not participating, or the template lives outside any app -- fall back to the first
    path segment of the template name so the tag still renders something useful in dev rather
    than silently emitting nothing.
    """
    if not template_name:
        # A Template built from a string has ``origin.template_name is None`` (P0 finding 2).
        return ""

    from .. import naming

    ref = None
    if origin_name:
        from .. import discovery

        try:
            ref = discovery.template_ref_for_origin(origin_name)
        except Exception:  # pragma: no cover - discovery must never break a render
            logger.debug("scoped_css: discovery failed for origin %r", origin_name, exc_info=True)

    if ref is not None:
        app_label, name = ref.app.label, ref.name
    else:
        app_label, name = _app_label_from_template_name(template_name), template_name
        if not app_label:
            return ""

    return naming.scope_attr(app_label, naming.template_key(app_label, name))


class CSSScopeNode(template.Node):
    """``{% css_scope %}`` -- emits ``attr(T)`` for the template the tag is *written in*.

    T comes from ``self.origin.template_name``, fixed at parse time by ``Parser.extend_nodelist``.
    NOT from ``context.render_context.template``: P0 proved that reports the root of the
    ``{% extends %}`` chain (``base_django.html``) exactly where authors place this tag -- inside
    a ``{% block %}`` -- which would collapse every page in every app into one scope.
    """

    def render(self, context):
        try:
            origin = getattr(self, "origin", None)
            return mark_safe(  # noqa: S308 - an attribute name from [a-z0-9_-] only
                _attr_for(getattr(origin, "template_name", None), getattr(origin, "name", None))
            )
        except Exception:
            logger.debug("scoped_css: {%% css_scope %%} could not resolve its scope", exc_info=True)
            return ""


class CSSDepNode(template.Node):
    """{% css_dep "path.html" %} — renders "", exists only as a graph edge."""

    def __init__(self, path: str):
        self.path = path

    def render(self, context):
        return ""


@register.tag
def css_scope(parser, token):
    return CSSScopeNode()


@register.tag
def css_dep(parser, token):
    bits = token.split_contents()
    if len(bits) != 2 or bits[1][0] not in "\"'":
        raise template.TemplateSyntaxError("css_dep takes exactly one quoted template path")
    return CSSDepNode(bits[1][1:-1])


@register.simple_tag(takes_context=True)
def css_scope_page(context):
    """attr(entry) for context.template.name."""
    try:
        tpl = getattr(context, "template", None)
        origin = getattr(tpl, "origin", None)
        return mark_safe(  # noqa: S308 - an attribute name from [a-z0-9_-] only
            _attr_for(getattr(tpl, "name", None), getattr(origin, "name", None))
        )
    except Exception:
        logger.debug("scoped_css: {%% css_scope_page %%} could not resolve the entry scope", exc_info=True)
        return ""


#: Where the per-request "already emitted" set is parked on ``request``.
_EMITTED_ATTR = "_scoped_css_emitted_entries"


def _already_emitted(context, entry_name: str) -> bool:
    """Record ``entry_name`` against this request; True when it was already recorded.

    A ``TemplateExtension`` panel delivers its own ``<link>`` in-body (see the tag's docstring),
    and the same panel can be rendered several times on one page -- once per object in a list, or
    once per tab. Without this, each render repeats the identical ``<link>``. The set lives on
    ``request`` because that is the only object whose lifetime is exactly one response and which
    every nested ``Context`` can still reach; with no request in the context (a bare
    ``Template.render(Context({}))``, a management command) there is nothing to dedupe against and
    the tag emits every time, which is the old behaviour.
    """
    request = None
    try:
        request = context.get("request", None)
    except Exception:  # pragma: no cover - a Context subclass without .get
        pass
    if request is None:
        request = getattr(context, "request", None)
    if request is None:
        return False

    emitted = getattr(request, _EMITTED_ATTR, None)
    if emitted is None:
        emitted = set()
        try:
            setattr(request, _EMITTED_ATTR, emitted)
        except Exception:  # pragma: no cover - an immutable stand-in for a request
            return False
    if entry_name in emitted:
        return True
    emitted.add(entry_name)
    return False


@register.simple_tag(takes_context=True)
def scoped_css_links(context, entry=None):
    """``<link>`` tags for an entry's bundle(s). Empty string if there are none; never raises.

    ``{% scoped_css_links %}`` uses ``context.template.name`` -- the page being rendered. That is
    the host root template's usage, and the one ARCHITECTURE.md § Delivery describes.

    ``{% scoped_css_links "example_app/panels/device_widgets.html" %}`` looks up *that* entry
    instead. It exists for the one place a bundle cannot ride on the page: a Nautobot
    ``TemplateExtension`` panel renders inside a **core** view, so neither ``ScopedCSSMixin`` nor
    the page's scope root belongs to the app, and ``context.template.name`` is a core template
    with no bundle of its own. Until the core change lands, such a fragment must deliver its own
    ``<link>`` from inside ``<body>`` -- which is valid HTML5 -- and declare itself an entry by
    naming itself here (``graph.Node.is_entry``).

    Emission is deduplicated **per request per entry** (``_already_emitted``), so a panel rendered
    once per row of a list does not repeat its ``<link>``.

    Calls ``dev.ensure_fresh`` first when ``AUTO_COMPILE``.
    """
    try:
        if entry:
            entry_name = str(entry)
        else:
            tpl = getattr(context, "template", None)
            entry_name = getattr(tpl, "name", None)
        if not entry_name:
            return ""

        if _already_emitted(context, entry_name):
            return ""

        from .. import conf, dev, manifest

        if conf.get("AUTO_COMPILE"):
            dev.ensure_fresh(entry_name)

        record = manifest.lookup(entry_name)
        if not record:
            return ""

        # Schema version 1 records a single "bundle"; accept a future "bundles" list too.
        bundles = record.get("bundles") or [record.get("bundle")]
        bundles = [b for b in bundles if b]
        if not bundles:
            return ""
        return format_html_join("\n", '<link rel="stylesheet" href="{}">', ((static(b),) for b in bundles))
    except Exception:
        logger.debug("scoped_css: {%% scoped_css_links %%} emitted nothing", exc_info=True)
        return ""
