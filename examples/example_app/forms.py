"""Forms for Widget: edit, filter, bulk edit."""

from django import forms
from nautobot.apps.forms import (
    DynamicModelChoiceField,
    NautobotBulkEditForm,
    NautobotFilterForm,
    NautobotModelForm,
    TagFilterField,
)
from nautobot.dcim.models import Device

from example_app.models import Widget


class WidgetForm(NautobotModelForm):
    """Create/update form."""

    device = DynamicModelChoiceField(queryset=Device.objects.all(), required=False)

    class Meta:
        model = Widget
        fields = ["name", "description", "device", "tags"]


class WidgetFilterForm(NautobotFilterForm):
    """The form behind the list view's filter panel."""

    model = Widget

    q = forms.CharField(required=False, label="Search")
    name = forms.CharField(required=False)
    device = DynamicModelChoiceField(queryset=Device.objects.all(), required=False)
    tags = TagFilterField(model)


class WidgetBulkEditForm(NautobotBulkEditForm):
    """Bulk edit form. `pk` is the checkbox column the table's ToggleColumn feeds."""

    pk = forms.ModelMultipleChoiceField(queryset=Widget.objects.all(), widget=forms.MultipleHiddenInput)
    description = forms.CharField(max_length=255, required=False)
    device = DynamicModelChoiceField(queryset=Device.objects.all(), required=False)

    class Meta:
        nullable_fields = ["description", "device"]
