"""manifest.py: the version-1 document, and lookup across participating apps."""

import json
from pathlib import Path

import pytest

from scoped_css import build, manifest
from scoped_css.bundler import BundleRecord

ENTRY = "testapp/page.html"
PAGE_ATTR = "data-css-testapp-page"


@pytest.fixture
def document(testapp, output_dir):
    build.build_app(testapp)
    return json.loads(manifest.manifest_path(output_dir).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------- schema


def test_manifest_is_written_next_to_the_bundles(testapp, output_dir):
    path = manifest.write(output_dir, build.build_app(testapp))
    assert path == output_dir / "manifest.json"
    assert path.is_file()


def test_document_shape(document):
    assert document["version"] == 1
    assert set(document) == {"version", "entries"}
    record = document["entries"][ENTRY]
    assert record["attr"] == PAGE_ATTR
    assert record["bundle"].startswith("testapp/scoped_css/page.")
    assert record["bundle"].endswith(".css")
    assert isinstance(record["source_mtime"], float)
    assert [Path(p).name for p in record["sources"]] == [
        "page.css",
        "tile.module.css",
        "modal.module.css",
        "fragment.module.css",
    ]


def test_each_source_records_its_scope_and_kind(document):
    details = document["entries"][ENTRY]["source_details"]
    assert [(Path(d["path"]).name, d["scope"], d["kind"]) for d in details] == [
        ("page.css", PAGE_ATTR, "page"),
        ("tile.module.css", "data-css-testapp-components-tile", "element"),
        ("modal.module.css", PAGE_ATTR, "page"),
        ("fragment.module.css", PAGE_ATTR, "page"),
    ]


def test_entries_without_a_bundle_are_absent(document):
    """base.html is an entry (it has {% extends %}) but owns no stylesheet, so it has no record."""
    assert list(document["entries"]) == [
        "testapp/base_app.html",
        ENTRY,
        "testapp/page2.html",
        "testapp/page3.html",
        "testapp/panels/self_entry.html",
    ]


# ------------------------------------------------------------------------- lookup


def test_lookup_finds_the_entry_across_participating_apps(testapp, output_dir):
    build.build_app(testapp)
    record = manifest.lookup(ENTRY)
    assert record is not None
    assert record["attr"] == PAGE_ATTR
    assert (output_dir / Path(record["bundle"]).name).is_file()


def test_lookup_returns_none_for_an_unknown_entry(testapp, output_dir):
    build.build_app(testapp)
    assert manifest.lookup("testapp/nope.html") is None
    assert manifest.lookup("base.html") is None


def test_lookup_without_a_manifest_is_none(output_dir):
    assert manifest.lookup(ENTRY) is None


def test_lookup_is_cached_but_notices_a_rewrite(testapp, output_dir):
    build.build_app(testapp)
    first = manifest.lookup(ENTRY)

    path = manifest.manifest_path(output_dir)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["entries"][ENTRY]["attr"] = "data-css-testapp-rewritten"
    path.write_text(json.dumps(document), encoding="utf-8")
    import os

    stamp = path.stat().st_mtime + 10
    os.utime(path, (stamp, stamp))  # mtime resolution is coarser than this test is fast

    assert first["attr"] == PAGE_ATTR
    assert manifest.lookup(ENTRY)["attr"] == "data-css-testapp-rewritten"


def test_an_unreadable_manifest_is_not_fatal(testapp, output_dir):
    build.build_app(testapp)
    manifest.clear_cache()
    manifest.manifest_path(output_dir).write_text("{not json", encoding="utf-8")
    assert manifest.lookup(ENTRY) is None


# -------------------------------------------------------------------------- write


def test_write_replaces_previous_entries(testapp, output_dir):
    build.build_app(testapp)
    assert manifest.lookup(ENTRY) is not None

    manifest.write(output_dir, [])
    assert manifest.lookup(ENTRY) is None
    assert json.loads(manifest.manifest_path(output_dir).read_text(encoding="utf-8"))["entries"] == {}


def test_write_skips_an_empty_manifest_for_an_app_with_no_bundles(tmp_path):
    path = manifest.write(tmp_path / "unused", [])
    assert not path.exists()


def test_entries_are_sorted_for_a_stable_diff(tmp_path):
    def record(entry):
        return BundleRecord(entry=entry, bundle="b.css", attr="a", sources=[], source_mtime=0.0)

    manifest.write(tmp_path, [record("z/page.html"), record("a/page.html")])
    document = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert list(document["entries"]) == ["a/page.html", "z/page.html"]
