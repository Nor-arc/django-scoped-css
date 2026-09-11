"""Template dependency graph via Django's own lexer (no regex over template source).

P0 verdict A2: walk ``Lexer(source).tokenize()`` and read BLOCK tokens. This needs no configured
engine and no importable tag libraries, so it runs in CI, at wheel build time, and over a Nautobot
app without booting Nautobot -- a nodelist walk dies on the first ``{% load helpers %}``.
``tests/spike_walkers.py`` keeps the rejected nodelist walk (A1) alive as a fixture-suite
cross-check against drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from django.template.base import Lexer, TokenType

from .discovery import AppTemplates
from .naming import scope_attr, template_key

try:  # Django >= 3.0 keeps it here; guarded because it is not a documented API.
    from django.template.loader_tags import construct_relative_path
except ImportError:  # pragma: no cover
    try:
        from django.template.base import construct_relative_path
    except ImportError:  # pragma: no cover

        def construct_relative_path(current_name, relative_name, allow_recursion=False):
            return relative_name


#: Fences the Lexer already handles for us (it emits the enclosed body as TEXT tokens).
_SKIP_TAGS = frozenset({"verbatim", "endverbatim"})

#: Filters whose literal argument is a usable static parent for a dynamic ``{% extends %}``.
_DEFAULT_FILTERS = ("|default:", "|default_if_none:")

#: Scope kinds recorded on every ordered source.
KIND_PAGE = "page"
KIND_ELEMENT = "element"


@dataclass
class Node:
    name: str
    includes: list[str] = field(default_factory=list)  # literal {% include %} and {% css_dep %} targets
    extends: str | None = None  # literal {% extends %} parent
    has_scope_tag: bool = False  # contains {% css_scope %}
    dynamic_includes: int = 0  # {% include var %} occurrences (warned)
    # --- detail the four scalars above cannot carry -------------------------------------
    css_deps: list[str] = field(default_factory=list)  # subset of `includes` reached via {% css_dep %}
    extends_dynamic: str | None = None  # raw expression when {% extends %} is not a literal
    dynamic_expressions: list[str] = field(default_factory=list)  # raw {% include var %} expressions
    link_targets: list[str] = field(default_factory=list)  # literal {% scoped_css_links "x" %} arguments
    declares_self_entry: bool = False  # contains {% scoped_css_links "<its own name>" %}

    @property
    def has_extends(self) -> bool:
        """True for any ``{% extends %}``, literal or not -- one of the two things that makes an entry."""
        return self.extends is not None or self.extends_dynamic is not None

    @property
    def is_entry(self) -> bool:
        """An entry is a template that carries ``{% extends %}`` *or* declares itself one.

        The second form is ``{% scoped_css_links "<its own template name>" %}``: the template says
        "I am a self-contained styled unit, and I deliver my own ``<link>``". That is what a
        ``TemplateExtension`` panel needs -- it renders inside a CORE view, where neither
        ``ScopedCSSMixin`` nor the page's scope root exists, so it cannot ride on any page's
        bundle. ``SCOPED_CSS["ENTRIES"]`` remains the alternative for a template whose author
        would rather not write the tag (see ``discovery.scan``).
        """
        return self.has_extends or self.declares_self_entry


@dataclass
class EntryGraph:
    entry: str
    nodes: dict[str, Node]
    # (template_name, scope_attr, kind) in DFS order, entry first; a partial can appear under
    # several scopes. kind is "page" (scope is the entry's own attribute) or "element"
    # (a {% css_scope %}-tagged partial compiling under its own attribute).
    ordered_sources: list[tuple[str, str, str]]
    warnings: list[str]
    attr: str = ""  # the entry's page attribute
    external: list[str] = field(default_factory=list)  # edges outside the app: recorded, never scanned


# --------------------------------------------------------------------------------------
# Lexing one template
# --------------------------------------------------------------------------------------


def _unquote(bit: str) -> str | None:
    """Return the string literal inside ``bit``, or None when ``bit`` is an expression."""
    if len(bit) >= 2 and bit[0] in "\"'" and bit[-1] == bit[0]:
        return bit[1:-1]
    return None


def analyze_source(source: str, name: str) -> Node:
    """Extract the edges of one template from its raw source. No engine, no settings."""
    node = Node(name=name)
    # Django's do_comment is ``parser.skip_past("endcomment")`` -- comments do NOT nest, so a
    # boolean (not a depth counter) reproduces the engine's behaviour exactly.
    in_comment = False

    for token in Lexer(source).tokenize():
        # {# ... #} is a COMMENT token and {% verbatim %} bodies are TEXT, so the BLOCK-only
        # filter already discards both.
        if token.token_type is not TokenType.BLOCK:
            continue
        try:
            bits = token.split_contents()
        except ValueError:  # unterminated string literal in a tag
            continue
        if not bits:
            continue
        tag = bits[0]

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

        if tag == "css_scope":
            node.has_scope_tag = True
            continue
        if tag == "scoped_css_links":
            # Argument-free in the host root template (looks the entry up from
            # context.template.name) -- nothing to record. With a quoted literal equal to this
            # template's own name it is a self-declaration: see Node.is_entry.
            if len(bits) >= 2:
                # allow_recursion=True: naming *itself* is the whole point of the argument, and
                # construct_relative_path raises TemplateSyntaxError on a self-referential
                # "./x.html" without it.
                target = _unquote(construct_relative_path(name, bits[1], allow_recursion=True))
                if target is not None:
                    node.link_targets.append(target)
                    if target == name:
                        node.declares_self_entry = True
            continue
        if tag not in ("extends", "include", "css_dep") or len(bits) < 2:
            continue

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
                node.dynamic_includes += 1
                node.dynamic_expressions.append(bits[1])
            else:
                node.includes.append(target)
        elif target is not None:  # css_dep -- an edge exactly like an include
            node.includes.append(target)
            node.css_deps.append(target)

    return node


def analyze_path(path: Path, name: str) -> Node:
    """Analyze a template read from disk, memoized on (path, mtime)."""
    path = Path(path)
    try:
        stamp = path.stat().st_mtime
    except OSError:  # pragma: no cover - raced away between discovery and analysis
        return Node(name=name)
    cache_key = (str(path), name)
    cached = _ANALYSIS_CACHE.get(cache_key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    node = analyze_source(path.read_text(encoding="utf-8"), name)
    _ANALYSIS_CACHE[cache_key] = (stamp, node)
    return node


_ANALYSIS_CACHE: dict[tuple[str, str], tuple[float, Node]] = {}


def clear_cache() -> None:
    """Drop memoized template analyses (tests, and long-lived dev processes)."""
    _ANALYSIS_CACHE.clear()


def analyze_template(name: str, app_templates: AppTemplates | None = None) -> Node:
    """Analyze the template called `name` by lexing its source.

    ``app_templates`` short-circuits template resolution; without it the source is located
    through the configured Django template loaders (without parsing it).
    """
    if app_templates is not None:
        ref = app_templates.templates.get(name)
        if ref is not None:
            return analyze_path(ref.path, name)
    path = _find_source_path(name)
    if path is None:
        return Node(name=name)
    return analyze_path(path, name)


def _find_source_path(name: str) -> Path | None:
    """Locate a template on disk through the loaders, without compiling it."""
    from django.template import engines
    from django.template.backends.django import DjangoTemplates

    for backend in engines.all():
        if not isinstance(backend, DjangoTemplates):
            continue
        for loader in backend.engine.template_loaders:
            try:
                origins = loader.get_template_sources(name)
            except Exception:  # pragma: no cover - loader without filesystem origins
                continue
            for origin in origins:
                candidate = Path(origin.name)
                if candidate.is_file():
                    return candidate
    return None


def resolve_extends(node: Node) -> str | None:
    """The static parent of ``node``, including the documented dynamic-extends fallback.

    ``{% extends root_template|default:"base_django.html" %}`` -- base.html's real form, and the
    interim root-swap mechanism -- resolves to the literal argument of a trailing ``default`` /
    ``default_if_none`` filter, else to ``SCOPED_CSS["ROOT_PARENT"]``.
    """
    if node.extends:
        return node.extends
    if not node.extends_dynamic:
        return None
    for marker in _DEFAULT_FILTERS:
        if marker in node.extends_dynamic:
            literal = _unquote(node.extends_dynamic.rsplit(marker, 1)[1].strip())
            if literal:
                return literal
    from . import conf

    try:
        return conf.get("ROOT_PARENT")
    except Exception:  # pragma: no cover - settings not configured (bare dry-run)
        return None


# --------------------------------------------------------------------------------------
# Entry graphs
# --------------------------------------------------------------------------------------


def build_entry_graph(app_templates: AppTemplates, entry: str) -> EntryGraph:
    """Resolve scope(T) per ARCHITECTURE.md: own attr if has_scope_tag else includer's scope; entry is root.

    The DFS follows ``{% include %}``, ``{% css_dep %}`` and in-app ``{% extends %}`` edges -- the
    spec's definition of a *partial*. A parent that lives in this app's own templates/ dir is a
    source: its colocated stylesheets and its own includes join the closure of every entry that
    extends it. A parent outside the app (``generic/object_list.html``, ``base_django.html`` in a
    real Nautobot deployment) is recorded in ``external`` and never scanned or bundled.

    **Order: a parent's stylesheets are emitted BEFORE the child's.** The in-app base template is
    the more general layer; the page that extends it is the more specific one, and CSS breaks ties
    at equal specificity by source order, so the child must come last to be able to override its
    own base. The grandparent precedes the parent for the same reason.
    """
    label = app_templates.app.label
    entry_attr = scope_attr(label, template_key(label, entry))

    nodes: dict[str, Node] = {}
    ordered: list[tuple[str, str, str]] = []
    warnings: list[str] = []
    external: list[str] = []
    seen: set[tuple[str, str]] = set()

    def visit(name: str, inherited: str, is_entry: bool = False) -> None:
        ref = app_templates.templates.get(name)
        if ref is None:
            # Outside the app's own templates/ dir (Nautobot core, another app): an edge, no scan.
            if name not in external:
                external.append(name)
            return
        node = nodes.get(name)
        if node is None:
            node = analyze_path(ref.path, name)
            nodes[name] = node
            for expression in node.dynamic_expressions:
                warnings.append(
                    f"scoped_css.W002: dynamic include in {name}: "
                    f"{{% include {expression} %}} cannot be followed statically; "
                    f'add {{% css_dep "..." %}} for every template it can resolve to.'
                )

        if is_entry:
            # scope(entry) = attr(entry) either way. `kind` only decides whether the compiler also
            # emits self-match forms (`[attr].card` beside `[attr] .card`), and that depends on
            # what the scope root *is*. For a page it is core's <main>, which never carries the
            # app's classes, so self-match forms are dead weight. For a self-declaring entry --
            # one with no {% extends %} that carries {% scoped_css_links "<itself>" %} -- the root
            # is the fragment's own {% css_scope %}-tagged element, which does carry them.
            scope = entry_attr
            owns_its_root = node.declares_self_entry and not node.has_extends and node.has_scope_tag
            kind = KIND_ELEMENT if owns_its_root else KIND_PAGE
        elif node.has_scope_tag:
            scope, kind = scope_attr(label, ref.key), KIND_ELEMENT
        else:
            scope = inherited
            kind = KIND_PAGE if scope == entry_attr else KIND_ELEMENT

        if (name, scope) in seen:
            return
        seen.add((name, scope))

        # An in-app {% extends %} parent is a source, and goes in FIRST so the child can override
        # it. Marked before recursing: a cycle would otherwise re-enter through the parent.
        parent = resolve_extends(node)
        if parent and parent != name:
            visit(parent, scope)

        ordered.append((name, scope, kind))
        for child in node.includes:
            visit(child, scope)

    visit(entry, entry_attr, is_entry=True)
    return EntryGraph(
        entry=entry,
        nodes=nodes,
        ordered_sources=ordered,
        warnings=warnings,
        attr=entry_attr,
        external=external,
    )
