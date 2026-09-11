"""P1: the compiler test matrix from ARCHITECTURE.md, plus the golden example-app stylesheets."""

import pathlib
from typing import NamedTuple

import pytest

from scoped_css.compiler import CompileError, Report, transform

ATTR = "data-css-t"

GOLDEN = pathlib.Path(__file__).parent / "golden"
GOLDEN_INPUT = GOLDEN / "input"
GOLDEN_EXPECTED = GOLDEN / "expected"


def compile_css(css, attr=ATTR, source_name="t.css", **kwargs):
    """Transform and return only the output text."""
    out, _ = transform(css, attr, source_name=source_name, **kwargs)
    return out


# ======================================================================================
# Matrix: comma list
# ======================================================================================


def test_comma_list_prefixes_each_selector_independently():
    assert compile_css(".a, .b { color: red }") == (
        "[data-css-t] .a, [data-css-t].a, [data-css-t] .b, [data-css-t].b { color: red }"
    )


def test_comma_list_keeps_the_authors_line_breaks():
    assert compile_css(".a:hover,\n.b:focus { color: red }") == (
        "[data-css-t] .a:hover, [data-css-t].a:hover,\n[data-css-t] .b:focus, [data-css-t].b:focus { color: red }"
    )


def test_comma_inside_is_is_not_a_selector_boundary():
    assert compile_css(":is(.a, .b) .c { }") == "[data-css-t] :is(.a, .b) .c, [data-css-t]:is(.a, .b) .c { }"


def test_comma_inside_where_is_not_a_selector_boundary():
    assert compile_css(".c:where(.a, .b) { }") == "[data-css-t] .c:where(.a, .b), [data-css-t].c:where(.a, .b) { }"


def test_comma_inside_an_attribute_selector_is_not_a_selector_boundary():
    assert compile_css('[title="a, b"] { }') == '[data-css-t] [title="a, b"], [data-css-t][title="a, b"] { }'


# ======================================================================================
# Matrix: combinators and pseudos
# ======================================================================================


@pytest.mark.parametrize("combinator", [">", "+", "~"])
def test_combinators_survive_intact(combinator):
    css = f".a {combinator} .b {{ }}"
    assert compile_css(css) == f"[data-css-t] .a {combinator} .b, [data-css-t].a {combinator} .b {{ }}"


def test_descendant_combinator_survives_intact():
    assert compile_css(".a .b .c { }") == "[data-css-t] .a .b .c, [data-css-t].a .b .c { }"


def test_pseudo_class_and_pseudo_element_are_untouched():
    assert compile_css(".x:checked + .y::after { }") == (
        "[data-css-t] .x:checked + .y::after, [data-css-t].x:checked + .y::after { }"
    )


def test_functional_pseudo_class_is_untouched():
    assert compile_css(".a:not(.b) .c { }") == "[data-css-t] .a:not(.b) .c, [data-css-t].a:not(.b) .c { }"


# ======================================================================================
# Matrix: declarations are never rewritten
# ======================================================================================


def test_content_string_that_looks_like_a_selector_is_not_rewritten():
    assert compile_css('.tile::after { content: ".tile"; }') == (
        '[data-css-t] .tile::after, [data-css-t].tile::after { content: ".tile"; }'
    )


def test_attribute_selector_value_is_not_rewritten():
    assert compile_css('[class*="tile"] { }') == '[data-css-t] [class*="tile"], [data-css-t][class*="tile"] { }'


def test_custom_property_declaration_is_untouched():
    assert compile_css(".card { --bs-card-border-color: var(--bs-primary); }") == (
        "[data-css-t] .card, [data-css-t].card { --bs-card-border-color: var(--bs-primary); }"
    )


def test_url_value_is_untouched():
    css = ".a { background: url(\"data:image/svg+xml,%3Csvg xmlns='http://x'/%3E\"); }"
    assert compile_css(css) == (
        "[data-css-t] .a, [data-css-t].a { background: url(\"data:image/svg+xml,%3Csvg xmlns='http://x'/%3E\"); }"
    )


def test_important_and_hex_colors_are_untouched():
    assert compile_css(".a { color: #6610F2 !important; }") == (
        "[data-css-t] .a, [data-css-t].a { color: #6610F2 !important; }"
    )


# ======================================================================================
# Matrix: comments
# ======================================================================================


