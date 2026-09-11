"""naming.py: the one string both the CSS side and the HTML side must agree on."""

import pytest

from scoped_css.naming import scope_attr, template_key


def test_spec_example():
    """ARCHITECTURE.md § Vocabulary, verbatim."""
    assert template_key("example_app", "example_app/components/widget_tile.html") == "components-widget_tile"


def test_attr_for_the_spec_example():
    key = template_key("example_app", "example_app/widget_retrieve.html")
    assert scope_attr("example_app", key) == "data-css-example_app-widget_retrieve"


@pytest.mark.parametrize(
    ("label", "path", "expected"),
    [
        # Only a *leading* app-label segment is dropped, and only once.
        ("testapp", "testapp/page.html", "page"),
        ("testapp", "testapp/testapp/page.html", "testapp-page"),
        ("testapp", "page.html", "page"),
        # Directory separators become dashes.
        ("testapp", "testapp/inc/modal.html", "inc-modal"),
        ("testapp", "testapp/a/b/c.html", "a-b-c"),
        # Everything outside [a-z0-9_-] becomes an underscore, after lowercasing.
        ("testapp", "testapp/Add Widget.html", "add_widget"),
        ("testapp", "testapp/inc/widget.v2.html", "inc-widget_v2"),
        ("testapp", "testapp/été.html", "_t_"),
        # A template whose name merely contains the label is untouched.
        ("testapp", "other/testapp/x.html", "other-testapp-x"),
        # Not an .html file: nothing to strip.
        ("testapp", "testapp/partial.txt", "partial_txt"),
    ],
)
def test_template_key(label, path, expected):
    assert template_key(label, path) == expected


def test_key_is_a_valid_attribute_suffix():
    attr = scope_attr("testapp", template_key("testapp", "testapp/components/tile.html"))
    assert attr == "data-css-testapp-components-tile"
    assert all(c.isalnum() or c in "_-" for c in attr)


def test_distinct_templates_get_distinct_keys():
    keys = {
        template_key("testapp", name)
        for name in ("testapp/page.html", "testapp/inc/modal.html", "testapp/components/tile.html")
    }
    assert len(keys) == 3
