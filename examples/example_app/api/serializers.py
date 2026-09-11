"""REST API serializer for Widget."""

from nautobot.apps.api import NautobotModelSerializer

from example_app.models import Widget


class WidgetSerializer(NautobotModelSerializer):
    """Widget serializer; `__all__` picks up the mixin fields PrimaryModel brings."""

    class Meta:
        model = Widget
        fields = "__all__"
