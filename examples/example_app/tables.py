"""Table for the Widget list view."""

import django_tables2 as tables
from nautobot.apps.tables import BaseTable, ButtonsColumn, ToggleColumn

from example_app.models import Widget


class WidgetTable(BaseTable):
    """Name / device / actions, plus the checkbox column bulk edit needs."""

    pk = ToggleColumn()
    name = tables.LinkColumn()
    device = tables.LinkColumn()
    actions = ButtonsColumn(Widget)

    class Meta(BaseTable.Meta):
        model = Widget
        fields = ["pk", "name", "description", "device", "actions"]
        default_columns = ["pk", "name", "device", "actions"]
