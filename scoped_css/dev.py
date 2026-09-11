"""On-demand compilation when SCOPED_CSS["AUTO_COMPILE"] (defaults to DEBUG)."""

import logging
import os
from pathlib import Path

logger = logging.getLogger("scoped_css")


def is_stale(record: dict | None, output_dir: Path | None = None) -> bool:
    """True when the entry needs rebuilding.

    Stale when there is no manifest record at all, when a recorded source has been deleted or has
    an mtime newer than the recorded ``source_mtime``, or when the bundle file itself is gone.
    ``output_dir`` is the app's ``static/<label>/scoped_css/`` dir; when omitted the bundle-exists
    check is skipped (the mtime comparison still runs).
    """
    if not record:
        return True

    recorded = record.get("source_mtime")
    if recorded is None:
        return True

    for source in record.get("sources") or []:
        try:
            if os.path.getmtime(source) > recorded:
                return True
        except OSError:
            # A source that vanished is a change too.
            return True

    bundle = record.get("bundle")
    if output_dir is not None and bundle:
        if not (Path(output_dir) / Path(bundle).name).exists():
            return True

    return False


def app_templates_for(entry_template_name: str):
    """The ``AppTemplates`` of the participating app that owns ``entry_template_name``, or None."""
    from . import discovery

    for app in discovery.participating_apps():
        try:
            app_templates = discovery.scan(app)
        except Exception:
            logger.debug("scoped_css: scan of %r failed", getattr(app, "label", app), exc_info=True)
            continue
        if entry_template_name in app_templates.templates or entry_template_name in app_templates.entries:
            return app_templates
    return None


def ensure_fresh(entry_template_name: str) -> None:
    """Rebuild the entry if its bundle is missing or any source mtime exceeds manifest source_mtime.
    Never raises into the template render; log and return.

    Note: v1 rebuilds the *whole owning app*, not just this entry. Apps have a handful of entries,
    a rebuild is cheap next to a page render, and a whole-app pass also picks up stylesheets that
    were added since the manifest was written (which a per-entry source-mtime check cannot see).
    """
    try:
        from . import manifest

        app_templates = app_templates_for(entry_template_name)
        if app_templates is None:
            return

        record = manifest.lookup(entry_template_name)
        if not is_stale(record, getattr(app_templates, "output_dir", None)):
            return

        from .build import build_app

        build_app(app_templates.app)
        logger.debug("scoped_css: rebuilt app %r for entry %r", app_templates.app.label, entry_template_name)
    except Exception:
        logger.debug("scoped_css: auto-compile for %r failed", entry_template_name, exc_info=True)


def ensure_output_dirs() -> None:
    """Create every participating app's output dir before Django's staticfiles finder looks.

    ``AppDirectoriesFinder`` enumerates each app's ``static/`` directory exactly once, on first
    use, with ``os.path.isdir``. An app whose only static content is compiled CSS has no
    ``static/`` dir until its first build, so a bundle written by the first on-demand compile
    would 404 until the server restarts. Creating the directory at startup (``AppConfig.ready``)
    makes that first build servable immediately. Read-only installs are left alone.
    """
    from . import discovery

    for app in discovery.participating_apps():
        target = discovery.output_dir(app)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("scoped_css: could not create %s: %s", target, exc)
