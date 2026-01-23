from django.apps import AppConfig
from django.contrib import admin


class ArtikliConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'artikli'

    def ready(self):
        admin.site.site_header = "Mozart"
        admin.site.site_title = "Mozart"
        admin.site.index_title = "Mozart"
