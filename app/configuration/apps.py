from django.apps import AppConfig


class ConfigurationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'configuration'
    verbose_name = "Konfiguracija"

    def ready(self):
        from django.apps import apps as django_apps
        from auditlog.registry import auditlog
        from django.contrib.admin.options import ModelAdmin
        from django.core.exceptions import FieldDoesNotExist
        from django.db import models
        from django.utils import timezone
        from django.utils.text import capfirst

        audit_apps = {"orders", "artikli", "configuration", "contacts", "stock", "mailbox_app"}
        for model in django_apps.get_models():
            if model._meta.app_label not in audit_apps:
                continue
            if auditlog.contains(model):
                continue
            auditlog.register(model)

        if getattr(ModelAdmin, "_mozzart_date_format_patched", False):
            return

        original_get_list_display = ModelAdmin.get_list_display

        def _make_date_formatter(field_name, fmt, label):
            def _formatter(obj):
                value = getattr(obj, field_name, None)
                if value is None:
                    return ""
                if isinstance(value, timezone.datetime) and timezone.is_aware(value):
                    value = timezone.localtime(value)
                return value.strftime(fmt)

            _formatter.short_description = label
            _formatter.admin_order_field = field_name
            _formatter.__name__ = f"{field_name}_formatted"
            return _formatter

        def get_list_display(self, request):
            display = list(original_get_list_display(self, request))
            formatted = []
            for item in display:
                if not isinstance(item, str):
                    formatted.append(item)
                    continue
                if callable(getattr(self, item, None)):
                    formatted.append(item)
                    continue
                try:
                    field = self.model._meta.get_field(item)
                except FieldDoesNotExist:
                    formatted.append(item)
                    continue
                label = capfirst(getattr(field, "verbose_name", item))
                if isinstance(field, models.DateTimeField):
                    formatted.append(_make_date_formatter(item, "%d.%m.%Y %H:%M", label))
                elif isinstance(field, models.DateField):
                    formatted.append(_make_date_formatter(item, "%d.%m.%Y", label))
                else:
                    formatted.append(item)
            return tuple(formatted)

        ModelAdmin.get_list_display = get_list_display
        ModelAdmin._mozzart_date_format_patched = True
