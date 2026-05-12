from django.apps import AppConfig


class BarionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "barion"
    verbose_name = "Barion"

    def ready(self):
        from . import signals  # noqa: F401
