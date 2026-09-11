"""Locate apps, their templates, colocated stylesheets, entries, and output dirs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from django.apps import AppConfig, apps

from . import conf

#: A stylesheet colocated with ``X.html`` is either of these siblings.
MODULE_SUFFIX = ".module.css"
PLAIN_SUFFIX = ".css"


@dataclass(frozen=True)
class TemplateRef:
    app: AppConfig
    name: str  # Django template name, e.g. "testapp/page.html"
    path: Path  # absolute path on disk
    css: Path | None = None  # sibling X.css (global within page), if present
    module_css: Path | None = None  # sibling X.module.css (scoped), if present

    @property
    def key(self) -> str:
        from .naming import template_key

        return template_key(self.app.label, self.name)

    @property
    def attr(self) -> str:
        from .naming import scope_attr

        return scope_attr(self.app.label, self.key)

    @property
    def stylesheets(self) -> list[Path]:
        """Colocated stylesheets in bundle order: the global one first, then the scoped one."""
        return [p for p in (self.css, self.module_css) if p is not None]


@dataclass
class AppTemplates:
    app: AppConfig
    templates_dir: Path
    output_dir: Path  # <app.path>/static/<label>/scoped_css/
    templates: dict[str, TemplateRef] = field(default_factory=dict)  # by template name
    entries: list[str] = field(default_factory=list)  # template names

    def ref(self, name: str) -> TemplateRef | None:
        return self.templates.get(name)


# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------


def templates_dir(app: AppConfig) -> Path:
    return Path(app.path) / "templates"


def output_dir(app: AppConfig) -> Path:
    """Where this app's bundles + manifest live: ``<app.path>/static/<label>/scoped_css/``.

    Same location in dev (editable install, written on demand) and prod (prebuilt into the wheel),
    which is what makes the bundle servable by staticfiles under ``<label>/scoped_css/<file>``.

    ``SCOPED_CSS["OUTPUT_DIR"]`` redirects every app to ``<OUTPUT_DIR>/<label>/scoped_css/``. That
    is a test/CI escape hatch only — see conf.DEFAULTS: the manifest's static path is unchanged, so
    staticfiles cannot find the files and a rendered ``<link>`` would 404.
    """
    override = conf.get("OUTPUT_DIR")
    if override:
        return Path(override) / app.label / "scoped_css"
    return Path(app.path) / "static" / app.label / "scoped_css"


def static_prefix(app: AppConfig) -> str:
    """The ``{% static %}``-relative prefix of this app's bundles."""
    return f"{app.label}/scoped_css"


# --------------------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------------------


def has_colocated_css(directory: Path) -> bool:
    """Whether any ``X.css``/``X.module.css`` under ``directory`` sits beside an ``X.html``."""
    if not directory.is_dir():
        return False
    for stylesheet in directory.rglob("*.css"):
        if _template_for_stylesheet(stylesheet).is_file():
            return True
    return False


def _template_for_stylesheet(stylesheet: Path) -> Path:
    name = stylesheet.name
    stem = name[: -len(MODULE_SUFFIX)] if name.endswith(MODULE_SUFFIX) else name[: -len(PLAIN_SUFFIX)]
    return stylesheet.with_name(f"{stem}.html")


def participating_apps() -> list[AppConfig]:
    """Apps in SCOPED_CSS["APPS"], or every installed app that has a templates/ dir with any colocated css."""
    configured = conf.get("APPS")
    if configured is not None:
        found = []
        for label in configured:
            try:
                found.append(apps.get_app_config(label))
            except LookupError:
                continue
        return found
    return [app for app in apps.get_app_configs() if has_colocated_css(templates_dir(app))]


# --------------------------------------------------------------------------------------
# Scanning one app
# --------------------------------------------------------------------------------------


def scan(app: AppConfig) -> AppTemplates:
    """Walk <app.path>/templates/**/*.html, attach colocated css, detect entries.

    A template is an entry when any of three things is true (all detected with the Lexer, never a
    regex over the raw text -- see ``graph.analyze_source``):

    1. it contains ``{% extends %}`` -- it is a page;
    2. it contains ``{% scoped_css_links "<its own template name>" %}`` -- it declares itself a
       self-contained styled unit that delivers its own ``<link>`` (``graph.Node.is_entry``);
    3. it is listed in ``SCOPED_CSS["ENTRIES"][app.label]``.
    """
    from .graph import analyze_path

    root = templates_dir(app)
    found = AppTemplates(app=app, templates_dir=root, output_dir=output_dir(app))
    if not root.is_dir():
        return found

    declared = set(conf.get("ENTRIES").get(app.label, ()))
    entries: list[str] = []

    for path in sorted(root.rglob("*.html")):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        plain = path.with_name(f"{path.stem}{PLAIN_SUFFIX}")
        module = path.with_name(f"{path.stem}{MODULE_SUFFIX}")
        found.templates[name] = TemplateRef(
            app=app,
            name=name,
            path=path,
            css=plain if plain.is_file() else None,
            module_css=module if module.is_file() else None,
        )
        try:
            is_entry = analyze_path(path, name).is_entry
        except OSError:  # pragma: no cover - unreadable file, never abort the whole app
            is_entry = False
        if is_entry or name in declared:
            entries.append(name)

    # A declared entry that is not on disk is still reported, so the caller can warn about it.
    entries.extend(sorted(name for name in declared if name not in found.templates))
    found.entries = entries
    return found


def orphan_stylesheets(app_templates: AppTemplates) -> list[Path]:
    """Colocated-looking stylesheets with no matching ``X.html`` (feeds checks.W003)."""
    owned = {str(p) for ref in app_templates.templates.values() for p in ref.stylesheets}
    if not app_templates.templates_dir.is_dir():
        return []
    return sorted(path for path in app_templates.templates_dir.rglob("*.css") if str(path) not in owned)


# --------------------------------------------------------------------------------------
# Origin -> TemplateRef (used by {% css_scope %} at render time)
# --------------------------------------------------------------------------------------

_ORIGIN_INDEX: dict[str, TemplateRef] = {}


def clear_cache() -> None:
    """Drop the origin index (tests; long-lived dev processes that add templates)."""
    _ORIGIN_INDEX.clear()


def _rebuild_origin_index() -> None:
    _ORIGIN_INDEX.clear()
    for app in participating_apps():
        for ref in scan(app).templates.values():
            _ORIGIN_INDEX[str(ref.path)] = ref


def template_ref_for_origin(origin_name: str) -> TemplateRef | None:
    """Map a Template.origin.name (absolute path) back to its TemplateRef, or None if not an app template."""
    if not origin_name:
        return None
    key = str(Path(origin_name))
    ref = _ORIGIN_INDEX.get(key)
    if ref is not None:
        return ref
    # A miss may simply mean the index predates this template; rebuild once, then give up.
    _rebuild_origin_index()
    return _ORIGIN_INDEX.get(key)
