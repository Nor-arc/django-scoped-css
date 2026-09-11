"""P3: the compile_css management command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from scoped_css import build, dev, discovery, graph, manifest
from scoped_css.graph import KIND_ELEMENT, KIND_PAGE, EntryGraph, Node


def run(*args, **options):
    out = StringIO()
    call_command("compile_css", *args, stdout=out, stderr=out, **options)
    return out.getvalue()


# --------------------------------------------------------------------------- fakes


def ref(name, *sheets):
    sheets = [Path(s) for s in sheets]
    return SimpleNamespace(name=name, stylesheets=sheets, css=None, module_css=None)


@pytest.fixture
def fake_app(monkeypatch, tmp_path):
    app = SimpleNamespace(label="testapp", path=str(tmp_path))
    app_templates = SimpleNamespace(
        app=app,
        templates_dir=tmp_path / "templates",
        output_dir=tmp_path / "static" / "testapp" / "scoped_css",
        templates={
            "testapp/page.html": ref("testapp/page.html", tmp_path / "page.css"),
            "testapp/components/tile.html": ref("testapp/components/tile.html", tmp_path / "tile.module.css"),
        },
        entries=["testapp/page.html"],
    )
    entry_graph = EntryGraph(
        entry="testapp/page.html",
        nodes={"testapp/page.html": Node(name="testapp/page.html")},
        ordered_sources=[
            ("testapp/page.html", "data-css-testapp-page", KIND_PAGE),
            ("testapp/components/tile.html", "data-css-testapp-components-tile", KIND_ELEMENT),
        ],
        warnings=["dynamic include in testapp/page.html"],
        attr="data-css-testapp-page",
    )
    monkeypatch.setattr(discovery, "participating_apps", lambda: [app])
    monkeypatch.setattr(discovery, "scan", lambda a: app_templates)
    monkeypatch.setattr(graph, "build_entry_graph", lambda at, entry: entry_graph)
    return app_templates


# ---------------------------------------------------------------------------- build


def test_default_run_builds_every_participating_app(monkeypatch, fake_app):
    built = []
    record = SimpleNamespace(
        entry="testapp/page.html",
        bundle="testapp/scoped_css/page.abc12345.css",
        sources=["/a.css", "/b.css"],
        warnings=["a compiler warning"],
    )
    monkeypatch.setattr(build, "build_app", lambda app, **kw: built.append(app) or [record])

    out = run()
    assert built == [fake_app.app]
    assert "testapp/page.html -> testapp/scoped_css/page.abc12345.css (2 source(s))" in out
    assert "a compiler warning" in out
    assert "1 bundle(s) across 1 app(s)" in out


def test_app_option_restricts_the_build(monkeypatch, fake_app):
    built = []
    monkeypatch.setattr(build, "build_app", lambda app, **kw: built.append(app) or [])
    run("--app", "testapp")
    assert built == [fake_app.app]


def test_an_unknown_app_label_is_a_command_error(fake_app):
    with pytest.raises(CommandError) as excinfo:
        run("--app", "nosuchapp")
    assert "nosuchapp" in str(excinfo.value)
    assert "testapp" in str(excinfo.value)


def test_app_is_repeatable(monkeypatch, fake_app):
    built = []
    monkeypatch.setattr(build, "build_app", lambda app, **kw: built.append(app) or [])
    run("--app", "testapp", "--app", "testapp")
    assert built == [fake_app.app, fake_app.app]


# ----------------------------------------------------------------------------- list


def test_list_prints_ordered_sources_with_their_scope_attributes(fake_app):
    out = run("--list")
    assert "entry testapp/page.html  [data-css-testapp-page]" in out
    rows = [tuple(line.split()) for line in out.splitlines() if line.startswith("      ")]
    assert rows == [
        ("testapp/page.html", "page", "page.css"),
        ("testapp/components/tile.html", "element", "[data-css-testapp-components-tile]", "tile.module.css"),
    ]
    assert "dynamic include in testapp/page.html" in out


def test_list_does_not_build(monkeypatch, fake_app):
    def explode(app, **kwargs):
        raise AssertionError("--list must not build")

    monkeypatch.setattr(build, "build_app", explode)
    run("--list")


# ---------------------------------------------------------------------------- check


def test_check_fails_when_a_bundle_is_missing(monkeypatch, fake_app):
    monkeypatch.setattr(manifest, "lookup", lambda entry: None)
    with pytest.raises(CommandError) as excinfo:
        run("--check")
    assert "testapp/page.html" in str(excinfo.value)
    assert "no bundle" in str(excinfo.value)


def test_check_fails_when_a_source_is_newer_than_the_manifest(monkeypatch, fake_app, tmp_path):
    source = tmp_path / "page.css"
    source.write_text(".a{}")
    monkeypatch.setattr(
        manifest,
        "lookup",
        lambda entry: {"bundle": "testapp/scoped_css/page.abc.css", "sources": [str(source)], "source_mtime": 0.0},
    )
    with pytest.raises(CommandError) as excinfo:
        run("--check")
    assert "stale" in str(excinfo.value)


def test_check_passes_when_everything_is_current(monkeypatch, fake_app, tmp_path):
    monkeypatch.setattr(manifest, "lookup", lambda entry: {"sources": [], "source_mtime": 1.0})
    monkeypatch.setattr(dev, "is_stale", lambda record, output_dir=None: False)
    assert "up to date" in run("--check")


def test_check_ignores_an_entry_with_no_stylesheets(monkeypatch, fake_app):
    for template_ref in fake_app.templates.values():
        template_ref.stylesheets = []
    monkeypatch.setattr(manifest, "lookup", lambda entry: None)
    assert "up to date" in run("--check")


def test_check_does_not_build(monkeypatch, fake_app):
    def explode(app, **kwargs):
        raise AssertionError("--check must not build")

    monkeypatch.setattr(build, "build_app", explode)
    monkeypatch.setattr(dev, "is_stale", lambda record, output_dir=None: False)
    run("--check")


# ------------------------------------------------------------- end to end, real app


def test_end_to_end_build_and_check_for_the_fixture_app(output_dir):
    """Build the real fixture app through the command, then prove --check is quiet."""
    out = run()
    assert "testapp/page.html ->" in out

    record = manifest.lookup("testapp/page.html")
    assert record is not None
    bundle = output_dir / Path(record["bundle"]).name
    assert bundle.exists()

    css = bundle.read_text()
    assert "data-css-testapp-components-tile" in css  # tile.module.css, element scope
    assert "data-css-testapp-page" in css  # modal/fragment .module.css, page scope
    assert ".tooltip-inner" in css  # page.css, verbatim

    # --check is quiet immediately after a build.
    assert "up to date" in run("--check")


def test_list_of_the_real_app_indents_sources_under_their_entry(output_dir):
    """--list is read by humans: one block per entry, sources indented with scope kind and files."""
    lines = run("--list").splitlines()
    assert lines[0] == "testapp (6 entries)"

    start = lines.index("  entry testapp/page2.html  [data-css-testapp-page2]")
    block = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        assert line.startswith("      "), line  # sources are indented under their entry
        block.append(tuple(line.split()))

    # The in-app {% extends %} parent's stylesheet precedes the child's (GAP 1 order).
    assert block == [
        ("base_django.html", "page", "-"),
        ("base.html", "page", "-"),
        ("testapp/base_app.html", "page", "base_app.css"),
        ("testapp/inc/modal.html", "page", "modal.module.css"),
        ("testapp/page2.html", "page", "page2.module.css"),
    ]


def test_list_names_the_scope_of_an_element_scoped_partial(output_dir):
    """A {% css_scope %}-tagged partial compiles under its own attribute; --list says so."""
    lines = run("--list").splitlines()
    tile = next(line for line in lines if "components/tile.html" in line)
    assert tile.split() == [
        "testapp/components/tile.html",
        "element",
        "[data-css-testapp-components-tile]",
        "tile.module.css",
    ]
