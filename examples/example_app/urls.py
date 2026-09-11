"""UI URL routing. NautobotAppConfig.ready() mounts this at /plugins/example-widgets/.

The router's detail route is named bare (``plugins:example_app:widget``); the custom
``@action`` becomes ``plugins:example_app:widget_widget_table``, which is the name
``widget_retrieve.html`` reverses for its ``hx-get``.
"""

from nautobot.apps.urls import NautobotUIViewSetRouter

from example_app.views import WidgetUIViewSet

router = NautobotUIViewSetRouter()
router.register("widgets", WidgetUIViewSet)

urlpatterns = router.urls
