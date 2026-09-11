# scoped_css

Colocate a stylesheet with the template that uses it. The build finds it through the template
graph, compiles its selectors so they cannot escape that page, bundles one CSS file per page, and
delivers one `<link>`.

Django namespaces every other thing your app ships — models, URLs, templates, static files — but
not CSS. Your `.card { border: none }` lands on the host's navbar card and on the other installed
app's cards. The usual answer is an `.acme-` prefix on every class, which works until someone
forgets. This does the namespacing for you, at build time, from ordinary CSS.

No Node, no HMR, no PostCSS. Python and `tinycss2`.

**A runnable example app lives in [`examples/example_app`](examples/example_app/).** It is a real
Nautobot app — one model, one viewset, one `TemplateExtension` panel, seven colocated stylesheets —
and its README says what each file demonstrates, how to run it, and which lines disappear after the
core change. Read it alongside this guide; §11 below covers the one case it demonstrates that this
guide otherwise does not.

---

## 1. Install

Add the dependency:

```toml
# pyproject.toml
[tool.poetry.dependencies]
scoped-css = "^0.1"
```

Add it to your app's `installed_apps` so its template tags, system checks and management command
are loaded whenever your app is:

```python
# example_app/__init__.py
from nautobot.apps import NautobotAppConfig


class ExampleAppConfig(NautobotAppConfig):
    name = "example_app"
    ...
    installed_apps = ["scoped_css"]
```

No settings are required. Every installed app that has a stylesheet sitting beside a template is
picked up automatically.

## 2. Colocate the files

Move each stylesheet next to the template that uses it, and name it after that template:

```
example_app/
├── templates/example_app/
│   ├── widget_retrieve.html
│   ├── widget_retrieve.css            ← global within this page
│   ├── widget_retrieve.module.css     ← scoped to this page
│   ├── components/
│   │   ├── widget_tile.html
│   │   └── widget_tile.module.css
│   └── inc/
│       ├── add_widget_modal.html
│       └── add_widget_modal.module.css
└── static/example_app/scoped_css/     ← build output; gitignore it
```

The two suffixes are the whole API:

| File | What happens to it | Use it for |
|---|---|---|
| `X.module.css` | every top-level selector is prefixed with a scope attribute | everything, by default |
| `X.css` | copied into the bundle **verbatim** | rules that must reach markup outside the page |

Then delete the `<link>` tags and `{% block extra_styles %}` `<style>` blocks that used to load
those files. The bundle replaces them.

## 3. Write ordinary CSS

No new syntax. Native nesting works; only the top-level selector is rewritten, so `&` keeps
meaning what it means.

```css
/* templates/example_app/components/widget_tile.module.css */
.widget-tile {
    transition: box-shadow .15s ease-in-out;
    &:hover { box-shadow: var(--bs-box-shadow-sm); }
}

.card { border: none; }              /* safe: only .card inside YOUR page */

@media (hover: hover) {
    .widget-tile:hover .preview { opacity: .9; }
}
```

compiles to

```css
[data-css-example_app-widget_retrieve] .widget-tile {
    transition: box-shadow .15s ease-in-out;
    &:hover { box-shadow: var(--bs-box-shadow-sm); }
}
[data-css-example_app-widget_retrieve] .card { border: none; }
...
```

The attribute is the *page's* — `widget_tile.module.css` inherits the scope of the page that includes
it, because `widget_tile.html` carries no `{% css_scope %}` of its own. That is the default. To give
a partial its own narrower attribute, see §8.

### When to use plain `.css` instead

Bootstrap moves some elements out of your markup. A popover or tooltip is appended to `<body>`,
outside the page's scope attribute, so a scoped rule for it would never match:

```html
<img class="widget-preview-img"
     data-bs-toggle="popover"
     data-bs-content="...">
```

```css
/* templates/example_app/widget_retrieve.css   ← plain .css, NOT .module.css */
/* Bootstrap appends the popover to <body>, outside the page scope. */
.popover-body .widget-preview-img { max-width: 22rem; }
```

Same for tooltips (`.tooltip-inner`), `<dialog>` and anything else portalled to the document root.
Rules in a plain `.css` are global — keep them few, keep them specific, and say in a comment why
they have to be.

