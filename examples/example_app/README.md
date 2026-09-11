# example_app

A small, runnable Nautobot app that uses `scoped_css` for everything it styles. It exists to be
read and to be run: every file below demonstrates exactly one thing, and the comment at the top of
each one says which.

It mirrors how Nautobot core ships `examples/example_app`: it is not installed by the library, not
imported by the library's tests, and not part of the wheel. Its build *is* verified from the
library's test suite, without Nautobot — see [Verifying the build](#verifying-the-build).

---

## What each file demonstrates

### Templates and their colocated stylesheets

| File | Demonstrates |
|---|---|
| `templates/example_app/widget_list.html` | The **interim wrapper**. Extends `generic/object_list.html` and puts `{% css_scope %}` on one `<div>` around `{{ block.super }}`, so the whole core list view is inside this page's scope. One line, deleted after the core change. |
| `…/widget_list.module.css` | Scoping **bare framework resets**: `.card { border: none }` and `.table-responsive { overflow: visible }` target wrappers *core* renders. Unscoped, they were the original bug; page-scoped, they reach this page and nothing else. Also `@keyframes` (never rewritten) and an attribute selector whose value is left alone. |
| `…/widget_retrieve.html` | The same wrapper, plus `{% include %}` of a component and a modal, plus `{% css_dep %}`. |
| `…/widget_retrieve.module.css` | Theme selectors (`[data-bs-theme="dark"]` lives on `<html>`, *above* the scope root, so the attribute is inserted **after** it), nested `@media`/`@supports`, and `@media print`. |
| `…/widget_retrieve.css` | **Plain `.css`, copied in verbatim.** Bootstrap moves a popover to the end of `<body>`, outside the page's scope root, so a compiled rule could never match it. One rule, with a comment saying why it has to be global. |
| `…/components/widget_tile.html` | **No `{% css_scope %}` — the default.** The partial inherits the scope of whichever page includes it. |
| `…/components/widget_tile.module.css` | Native CSS nesting (`&` still resolves), `@container`, and a leading type selector (`div.card > .card-header`), which gets the descendant form only. |
| `…/inc/add_widget_modal.html` | A modal partial; also inherits the page scope, because Bootstrap leaves a modal where it is in the DOM. |
| `…/inc/add_widget_modal.module.css` | **The prefix anti-pattern, retired.** Its header records that every selector here used to begin with a hand-written `.acme-` prefix, and why the scope attribute replaces it. |
| `…/htmx/widget_table.html` | A fragment that only ever arrives by `hx-get`. No static walk can see it. |
| `…/htmx/widget_table.module.css` | Reached only because `widget_retrieve.html` declares `{% css_dep "example_app/htmx/widget_table.html" %}`. Without that it is an orphan and `manage.py check` says so (W003). |
| `…/panels/device_widgets.html` | **The panel case** — see below. Begins `{% scoped_css_links "example_app/panels/device_widgets.html" %}` and carries `{% css_scope %}` on its root element. |
| `…/panels/device_widgets.module.css` | **Element scope**, with self-match forms (`[attr].device-widgets` as well as `[attr] .device-widgets`), because the scope root is markup this app renders. |

### Python

| File | Demonstrates |
|---|---|
| `__init__.py` | `ExampleAppConfig(NautobotAppConfig)` with `installed_apps = ["scoped_css"]` — the one install step. `template_extensions` and `menu_items` are left at their defaults on purpose. |
| `models.py` | `Widget(PrimaryModel)` with an optional FK to `dcim.Device`, which is what gives the panel something to render. |
| `views.py` | `WidgetUIViewSet(ScopedCSSMixin, NautobotUIViewSet)` — the Python half of the interim — and the `@action(detail=True)` HTMX endpoint behind `{% css_dep %}`. |
| `template_content.py` | `DeviceWidgetsExtension(TemplateExtension)` with `object_detail_panels = [DeviceWidgetsPanel(weight=1000)]`, a stock `Panel` whose `body_content_template_path` is this app's own template. |
| `filters.py`, `forms.py`, `tables.py`, `urls.py`, `navigation.py`, `api/` | Ordinary Nautobot plumbing, so the app actually runs. Nothing scoped_css-specific. |

### The JS hook

`js-widget-table` (in `widget_retrieve.html`) and `js-add-widget-submit` (in `add_widget_modal.html`)
keep a prefix, and no stylesheet in this app selects them. That is the one prefix worth keeping:
it marks a name as *behaviour*, so a reader knows that deleting it breaks the page rather than its
looks. Every **styling** prefix is gone — the scope attribute is the namespace now.

---

## Running it in a Nautobot dev environment

```bash
# 1. Install the library and this app into your Nautobot environment.
pip install -e /path/to/scoped_css
export PYTHONPATH="/path/to/scoped_css/examples:$PYTHONPATH"
#    ...or `pip install -e /path/to/scoped_css/examples` once you give it a pyproject.toml.

# 2. Enable it.
#    nautobot_config.py:
#        PLUGINS = ["example_app"]
#    `installed_apps = ["scoped_css"]` on the app config pulls the library in; you do not add it.

# 3. Migrate and collect.
nautobot-server post_upgrade

# 4. Build the bundles.
nautobot-server compile_css --app example_app
nautobot-server compile_css --app example_app --list    # what went into each bundle, and why
nautobot-server compile_css --check                     # exit 1 if stale — put this in CI
```

With `DEBUG = True` you can skip step 4: `SCOPED_CSS["AUTO_COMPILE"]` defaults to `settings.DEBUG`,
so editing a stylesheet and reloading rebuilds the bundle.

