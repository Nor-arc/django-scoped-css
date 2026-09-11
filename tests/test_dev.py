"""P3: dev.ensure_fresh — the AUTO_COMPILE freshness gate."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from scoped_css import build, dev, discovery, manifest


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "page.css"
    path.write_text(".a{}")
    return path


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / "page.abc12345.css").write_text("/* built */")
    return "testapp/scoped_css/page.abc12345.css"


def record_for(source, bundle, *, mtime_offset=0.0):
    return {
        "bundle": bundle,
        "attr": "data-css-testapp-page",
        "sources": [str(source)],
        "source_mtime": os.path.getmtime(source) + mtime_offset,
    }


# --------------------------------------------------------------------------- is_stale


def test_no_manifest_record_is_stale():
    assert dev.is_stale(None) is True


def test_a_record_without_a_source_mtime_is_stale():
    assert dev.is_stale({"bundle": "a/b.css", "sources": []}) is True


def test_a_fresh_record_is_not_stale(tmp_path, source, bundle):
    assert dev.is_stale(record_for(source, bundle), tmp_path) is False


def test_a_touched_source_is_stale(tmp_path, source, bundle):
    record = record_for(source, bundle, mtime_offset=-10)
    assert dev.is_stale(record, tmp_path) is True


def test_a_deleted_source_is_stale(tmp_path, source, bundle):
    record = record_for(source, bundle)
    source.unlink()
    assert dev.is_stale(record, tmp_path) is True


def test_a_missing_bundle_is_stale(tmp_path, source, bundle):
    record = record_for(source, bundle)
    (tmp_path / "page.abc12345.css").unlink()
    assert dev.is_stale(record, tmp_path) is True


def test_the_bundle_check_is_skipped_without_an_output_dir(tmp_path, source, bundle):
    (tmp_path / "page.abc12345.css").unlink()
    assert dev.is_stale(record_for(source, bundle)) is False


# ----------------------------------------------------------------------- ensure_fresh


@pytest.fixture
def app():
    return SimpleNamespace(label="testapp", path="/nonexistent/testapp")


@pytest.fixture
def wired(monkeypatch, app, tmp_path):
    """Point discovery + build at fakes; return the list build_app() records calls into."""
    app_templates = SimpleNamespace(
        app=app,
        templates_dir=tmp_path,
        output_dir=tmp_path,
        templates={"testapp/page.html": SimpleNamespace(name="testapp/page.html")},
        entries=["testapp/page.html"],
    )
    built: list = []
    monkeypatch.setattr(discovery, "participating_apps", lambda: [app])
    monkeypatch.setattr(discovery, "scan", lambda a: app_templates)
    monkeypatch.setattr(build, "build_app", lambda a, **kw: built.append(a) or [])
    return built


def test_ensure_fresh_rebuilds_the_owning_app_when_stale(monkeypatch, wired, app):
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    dev.ensure_fresh("testapp/page.html")
    assert wired == [app]


def test_ensure_fresh_does_nothing_when_the_bundle_is_current(monkeypatch, wired, tmp_path, source, bundle):
    monkeypatch.setattr(manifest, "lookup", lambda name: record_for(source, bundle))
    dev.ensure_fresh("testapp/page.html")
    assert wired == []


def test_ensure_fresh_rebuilds_after_a_source_is_touched(monkeypatch, wired, app, source, bundle):
    monkeypatch.setattr(manifest, "lookup", lambda name: record_for(source, bundle, mtime_offset=-10))
    dev.ensure_fresh("testapp/page.html")
    assert wired == [app]


def test_ensure_fresh_ignores_a_template_no_participating_app_owns(monkeypatch, wired):
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    dev.ensure_fresh("someotherapp/page.html")
    assert wired == []


def test_ensure_fresh_swallows_a_failing_build(monkeypatch, wired):
    def explode(app, **kwargs):
        raise RuntimeError("compiler is on fire")

    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    monkeypatch.setattr(build, "build_app", explode)
    dev.ensure_fresh("testapp/page.html")  # must not raise into the render


def test_ensure_fresh_swallows_a_failing_discovery(monkeypatch):
    def explode():
        raise RuntimeError("no apps for you")

    monkeypatch.setattr(discovery, "participating_apps", explode)
    dev.ensure_fresh("testapp/page.html")


def test_ensure_fresh_isolates_one_unscannable_app(monkeypatch, app, tmp_path):
    """A broken app must not hide the app that actually owns the entry."""
    broken = SimpleNamespace(label="broken", path="/nonexistent/broken")
    good = SimpleNamespace(
        app=app,
        output_dir=tmp_path,
        templates={},
        entries=["testapp/page.html"],
    )

    def scan(a):
        if a is broken:
            raise RuntimeError("unreadable")
        return good

    built: list = []
    monkeypatch.setattr(discovery, "participating_apps", lambda: [broken, app])
    monkeypatch.setattr(discovery, "scan", scan)
    monkeypatch.setattr(manifest, "lookup", lambda name: None)
    monkeypatch.setattr(build, "build_app", lambda a, **kw: built.append(a) or [])

    dev.ensure_fresh("testapp/page.html")
    assert built == [app]


def test_ensure_output_dirs_creates_each_participating_app_output_dir(settings, tmp_path):
    settings.SCOPED_CSS = {"OUTPUT_DIR": str(tmp_path)}
    from scoped_css import dev

    dev.ensure_output_dirs()
    assert (tmp_path / "testapp" / "scoped_css").is_dir()


def test_app_ready_creates_output_dirs_when_auto_compile(settings, tmp_path):
    """Django's AppDirectoriesFinder snapshots app static/ dirs once; ready() must run first."""
    settings.SCOPED_CSS = {"OUTPUT_DIR": str(tmp_path), "AUTO_COMPILE": True}
    from django.apps import apps

    apps.get_app_config("scoped_css").ready()
    assert (tmp_path / "testapp" / "scoped_css").is_dir()


def test_app_ready_leaves_disk_alone_when_auto_compile_off(settings, tmp_path):
    settings.SCOPED_CSS = {"OUTPUT_DIR": str(tmp_path), "AUTO_COMPILE": False}
    from django.apps import apps

    apps.get_app_config("scoped_css").ready()
    assert not (tmp_path / "testapp").exists()
