"""bundler.py: one bundle per entry, in source order, scoped per template."""

import re
from pathlib import Path

import pytest

from scoped_css import build, bundler, discovery, graph

FIXTURE_TEMPLATES = Path(__file__).parent / "testapp" / "templates"

PAGE_ATTR = "data-css-testapp-page"
TILE_ATTR = "data-css-testapp-components-tile"
ENTRY = "testapp/page.html"


@pytest.fixture
def built(testapp, output_dir):
    """The page entry's BundleRecord, freshly built."""
    records = {record.entry: record for record in build.build_app(testapp)}
    return records[ENTRY]


def _bundle_text(record):
    return record.path.read_text(encoding="utf-8")


# --------------------------------------------------------------------- composition


def test_bundle_is_written_with_a_content_hashed_name(built, output_dir):
    assert built.path.parent == output_dir
    assert re.fullmatch(r"page\.[0-9a-f]{8}\.css", built.path.name), built.path.name
    assert built.bundle == f"testapp/scoped_css/{built.path.name}"
    assert built.attr == PAGE_ATTR
    assert built.entry == ENTRY


def test_plain_css_is_bundled_verbatim(built):
    original = (FIXTURE_TEMPLATES / "testapp/page.css").read_text(encoding="utf-8").strip()
    text = _bundle_text(built)
    assert original in text
    assert "/* source: testapp/page.css */" in text


def test_page_scoped_module_css_has_no_self_match_forms(built):
    """modal.html has no {% css_scope %}: page scope, and the scope root is core's <main>."""
    text = _bundle_text(built)
    assert f"/* source: testapp/inc/modal.module.css [scope: {PAGE_ATTR}] */" in text
    assert f"[{PAGE_ATTR}] .modal-body" in text
    assert f"[{PAGE_ATTR}] .hint" in text
    assert f"[{PAGE_ATTR}].modal-body" not in text  # self-match would be dead weight
    assert f"[{PAGE_ATTR}].hint" not in text


def test_element_scoped_module_css_keeps_self_match_forms(built):
    """tile.html carries {% css_scope %}: its own attribute sits ON the element it styles."""
    text = _bundle_text(built)
    assert f"/* source: testapp/components/tile.module.css [scope: {TILE_ATTR}] */" in text
    assert f"[{TILE_ATTR}] .tile," in text
    assert f"[{TILE_ATTR}].tile" in text  # the self-match form
    assert f"[{TILE_ATTR}] .card, [{TILE_ATTR}].card" in text
    assert PAGE_ATTR not in _chunk(text, "testapp/components/tile.module.css")


def _chunk(text, source_name):
    """The bundle section belonging to one source file."""
    for part in text.split("/* source: "):
        if part.startswith(source_name):
            return part
    raise AssertionError(f"{source_name} is not in the bundle")


def test_css_dep_target_is_bundled_under_the_page_scope(built):
    text = _bundle_text(built)
    assert f"/* source: testapp/htmx/fragment.module.css [scope: {PAGE_ATTR}] */" in text
    assert f"[{PAGE_ATTR}] .cell" in text


def test_source_order_is_entry_first_then_dfs(built):
    text = _bundle_text(built)
    positions = [
        text.index("testapp/page.css"),
        text.index("testapp/components/tile.module.css"),
        text.index("testapp/inc/modal.module.css"),
        text.index("testapp/htmx/fragment.module.css"),
    ]
    assert positions == sorted(positions)
    assert [Path(p).name for p in built.sources] == [
        "page.css",
        "tile.module.css",
        "modal.module.css",
        "fragment.module.css",
    ]
    assert all(Path(p).is_absolute() for p in built.sources)


def test_each_source_records_its_scope_and_kind(built):
    assert built.source_details == [
        {
            "path": str(FIXTURE_TEMPLATES / "testapp/page.css"),
            "template": ENTRY,
            "scope": PAGE_ATTR,
            "kind": "page",
        },
        {
            "path": str(FIXTURE_TEMPLATES / "testapp/components/tile.module.css"),
            "template": "testapp/components/tile.html",
            "scope": TILE_ATTR,
            "kind": "element",
        },
        {
            "path": str(FIXTURE_TEMPLATES / "testapp/inc/modal.module.css"),
            "template": "testapp/inc/modal.html",
            "scope": PAGE_ATTR,
            "kind": "page",
        },
        {
            "path": str(FIXTURE_TEMPLATES / "testapp/htmx/fragment.module.css"),
            "template": "testapp/htmx/fragment.html",
            "scope": PAGE_ATTR,
            "kind": "page",
        },
    ]


def test_source_mtime_is_the_newest_source(built):
    assert built.source_mtime == max(Path(p).stat().st_mtime for p in built.sources)


