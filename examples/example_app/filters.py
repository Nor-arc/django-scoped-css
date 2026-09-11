"""FilterSet for Widget."""

from nautobot.apps.filters import NautobotFilterSet, SearchFilter

from example_app.models import Widget


class WidgetFilterSet(NautobotFilterSet):
    """Name/description search plus the generated field filters."""

    q = SearchFilter(filter_predicates={"name": "icontains", "description": "icontains"})

    class Meta:
        model = Widget
        fields = ["id", "name", "description", "device", "tags"]