Then visit **Apps → scoped_css Example → Widgets** for the list and detail pages, and any
**device** detail page for the panel.

`nautobot-server compile_css --list` on a clean checkout prints:

```
example_app (3 entries)
  entry example_app/panels/device_widgets.html  [data-css-example_app-panels-device_widgets]
      example_app/panels/device_widgets.html  element  device_widgets.module.css

  entry example_app/widget_list.html  [data-css-example_app-widget_list]
      example_app/widget_list.html  page  widget_list.module.css
      generic/object_list.html  (outside the app: edge only)

  entry example_app/widget_retrieve.html  [data-css-example_app-widget_retrieve]
      example_app/widget_retrieve.html         page  widget_retrieve.css, widget_retrieve.module.css
      example_app/htmx/widget_table.html       page  widget_table.module.css
      example_app/components/widget_tile.html  page  widget_tile.module.css
      example_app/inc/add_widget_modal.html    page  add_widget_modal.module.css
      generic/object_retrieve.html  (outside the app: edge only)
```

Note the two kinds of edge that never become sources: `generic/object_*.html` lives in Nautobot,
so it is recorded and never scanned.

---

## Today vs. after the core change

Core will eventually emit `{% scoped_css_links %}` and stamp `<main id="main-content">` with
`{% css_scope_page %}`. Everything in the **Today** column is interim, and every one of those
lines is deleted when that lands. **The stylesheets never change.**

| | Today | After the core change |
|---|---|---|
| Getting the `<link>` into a page of ours | `ScopedCSSMixin` on the viewset (`views.py`) | nothing — core emits it |
| Getting the scope attribute onto a page of ours | `{% css_scope %}` on one `<div>` in `{% block content %}` (`widget_list.html`, `widget_retrieve.html`) | nothing — core stamps `<main>` |
| Getting the `<link>` for a panel on a **core** page | `{% scoped_css_links "example_app/panels/device_widgets.html" %}` in the panel body | nothing — core emits it |
| Getting the scope attribute onto that panel | `{% css_scope %}` on the panel's root element | **unchanged — still required** |
| Colocated stylesheets | unchanged | unchanged |
| `{% css_dep %}` for the HTMX fragment | unchanged | unchanged |
| Element scope on `widget_tile` / the modal | not used (they inherit the page scope) | not used |

A page that still carries the interim `{% css_scope %}` after the core change keeps working: the
attribute is simply present twice, on `<main>` and on the wrapper.

---

## The panel on a core page

`DeviceWidgetsExtension` puts a panel on Nautobot's **own** device detail view. That one fact
breaks every assumption the rest of this app relies on:

- **`ScopedCSSMixin` cannot run.** The view belongs to `dcim`, not to this app, so nothing
  reparents the page onto `scoped_css/root.html` and nothing puts a `<link>` in the `<head>`.
- **`context.template.name` is useless as a key.** It is a core template, which has no bundle
  belonging to this app.
- **There is no page scope root to inherit.** Claiming core's `<main>` would be precisely the leak
  this library exists to prevent.

So the panel template does two things no other template here does:

```django
{% load scoped_css %}{% scoped_css_links "example_app/panels/device_widgets.html" %}
…
<div class="device-widgets" {% css_scope %}>
```

1. **It names itself**, which makes it an *entry* with its own bundle, and delivers that bundle's
   `<link>` from inside `<body>` — valid HTML5, and the only place the app can reach. The tag
   emits it **at most once per request per entry**, so the same panel rendered several times on
   one page (once per row, once per tab) still yields exactly one `<link>`.
2. **It carries `{% css_scope %}` on its root element**, which is *mandatory* here rather than the
   opt-in narrowing it is on a page the app owns. Every rule in `device_widgets.module.css` is
   boxed into that one `<div>` — including the bare `.list-group-item` override, which reaches
   this panel and neither the core page hosting it nor another app's panel beside it.

Because that scope root is markup this app renders, and it carries the classes being styled, the
compiler emits the self-match form too:

```css
.device-widgets  →  [data-css-example_app-panels-device_widgets] .device-widgets,
                    [data-css-example_app-panels-device_widgets].device-widgets
```

A page skips that form, because a page's scope root is core's `<main>`, which never carries an
app's classes.

The panel itself is a stock `Panel` with one keyword argument:

```python
class DeviceWidgetsPanel(Panel):
    body_content_template_path = "example_app/panels/device_widgets.html"
    label = "Widgets"
    section = SectionChoices.RIGHT_HALF
```

Nautobot renders that template with the whole page context flattened into it, so `object` — the
Device — is available, and Nautobot draws the surrounding card while the app draws the contents.

---

## Verifying the build

The library's own test suite builds this app **without Nautobot installed**, in
`tests/test_example_app.py`. It works because the graph is a lexer walk over raw template source
(ARCHITECTURE.md § Spike findings 1): a `SimpleNamespace` with a `label` and a `path` is all
`discovery` and `bundler` ever ask of an `AppConfig`, so the real templates and real stylesheets
are scanned, graphed and bundled exactly as a deployment would.

```bash
cd /path/to/scoped_css
poetry run pytest -q tests/test_example_app.py
poetry run ruff check examples/ && poetry run ruff format --check examples/
```

It asserts: three entries; `widget_tile.module.css` under the `widget_retrieve` page attribute in
descendant form only; `device_widgets.module.css` under its own attribute *with* self-match forms;
the HTMX fragment reached through `{% css_dep %}`; zero dynamic includes; zero orphans; and no
build warnings from any entry.
