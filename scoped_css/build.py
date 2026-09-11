"""Orchestration: scan an app, graph every entry, bundle it, write the manifest.

`compile_css` and `dev.ensure_fresh` both go through here, so there is exactly one definition of
what "build this app" means.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

from . import discovery, graph, manifest
from .bundler import BundleRecord, build_entry

logger = logging.getLogger("scoped_css")


def build_app(app: AppConfig, *, warnings: list[str] | None = None) -> list[BundleRecord]:
    """Build every entry of one app and (re)write its manifest.

    Failures are isolated per entry: one unparseable template or stylesheet must not cost the app
    its other bundles. Collected warnings (W002 dynamic includes, compiler warnings) are appended
    to ``warnings`` when one is given, and are also carried on each BundleRecord.
    """
    app_templates = discovery.scan(app)
    records: list[BundleRecord] = []

    for entry in app_templates.entries:
        try:
            entry_graph = graph.build_entry_graph(app_templates, entry)
            record = build_entry(app_templates, entry_graph)
        except Exception:
            logger.warning("scoped_css: entry %r in app %r failed to build", entry, app.label, exc_info=True)
            if warnings is not None:
                warnings.append(f"scoped_css: entry {entry!r} in app {app.label!r} failed to build")
            continue
        if record is None:
            continue
        records.append(record)
        if warnings is not None:
            warnings.extend(record.warnings)

    manifest.write(app_templates.output_dir, records)
    manifest.clear_cache()
    return records


def build_all(apps: list[AppConfig] | None = None, *, warnings: list[str] | None = None) -> list[BundleRecord]:
    """Build every participating app (or just ``apps``). Returns every bundle record produced."""
    records: list[BundleRecord] = []
    for app in apps if apps is not None else discovery.participating_apps():
        records.extend(build_app(app, warnings=warnings))
    return records