def test_comment_between_rules_is_preserved_verbatim():
    assert compile_css("/* .card note */\n.a { }") == "/* .card note */\n[data-css-t] .a, [data-css-t].a { }"


def test_comment_inside_a_declaration_block_is_preserved_verbatim():
    assert compile_css(".a { font-size: 1rem; /* 16px */ }") == (
        "[data-css-t] .a, [data-css-t].a { font-size: 1rem; /* 16px */ }"
    )


def test_comment_leading_a_selector_stays_outside_the_prefix():
    assert compile_css("/* c */ .a { }") == "/* c */ [data-css-t] .a, [data-css-t].a { }"


# ======================================================================================
# Matrix: at-rules
# ======================================================================================


def test_media_block_is_recursed_into():
    css = "@media (hover: hover) {\n    .a:hover { color: red }\n}"
    assert compile_css(css) == (
        "@media (hover: hover) {\n    [data-css-t] .a:hover, [data-css-t].a:hover { color: red }\n}"
    )


def test_comment_inside_a_media_block_is_preserved():
    css = "@media (hover: hover) {\n  /* only selectable cards lift */\n  .a { }\n}"
    assert compile_css(css) == (
        "@media (hover: hover) {\n  /* only selectable cards lift */\n  [data-css-t] .a, [data-css-t].a { }\n}"
    )


def test_media_nested_inside_supports_is_recursed_into_at_both_levels():
    css = "@supports (display: grid) {\n    @media (min-width: 768px) {\n        .a { }\n    }\n}"
    assert compile_css(css) == (
        "@supports (display: grid) {\n"
        "    @media (min-width: 768px) {\n"
        "        [data-css-t] .a, [data-css-t].a { }\n"
        "    }\n"
        "}"
    )


def test_supports_block_is_recursed_into():
    assert compile_css("@supports (display: grid) { .a { } }") == (
        "@supports (display: grid) { [data-css-t] .a, [data-css-t].a { } }"
    )


def test_container_block_is_recursed_into():
    assert compile_css("@container card (min-width: 20rem) { .a { } }") == (
        "@container card (min-width: 20rem) { [data-css-t] .a, [data-css-t].a { } }"
    )


def test_block_form_layer_is_recursed_into():
    assert compile_css("@layer base { .a { } }") == "@layer base { [data-css-t] .a, [data-css-t].a { } }"


def test_statement_form_layer_is_passed_through_verbatim():
    assert compile_css("@layer base, components;") == "@layer base, components;"


def test_keyframes_percentage_selectors_are_untouched():
    css = "@keyframes fade {\n    0% { opacity: 0 }\n    100% { opacity: 1 }\n}"
    assert compile_css(css) == css


def test_keyframes_with_from_and_to_are_untouched():
    css = "@keyframes fade { from { opacity: 0 } to { opacity: 1 } }"
    assert compile_css(css) == css


def test_font_face_is_untouched():
    css = '@font-face { font-family: "X"; src: url("x.woff2"); }'
    assert compile_css(css) == css


def test_property_at_rule_is_untouched():
    css = '@property --x { syntax: "<color>"; inherits: false; initial-value: red; }'
    assert compile_css(css) == css


def test_string_quote_style_is_normalised_by_the_serializer():
    """tinycss2 re-serializes every string with double quotes, even in passed-through at-rules.

    Semantically identical, but it is a byte-level change, so pin it rather than let it drift.
    """
    assert compile_css("@property --x { syntax: '<color>'; }") == '@property --x { syntax: "<color>"; }'
    assert compile_css(".a { background: url('x.png') }") == (
        '[data-css-t] .a, [data-css-t].a { background: url("x.png") }'
    )


def test_charset_is_untouched():
    css = '@charset "utf-8";'
    assert compile_css(css) == css


def test_import_passes_through_with_a_warning():
    out, report = transform('@import "other.css";\n.a { }', ATTR, source_name="t.css")
    assert out == '@import "other.css";\n[data-css-t] .a, [data-css-t].a { }'
    assert len(report.warnings) == 1
    assert "@import" in report.warnings[0]


# ======================================================================================
# Matrix: native nesting
# ======================================================================================


def test_only_the_outer_rule_of_a_nested_ruleset_is_prefixed():
    css = ".a { color: red; .b { color: blue } &:hover { color: green } }"
    assert compile_css(css) == (
        "[data-css-t] .a, [data-css-t].a { color: red; .b { color: blue } &:hover { color: green } }"
    )