## 4. Get the scope attribute onto the page

The compiled rules match *inside* an element carrying the page's scope attribute. Something has to
put it there.

### Today (the one-line interim)

Nautobot core does not stamp it yet, so you do two things:

```python
# example_app/views.py
from scoped_css.nautobot import ScopedCSSMixin


class WidgetUIViewSet(ScopedCSSMixin, NautobotUIViewSet):
    queryset = Widget.objects.all()
    # ... the rest of your viewset is unchanged
```

```django
{# templates/example_app/widget_retrieve.html #}
{% extends "generic/object_retrieve.html" %}
{% load scoped_css %}

{% block content %}
<div class="row" {% css_scope %}>     {# ← the one line #}
  ...
{% endblock %}
```

The mixin gets the `<link>` into the `<head>`. `{% css_scope %}` — argument-free, it knows which
template it is written in — puts the attribute on the outermost element of your content block.

### After the core change

Core emits the link and stamps `<main>`:

```django
{% scoped_css_links %}
{% block extra_styles %}{% endblock %}

<main id="main-content" {% css_scope_page %}>
    {% block content %}{% endblock %}
</main>
```

Then delete the mixin and delete the `{% css_scope %}` line. Your app ships stylesheets and
nothing else — no template edits at all. Both states are covered by the test suite
(`tests/test_nautobot_mixin.py`), and a page that still carries the interim `{% css_scope %}`
keeps working: the attribute is simply present twice.

## 5. Build

```bash
nautobot-server compile_css              # build every app
nautobot-server compile_css --app example_app
nautobot-server compile_css --list       # what would go into each bundle, and why
nautobot-server compile_css --check      # exit 1 if any bundle is stale — put this in CI
```

In development you can skip it: `SCOPED_CSS["AUTO_COMPILE"]` defaults to `settings.DEBUG`, so
editing a stylesheet and reloading the page rebuilds the bundle. Ship the bundles in your wheel
(they are written into `static/<app_label>/scoped_css/`, where `collectstatic` finds them) and run
`--check` in CI so a forgotten rebuild fails the pipeline instead of the deploy.

`manage.py check` reports three warnings worth knowing:

- **W001** — an entry has colocated CSS but no compiled bundle (production only).
- **W002** — a `{% include some_var %}` whose target cannot be resolved statically. Add
  `{% css_dep "the/template.html" %}` for each possible target.
- **W003** — a stylesheet no entry can reach. Usually a typo in the filename, or a partial that is
  only ever loaded by `hx-get` (see below).

## 6. What the browser gets

One request per page:

```html
<link rel="stylesheet" href="/static/example_app/scoped_css/widget_retrieve.3f9a1c2d.css">
```

Content-hashed, so it is immutable and cacheable forever. Inside it, one section per source file
with a banner naming where it came from and which scope it compiled under:

```css
/* source: example_app/widget_retrieve.css */
.popover-body .widget-preview-img { max-width: 22rem; }

/* source: example_app/components/widget_tile.module.css [scope: data-css-example_app-widget_retrieve] */
[data-css-example_app-widget_retrieve] .widget-tile { ... }
```

## 7. Templates the build cannot see

The graph follows `{% extends %}` and `{% include %}` with literal paths. It cannot follow an
`hx-get` — the fragment is fetched by the browser, long after the build ran. Tell it:

```django
{# widget_retrieve.html #}
{% load scoped_css %}
{% css_dep "example_app/htmx/widget_table.html" %}
```

`{% css_dep %}` renders nothing. It exists so `widget_table.module.css` joins this page's
bundle, already scoped and already loaded when the fragment is swapped in. This is the same idea
as Vite's dynamic-import hint, and it is what W002/W003 are nudging you towards.

## 8. Narrowing the scope (opt-in)

By default every stylesheet in a page's closure compiles under the **page's** attribute. That is
usually what you want: one scope, and a partial included in two places styles the same in both.

Put `{% css_scope %}` on a partial's own root element and that partial's `.module.css` compiles
under *its* attribute instead — so its rules cannot reach the rest of the page either:

```django
{# components/widget_tile.html #}
{% load scoped_css %}
<div class="widget-tile-wrapper" {% css_scope %}>
  <div class="card widget-tile">...</div>
</div>
```

