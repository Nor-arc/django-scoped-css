"""One menu item, so the example is reachable from the UI.

``NautobotAppConfig.menu_items`` defaults to ``"navigation.menu_items"``, so this module is found
with no configuration. App links are namespaced ``plugins:<app_label>:<name>``.
"""

from nautobot.apps.ui import NavMenuAddButton, NavMenuGroup, NavMenuItem, NavMenuTab

menu_items = (
    NavMenuTab(
        name="Apps",
        weight=5000,
        groups=(
            NavMenuGroup(
                name="scoped_css Example",
                weight=100,
                items=(
                    NavMenuItem(
                        link="plugins:example_app:widget_list",
                        name="Widgets",
                        weight=100,
                        permissions=["example_app.view_widget"],
                        buttons=(
                            NavMenuAddButton(
                                link="plugins:example_app:widget_add",
                                permissions=["example_app.add_widget"],
                            ),
                        ),
                    ),
                ),
            ),
        ),
    ),
)