def test_nested_child_combinator_selector_is_untouched():
    # `> .x` cannot appear at top level, but inside a rule body it is a relative selector
    # that must survive verbatim -- the scope comes from the prefixed parent.
    css = ".a { > .x { color: red } }"
    assert compile_css(css) == "[data-css-t] .a, [data-css-t].a { > .x { color: red } }"


def test_nested_media_inside_a_rule_body_is_untouched():
    css = ".a { @media (min-width: 768px) { color: red } }"
    assert compile_css(css) == "[data-css-t] .a, [data-css-t].a { @media (min-width: 768px) { color: red } }"


# ======================================================================================
# Matrix: type / universal selectors get no self-match form
# ======================================================================================


def test_type_selector_gets_the_descendant_form_only():
    assert compile_css("div.card { }") == "[data-css-t] div.card { }"


def test_bare_type_selector_gets_the_descendant_form_only():
    assert compile_css("a:hover { }") == "[data-css-t] a:hover { }"


def test_universal_selector_gets_the_descendant_form_only():
    assert compile_css("* { }") == "[data-css-t] * { }"


def test_universal_selector_with_a_descendant_gets_the_descendant_form_only():
    assert compile_css("* .a { }") == "[data-css-t] * .a { }"


def test_type_selector_later_in_the_selector_still_gets_the_self_match_form():
    assert compile_css(".a div { }") == "[data-css-t] .a div, [data-css-t].a div { }"


def test_id_hash_selector_gets_both_forms():
    assert compile_css("#modal .btn { }") == "[data-css-t] #modal .btn, [data-css-t]#modal .btn { }"


def test_selector_starting_with_a_combinator_gets_the_descendant_form_only():
    # Not valid at top level, but the two forms would be identical, so emit one.
    assert compile_css("> .x { }") == "[data-css-t] > .x { }"


# ======================================================================================
# Matrix: outer-ancestor compounds (`html`, `:root`, `body`, theme attributes)
# ======================================================================================


def test_theme_attribute_gets_the_scope_attribute_inserted_after_it():
    # Golden finding #2: `[data-bs-theme]` lives on <html>, outside the scope root, so a leading
    # `[attr]` would make the rule unmatchable.
    assert compile_css('[data-bs-theme="dark"] .x { }') == '[data-bs-theme="dark"] [data-css-t] .x { }'


def test_data_theme_attribute_is_also_treated_as_an_outer_ancestor():
    assert compile_css('[data-theme="dark"] .x:hover { }') == '[data-theme="dark"] [data-css-t] .x:hover { }'


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("html .a", "html [data-css-t] .a"),
        ("html.dark .a > .b", "html.dark [data-css-t] .a > .b"),
        (":root .a", ":root [data-css-t] .a"),
        (":root.theme-x .a", ":root.theme-x [data-css-t] .a"),
        ("body .a", "body [data-css-t] .a"),
        ("body.modal-open .a", "body.modal-open [data-css-t] .a"),
        ("html[data-bs-theme] .a", "html[data-bs-theme] [data-css-t] .a"),
    ],
)
def test_outer_ancestor_compounds_keep_their_position(selector, expected):
    out, report = transform(f"{selector} {{ }}", ATTR, source_name="t.css")
    assert out == f"{expected} {{ }}"
    assert report.warnings == []


def test_outer_ancestor_match_is_case_insensitive():
    assert compile_css("BODY .a { }") == "BODY [data-css-t] .a { }"


def test_outer_ancestor_never_gets_a_self_match_form():
    assert (
        compile_css(
            '[data-bs-theme="dark"] .x { }',
        )
        == '[data-bs-theme="dark"] [data-css-t] .x { }'
    )
    assert compile_css(".x { }") == "[data-css-t] .x, [data-css-t].x { }"


def test_outer_ancestor_combinator_keeps_the_attribute_between_the_two():
    assert compile_css("html > .x { }") == "html [data-css-t] > .x { }"


def test_outer_ancestor_does_not_contribute_its_own_classes():
    # `dark` is host chrome, not app markup, so it must not land in the dead-CSS class set.
    _, report = transform("body.dark .a { }", ATTR, source_name="t.css")
    assert report.classes == {"a"}


