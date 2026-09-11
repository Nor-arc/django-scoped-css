"""tinycss2-based transform: prefix every top-level selector with the scope attribute."""

from dataclasses import dataclass, field

import tinycss2

#: At-rules whose block holds rules that must themselves be scoped.
NESTED_AT_RULES = frozenset({"media", "supports", "container", "layer"})

#: Prefix of the scope attribute, used by the idempotency guard.
SCOPE_ATTR_PREFIX = "data-css-"

#: First compounds that live *outside* any scope root (on <html> or <body>). The scope attribute
#: is inserted after them instead of before, so the rule stays matchable. Matched case-insensitively
#: by prefix against the serialized first compound, so ``html`` matches ``html`` and ``html.dark``
#: but not ``.html``, and ``[data-bs-theme`` matches ``[data-bs-theme="dark"]``.
DEFAULT_OUTER_SELECTORS = ("html", ":root", "body", "[data-bs-theme", "[data-theme")

#: Selector combinators that terminate a compound selector.
_COMBINATORS = frozenset({">", "+", "~"})

#: Node types that carry no selector meaning and may be trimmed from a selector's edges.
_TRIMMABLE = frozenset({"whitespace", "comment"})

#: Component-value types that nest a token list (so commas inside them are not top level).
_BLOCK_TYPES = frozenset({"() block", "[] block", "{} block", "function"})


class CompileError(Exception):
    """A stylesheet cannot be compiled (already compiled, or unparseable)."""

    def __init__(self, source_name, message=""):
        super().__init__(source_name, message)
        self.source_name = source_name
        self.message = message

    def __str__(self):
        return f"{self.source_name}: {self.message}" if self.message else str(self.source_name)


@dataclass
class Report:
    source_name: str
    classes: set[str] = field(default_factory=set)  # class names seen in prefixed selectors
    warnings: list[str] = field(default_factory=list)  # :root/html/body, @import, etc.


@dataclass
class _Options:
    """Everything the prelude rewriter needs, threaded through the rule walk."""

    attr: str
    report: Report
    self_match: bool
    outer_selectors: tuple[str, ...]


def transform(
    css: str,
    attr: str,
    *,
    source_name: str = "<string>",
    self_match: bool = True,
    outer_selectors: list[str] | None = None,
) -> tuple[str, Report]:
    """See ARCHITECTURE.md § Build pieces → compiler, and the test matrix.

    - Prefix only top-level qualified-rule preludes. Nested rules untouched.
    - Each comma-separated selector -> `[attr] sel`, plus `[attr]sel` when the first compound
      has no type/universal selector and ``self_match`` is true.
    - A selector whose first compound matches ``outer_selectors`` gets the attribute inserted
      *after* that compound (`[data-bs-theme="dark"] [attr] .x`) and never a self-match form,
      because those compounds sit outside the scope root. A selector that is *only* such a
      compound (`body { }`) is left unprefixed with a warning.
    - Recurse into @media/@supports/@container/@layer{}. Leave @keyframes/@font-face/@property/
      @charset verbatim; @import passes through with a warning.
    - Any top-level prelude already starting with `[data-css-` -> CompileError.
    """
    report = Report(source_name=source_name)
    options = _Options(
        attr=attr,
        report=report,
        self_match=self_match,
        outer_selectors=tuple(DEFAULT_OUTER_SELECTORS if outer_selectors is None else outer_selectors),
    )
    nodes = tinycss2.parse_stylesheet(css, skip_comments=False, skip_whitespace=False)
    return _transform_nodes(nodes, options), report


# --------------------------------------------------------------------------------------
# Rule-list walking
# --------------------------------------------------------------------------------------


def _transform_nodes(nodes, options):
    """Serialize a rule list, rewriting the preludes of qualified rules found in it."""
    out = []
    for node in nodes:
        if node.type == "qualified-rule":
            prelude = _transform_prelude(node.prelude, options)
            out.append(f"{prelude}{{{tinycss2.serialize(node.content)}}}")
        elif node.type == "at-rule":
            out.append(_transform_at_rule(node, options))
        elif node.type == "error":
            raise CompileError(
                options.report.source_name,
                f"CSS parse error on line {node.source_line}: {node.message}",
            )
        else:
            # Whitespace, comments, and stray declarations: verbatim.
            out.append(tinycss2.serialize([node]))
    return "".join(out)


def _transform_at_rule(rule, options):
    """Recurse into conditional-group at-rules; pass everything else through verbatim."""
    keyword = rule.lower_at_keyword
    if keyword == "import":
        options.report.warnings.append(
            f"@import on line {rule.source_line} passed through unscoped: rules in the imported "
            f"stylesheet are not compiled."
        )
        return tinycss2.serialize([rule])
    if keyword in NESTED_AT_RULES and rule.content is not None:
        inner = tinycss2.parse_blocks_contents(rule.content, skip_comments=False, skip_whitespace=False)
        at_keyword = tinycss2.serialize_identifier(rule.at_keyword)
        prelude = tinycss2.serialize(rule.prelude)
        return f"@{at_keyword}{prelude}{{{_transform_nodes(inner, options)}}}"
    # @keyframes, @font-face, @property, @charset, statement-form @layer, unknown at-rules.
    return tinycss2.serialize([rule])


