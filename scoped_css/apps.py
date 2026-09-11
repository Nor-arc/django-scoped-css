from django.apps import AppConfig


class ScopedCSSConfig(AppConfig):
    name = "scoped_css"
    verbose_name = "Scoped CSS"

    def ready(self):
        from . import checks  # noqa: F401  registers system checks
        from .conf import get

        if get("AUTO_COMPILE"):
            from .dev import ensure_output_dirs

            ensure_output_dirs()
