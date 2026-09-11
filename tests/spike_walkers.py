"""P0 spike: two candidate implementations of the template-graph walk.

Not library code. These live under tests/ on purpose: the spike compares them so that
``scoped_css/graph.py`` can be written once, against the winner.

A1 -- walk the parsed ``Template.nodelist`` recursively via each node's ``child_nodelists``.
A2 -- walk ``django.template.base.Lexer(source).tokenize()`` and read BLOCK tokens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from django.template.base import Lexer, TokenType

try:  # Django >= 3.0 keeps it here; guarded because it is not a documented API.
    from django.template.loader_tags import construct_relative_path
except ImportError:  # pragma: no cover
    from django.template.base import construct_relative_path

# --------------------------------------------------------------------------- shared


@dataclass
class SpikeNode:
    """What both approaches are expected to extract from one template."""

    name: str
    extends: str | None = None
    extends_dynamic: str | None = None  # raw expression when {% extends %} is not a literal
    includes: list[str] = field(default_factory=list)
    css_deps: list[str] = field(default_factory=list)
    dynamic_includes: list[str] = field(default_factory=list)  # raw expressions
    has_scope_tag: bool = False


def _unquote(bit: str) -> str | None:
    """Return the string literal inside ``bit``, or None when ``bit`` is an expression."""
    if len(bit) >= 2 and bit[0] in "\"'" and bit[-1] == bit[0]:
        return bit[1:-1]
    return None


# ------------------------------------------------------------------------------- A1


def analyze_a1(name: str) -> SpikeNode:
    """Approach A1: load through the engine and recurse over ``child_nodelists``.

    Requires a configured Django engine *and* that every ``{% load %}``ed tag library in the
    template (and in every template it extends) is importable.
    """
    from django.template.loader import get_template
    from django.template.loader_tags import ExtendsNode, IncludeNode

    from scoped_css.templatetags.scoped_css import CSSDepNode, CSSScopeNode

    node = SpikeNode(name=name)
    template = get_template(name).template

    def literal(filter_expression) -> str | None:
        # FilterExpression.var is a plain ``str`` for a quoted literal, a ``Variable`` otherwise.
        # Filters applied to a literal (e.g. |default:"x") make it non-literal for our purposes.
        if isinstance(filter_expression.var, str) and not filter_expression.filters:
            return filter_expression.var
        return None

    def walk(nodelist):
        for n in nodelist:
            if isinstance(n, ExtendsNode):
                parent = literal(n.parent_name)
                if parent is None:
                    node.extends_dynamic = str(n.parent_name.token)
                else:
                    node.extends = parent
            elif isinstance(n, IncludeNode):
                target = literal(n.template)
                if target is None:
                    node.dynamic_includes.append(str(n.template.token))
                else:
                    node.includes.append(target)
            elif isinstance(n, CSSDepNode):
                node.css_deps.append(n.path)
            elif isinstance(n, CSSScopeNode):
                node.has_scope_tag = True
            for attr in n.child_nodelists:
                child = getattr(n, attr, None)
                if child:
                    walk(child)

    walk(template.nodelist)
    return node


# ------------------------------------------------------------------------------- A2

_SKIP_TAGS = {"verbatim", "endverbatim"}


def analyze_a2(source: str, name: str) -> SpikeNode:
    """Approach A2: lex the raw source. No engine, no settings, no tag libraries."""
    node = SpikeNode(name=name)
    # Django's do_comment is ``parser.skip_past("endcomment")`` -- comments do NOT nest, so a
    # boolean (not a depth counter) reproduces the engine's behaviour exactly.
    in_comment = False

    for token in Lexer(source).tokenize():
        # The Lexer already downgrades everything between {% verbatim %} and {% endverbatim %}
        # to TEXT tokens, so verbatim spans cost us nothing beyond ignoring the fence tags.
        if token.token_type is not TokenType.BLOCK:
            continue
        try:
            bits = token.split_contents()
        except ValueError:  # unterminated string literal in a tag
            continue
        if not bits:
            continue
        tag = bits[0]

        # {% comment %} .. {% endcomment %} spans are *not* handled by the Lexer.
        if tag == "endcomment":
            in_comment = False
            continue
        if in_comment:
            continue
        if tag == "comment":
            in_comment = True
            continue
        if tag in _SKIP_TAGS:
            continue

        if tag in ("extends", "include", "css_dep") and len(bits) >= 2:
            # Resolve "./x.html" / "../x.html" exactly the way do_include/do_extends do.
            raw = construct_relative_path(name, bits[1], allow_recursion=tag == "include")
            target = _unquote(raw)
            if tag == "extends":
                if target is None:
                    node.extends_dynamic = bits[1]
                else:
                    node.extends = target
            elif tag == "include":
                if target is None:
                    node.dynamic_includes.append(bits[1])
                else:
                    node.includes.append(target)
            elif target is not None:
                node.css_deps.append(target)
        elif tag == "css_scope":
            node.has_scope_tag = True

    return node


def analyze_a2_path(path: Path, name: str) -> SpikeNode:
    return analyze_a2(path.read_text(encoding="utf-8"), name)


# ---------------------------------------------------------------- extends fallback

_DEFAULT_FILTERS = ("|default:", "|default_if_none:")


def extends_default_fallback(expression: str) -> str | None:
    """Recover a static parent from ``{% extends var|default:"base_django.html" %}``.

    The fixture app -- and the Nautobot interim documented in ARCHITECTURE.md -- swaps the root
    template through a context variable, so the ``{% extends %}`` in ``base.html`` is *not* a
    literal. The literal argument of a trailing ``default`` filter is the static answer.
    """
    for marker in _DEFAULT_FILTERS:
        if marker in expression:
            return _unquote(expression.rsplit(marker, 1)[1].strip())
    return None


# ------------------------------------------------------------------- closure helper


def include_closure_a2(root_name: str, resolve) -> tuple[dict[str, SpikeNode], list[str]]:
    """DFS the literal include/css_dep/extends closure of ``root_name`` using A2.

    ``resolve(name)`` returns a Path for a template we own, or None for one we cannot see
    (e.g. a Nautobot core template). Returns ``(nodes, unresolved)``.
    """
    nodes: dict[str, SpikeNode] = {}
    unresolved: list[str] = []
    stack = [root_name]
    while stack:
        name = stack.pop(0)
        if name in nodes or name in unresolved:
            continue
        path = resolve(name)
        if path is None:
            unresolved.append(name)
            continue
        node = analyze_a2_path(path, name)
        nodes[name] = node
        stack.extend(node.includes)
        stack.extend(node.css_deps)
        if node.extends:
            stack.append(node.extends)
    return nodes, unresolved
