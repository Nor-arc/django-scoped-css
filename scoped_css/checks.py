"""Django system checks: W001 missing bundle, W002 dynamic include, W003 orphan stylesheet."""

import logging

from django.core.checks import Tags, Warning, register

logger = logging.getLogger("scoped_css")


def _stylesheets(ref):
    """The colocated stylesheets attached to a TemplateRef, as a tuple of paths."""
    if ref is None:
        return ()
    sheets = getattr(ref, "stylesheets", None)
    if sheets is None:
        sheets = (getattr(ref, "css", None), getattr(ref, "module_css", None))
    return tuple(p for p in sheets if p)


def _check_app(app, auto_compile):
    from . import discovery, graph, manifest

    messages = []
    app_templates = discovery.scan(app)

    reached = set()  # stylesheet paths reachable from at least one entry
    dynamic = {}  # template name -> count, deduped across entries

    for entry in app_templates.entries:
        try:
            entry_graph = graph.build_entry_graph(app_templates, entry)
        except Exception:
            logger.debug("scoped_css: graph for entry %r failed", entry, exc_info=True)
            continue

        entry_has_css = False
        for source in entry_graph.ordered_sources:
            # (template_name, scope_attr) in the original contract; (name, scope, kind) as built.
            sheets = _stylesheets(app_templates.templates.get(source[0]))
            if sheets:
                entry_has_css = True
                reached.update(sheets)

        for name, node in (entry_graph.nodes or {}).items():
            if getattr(node, "dynamic_includes", 0):
                dynamic[name] = max(dynamic.get(name, 0), node.dynamic_includes)

        # W001 -- only meaningful in production; with AUTO_COMPILE the bundle is built on demand.
        if entry_has_css and not auto_compile and not manifest.lookup(entry):
            messages.append(
                Warning(
                    f"Entry template {entry!r} has colocated stylesheets but no compiled bundle.",
                    hint="Run `manage.py compile_css` (or ship the bundles in the wheel).",
                    obj=app.label,
                    id="scoped_css.W001",
                )
            )

    for name in sorted(dynamic):
        messages.append(
            Warning(
                f"{name!r} uses a dynamic {{% include %}}; its target cannot be resolved statically, "
                f"so any colocated stylesheet it reaches will be missing from the bundle "
                f"({dynamic[name]} occurrence(s)).",
                hint='Add {% css_dep "app/the_template.html" %} for each possible target.',
                obj=app.label,
                id="scoped_css.W002",
            )
        )

    # W003, two flavours of orphan: a stylesheet colocated with a template no entry can reach,
    # and a stylesheet with no `X.html` beside it at all.
    orphans = [
        sheet
        for name in sorted(app_templates.templates)
        for sheet in _stylesheets(app_templates.templates[name])
        if sheet not in reached
    ]
    try:
        orphans.extend(discovery.orphan_stylesheets(app_templates))
    except Exception:  # pragma: no cover - optional helper
        logger.debug("scoped_css: orphan_stylesheets() failed", exc_info=True)

    for sheet in orphans:
        messages.append(
            Warning(
                f"Colocated stylesheet {str(sheet)!r} is not reachable from any entry template; "
                f"it will never be bundled.",
                hint=(
                    'Include or {% css_dep %} the template from an entry, or add the template to SCOPED_CSS["ENTRIES"].'
                ),
                obj=app.label,
                id="scoped_css.W003",
            )
        )

    return messages


@register(Tags.templates)
def check_scoped_css(app_configs, **kwargs):
    try:
        from . import conf, discovery
    except Exception:  # pragma: no cover - a broken install should not break `manage.py check`
        logger.debug("scoped_css: checks could not import the build modules", exc_info=True)
        return []

    try:
        apps = list(discovery.participating_apps())
    except Exception:
        logger.debug("scoped_css: participating_apps() failed", exc_info=True)
        return []

    if app_configs is not None:
        wanted = {a.label for a in app_configs}
        apps = [a for a in apps if a.label in wanted]

    auto_compile = bool(conf.get("AUTO_COMPILE"))

    messages = []
    for app in apps:
        try:
            messages.extend(_check_app(app, auto_compile))
        except Exception:
            logger.debug("scoped_css: checks for app %r failed", getattr(app, "label", app), exc_info=True)
    return messages
