"""UI viewset for Widget — and the two lines scoped_css asks of a view today.

``ScopedCSSMixin`` is the whole of the Python-side interim (ARCHITECTURE.md § Delivery): it sets
``root_template`` so the page is reparented onto ``scoped_css/root.html``, which emits
``{% scoped_css_links %}`` into the ``<head>``. Once Nautobot core emits the links itself, delete
the mixin from the bases and this file has nothing scoped_css-specific left in it.
"""

from django.shortcuts import render
from nautobot.apps.views import NautobotUIViewSet
from rest_framework.decorators import action

from example_app.api.serializers import WidgetSerializer
from example_app.filters import WidgetFilterSet
from example_app.forms import WidgetBulkEditForm, WidgetFilterForm, WidgetForm
from example_app.models import Widget
from example_app.tables import WidgetTable
from scoped_css.nautobot import ScopedCSSMixin


class WidgetUIViewSet(ScopedCSSMixin, NautobotUIViewSet):
    """Widget list/detail/edit/delete.

    ``ScopedCSSMixin`` comes FIRST in the bases so its ``get_extra_context`` runs before the
    viewset's — it calls ``super()`` and merges, so ``object_detail_content`` and ``active_tab``
    survive. See ``tests/test_nautobot_mixin.py`` in the library for both delivery stories.

    ``widget_list.html`` / ``widget_retrieve.html`` are picked up automatically: Nautobot resolves
    ``<app_label>/<model_name>_<action>.html`` before falling back to ``generic/object_*.html``.
    """

    queryset = Widget.objects.all()
    table_class = WidgetTable
    filterset_class = WidgetFilterSet
    filterset_form_class = WidgetFilterForm
    form_class = WidgetForm
    bulk_update_form_class = WidgetBulkEditForm
    serializer_class = WidgetSerializer

    @action(detail=True, url_path="widget-table", url_name="widget_table", custom_view_base_action="view")
    def widget_table(self, request, *args, **kwargs):
        """HTMX endpoint: the table fragment ``widget_retrieve.html`` pulls in with ``hx-get``.

        This is precisely the case ``{% css_dep %}`` exists for. The fragment is fetched by the
        browser long after the build ran, so no static walk could ever reach it — the page names
        it explicitly instead, and ``widget_table.module.css`` rides in on the page's bundle,
        already compiled under the page's scope attribute. The fragment itself needs no ``<link>``
        and no ``{% css_scope %}``: it is swapped INTO the page's scope root.

        Returns a plain ``HttpResponse`` rather than a DRF ``Response`` so the HTML renderer does
        not wrap the fragment in the full page chrome.
        """
        widget = self.get_object()
        widgets = Widget.objects.none() if widget.device is None else widget.device.widgets.all()
        return render(request, "example_app/htmx/widget_table.html", {"widgets": widgets})