@pytest.mark.parametrize("selector", [":root", "html", "body", "html.dark", '[data-bs-theme="dark"]'])
def test_bare_outer_compound_is_passed_through_with_a_warning(selector):
    out, report = transform(f"{selector} {{ color: red }}", ATTR, source_name="t.css")
    assert out == f"{selector} {{ color: red }}"
    assert len(report.warnings) == 1
    assert "left unscoped" in report.warnings[0]


def test_bare_outer_compound_contributes_no_classes():
    _, report = transform("html.dark { }", ATTR, source_name="t.css")
    assert report.classes == set()


def test_only_the_bare_outer_selector_in_a_comma_list_is_skipped():
    out, report = transform("body, .a { }", ATTR, source_name="t.css")
    assert out == "body, [data-css-t] .a, [data-css-t].a { }"
    assert len(report.warnings) == 1


def test_outer_selector_word_later_in_the_selector_is_prefixed_normally():
    assert compile_css(".a body { }") == "[data-css-t] .a body, [data-css-t].a body { }"


def test_class_that_merely_starts_with_an_outer_name_is_not_an_outer_compound():
    assert compile_css(".html .a { }") == "[data-css-t] .html .a, [data-css-t].html .a { }"


def test_outer_selectors_can_be_overridden():
    out, report = transform(".theme-dark .x { }", ATTR, source_name="t.css", outer_selectors=[".theme-dark"])
    assert out == ".theme-dark [data-css-t] .x { }"
    assert report.warnings == []


def test_empty_outer_selectors_disables_outer_handling():
    out, _ = transform('[data-bs-theme="dark"] .x { }', ATTR, source_name="t.css", outer_selectors=[])
    assert out == '[data-css-t] [data-bs-theme="dark"] .x, [data-css-t][data-bs-theme="dark"] .x { }'


# ======================================================================================
# Non-outer attribute selectors: prefixed normally, but flagged
# ======================================================================================


def test_non_outer_attribute_first_compound_is_prefixed_with_a_warning():
    out, report = transform("[data-foo] .x { }", ATTR, source_name="t.css")
    assert out == "[data-css-t] [data-foo] .x, [data-css-t][data-foo] .x { }"
    assert len(report.warnings) == 1
    assert "[data-foo]" in report.warnings[0]
    assert "OUTER_SELECTORS" in report.warnings[0]


def test_attribute_selector_later_in_the_selector_is_not_flagged():
    _, report = transform('.a [data-foo="x"] { }', ATTR, source_name="t.css")
    assert report.warnings == []


# ======================================================================================
# Matrix: self_match=False
# ======================================================================================


def test_self_match_false_emits_descendant_forms_only():
    assert compile_css(".a, div.b { }", self_match=False) == "[data-css-t] .a, [data-css-t] div.b { }"


def test_self_match_false_across_a_media_block():
    css = "@media (min-width: 768px) {\n    .a:hover { }\n}"
    assert compile_css(css, self_match=False) == "@media (min-width: 768px) {\n    [data-css-t] .a:hover { }\n}"


def test_self_match_false_leaves_outer_and_bare_outer_handling_unchanged():
    out, report = transform('[data-bs-theme="dark"] .x { }\nbody { }', ATTR, source_name="t.css", self_match=False)
    assert out == '[data-bs-theme="dark"] [data-css-t] .x { }\nbody { }'
    assert len(report.warnings) == 1


def test_self_match_true_is_the_default():
    assert compile_css(".a { }") == "[data-css-t] .a, [data-css-t].a { }"


# ======================================================================================
# Matrix: idempotency guard
# ======================================================================================


def test_already_compiled_input_raises_compile_error():
    with pytest.raises(CompileError) as excinfo:
        transform("[data-css-app-page] .a { }", ATTR, source_name="page.module.css")
    assert excinfo.value.source_name == "page.module.css"
    assert "page.module.css" in str(excinfo.value)


def test_already_compiled_input_inside_a_media_block_raises_compile_error():
    with pytest.raises(CompileError):
        transform("@media (min-width: 1px) { [data-css-x] .a { } }", ATTR, source_name="t.css")


def test_transforming_output_a_second_time_raises_rather_than_double_prefixing():
    once = compile_css(".a, .b { color: red }")
    with pytest.raises(CompileError):
        transform(once, ATTR, source_name="t.css")


