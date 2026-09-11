"""Settings access. All keys optional; see ARCHITECTURE.md § Settings."""

from django.conf import settings

DEFAULTS = {
    "APPS": None,
    "ENTRIES": {},
    "AUTO_COMPILE": None,
    "ROOT_PARENT": "base_django.html",
    # None -> compiler.DEFAULT_OUTER_SELECTORS (html, :root, body, [data-bs-theme, [data-theme).
    "OUTER_SELECTORS": None,
    # Test/CI-only escape hatch. An absolute path; when set, every app's bundles are written to
    # `<OUTPUT_DIR>/<app_label>/scoped_css/` instead of `<app.path>/static/<label>/scoped_css/`.
    # The manifest's `bundle` value is unchanged (`<label>/scoped_css/<file>`), so under
    # OUTPUT_DIR the files are NOT servable by staticfiles: a rendered <link> will 404. It exists
    # so concurrent test processes get their own tmp dir instead of racing on the shared one.
    "OUTPUT_DIR": None,
}


def get(key):
    user = getattr(settings, "SCOPED_CSS", {}) or {}
    value = user.get(key, DEFAULTS.get(key))
    if key == "AUTO_COMPILE" and value is None:
        return bool(settings.DEBUG)
    return value
