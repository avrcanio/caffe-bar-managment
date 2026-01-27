from django.core.exceptions import ValidationError
from django.db import models
from decimal import Decimal


class PointOfIssueData(models.Model):
    rm_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=150)

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Mjesto izdavanja"
        verbose_name_plural = "Mjesta izdavanja"


class RemarisCookie(models.Model):
    cookie = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "Remaris cookie"

    class Meta:
        verbose_name = "Remaris cookie"
        verbose_name_plural = "Remaris cookies"


class TaxGroup(models.Model):
    name = models.CharField(max_length=150, verbose_name="naziv")
    rate = models.DecimalField(max_digits=5, decimal_places=4, verbose_name="stopa")
    code = models.CharField(max_length=50, blank=True, default="", verbose_name="sifra")
    is_active = models.BooleanField(default=True, verbose_name="aktivno")

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    class Meta:
        verbose_name = "Porezna grupa"
        verbose_name_plural = "Porezne grupe"


class PaymentType(models.Model):
    rm_id = models.IntegerField(null=True, blank=True, unique=True, verbose_name="rm id")
    name = models.CharField(max_length=150, verbose_name="naziv")
    code = models.CharField(max_length=50, blank=True, default="", verbose_name="sifra")
    is_active = models.BooleanField(default=True, verbose_name="aktivno")

    def __str__(self) -> str:
        return f"{self.name} ({self.rm_id})"

    class Meta:
        verbose_name = "Tip placanja"
        verbose_name_plural = "Tipovi placanja"


class CompanyProfile(models.Model):
    name = models.CharField(max_length=255, verbose_name="naziv")
    address = models.CharField(max_length=255, blank=True, default="", verbose_name="adresa")
    postal_code = models.CharField(max_length=20, blank=True, default="", verbose_name="postanski broj")
    city = models.CharField(max_length=100, blank=True, default="", verbose_name="grad")
    oib = models.CharField(max_length=30, blank=True, default="", verbose_name="oib")
    email = models.EmailField(blank=True, default="", verbose_name="email")
    phone = models.CharField(max_length=50, blank=True, default="", verbose_name="telefon")
    logo = models.ImageField(upload_to="branding/", blank=True, null=True, verbose_name="logo")
    lgu = models.ForeignKey(
        "LocalGovernmentUnit",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Grad / općina (PnP)",
    )

    def __str__(self) -> str:
        return self.name

    class Meta:
        verbose_name = "Podaci tvrtke"
        verbose_name_plural = "Podaci tvrtke"


class OrderEmailTemplate(models.Model):
    subject_template = models.CharField(
        max_length=255,
        default="Narudzba #{order_id}",
        verbose_name="predlozak subjecta",
    )
    body_template = models.TextField(
        default="U prilogu se nalazi narudzba {order_id}.",
        verbose_name="predlozak poruke",
    )
    active = models.BooleanField(default=True, verbose_name="aktivno")

    def __str__(self) -> str:
        return "Order email template"

    class Meta:
        verbose_name = "Predlozak emaila narudzbe"
        verbose_name_plural = "Predlosci emaila narudzbi"


class DocumentType(models.Model):
    DIRECTION_IN = "in"
    DIRECTION_OUT = "out"
    DIRECTION_CHOICES = (
        (DIRECTION_IN, "Ulaz"),
        (DIRECTION_OUT, "Izlaz"),
    )

    name = models.CharField(max_length=150, verbose_name="naziv")
    code = models.CharField(max_length=50, unique=True, verbose_name="sifra")
    direction = models.CharField(
        max_length=3,
        choices=DIRECTION_CHOICES,
        verbose_name="smjer",
    )
    description = models.TextField(blank=True, default="", verbose_name="opis")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="redoslijed")
    is_active = models.BooleanField(default=True, verbose_name="aktivno")
    ledger = models.ForeignKey(
        "accounting.Ledger",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="document_types",
        verbose_name="ledger",
    )
    stock_account = models.ForeignKey(
        "Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_types_stock",
        verbose_name="konto zalihe",
    )
    counterpart_account = models.ForeignKey(
        "Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="document_types_counterpart",
        verbose_name="konto protustavke",
    )
    ar_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_postable": True},
        verbose_name="konto kupaca",
    )
    ap_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_postable": True},
        verbose_name="konto dobavljaca",
    )
    vat_output_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_postable": True},
        verbose_name="konto PDV obveze",
    )
    vat_input_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_postable": True},
        verbose_name="konto pretporeza",
    )
    revenue_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_postable": True},
        verbose_name="konto prihoda",
    )
    expense_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        limit_choices_to={"is_postable": True},
        verbose_name="konto rashoda",
    )

    def clean(self):
        if not self.ledger_id:
            return
        for field in [
            "ar_account",
            "ap_account",
            "vat_output_account",
            "vat_input_account",
            "revenue_account",
            "expense_account",
        ]:
            acc = getattr(self, field)
            if acc and acc.ledger_id != self.ledger_id:
                raise ValidationError({field: "Odabrani konto mora biti iz istog ledgera."})

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    class Meta:
        verbose_name = "Tip dokumenta"
        verbose_name_plural = "Tipovi dokumenata"
        ordering = ("sort_order", "name")


class Account(models.Model):
    code = models.CharField(max_length=20, unique=True, verbose_name="sifra")
    name = models.CharField(max_length=255, verbose_name="naziv")
    is_active = models.BooleanField(default=True, verbose_name="aktivno")

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    class Meta:
        verbose_name = "Konto"
        verbose_name_plural = "Konta"
        ordering = ("code",)


class ConsumptionTaxCategory(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "PnP kategorija"
        verbose_name_plural = "PnP kategorije"

    def __str__(self) -> str:
        return self.name


class LocalGovernmentUnit(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name="naziv")
    pnp_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.0200"),
        help_text="Stopa poreza na potrošnju (npr. 0.0200 za 2%)",
        verbose_name="PnP stopa",
    )
    oib = models.CharField(max_length=11, blank=True, null=True, verbose_name="OIB")
    is_active = models.BooleanField(default=True, verbose_name="aktivno")

    class Meta:
        verbose_name = "Grad / Općina (PnP)"
        verbose_name_plural = "Gradovi / Općine (PnP)"

    def __str__(self) -> str:
        return f"{self.name} ({self.pnp_rate * 100}%)"