def test_a_non_scope_attribute_selector_is_not_mistaken_for_compiled_output():
    assert compile_css('[data-widget="x"] .a { }') == (
        '[data-css-t] [data-widget="x"] .a, [data-css-t][data-widget="x"] .a { }'
    )


def test_an_outer_attribute_selector_is_not_mistaken_for_compiled_output():
    assert compile_css('[data-bs-theme="dark"] .a { }') == '[data-bs-theme="dark"] [data-css-t] .a { }'


# ======================================================================================
# Matrix: degenerate input
# ======================================================================================


def test_empty_file_produces_empty_output():
    out, report = transform("", ATTR, source_name="t.css")
    assert out == ""
    assert report.classes == set()
    assert report.warnings == []


def test_whitespace_only_file_is_preserved():
    assert compile_css("\n\n  \n") == "\n\n  \n"


def test_comments_only_file_is_preserved():
    css = "/* one */\n\n/* two */\n"
    assert compile_css(css) == css


def test_rule_with_an_empty_prelude_does_not_crash():
    assert compile_css("{ color: red }") == "{ color: red }"


def test_empty_slot_in_a_comma_list_does_not_crash():
    assert compile_css(".a, { }") == "[data-css-t] .a, [data-css-t].a, { }"


def test_truncated_input_that_tinycss2_reports_as_an_error_raises_compile_error():
    # tinycss2 auto-closes most unbalanced input; a selector with no block at all is a real error.
    with pytest.raises(CompileError) as excinfo:
        transform(".a, .b", ATTR, source_name="broken.css")
    assert excinfo.value.source_name == "broken.css"
    assert "parse error" in str(excinfo.value)


def test_unclosed_block_is_auto_closed_by_tinycss2_rather_than_rejected():
    # Documenting tinycss2's error recovery: the missing `}` is synthesised, not reported.
    assert compile_css("@media (hover: hover) { .a { } ") == (
        "@media (hover: hover) { [data-css-t] .a, [data-css-t].a { } }"
    )


# ======================================================================================
# Report
# ======================================================================================


def test_report_carries_the_source_name():
    _, report = transform(".a { }", ATTR, source_name="thing.module.css")
    assert isinstance(report, Report)
    assert report.source_name == "thing.module.css"


def test_report_collects_class_names_from_prefixed_preludes():
    css = ".a > .b, .c:hover .d { }\n@media (min-width: 1px) { .e { } }"
    _, report = transform(css, ATTR, source_name="t.css")
    assert report.classes == {"a", "b", "c", "d", "e"}


def test_report_collects_class_names_from_inside_functional_pseudo_classes():
    _, report = transform(":is(.a, .b):not(.c) { }", ATTR, source_name="t.css")
    assert report.classes == {"a", "b", "c"}


def test_report_does_not_collect_class_names_from_declarations_or_attribute_values():
    _, report = transform('[class*="tile"] { content: ".ghost"; }', ATTR, source_name="t.css")
    assert report.classes == set()


def test_report_has_no_warnings_for_ordinary_input():
    _, report = transform(".a { }\n@media (min-width: 1px) { .b { } }", ATTR, source_name="t.css")
    assert report.warnings == []


# ======================================================================================
# Golden files: whole stylesheets from the example app, compiled end to end
# ======================================================================================

#: The app the golden stylesheets belong to; the scope attribute is derived from it.
GOLDEN_APP_LABEL = "example_app"


class GoldenCase(NamedTuple):
    self_match: bool
    warnings: int


#: How each golden is compiled, and how many warnings it is expected to produce.
#:
#: Page-scope files (``self_match=False``) are compiled the way the bundler compiles a page: the
#: scope root is the host's ``<main>``, which never carries app classes, so self-match forms
#: would be dead weight. ``widget_tile.css`` belongs to a partial that carries its own
#: ``{% css_scope %}``, so it compiles under element scope and *does* get the self-match forms.
GOLDEN_CASES = {
    "add_widget_modal.css": GoldenCase(self_match=False, warnings=0),
    "edge_cases.css": GoldenCase(self_match=False, warnings=3),
    "theme_and_media.css": GoldenCase(self_match=False, warnings=0),
    "widget_list.css": GoldenCase(self_match=False, warnings=0),
    "widget_tile.css": GoldenCase(self_match=True, warnings=0),
}
GOLDEN_NAMES = sorted(GOLDEN_CASES)


