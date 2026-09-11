# scoped_css — Architecture

Vite-shaped CSS for Django apps, built for Nautobot apps, in pure Python.

Colocate a stylesheet with the template that uses it. The build discovers it through the
template graph, compiles scoped rules that cannot escape the page or partial they belong to,
bundles one file per page, and delivers one `<link>`. By default the author writes **no
declarations in templates at all** — only files.

## Purpose and non-goals

**Purpose.** Django namespaces everything an app ships except CSS. Two apps on one page share
one global selector namespace with Bootstrap and the host. Authors respond with prefix
conventions (`acme-`) that decay, and unscoped framework overrides (`.card { border: none }`)
that leak into markup they don't own. This library gives app CSS the namespace Django never
did, mechanically, at build time.

*Evidence, from the pilot app — a real Nautobot app we converted:* four competing hand-written
prefixes had accumulated across its stylesheets, and a `.card { border: none }` written for one
list view was flattening the host's own cards on every page that loaded it.

**Non-goals.**
- Class-name mangling / CSS Modules semantics. Attribute scoping is used so Bootstrap classes
  keep working verbatim and every rule gains one specificity level for free.
- A Node toolchain, HMR, or the PostCSS ecosystem. Native CSS nesting covers most SCSS wants.
- Bidirectional isolation. Framework CSS reaching *in* is desired; app CSS leaking *out* is the
  failure this prevents.

## Vocabulary

