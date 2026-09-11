"""discovery.py: apps, templates, colocated stylesheets, entries, origin mapping."""

from pathlib import Path

import pytest

from scoped_css import discovery

FIXTURE_TEMPLATES = Path(__file__).parent / "testapp" / "templates"


@pytest.fixture(autouse=True)
def _fresh_caches():
    discovery.clear_cache()
    yield
    discovery.clear_cache()


# --------------------------------------------------------------------------- apps


def test_participating_apps_finds_apps_with_colocated_css(testapp):
    labels = [app.label for app in discovery.participating_apps()]
    assert "testapp" in labels
    # scoped_css itself ships templates/scoped_css/root.html but no colocated stylesheet.
    assert "scoped_css" not in labels


def test_participating_apps_honours_the_apps_setting(settings):
    settings.SCOPED_CSS = {"APPS": ["testapp", "does_not_exist"]}
    assert [app.label for app in discovery.participating_apps()] == ["testapp"]


def test_paths_are_derived_from_the_app_config(testapp):
    assert discovery.templates_dir(testapp) == FIXTURE_TEMPLATES
    assert discovery.output_dir(testapp) == Path(testapp.path) / "static" / "testapp" / "scoped_css"


def test_output_dir_setting_relocates_every_app(settings, testapp, tmp_path):
    """The test/CI escape hatch: one absolute root, still one dir per app label."""
    settings.SCOPED_CSS = {"OUTPUT_DIR": str(tmp_path / "out")}
    assert discovery.output_dir(testapp) == tmp_path / "out" / "testapp" / "scoped_css"


def test_output_dir_setting_does_not_change_the_static_path(settings, testapp, tmp_path):
    """The manifest's `bundle` stays `<label>/scoped_css/<file>` — which is why the relocated
    files are NOT servable by staticfiles, and why this is for tests only."""
    from scoped_css import build

    settings.SCOPED_CSS = {"OUTPUT_DIR": str(tmp_path / "out")}
    record = {r.entry: r for r in build.build_app(testapp)}["testapp/page.html"]
    assert record.bundle.startswith("testapp/scoped_css/")
    assert record.path.parent == tmp_path / "out" / "testapp" / "scoped_css"
    assert discovery.static_prefix(testapp) == "testapp/scoped_css"


# ------------------------------------------------------------------------ scanning


def test_scan_names_templates_relative_to_the_templates_dir(testapp):
    found = discovery.scan(testapp)
    assert found.templates_dir == FIXTURE_TEMPLATES
    assert "testapp/page.html" in found.templates
    assert "testapp/components/tile.html" in found.templates
    assert "base_django.html" in found.templates  # no app segment: it lives at the loader root
    ref = found.templates["testapp/page.html"]
    assert ref.path == FIXTURE_TEMPLATES / "testapp/page.html"
    assert ref.app.label == "testapp"


def test_scan_attaches_colocated_stylesheets(testapp):
    found = discovery.scan(testapp)

    page = found.templates["testapp/page.html"]
    assert page.css == FIXTURE_TEMPLATES / "testapp/page.css"
    assert page.module_css is None

    tile = found.templates["testapp/components/tile.html"]
    assert tile.css is None
    assert tile.module_css == FIXTURE_TEMPLATES / "testapp/components/tile.module.css"
    assert tile.stylesheets == [tile.module_css]

    assert found.templates["base_django.html"].stylesheets == []


def test_template_ref_exposes_key_and_attr(testapp):
    tile = discovery.scan(testapp).templates["testapp/components/tile.html"]
    assert tile.key == "components-tile"
    assert tile.attr == "data-css-testapp-components-tile"


# ------------------------------------------------------------------------- entries


def test_entries_are_templates_containing_extends(testapp):
    entries = discovery.scan(testapp).entries
    assert "testapp/page.html" in entries
    # base.html's {% extends %} is dynamic (`root_template|default:"..."`) but it is still an entry.
    assert "base.html" in entries
    assert "base_django.html" not in entries
    assert "testapp/inc/modal.html" not in entries
    assert "testapp/components/tile.html" not in entries


def test_entry_detection_uses_the_lexer_not_a_regex(testapp):
    """`{% extends %}` inside {% comment %} / {% verbatim %} is not an extends."""
    name = "testapp/spike/commented_extends.html"
    raw = (FIXTURE_TEMPLATES / name).read_text(encoding="utf-8")
    assert "{% extends" in raw  # a regex over the source would call this an entry
    assert name not in discovery.scan(testapp).entries


def test_a_self_declaring_template_is_an_entry(testapp):
    """`{% scoped_css_links "<its own name>" %}` makes an entry with no {% extends %} in sight."""
    name = "testapp/panels/self_entry.html"
    raw = (FIXTURE_TEMPLATES / name).read_text(encoding="utf-8")
    assert "{% extends" not in raw
    assert name in discovery.scan(testapp).entries


def test_declared_entries_are_added(settings, testapp):
    settings.SCOPED_CSS = {"ENTRIES": {"testapp": ["testapp/htmx/fragment.html"]}}
    entries = discovery.scan(testapp).entries
    assert "testapp/htmx/fragment.html" in entries
    assert "testapp/page.html" in entries  # extends-detected entries are kept


def test_scan_of_an_app_without_templates_is_empty(monkeypatch, testapp):
    monkeypatch.setattr(discovery, "templates_dir", lambda app: Path(app.path) / "no_such_dir")
    found = discovery.scan(testapp)
    assert found.templates == {}
    assert found.entries == []


# ---------------------------------------------------------------- origin mapping


def test_template_ref_for_origin_maps_an_absolute_path_back(testapp):
    ref = discovery.template_ref_for_origin(str(FIXTURE_TEMPLATES / "testapp/components/tile.html"))
    assert ref is not None
    assert ref.name == "testapp/components/tile.html"
    assert ref.app.label == "testapp"


def test_template_ref_for_origin_ignores_foreign_paths():
    assert discovery.template_ref_for_origin("/nowhere/base_django.html") is None
    assert discovery.template_ref_for_origin("") is None
    assert discovery.template_ref_for_origin("<unknown source>") is None


def test_template_ref_for_origin_survives_a_stale_index(testapp, mutable_templates):
    """A miss forces one rebuild, so a template added after the first call is still found."""
    discovery.template_ref_for_origin(str(mutable_templates / "testapp/page.html"))
    new = mutable_templates / "testapp/spike/_tmp_origin.html"
    new.write_text("<p>temporary</p>", encoding="utf-8")
    ref = discovery.template_ref_for_origin(str(new))
    assert ref is not None and ref.name == "testapp/spike/_tmp_origin.html"


# ------------------------------------------------------------------------ orphans


def test_orphan_stylesheets_reports_only_unmatched_files(testapp, mutable_templates):
    assert discovery.orphan_stylesheets(discovery.scan(testapp)) == []

    orphan = mutable_templates / "testapp/_tmp_orphan.module.css"
    orphan.write_text(".x {}", encoding="utf-8")
    assert discovery.orphan_stylesheets(discovery.scan(testapp)) == [orphan]