def golden_attr(name):
    return f"data-css-{GOLDEN_APP_LABEL}-{pathlib.Path(name).stem}"


def compile_golden(name):
    source = (GOLDEN_INPUT / name).read_text(encoding="utf-8")
    return transform(source, golden_attr(name), source_name=name, self_match=GOLDEN_CASES[name].self_match)


def test_every_golden_input_is_wired_into_a_case():
    assert sorted(p.name for p in GOLDEN_INPUT.glob("*.css")) == GOLDEN_NAMES


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_golden_file_matches_byte_for_byte(name):
    out, _ = compile_golden(name)
    assert out == (GOLDEN_EXPECTED / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_golden_file_output_is_not_recompilable(name):
    expected = (GOLDEN_EXPECTED / name).read_text(encoding="utf-8")
    with pytest.raises(CompileError):
        transform(expected, golden_attr(name), source_name=name, self_match=GOLDEN_CASES[name].self_match)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_golden_file_warning_count_is_pinned(name):
    _, report = compile_golden(name)
    assert len(report.warnings) == GOLDEN_CASES[name].warnings


def test_golden_warnings_are_all_bare_outer_selectors():
    """`edge_cases.css` is the only golden that warns: two bare outer rules, one in a comma list."""
    _, report = compile_golden("edge_cases.css")
    assert [w for w in report.warnings if "left unscoped" in w] == report.warnings


@pytest.mark.parametrize("name", [n for n in GOLDEN_NAMES if not GOLDEN_CASES[n].self_match])
def test_page_scope_golden_has_no_self_match_forms(name):
    expected = (GOLDEN_EXPECTED / name).read_text(encoding="utf-8")
    assert f"[{golden_attr(name)}]." not in expected
    assert f"[{golden_attr(name)}]#" not in expected


def test_element_scope_golden_carries_both_forms():
    """The one element-scope golden pins the other half of the matrix."""
    attr = golden_attr("widget_tile.css")
    expected = (GOLDEN_EXPECTED / "widget_tile.css").read_text(encoding="utf-8")
    assert f"[{attr}] .widget-tile.card, [{attr}].widget-tile.card {{" in expected
    # ... except after a type selector, which never gets the self-match form.
    assert f"[{attr}] div.card > .card-header {{" in expected
    assert f"[{attr}]div.card" not in expected


def test_golden_theme_rule_stays_matchable():
    """Golden review finding #2: the dark-mode rule must keep `[data-bs-theme]` outermost."""
    name = "theme_and_media.css"
    expected = (GOLDEN_EXPECTED / name).read_text(encoding="utf-8")
    assert f'[data-bs-theme="dark"] [{golden_attr(name)}] .widget-card:hover {{' in expected
    assert f'[{golden_attr(name)}] [data-bs-theme="dark"]' not in expected


def test_golden_escape_decoding_is_pinned():
    """tinycss2 decodes CSS string escapes on the round trip: `content: "\\2713"` -> `content: "✓"`.

    Semantically identical for a UTF-8 stylesheet, but it is a real byte-level change to a
    declaration value, so pin it rather than let it drift silently.
    """
    name = "add_widget_modal.css"
    assert '"\\2713"' in (GOLDEN_INPUT / name).read_text(encoding="utf-8")
    expected = (GOLDEN_EXPECTED / name).read_text(encoding="utf-8")
    assert 'content: "✓";' in expected
    assert "\\2713" not in expected


def test_golden_quote_normalisation_is_pinned():
    """The other byte-level change tinycss2 makes to a declaration: `'x'` -> `"x"`."""
    name = "add_widget_modal.css"
    assert "'Helvetica Neue'" in (GOLDEN_INPUT / name).read_text(encoding="utf-8")
    expected = (GOLDEN_EXPECTED / name).read_text(encoding="utf-8")
    assert '"Helvetica Neue"' in expected
    assert "'Helvetica Neue'" not in expected


if __name__ == "__main__":  # pragma: no cover - regeneration helper
    for _name in GOLDEN_NAMES:
        _out, _report = compile_golden(_name)
        (GOLDEN_EXPECTED / _name).write_text(_out, encoding="utf-8")
        print(f"regenerated {_name}: {len(_report.classes)} classes, {len(_report.warnings)} warnings")
