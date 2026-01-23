from django.apps import AppConfig


class ConfigurationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'configuration'
    verbose_name = "Konfiguracija"

    def ready(self):
        from django.apps import apps as django_apps
        from auditlog.registry import auditlog

        audit_apps = {"orders", "artikli", "configuration", "contacts", "stock", "mailbox_app"}
        for model in django_apps.get_models():
            if model._meta.app_label not in audit_apps:
                continue
            if auditlog.contains(model):
                continue
            auditlog.register(model)