Use it when a partial's rules are aggressive enough that you want them boxed in — a `.card`
override, a `td { padding: 0 }` — not routinely.

## 9. Conventions

- **Prefer your own class.** `.widget-tile { ... }` beats `.card { ... }` even inside a scope: it
  survives being moved, and it reads as intent.
- **Override a global class only for markup you don't render.** `.card`, `.table-responsive`,
  `.modal-title` are worth overriding when the element comes from a core template or a Bootstrap
  component you only configure. When *you* wrote the `<div class="card">`, add your own class to
  it instead.
- **Page scope by default.** Reach for `{% css_scope %}` on a partial only when you have a reason.
- **Keep plain `.css` for portalled markup.** Tooltips, popovers, modals moved to `<body>`. Every
  other rule belongs in `.module.css`.
- **Don't hand-write a prefix any more.** `.acme-widget-tile` and the scope attribute do the same
  job twice. Drop the prefix when you convert a file; the attribute is now the namespace.

## 10. How it works

**Attribute scoping, not class mangling.** Every compiled selector gains an ancestor:
`.widget-tile` becomes `[data-css-…] .widget-tile`. Your class names are untouched, so Bootstrap's
own classes keep working and you can read the compiled output.

**Specificity.** `[data-css-…] .card` is (0,2,0); Bootstrap's `.card` is (0,1,0). Your override
wins on specificity rather than on load order — so it does not matter whether the framework
stylesheet is loaded before or after yours.

**Self-match.** A selector whose first compound has no element type also gets an `[attr].widget-tile`
form, for the case where the scope attribute is on the very element being styled. Page-scoped
rules skip it: the page's scope root is core's `<main>`, which never carries your classes.

**Outer selectors.** A theme selector lives on `<html>`, above the scope root, so prefixing it
would make the rule unmatchable. Those get the attribute inserted *after* the outer compound:

```css
[data-bs-theme="dark"] .widget-tile { ... }
/* → */
[data-bs-theme="dark"] [data-css-…] .widget-tile { ... }
```

The default list is `html`, `:root`, `body`, `[data-bs-theme`, `[data-theme`, and is configurable
via `SCOPED_CSS["OUTER_SELECTORS"]`. A rule that is *only* an outer selector (`body { … }`) is
passed through unprefixed with a warning — it is global, and the build tells you so.

**Left alone.** `@keyframes`, `@font-face`, `@property`, `@charset`, custom properties, strings,
comments, `url()` and attribute-selector values are never rewritten. `@media`, `@supports`,
`@container` and block-form `@layer` are recursed into.

## 11. A panel on someone else's page

Everything above assumes the page is yours. A Nautobot `TemplateExtension` panel is the case where
it is not: it renders inside a **core** view, so `ScopedCSSMixin` never runs, no `<link>` reaches
the `<head>`, `context.template.name` is a core template with no bundle of yours, and there is no
scope root of yours to inherit — claiming core's `<main>` would be the very leak this library
prevents.

So the panel's template declares itself an entry, delivers its own `<link>` in-body, and owns its
scope root:

```django
{% load scoped_css %}{% scoped_css_links "example_app/panels/device_widgets.html" %}

<div class="device-widgets" {% css_scope %}>
  ...
</div>
```

`{% scoped_css_links %}` with an explicit entry argument looks that entry up instead of
`context.template.name`, and **naming yourself is also what makes the template an entry** with a
bundle of its own. The link is emitted at most once per request per entry, so the same panel
rendered once per row still produces one `<link>`. In-body `<link>` is valid HTML5, and this line
goes away once core emits the links itself.

Here `{% css_scope %}` is **required**, not the opt-in narrowing of §8 — and because the scope root
is markup you render, your rules also get the self-match form (`[attr].device-widgets`), which
page-scoped rules skip.

See [`examples/example_app/template_content.py`](examples/example_app/template_content.py) and
[`templates/example_app/panels/device_widgets.html`](examples/example_app/templates/example_app/panels/device_widgets.html).

---

See `ARCHITECTURE.md` for the full specification, the settings reference, and the spike findings
behind the design decisions, and `examples/example_app/README.md` for the worked example.
