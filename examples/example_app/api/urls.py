"""API URL routing. NautobotAppConfig.ready() mounts this under the `example_app-api` namespace."""

from nautobot.apps.api import OrderedDefaultRouter

from example_app.api.views import WidgetViewSet

router = OrderedDefaultRouter()
router.register("widgets", WidgetViewSet)

urlpatterns = router.urls
