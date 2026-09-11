"""A panel injected into Nautobot's OWN device detail page — the hard case for scoped CSS.

This is the one place an app renders markup into a page it does not own, and it is why
``{% scoped_css_links "<entry>" %}`` and self-declaring entries exist (ARCHITECTURE.md
§ Runtime pieces, § Vocabulary). Everything a page-owning app relies on is unavailable here:

* ``ScopedCSSMixin`` cannot run — the view is ``dcim``'s, not this app's, so nothing reparents
  the page onto ``scoped_css/root.html`` and nothing puts a ``<link>`` in the ``<head>``;
* ``context.template.name`` is a core template, which has no bundle of this app's;
* there is no page scope root belonging to this app to inherit from, and claiming core's
  ``<main>`` would be exactly the leak this library prevents.

So the panel's template is its own entry with its own bundle, delivers its own ``<link>``
in-body, and carries ``{% css_scope %}`` on its own root element. See
``templates/example_app/panels/device_widgets.html``.

``NautobotAppConfig.template_extensions`` defaults to ``"template_content.template_extensions"``,
so this module is found with no configuration.
"""

from nautobot.apps.ui import Panel, SectionChoices, TemplateExtension


class DeviceWidgetsPanel(Panel):
    """A stock ``Panel`` with a custom body template.

    ``body_content_template_path`` is the supported hook for rendering an app's own template as a
    panel body (``Panel.render_body_content`` renders it via ``render_component_template``, which
    flattens the whole page context into it — so ``object``, the Device, is available). Nautobot
    draws the surrounding card, header and collapse toggle; this app draws only what is inside.

    Every ``Component`` requires ``weight``.
    """

    body_content_template_path = "example_app/panels/device_widgets.html"
    label = "Widgets"
    section = SectionChoices.RIGHT_HALF


class DeviceWidgetsExtension(TemplateExtension):
    """Adds the Widgets panel to every ``dcim.device`` detail page."""

    model = "dcim.device"

    object_detail_panels = [DeviceWidgetsPanel(weight=1000)]


template_extensions = [DeviceWidgetsExtension]
