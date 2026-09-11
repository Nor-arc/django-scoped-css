"""manifest.json per app output dir; see ARCHITECTURE.md for the schema (version 1)."""

from __future__ import annotations

import json
from pathlib import Path

from .bundler import BundleRecord

VERSION = 1
FILENAME = "manifest.json"

#: path -> (mtime, parsed document). Dev rebuilds are picked up because the mtime is part of
#: the validity test, not merely of the key.
_CACHE: dict[str, tuple[float, dict]] = {}


def manifest_path(output_dir: Path) -> Path:
    return Path(output_dir) / FILENAME


def clear_cache() -> None:
    """Drop the in-process manifest cache (tests; explicit rebuilds)."""
    _CACHE.clear()


def as_document(records: list[BundleRecord]) -> dict:
    """The version-1 document for a list of bundle records."""
    entries = {}
    for record in records:
        entries[record.entry] = {
            "bundle": record.bundle,
            "attr": record.attr,
            "sources": list(record.sources),
            "source_details": [dict(d) for d in getattr(record, "source_details", [])],
            "source_mtime": record.source_mtime,
        }
    return {"version": VERSION, "entries": dict(sorted(entries.items()))}


def write(output_dir: Path, records: list[BundleRecord]) -> Path:
    """Write (or rewrite) the app's manifest. Returns its path."""
    output_dir = Path(output_dir)
    path = manifest_path(output_dir)
    if not records and not path.exists():
        return path
    output_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(as_document(records), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    _CACHE.pop(str(path), None)
    return path


def read(path: Path) -> dict | None:
    """Parse one manifest, memoized on (path, mtime). None when it is missing or unreadable."""
    path = Path(path)
    try:
        stamp = path.stat().st_mtime
    except OSError:
        _CACHE.pop(str(path), None)
        return None
    cached = _CACHE.get(str(path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    _CACHE[str(path)] = (stamp, document)
    return document


def entries(output_dir: Path) -> dict:
    """Every entry recorded in one app's manifest."""
    document = read(manifest_path(output_dir))
    return (document or {}).get("entries", {}) or {}


def lookup(entry_template_name: str) -> dict | None:
    """Find the entry across all participating apps' manifests. In-process cache keyed by
    manifest path + mtime so dev rebuilds are picked up."""
    from . import discovery

    for app in discovery.participating_apps():
        record = entries(discovery.output_dir(app)).get(entry_template_name)
        if record is not None:
            return record
    return None