def test_banners_use_paths_relative_to_the_templates_dir(built):
    """The content hash must not depend on where the checkout lives."""
    assert str(FIXTURE_TEMPLATES) not in _bundle_text(built)


# -------------------------------------------------------------------------- dedupe


def test_the_same_stylesheet_under_the_same_scope_is_emitted_once(testapp, output_dir):
    app_templates = discovery.scan(testapp)
    entry_graph = graph.build_entry_graph(app_templates, ENTRY)
    # Two includers of modal.html, both under the page scope.
    entry_graph.ordered_sources.append(("testapp/inc/modal.html", PAGE_ATTR, "page"))

    record = bundler.build_entry(app_templates, entry_graph)
    assert _bundle_text(record).count("source: testapp/inc/modal.module.css") == 1
    assert len(record.sources) == 4


def test_the_same_stylesheet_under_two_scopes_is_emitted_twice(testapp, output_dir):
    app_templates = discovery.scan(testapp)
    entry_graph = graph.build_entry_graph(app_templates, ENTRY)
    entry_graph.ordered_sources.append(("testapp/inc/modal.html", TILE_ATTR, "element"))

    text = _bundle_text(bundler.build_entry(app_templates, entry_graph))
    assert text.count("source: testapp/inc/modal.module.css") == 2
    assert f"[{TILE_ATTR}] .modal-body" in text
    assert f"[{PAGE_ATTR}] .modal-body" in text


# ------------------------------------------------------------------- rebuild/stale


def test_stale_bundles_for_the_same_entry_are_removed(testapp, output_dir, built):
    stale = output_dir / "page.deadbeef.css"
    stale.write_text("/* previous build */", encoding="utf-8")
    other = output_dir / "other.deadbeef.css"  # a different entry: untouched
    other.write_text("/* other entry */", encoding="utf-8")

    rebuilt = {record.entry: record for record in build.build_app(testapp)}[ENTRY]

    assert not stale.exists()
    assert other.exists()
    assert rebuilt.path.exists()
    assert sorted(p.name for p in output_dir.glob("page.*.css")) == [rebuilt.path.name]


def test_rebuilding_unchanged_sources_is_stable(testapp, output_dir, built):
    again = {record.entry: record for record in build.build_app(testapp)}[ENTRY]
    assert again.bundle == built.bundle


def test_changing_a_source_changes_the_hash_and_drops_the_old_bundle(testapp, mutable_templates):
    first = {record.entry: record for record in build.build_app(testapp)}[ENTRY]

    stylesheet = mutable_templates / "testapp/inc/modal.module.css"
    stylesheet.write_text(stylesheet.read_text(encoding="utf-8") + "\n.extra { color: red; }\n", encoding="utf-8")
    graph.clear_cache()
    changed = {record.entry: record for record in build.build_app(testapp)}[ENTRY]

    assert changed.bundle != first.bundle
    assert f"[{PAGE_ATTR}] .extra" in _bundle_text(changed)
    assert not first.path.exists()


# ------------------------------------------------------------------- degenerate


def test_an_entry_without_stylesheets_produces_no_bundle(testapp, output_dir):
    app_templates = discovery.scan(testapp)
    entry_graph = graph.build_entry_graph(app_templates, "base.html")
    assert bundler.build_entry(app_templates, entry_graph) is None


def test_losing_every_stylesheet_removes_the_previous_bundle(testapp, output_dir, built):
    app_templates = discovery.scan(testapp)
    entry_graph = graph.build_entry_graph(app_templates, ENTRY)
    entry_graph.ordered_sources.clear()

    assert bundler.build_entry(app_templates, entry_graph) is None
    assert not built.path.exists()


def test_an_uncompilable_stylesheet_does_not_lose_the_rest_of_the_bundle(testapp, mutable_templates):
    """A .module.css that is already compiled raises CompileError; the entry still builds."""
    broken = mutable_templates / "testapp/inc/modal.module.css"
    broken.write_text("[" + PAGE_ATTR + "] .already { color: red; }\n", encoding="utf-8")
    graph.clear_cache()
    warnings: list[str] = []
    record = {r.entry: r for r in build.build_app(testapp, warnings=warnings)}[ENTRY]

    text = _bundle_text(record)
    assert "modal.module.css" not in text  # dropped
    assert "tile.module.css" in text  # everything else survived
    assert any("compile twice" in w or "already" in w for w in warnings), warnings


# ------------------------------------------------------------------------- build_all


def test_build_all_covers_every_participating_app(testapp, output_dir):
    from scoped_css import manifest

    records = build.build_all()
    assert ENTRY in [record.entry for record in records]
    assert manifest.manifest_path(output_dir).is_file()
