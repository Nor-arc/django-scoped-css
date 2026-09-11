"""Interim Nautobot integration until core stamps <main> and emits the links itself."""

from . import conf


class ScopedCSSMixin:
    """Add to a NautobotUIViewSet / legacy view. Reparents pages onto scoped_css/root.html,
    which emits {% scoped_css_links %} in the head. The page attribute still needs
    {% css_scope %} on the outermost element of the entry's content block (see ARCHITECTURE.md § Delivery).

    ``scoped_css/root.html`` extends ``SCOPED_CSS["ROOT_PARENT"]``. Template tags cannot reach
    settings from an ``{% extends %}`` expression and this library installs no context processor,
    so the parent is handed over as a context variable here.
    """

    scoped_css_root_template = "scoped_css/root.html"

    def get_extra_context(self, request, instance=None):
        context = super().get_extra_context(request, instance)
        if context is None:
            context = {}
        context["root_template"] = self.scoped_css_root_template
        context["scoped_css_root_parent"] = conf.get("ROOT_PARENT")
        return context
