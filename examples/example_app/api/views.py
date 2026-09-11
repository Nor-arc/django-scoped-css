"""REST API viewset for Widget."""

from nautobot.apps.api import NautobotModelViewSet

from example_app.api.serializers import WidgetSerializer
from example_app.filters import WidgetFilterSet
from example_app.models import Widget


class WidgetViewSet(NautobotModelViewSet):
    """Standard Nautobot model API viewset. Nothing scoped_css-specific: the API has no CSS."""

    queryset = Widget.objects.all()
    serializer_class = WidgetSerializer
    filterset_class = WidgetFilterSet
