"""The one model this example needs: a Widget, optionally attached to a Device."""

from django.db import models
from nautobot.apps.models import PrimaryModel


class Widget(PrimaryModel):
    """A named thing, optionally assigned to a Device.

    The FK to ``dcim.Device`` is what gives ``template_content.DeviceWidgetsExtension`` something
    to show: ``device.widgets.all()`` is the reverse accessor its panel renders.
    """

    name = models.CharField(max_length=255, unique=True)
    description = models.CharField(max_length=255, blank=True)
    device = models.ForeignKey(
        to="dcim.Device",
        on_delete=models.SET_NULL,
        related_name="widgets",
        blank=True,
        null=True,
    )

    # `name` is already `unique=True`, so BaseModel would infer this — declared anyway, because an
    # example should show the explicit form.
    natural_key_field_names = ["name"]

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
