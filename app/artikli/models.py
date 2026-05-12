import secrets

from django.core.exceptions import ValidationError
from django.db import models
from mptt.models import MPTTModel, TreeForeignKey


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
    pnp_category = models.ForeignKey(
        "configuration.ConsumptionTaxCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artikli",
        verbose_name="PnP kategorija",
    )
    tax_group = models.ForeignKey(
        "configuration.TaxGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
        related_name="artikli",
        verbose_name="porezna grupa",
    )
    category = models.ForeignKey(
        "Category",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="artikli",
        verbose_name="Kategorija",
    )
    is_sellable = models.BooleanField(default=True, verbose_name="Prodajni artikl")
    is_stock_item = models.BooleanField(default=False, verbose_name="Skladisni artikl")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        # Porezna grupa mora biti postavljena; ako nije, pokušaj default na PDV 25%.
        if not self.tax_group_id:
            try:
                from decimal import Decimal

                from configuration.models import TaxGroup

                tg = (
                    TaxGroup.objects.filter(code__iexact="PDV25").first()
                    or TaxGroup.objects.filter(rate=Decimal("0.2500")).order_by("id").first()
                )
                if tg:
                    self.tax_group = tg
            except Exception:
                # If TaxGroup table isn't available (early migrations) or any other
                # unexpected issue occurs, fall through to validation below.
                pass
        if not self.tax_group_id:
            raise ValidationError({"tax_group": "Porezna grupa je obavezna."})

        if not self.code:
            while True:
                code = "".join(secrets.choice("0123456789") for _ in range(8))
                if not Artikl.objects.filter(code=code).exists():
                    self.code = code
                    break
        super().save(*args, **kwargs)

    def packaging_path_summary(self) -> str:
        levels = list(self.packaging_levels.order_by("sort_order"))
        if not levels:
            return ""
        parts = []
        for idx, level in enumerate(levels):
            if idx == 0:
                parts.append(level.level_name)
                continue
            ratio = level.contains_previous
            ratio_display = (
                str(int(ratio))
                if ratio is not None and ratio == int(ratio)
                else f"{ratio:.4f}".rstrip("0").rstrip(".")
            )
            parts.append(f"{ratio_display}/{level.level_name}")
        return " -> ".join(parts)

    class Meta:
        verbose_name = "Artikl"
        verbose_name_plural = "Artikli"


class Normativ(models.Model):
    product = models.OneToOneField(
        "Artikl",
        on_delete=models.CASCADE,
        related_name="normativ",
        verbose_name="Prodajni (virtualni) artikl",
        limit_choices_to={"is_sellable": True},
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Normativ"
        verbose_name_plural = "Normativi"

    def __str__(self) -> str:
        return f"Normativ: {self.product}"


class NormativItem(models.Model):
    normativ = models.ForeignKey(
        "Normativ",
        on_delete=models.CASCADE,
        related_name="items",
    )
    ingredient = models.ForeignKey(
        "Artikl",
        on_delete=models.PROTECT,
        related_name="used_in_normatives",
        verbose_name="Skladisni artikl",
        limit_choices_to={"is_stock_item": True},
    )
    qty = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        verbose_name="Kolicina po 1 prodaji",
        help_text="npr. caj kutija 0.0500, kava kg 0.0090, limun kg 0.0400, med kom 1.0000",
    )

    class Meta:
        verbose_name = "Stavka normativa"
        verbose_name_plural = "Stavke normativa"
        constraints = [
            models.UniqueConstraint(
                fields=["normativ", "ingredient"],
                name="uniq_normativ_ingredient",
            )
        ]

    def __str__(self) -> str:
        return f"{self.normativ.product} -> {self.ingredient} ({self.qty})"


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


class Category(MPTTModel):
    name = models.CharField(max_length=120)
    parent = TreeForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class MPTTMeta:
        order_insertion_by = ["sort_order", "name"]

    class Meta:
        verbose_name = "Kategorija"
        verbose_name_plural = "Kategorije"
        ordering = ["tree_id", "lft"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="uniq_category_name_per_parent",
            )
        ]

    def __str__(self) -> str:
        return self.name




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


class ArtiklPackagingLevel(models.Model):
    artikl = models.ForeignKey(
        "Artikl",
        on_delete=models.CASCADE,
        related_name="packaging_levels",
        verbose_name="Artikl",
    )
    unit_of_measure = models.ForeignKey(
        "UnitOfMeasureData",
        on_delete=models.PROTECT,
        related_name="artikl_packaging_levels",
        verbose_name="Jedinica mjere",
    )
    contains_previous = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        verbose_name="Sadrži prethodnu razinu",
        help_text="Za prvu razinu ostavi prazno. Za svaku sljedeću upiši koliko prethodnih jedinica sadrži.",
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Redoslijed")

    def clean(self):
        super().clean()
        if not self.unit_of_measure_id:
            raise ValidationError({"unit_of_measure": "Jedinica mjere je obavezna."})
        if self.sort_order == 0:
            if self.contains_previous not in (None, ""):
                raise ValidationError(
                    {"contains_previous": "Prva razina pakiranja ne treba omjer prema prethodnoj razini."}
                )
        elif self.contains_previous is None:
            raise ValidationError(
                {"contains_previous": "Svaka razina iznad prve mora imati omjer prema prethodnoj razini."}
            )
        elif self.contains_previous <= 0:
            raise ValidationError(
                {"contains_previous": "Omjer prema prethodnoj razini mora biti veći od 0."}
            )

    @property
    def level_name(self) -> str:
        unit = getattr(self, "unit_of_measure", None)
        if unit and unit.name:
            return unit.name.strip().lower()
        return ""

    def __str__(self) -> str:
        return f"{self.artikl} / {self.level_name or self.unit_of_measure_id}"

    class Meta:
        verbose_name = "Razina originalnog pakiranja"
        verbose_name_plural = "Razine originalnih pakiranja"
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["artikl", "sort_order"],
                name="uniq_artikl_packaging_level_sort_order",
            )
        ]

# Create your models here.
