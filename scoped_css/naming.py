"""Deterministic names shared by the compiler (CSS side) and the template tags (HTML side).

Both sides must compute identical strings from identical inputs; there is no lookup table.
"""

import re

_UNSAFE = re.compile(r"[^a-z0-9_-]")


def template_key(app_label: str, relative_template_path: str) -> str:
    """`example_app/components/widget_tile.html` (in app example_app) -> `components-widget_tile`.

    relative_template_path is relative to the app's templates/ dir. Drop a leading `<app_label>/`
    segment, strip `.html`, `/` -> `-`, anything outside [a-z0-9_-] -> `_`, lowercase.
    """
    key = relative_template_path.replace("\\", "/").strip("/")
    prefix = f"{app_label}/"
    if key.startswith(prefix):
        key = key[len(prefix) :]
    if key.lower().endswith(".html"):
        key = key[: -len(".html")]
    # Lowercase before the unsafe sweep, so `Foo` becomes `foo` rather than `___`.
    key = key.lower().replace("/", "-")
    return _UNSAFE.sub("_", key)


def scope_attr(app_label: str, key: str) -> str:
    """`data-css-<app_label>-<key>`. Valueless attribute; CSS matches on presence."""
    return f"data-css-{_UNSAFE.sub('_', app_label.lower())}-{key}"