| Term | Meaning |
|---|---|
| **Entry** | A template under an app's `templates/` dir that owns a bundle. Three detectors, in the lexer walk: (a) it contains `{% extends %}` — it is a page; (b) it contains `{% scoped_css_links "<its own template name>" %}` — it declares itself a **self-contained styled unit** that delivers its own `<link>` (see *Runtime pieces*); (c) it is listed in `SCOPED_CSS["ENTRIES"]`. One bundle per entry. A template that is *only ever extended* (an in-app base) contains `{% extends %}` too, so it is detected as an entry and gets a bundle nobody links. Accepted: the cost is one unreferenced file. |
| **Self-declaring entry** | Detector (b) above: `graph.Node.declares_self_entry`. It exists for a fragment rendered inside a page the app does not own — a Nautobot `TemplateExtension` panel on a core detail view — which therefore cannot ride on any page's bundle. Because such a fragment carries `{% css_scope %}` on its own root element, its scope root is app markup that *does* carry app classes, so it compiles at `kind = "element"` (self-match forms emitted), unlike a page whose root is core's `<main>`. `scope(T)` is unchanged either way: `scope(entry) = attr(entry)`. |
| **Partial** | A template reached from an entry via `{% include "literal" %}`, `{% css_dep "literal" %}`, or — when it lives in the *same app's* `templates/` dir — `{% extends "literal" %}`. An in-app base template's colocated stylesheets and includes are part of every page that extends it (P2 gap #1 decision). Parents outside the app (`generic/object_list.html`) are edges only. |
| **Colocated stylesheet** | `X.css` or `X.module.css` beside `X.html`. `.css` is bundled verbatim (global within the page). `.module.css` is compiled: every top-level selector prefixed with a scope attribute. |
| **template_key** | Template path relative to the app's `templates/` dir, minus `.html`; a leading `<app_label>/` segment is dropped; `/` → `-`; any char outside `[a-z0-9_-]` → `_`; lowercased. `example_app/components/widget_tile.html` → `components-widget_tile`. |
| **attr(T)** | `data-css-<app_label>-<template_key(T)>`. Valueless HTML attribute; matched by presence. |
| **scope(T)** | Which attribute T's `.module.css` compiles under. If T contains `{% css_scope %}` → `attr(T)`. Else → `scope(includer)`. The entry is its own root: `scope(entry) = attr(entry)`. A partial reached from includers with different scopes compiles once per distinct scope. |
| **Page attribute** | `attr(entry)`. Stamped on the page's content wrapper — see *Delivery*. |

Why attribute scoping and why the attribute is an *ancestor*: compiled `[attr] .tile` and
`[attr].tile` both have specificity (0,2,0) against Bootstrap's `.tile` (0,1,0), so overrides
win outright instead of by load order; and everything below the attribute is in scope, so
nested includes inherit their page's scope with no wiring.

## Delivery

Two lines in the host's root template, both emitted from the manifest keyed by the entry
template name (`context.template.name` — Django sets this to the top-level template for the
whole render):

```django
{% scoped_css_links %}          {# <link rel="stylesheet" href="…/<entry>.<hash>.css"> #}
{% block extra_styles %}{% endblock %}

<main id="main-content" {% css_scope_page %}>   {# data-css-<app>-<entry_key> #}
    {% block content %}{% endblock %}
</main>
```

**Compatibility rule for the core PR:** emit `{% scoped_css_links %}` *before*
`{% block extra_styles %}`, never inside it. That block is empty in core today, so every app
overriding it does so without `{{ block.super }}`; placing output inside would silently drop
it for all of them.

**Until the core change ships**, the Nautobot interim (`scoped_css.nautobot.ScopedCSSMixin`)
sets `context["root_template"] = "scoped_css/root.html"`, which extends
`SCOPED_CSS["ROOT_PARENT"]` (default `base_django.html`) and overrides `extra_styles` to emit
the links. It cannot stamp `<main>` — that element is literal text in `base_django.html`, and a
template between `base.html` and `base_django.html` cannot override a block the leaf already
defines (`content` is defined by every page). So in the interim the author places
`{% css_scope %}` on the outermost element of the entry's `{% block content %}`. One line per
page, deleted when core stamps `<main>`.

## Runtime pieces

- **`{% css_scope %}`** — argument-free. Emits `attr(T)` where T is the template the tag is
  *written in*, taken at parse time from `self.origin.template_name` (the parser sets
  `Node.origin`). Do **not** use `context.render_context.template`: P0 proved it is wrong inside
  `{% block %}` under `{% extends %}` — `ExtendsNode.render` pushes the root of the extends chain,
  so it reports `base_django.html` exactly where authors place the tag. `origin.name` is the
  absolute path, which discovery maps to the owning app. Output is `mark_safe`. Never raises at
  render time.
- **`{% css_scope_page %}`** — emits `attr(entry)` for `context.template.name`. Used by the host
  root template on the content wrapper.
- **`{% scoped_css_links %}`** / **`{% scoped_css_links "app/entry.html" %}`** — manifest lookup by
  `context.template.name`, or by the **optional explicit entry argument** when one is given; emits
  one `<link>` per bundle via `{% static %}`. If `AUTO_COMPILE` is on, first calls
  `dev.ensure_fresh(entry)`. Emits nothing (no error) when the entry has no bundle.
  **At most once per request per entry:** the set of already-emitted entries is parked on
  `context["request"]` (falling back to `context.request`); with no request in the context — a bare
  `Template.render(Context({}))`, a management command — there is nothing to dedupe against and
  every call emits, which is the pre-existing behaviour.
  *Why the argument and the dedupe exist:* a `TemplateExtension` panel renders inside a **core**
  view. Neither `ScopedCSSMixin` nor the page's scope root is the app's, and `context.template.name`
  is a core template with no bundle — so until the core change lands the panel must name its own
  entry and deliver its `<link>` from inside `<body>`, which is valid HTML5. One page can render
  the same panel many times (once per row, once per tab), and the dedupe is what keeps that to one
  `<link>`. Naming itself is also what makes the panel template an entry (see *Vocabulary*), so the
  two features are one feature seen from the runtime and the build side.
- **`{% css_dep "path.html" %}`** — renders nothing; a build-time graph edge. Used for HTMX
  fragments and dynamic includes, the equivalent of Vite's dynamic-import hint.
- **`scoped_css.nautobot.ScopedCSSMixin`** — Nautobot-signature
  `get_extra_context(self, request, instance=None)` that sets `root_template`.

## Build pieces

- **`discovery`** — per app (all installed, or `SCOPED_CSS["APPS"]`): templates dir is
  `<app_config.path>/templates`; output dir is `<app_config.path>/static/<app_label>/scoped_css/`.
  Same location in dev (editable install, written on demand) and prod (prebuilt into the wheel).
  Colocated lookup, entry detection (`graph.Node.is_entry` — the three detectors in *Vocabulary*),
  template_key/attr derivation.
- **`graph`** — **lexer walk, not nodelist walk** (P0 verdict A2). `Lexer(source).tokenize()`
  needs no configured engine and no importable tag libraries, so it runs in CI, at wheel build,
  and over a Nautobot app without booting Nautobot (a nodelist walk fails on the first
  `{% load helpers %}`). Rules: consider only `TokenType.BLOCK`; `split_contents()` in
  `try/except ValueError`; track `{% comment %}…{% endcomment %}` with a **boolean** (comments do
  not nest — `do_comment` is `skip_past`); `{% verbatim %}` needs nothing (the Lexer already
  emits its body as TEXT); a target is literal iff it starts and ends with the same quote char,
  else record a dynamic include (`W002`) with the raw expression; run literal targets through
  `django.template.loader_tags.construct_relative_path` (guard the import — undocumented API);
  `{% extends var|default:"x.html" %}` resolves to the default literal (this is `base.html`'s
  real form); a `scoped_css_links` BLOCK token whose quoted literal equals the template's own name
  sets `declares_self_entry` (`allow_recursion=True` on `construct_relative_path` — naming *itself*
  is the point, and it raises without it). Templates outside the app's own `templates/` dir (e.g. `generic/object_retrieve.html`)
  are recorded as edges but never scanned or bundled. Includes inside `{% if %}`/`{% for %}` are
  collected unconditionally (over-approximation, as with Vite). Keep the fixture-suite
  cross-check against a nodelist walk (`tests/spike_walkers.py`) to catch drift.
- **`compiler.transform(css, attr, *, source_name)`** — `tinycss2`-based. Prefix only
  **top-level** qualified-rule preludes; nested rules are left for the browser (`&` inherits the
  scope). Split preludes on top-level commas; for each selector emit `[attr] sel` and, when the
  selector's first compound contains no type or universal selector, also `[attr]sel`.
  Recurse into `@media`, `@supports`, `@container`, and block-form `@layer`. Leave `@keyframes`,
  `@font-face`, `@property`, `@charset` verbatim; pass `@import` through with a warning.
  **Outer-ancestor compounds** (P1 golden review): a selector whose first compound is one of
  `outer_selectors` — default `html`, `:root`, `body`, `[data-bs-theme…]`, `[data-theme…]` — gets
  the attribute inserted *after* that compound, not before it:
  `[data-bs-theme="dark"] .x` → `[data-bs-theme="dark"] [attr] .x`. Those attributes live on
  `<html>`, outside any scope root, so a leading `[attr]` would make the rule unmatchable — and
  theme selectors are common in Nautobot apps. A selector that is *only* an outer compound
  (`body { }`) is left unprefixed with a warning. **`self_match`** kwarg (default `True`): when
  `False`, emit the descendant form only. The bundler passes `False` for page scope — the root is
  core's `<main>`, which never carries app classes, so self-match forms are dead weight that
  doubled output in the goldens — and `True` for element scope (tagged partial). Strings,
  comments, `url()`, custom properties, and attribute-selector values are untouched by
  construction (token level); note tinycss2 re-serialization normalizes string escapes and quote
  style (`"\2713"` → `"✓"`, `'x'` → `"x"`) — semantically identical, pinned by tests.
  Idempotency: a top-level prelude already beginning with `[data-css-` raises `CompileError`.
- **`bundler.build_entry`** — order follows `graph.ordered_sources`: in-app `{% extends %}`
  ancestors first (outermost first), then the entry's own stylesheet(s), then partials in DFS
  include order. **A parent precedes its child** so the child's rules win ties at equal
  specificity — a base template is the general layer, the page extending it the specific one.
  Dedupe by `(path, scope)`; `.css` verbatim, `.module.css` transformed; concat
  with `/* source: <path> [scope: <attr>] */` banners; filename
  `<entry_key>.<sha256[:8]>.css`; delete stale bundles for the same entry.
- **`manifest`** — `<outdir>/manifest.json` (each source also records its scope attr and kind):
  ```json
  {"version": 1,
   "entries": {"example_app/widget_retrieve.html":
     {"bundle": "example_app/scoped_css/widget_retrieve.3f9a1c2d.css",
      "attr": "data-css-example_app-widget_retrieve",
      "sources": ["…/widget_retrieve.css", "…/inc/add_widget_modal.module.css"],
      "source_mtime": 1757600000.0}}}
  ```
  In-process cache; in dev, invalidated when the file's mtime changes.
- **`dev.ensure_output_dirs()`** — called from `AppConfig.ready()` when `AUTO_COMPILE` is on. Django's
  `AppDirectoriesFinder` enumerates each app's `static/` dir exactly once (first use, `os.path.isdir`), so an
  app whose only static content is compiled CSS would 404 its first on-demand bundle until a restart. Found
  live: the example app's panel bundle compiled fine and served 404 until the server restarted.
- **`dev.ensure_fresh(entry)`** — when `AUTO_COMPILE` (default `settings.DEBUG`): rebuild the
  entry if any source mtime exceeds `source_mtime`, or the bundle is missing.
- **`checks`** — `scoped_css.W001` entry has colocated CSS but no bundle (production);
  `W002` dynamic include encountered; `W003` orphan stylesheet unreachable from any entry.
- **`compile_css`** management command — `--app LABEL` (repeatable), `--check` (exit 1 if any
  bundle is stale or missing; for CI), `--list` (print graph).

## Settings

```python
SCOPED_CSS = {
    "APPS": None,  # None = every app with colocated CSS
    "ENTRIES": {},  # {"app_label": ["extra/template.html"]}
    "AUTO_COMPILE": None,  # None → settings.DEBUG
    "ROOT_PARENT": "base_django.html",
    "OUTER_SELECTORS": ["html", ":root", "body", "[data-bs-theme", "[data-theme"],  # prefix match on first compound
    "OUTPUT_DIR": None,  # test/CI escape hatch, see below
}
```

`OUTPUT_DIR` (absolute path) redirects every app's bundles to `<OUTPUT_DIR>/<app_label>/scoped_css/`
instead of `<app.path>/static/<label>/scoped_css/`. The manifest's `bundle` value is unchanged
(`<label>/scoped_css/<file>`), so **files written under `OUTPUT_DIR` are not servable by
staticfiles** and a rendered `<link>` to them would 404. It exists so concurrent test processes get
a private `tmp_path` instead of racing on the shared fixture dir; never set it in a deployment.

## Test fixtures model both host states

`tests/testapp/templates/base_django.html` is the host **after** the core PR: `{% scoped_css_links %}`
emitted before `{% block extra_styles %}`, and `{% css_scope_page %}` on `<main id="main-content">`.
`tests/testapp/templates/legacy_host.html` is the host **before** it: neither. Interim-mixin tests set
`SCOPED_CSS["ROOT_PARENT"] = "legacy_host.html"` so the two delivery stories are proven separately and
never double-emit a `<link>`. `tests/testapp/templates/testapp/page3.html` carries **no** scoped_css
tag at all: it proves the zero-template-edit state against the post-PR host.
`tests/testapp/templates/testapp/panels/self_entry.html` is the third state: a fragment on a page
the app does not own, which names itself in `{% scoped_css_links %}` and so becomes an entry with
`kind = "element"`.

Tests never write into — nor edit anything inside — the shared fixture tree. The `output_dir`
fixture redirects builds via `SCOPED_CSS["OUTPUT_DIR"]` (test-only escape hatch → `tmp_path`), and
the `mutable_templates` fixture hands a test its own `copytree` of `templates/` with
`discovery.templates_dir` monkeypatched at it. Both exist because concurrent pytest processes
otherwise raced: the old `rmtree` of the shared output dir, and a test that rewrote
`inc/modal.module.css` to prove a rebuild, which could leave the fixture permanently corrupted.

## Repository layout

```
scoped_css/
  apps.py conf.py naming.py discovery.py graph.py compiler.py bundler.py
  manifest.py dev.py checks.py nautobot.py
  templatetags/scoped_css.py
  templates/scoped_css/root.html
  management/commands/compile_css.py
tests/
  settings.py conftest.py
  testapp/            fixture app: templates + colocated css + fake base_django.html
  golden/             input/ + expected/ whole stylesheets, compiled byte-for-byte
  test_*.py
  test_example_app.py build verification for examples/example_app, without Nautobot
examples/
  example_app/        a real, runnable Nautobot app; not installed, not imported by the tests
```

`examples/example_app` mirrors how Nautobot core ships its own `examples/example_app`. It is the
worked example for every feature here — including the `TemplateExtension` panel, the only case an
app cannot own its page. `tests/test_example_app.py` scans, graphs and bundles it from a
`SimpleNamespace` AppConfig, which works precisely because the graph is a lexer walk (P0 verdict
A2) and needs no engine, no tag libraries and no Nautobot.

Quality gates: `ruff check .`, `ruff format --check .`, `pytest`. Python ≥3.10, Django ≥4.2,
tinycss2 ≥1.3.

## Phases

| Phase | Scope | Gate |
|---|---|---|
| **P0 spike** | Prove two load-bearing assumptions against the fixture app and, read-only, against the pilot app (a real Nautobot app, converted alongside this one): (a) the graph walk via Django's parser finds every include and the `css_scope` node; (b) `render_context.template.name` is correct *inside* an `{% include %}`. | Both proven with tests; findings appended to this file under *Spike findings*. Gates P2 and P3. |
| **P1 compiler** | `compiler.py` against the full test matrix below plus golden files. Independent of P0. | Matrix green. |
| **P2 build** | `discovery.py`, `graph.py`, `bundler.py`, `manifest.py`. | Fixture app builds to a correct bundle + manifest; the pilot app's templates dry-run to scratch. |
| **P3 runtime** | templatetags, `dev.py`, `checks.py`, `nautobot.py` + `root.html`, `compile_css`. | End-to-end: render fixture page → one `<link>`, correct attribute on wrapper and on tagged partial. |
| **P4 integration** | Cross-module tests, README with the author walkthrough, dry-run conversion report for the pilot app. | `pytest`, `ruff` clean; README complete. |

### Compiler test matrix (P1 definition of done)

| Case | Input | Expectation |
|---|---|---|
| Comma list | `.a, .b` | each prefixed independently |
| Combinators | `.a > .b`, `.a + .b`, `.a ~ .b` | whole selector prefixed, combinators intact |
| Pseudo | `.x:checked + .y::after` | prefixed; pseudo-elements untouched |
| Content string | `content: ".tile"` | not rewritten |
| Attribute value | `[class*="tile"]` | value not rewritten |
| Custom property | `--bs-card-border-color` | untouched |
| Comment | `/* .card note */` | preserved verbatim |
| Nested at-rule | `@media (hover: hover)` | recursed; inner rules prefixed |
| Native nesting | `.a { .b {} &:hover {} }` | only `.a` prefixed; nested untouched |
| Keyframes | `@keyframes f { 0% {} }` | percentage selectors untouched |
| Type selector | `div.card` | descendant form only; no `[attr]div.card` |
| Outer ancestor | `[data-bs-theme="dark"] .x` | `[data-bs-theme="dark"] [attr] .x` — attr inserted after the outer compound |
| Bare outer | `body { }`, `:root { }` | warning; passed through unprefixed |
| self_match=False | `.a, div.b` | descendant forms only |
| Idempotency | already-compiled input | `CompileError`, not double-prefixed |
| Degenerate | empty file; comments only | valid output, no crash |
| Golden files | whole example-app stylesheets | byte-for-byte match with hand-reviewed fixtures, four at page scope (`self_match=False`) and one at element scope |

## Spike findings

_P0, run against Django 5.2.17 / Python 3.13. Tests: `tests/test_spike_graph.py`,
`tests/test_spike_render_context.py`; both candidate walkers in `tests/spike_walkers.py`. The
findings below were confirmed by a read-only dry run over **the pilot app** — a real Nautobot
app converted alongside this library — which is not part of this repository; the tests keep the
same properties pinned against the fixture app._

### 1. Assumption A — graph from Django's parser. **PROVEN. Verdict: A2 (lexer walk).**

Both approaches produce identical `(extends, includes, css_deps, has_scope_tag)` for every
fixture template (`test_a1_and_a2_agree_on_every_fixture_template`), so the choice is not about
accuracy — it is about what each one *requires*.

**A1 (nodelist walk) — rejected as the primary.** It needs a configured engine **and** every
`{% load %}`ed tag library importable, transitively through `{% extends %}`. Pointing a real
`Engine` at a Nautobot app's templates dir raises `TemplateSyntaxError: 'helpers' is not a
registered tag library` before any node is reachable — and `helpers` only exists inside
Nautobot. So A1 cannot analyse a Nautobot app unless the whole Nautobot stack is booted, which
rules it out for `--check` in CI, for wheel-time prebuilds, and for any app whose libraries
depend on the app being installed. A1 also propagates `TemplateSyntaxError` for a template that
merely *looks* broken to it, aborting the build for one bad file.

**A2 (lexer walk) — recommended.** `Lexer(source).tokenize()` needs no settings, no engine, no
app registry: verified by running it in a process where `django.conf.settings.configured` is
`False`, against the pilot app's real templates. It reads any `.html` on disk, and degrades
rather than raising on templates it cannot fully parse.

**A1 stays useful as a cross-check**, not as the engine of `graph.py`: in the fixture app's own
test suite it is cheap and catches drift in A2's tag recognition. Keep the agreement test.

Recommended `graph.py`:

- Walk `Lexer(path.read_text()).tokenize()`; consider only `TokenType.BLOCK`; `token.split_contents()`
  inside `try/except ValueError` (unterminated string literal) and skip on failure.
- **Comment spans:** track `{% comment %}` … `{% endcomment %}` with a **boolean, not a depth
  counter** — Django's `do_comment` is `parser.skip_past("endcomment")`, so comments do *not*
  nest and the first `endcomment` closes the span. Confirmed load-bearing on real code: one of
  the pilot app's HTMX fragments has a `{% comment %}` block immediately above a real
  `{% include %}`, and one of its modal partials opens with a 9-line comment block.
- **Verbatim spans:** no work needed. The `Lexer` already downgrades everything between
  `{% verbatim %}` and `{% endverbatim %}` to `TEXT` tokens; just ignore the two fence tags.
  `{# … #}` is a `COMMENT` token and is skipped by the `BLOCK`-only filter.
- **Relative paths:** run `bits[1]` through `django.template.loader_tags.construct_relative_path`
  before unquoting, so `{% include "./x.html" %}` resolves the same way `do_include` resolves it.
  Guard the import — it is not a documented API and has moved between modules.
- **Literal vs dynamic:** literal iff the bit starts and ends with the same quote char. Anything
  else is a dynamic include → `W002` warning carrying the raw expression, never silently dropped.
- **Include options:** `with x=1` / `only` never affect target detection (`bits[1]` is always the
  template). Verified against the eight `{% include … with … only %}` calls in one of the pilot
  app's modal partials.
- Over-approximate on purpose: includes inside `{% if %}`/`{% for %}` are collected unconditionally.

Realism run over the pilot app (read-only, 21 templates): **zero dynamic includes in the whole
app** — every `{% include %}` target was a literal. The full closure of its detail page is 6 app
templates (the page plus five modal partials) and one Nautobot-core parent
(`generic/object_retrieve.html`), correctly recorded as an edge and not traversed. Two further
partials are *not* in that closure: they arrive by `hx-get`, are invisible to any static walk,
and are precisely the case `{% css_dep %}` exists for. Templates outside the app's own
`templates/` dir must be recorded as edges but never scanned or bundled.

### 2. Assumption B — argument-free `{% css_scope %}`. **PARTIALLY DISPROVEN.**

Observed, for a `{% css_scope %}` written in `testapp/page.html`'s `{% block content %}` where
`page.html` → `base.html` → `base_django.html`:

| Expression | Value |
|---|---|
| `context.render_context.template.name` | **`base_django.html`** — *not* `testapp/page.html` |
| `context.template.name` | `testapp/page.html` (correct, constant for the whole render) |
| `self.origin.template_name` | `testapp/page.html` (correct) |
| `self.origin.name` | `/…/tests/testapp/templates/testapp/page.html` (absolute) |

`render_context.template` is correct **inside `{% include %}`** — page.html then
`components/tile.html` ×3, identical for plain, `… only` (renders via `context.new()`, whose
shallow copy shares the same `RenderContext` and `template`) and `… with x=1` (via
`context.push()`), and identical with or without a `RequestFactory` request. But it is **wrong
inside `{% block %}` under `{% extends %}`**: `ExtendsNode.render` ends with
`context.render_context.push_state(compiled_parent, isolated_context=False)`, so while the
leaf's block body executes, `render_context.template` is the **root of the extends chain**.

This matters because it is exactly the position the interim in *Delivery* prescribes ("the
author places `{% css_scope %}` on the outermost element of the entry's `{% block content %}`").
Shipping `render_context.template` would stamp every page with
`data-css-<app>-base_django`, collapsing all pages in all apps into one scope — a silent,
total failure of the isolation this library exists to provide.

**Correction to the spec.** `{% css_scope %}` must use **`self.origin.template_name`**, fixed at
parse time by `Parser.extend_nodelist` on every `Node`. It is lexically correct in all four
positions tested (entry block, plain include, `only`, `with`), needs no context at all, and
therefore cannot raise. Update the *Runtime pieces* bullet accordingly. The one degenerate case:
a `Template` built from a string has `origin.template_name is None` and
`origin.name == "<unknown source>"` — emit nothing rather than raising.

`context.template.name` **is** confirmed as the entry key for `{% scoped_css_links %}` and
`{% css_scope_page %}`, including when those tags sit in `base_django.html`: it stays
`testapp/page.html` for the whole render.

`origin.name` is an absolute filesystem path, so `discovery` can map it to the owning app by
prefix-matching `app_config.path`; `origin.template_name` is the loader-relative name and is the
right thing to use as the graph/manifest key.

### 3. Other contradictions with the spec above

- **`{% extends %}` is not always literal.** `tests/testapp/templates/base.html` is
  `{% extends root_template|default:"base_django.html" %}` — the interim's own root-swap
  mechanism. Neither A1 nor A2 can treat it as a literal parent (A1: `FilterExpression.var` is a
  `Variable` *and* `.filters` is non-empty; a literal with filters applied must also count as
  dynamic). `graph.py` needs a documented fallback so the chain terminates: read the literal
  argument of a trailing `default` / `default_if_none` filter, else fall back to
  `SCOPED_CSS["ROOT_PARENT"]`. With that fallback the chain is
  `testapp/page.html → base.html → base_django.html → ∅`.
- **`FilterExpression.var` is `str` for a literal, but only checking that is not enough** — the
  spec's rule (`node.template.var` is a `str`) must be ANDed with `not node.template.filters`.
- A1 raises `TemplateSyntaxError` on a template A2 still reads
  (`testapp/spike/broken/nested_comment.html`); whichever approach is used, the build must
  isolate failures per template rather than aborting the app.
- Custom tags that render templates (Nautobot's own helpers) are invisible to *both* approaches.
  `{% css_dep %}` is the only escape hatch; `W002`/`W003` are how authors find out.
