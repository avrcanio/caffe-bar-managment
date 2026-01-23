from django.db import models


class Stuff(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    name2 = models.CharField(max_length=255, blank=True, default="")
    card_number = models.CharField(max_length=50, blank=True, default="")
    tax_number = models.CharField(max_length=50, blank=True, default="")

    def __str__(self) -> str:
        return f"{self.name} ({self.rm_id})"

    class Meta:
        verbose_name = "Zaposlenik"
        verbose_name_plural = "Zaposlenici"


class Supplier(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    town = models.CharField(max_length=255, blank=True, default="")
    street = models.CharField(max_length=255, blank=True, default="")
    tax_number = models.CharField(max_length=50, blank=True, default="")
    orders_email = models.EmailField(blank=True, default="")
    mobile_devices = models.JSONField(blank=True, default=list)

    def __str__(self) -> str:
        return f"{self.name} ({self.rm_id})"

    class Meta:
        verbose_name = "Dobavljač"
        verbose_name_plural = "Dobavljači"
