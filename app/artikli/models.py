import secrets

from django.db import models


class Artikl(models.Model):
    rm_id = models.IntegerField(unique=True,null=True, blank=True)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, null=True)
    image = models.ImageField(upload_to="artikli/", blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    deposit = models.ForeignKey(
        "Deposit",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artikli",
        verbose_name="povratna naknada",
    )
    tax_group = models.ForeignKey(
        "configuration.TaxGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artikli",
        verbose_name="porezna grupa",
    )

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            while True:
                code = "".join(secrets.choice("0123456789") for _ in range(8))
                if not Artikl.objects.filter(code=code).exists():
                    self.code = code
                    break
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Artikl"
        verbose_name_plural = "Artikli"


class UnitOfMeasureData(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Jedinica mjere"
        verbose_name_plural = "Jedinice mjere"


class Deposit(models.Model):
    amount_eur = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="iznos u EUR")

    def __str__(self) -> str:
        return f"{self.amount_eur}"

    class Meta:
        verbose_name = "Povratna naknada"
        verbose_name_plural = "Povratne naknade"


class SalesGroupData(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=150)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Prodajna grupa"
        verbose_name_plural = "Prodajne grupe"


class KeyboardGroupData(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=150)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Tipkovna grupa"
        verbose_name_plural = "Tipkovne grupe"


class BaseGroupData(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=150)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Osnovna grupa"
        verbose_name_plural = "Osnovne grupe"


class ArtiklDetail(models.Model):
    artikl = models.OneToOneField("Artikl", on_delete=models.CASCADE, related_name="detail")
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    barcode = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    external_code = models.CharField(max_length=50, blank=True)

    base_group = models.ForeignKey(
        "BaseGroupData",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artikl_details_base",
    )
    sales_group = models.ForeignKey(
        "SalesGroupData",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artikl_details_sales",
    )
    keyboard_group = models.ForeignKey(
        "KeyboardGroupData",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artikl_details_keyboard",
    )

    unit_of_measure = models.ForeignKey(
        "UnitOfMeasureData",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artikl_details_unit",
    )
    standard_uom_id = models.IntegerField(null=True, blank=True)
    standard_uom_name = models.CharField(max_length=100, blank=True)
    quantity_in_suom = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    spillage_allowance = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    ordinal = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)

    point_of_issue = models.ForeignKey(
        "configuration.PointOfIssueData",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="artikl_details_point",
    )

    is_for_sale = models.BooleanField(default=False)
    is_purchased = models.BooleanField(default=False)
    is_product = models.BooleanField(default=False)
    is_commodity = models.BooleanField(default=False)
    is_immaterial = models.BooleanField(default=False)
    is_used_on_pos = models.BooleanField(default=False)
    is_package = models.BooleanField(default=False)
    is_negative_quantity_allowed = models.BooleanField(default=False)
    no_discount = models.BooleanField(default=False)
    has_return_fee = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    print_on_pricelist = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    class Meta:
        verbose_name = "Detalj artikla"
        verbose_name_plural = "Detalji artikala"

# Create your models here.