# --------------------------------------------------------------------------------------
# Prelude rewriting
# --------------------------------------------------------------------------------------


def _transform_prelude(prelude, options):
    """Rewrite one comma-separated selector list, preserving the author's own formatting."""
    pieces = []
    for part in _split_on_top_level_commas(prelude):
        lead, core, tail = _trim(part)
        if not core:
            # Degenerate: an empty prelude, or an empty slot in the comma list. Leave it alone.
            pieces.append(tinycss2.serialize(part))
            continue
        rewritten = _rewrite_selector(core, options)
        pieces.append(f"{tinycss2.serialize(lead)}{rewritten}{tinycss2.serialize(tail)}")
    return ",".join(pieces)


def _rewrite_selector(core, options):
    """Rewrite one selector (trimmed of surrounding trivia) and return its replacement text."""
    report = options.report
    if _looks_already_compiled(core):
        raise CompileError(
            report.source_name,
            f"selector on line {core[0].source_line} already begins with a "
            f"[{SCOPE_ATTR_PREFIX}…] scope attribute; refusing to compile twice.",
        )

    first, rest = _split_first_compound(core)
    first_text = tinycss2.serialize(first)

    if _matches_outer(first_text, options.outer_selectors):
        if not rest:
            # The whole selector is an outer compound (`body`, `html.dark`): nothing to scope.
            report.warnings.append(
                f"selector {first_text!r} on line {core[0].source_line} matches only an outer "
                f"ancestor, outside the scope root; left unscoped."
            )
            return first_text
        # Insert the scope attribute *after* the outer compound, so the rule stays matchable.
        _collect_classes(rest, report.classes)
        return f"{first_text} [{options.attr}]{tinycss2.serialize(rest)}"

    # `first` is empty only for a selector that opens with a combinator, which has no compound.
    if first and first[0].type == "[] block":
        report.warnings.append(
            f"selector {tinycss2.serialize(core).strip()!r} on line {core[0].source_line} starts "
            f"with attribute selector {first_text}; if that attribute lives outside the scope root "
            f"the rule will not match. Add its prefix to OUTER_SELECTORS if so."
        )

    _collect_classes(core, report.classes)
    core_text = tinycss2.serialize(core)
    forms = [f"[{options.attr}] {core_text}"]
    if options.self_match and _wants_self_match(core):
        forms.append(f"[{options.attr}]{core_text}")
    return ", ".join(forms)


def _split_on_top_level_commas(prelude):
    """Split on comma LiteralTokens at the top level.

    Commas inside parentheses, brackets, and functions (``:is(.a, .b)``) live inside a nested
    component value and are therefore never seen by this loop.
    """
    parts = [[]]
    for node in prelude:
        if _is_literal(node, ","):
            parts.append([])
        else:
            parts[-1].append(node)
    return parts


def _trim(part):
    """Split a selector into (leading trivia, selector core, trailing trivia)."""
    start, end = 0, len(part)
    while start < end and part[start].type in _TRIMMABLE:
        start += 1
    while end > start and part[end - 1].type in _TRIMMABLE:
        end -= 1
    return part[:start], part[start:end], part[end:]


def _split_first_compound(core):
    """Split a selector into (first compound, everything after it).

    The first compound ends at the first whitespace or combinator; the remainder keeps its
    original leading separator, so re-joining preserves the author's spacing.
    """
    for index, node in enumerate(core):
        if node.type == "whitespace" or (node.type == "literal" and node.value in _COMBINATORS):
            return core[:index], core[index:]
    return core, []


def _matches_outer(first_text, outer_selectors):
    """Whether a serialized first compound names an ancestor outside the scope root."""
    lowered = first_text.lower()
    return any(lowered.startswith(candidate.lower()) for candidate in outer_selectors)


def _wants_self_match(core):
    """Whether ``[attr]sel`` should be emitted alongside ``[attr] sel``.

    Not when the first compound begins with a type selector (``div.card``) or the universal
    selector (``*``) — the scope holder is an ancestor element, not a ``div``. Not when the
    selector begins with a combinator either, where the two forms would be identical.
    """
    first = core[0]
    if first.type == "ident" or _is_literal(first, "*"):
        return False
    return not (first.type == "literal" and first.value in _COMBINATORS)


def _looks_already_compiled(core):
    """Whether the selector already starts with a ``[data-css-…]`` scope attribute."""
    first = core[0]
    if first.type != "[] block":
        return False
    for node in first.content:
        if node.type in _TRIMMABLE:
            continue
        return node.type == "ident" and node.lower_value.startswith(SCOPE_ATTR_PREFIX)
    return False


def _collect_classes(nodes, classes):
    """Record every ``.name`` class token, descending into ``:is()``/``:where()`` and friends."""
    after_dot = False
    for node in nodes:
        if node.type in _BLOCK_TYPES:
            # FunctionBlock exposes its component values as ``arguments``, blocks as ``content``.
            _collect_classes(getattr(node, "content", None) or getattr(node, "arguments", None) or (), classes)
            after_dot = False
            continue
        if after_dot and node.type == "ident":
            classes.add(node.value)
        after_dot = _is_literal(node, ".")


def _is_literal(node, value):
    return node.type == "literal" and node.value == value
