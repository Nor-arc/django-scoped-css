import shutil

import pytest

from scoped_css import discovery, graph, manifest


@pytest.fixture
def testapp():
    from django.apps import apps

    return apps.get_app_config("testapp")


@pytest.fixture
def scoped_css_settings(settings):
    """Update SCOPED_CSS keys without clobbering the ones another fixture already set.

    ``settings.SCOPED_CSS = {...}`` replaces the whole dict, which would silently undo the
    ``OUTPUT_DIR`` redirect below. Call ``scoped_css_settings(KEY=value)`` instead; pytest-django's
    ``settings`` fixture still restores everything at teardown.
    """
    current = dict(getattr(settings, "SCOPED_CSS", {}) or {})

    def apply(**changes):
        current.update(changes)
        settings.SCOPED_CSS = dict(current)
        return settings.SCOPED_CSS

    apply()
    return apply


@pytest.fixture
def _clear_caches():
    for module in (manifest, discovery, graph):
        module.clear_cache()
    yield
    for module in (manifest, discovery, graph):
        module.clear_cache()


@pytest.fixture
def output_dir(tmp_path, testapp, scoped_css_settings, _clear_caches):
    """The fixture app's bundle dir, redirected into this test's own tmp_path.

    Tests must never build into ``tests/testapp/static/testapp/scoped_css/``: it is shared by
    every test process, and the ``rmtree`` that used to keep it clean raced under concurrent
    pytest runs. ``SCOPED_CSS["OUTPUT_DIR"]`` (see conf.DEFAULTS) gives each test a private dir.
    Bundles there are not servable by staticfiles, which no build-level test needs.
    """
    scoped_css_settings(OUTPUT_DIR=str(tmp_path / "scoped_css_output"))
    return discovery.output_dir(testapp)


@pytest.fixture
def mutable_templates(tmp_path, monkeypatch, testapp, output_dir):
    """A private copy of the fixture app's templates/ tree, for tests that edit it.

    ``tests/testapp/templates/`` is shared by every pytest process on the machine, so a test that
    rewrites a stylesheet to prove a rebuild — or drops a file in to prove discovery notices —
    would corrupt a concurrent run's build. ``discovery.templates_dir`` is redirected at the copy;
    every build-side consumer reads the dir through that one function.
    """
    root = tmp_path / "templates"
    shutil.copytree(discovery.templates_dir(testapp), root)
    monkeypatch.setattr(discovery, "templates_dir", lambda app: root)
    discovery.clear_cache()
    graph.clear_cache()
    return root
