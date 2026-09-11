"""A runnable Nautobot app that demonstrates every feature of ``scoped_css``.

It ships one model (``Widget``), one ``NautobotUIViewSet``, one ``TemplateExtension`` panel on
Nautobot's own device detail page, and seven colocated stylesheets. Between them they cover:

* **the default** — a partial with no ``{% css_scope %}`` inherits the page's scope
  (``components/widget_tile.html``);
* **element scope** — a fragment with ``{% css_scope %}`` on its own root compiles under its own
  attribute (``panels/device_widgets.html``);
* **plain ``.css``** — the escape hatch for markup Bootstrap portals out of the page, e.g. a
  popover appended to ``<body>`` (``widget_retrieve.css``);
* **``{% css_dep %}``** — a build-time edge to a fragment that only ever arrives by ``hx-get``
  (``htmx/widget_table.html``);
* **the interim delivery** — ``ScopedCSSMixin`` plus one ``{% css_scope %}`` per page, both
  deleted once Nautobot core stamps ``<main>`` (``views.py``, ``widget_*.html``);
* **the panel case** — a fragment rendered inside a CORE view, which can rely on none of the
  above and so declares itself an entry and delivers its own ``<link>``
  (``template_content.py``, ``panels/device_widgets.html``).

See ``examples/example_app/README.md`` for what each file demonstrates and how to run it.
"""

from nautobot.apps import NautobotAppConfig

__version__ = "0.1.0"


class ExampleAppConfig(NautobotAppConfig):
    """App config for the scoped_css example app."""

    name = "example_app"
    verbose_name = "scoped_css Example App"
    version = __version__
    author = "Network to Code, LLC"
    author_email = "info@networktocode.com"
    description = "Example Nautobot app demonstrating scoped_css: colocated, build-time-scoped CSS."
    base_url = "example-widgets"
    min_version = "3.2.0"

    # This is the ONE install step scoped_css needs. It pulls the library's template tags, system
    # checks and `compile_css` management command in whenever this app is installed, so a
    # deployment never has to add "scoped_css" to INSTALLED_APPS by hand.
    installed_apps = ["scoped_css"]

    # Left at their defaults on purpose, to show what an app gets for free:
    #   template_extensions = "template_content.template_extensions"
    #   menu_items          = "navigation.menu_items"


config = ExampleAppConfig
