from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class Pos(models.Model):
    class Platform(models.TextChoices):
        WINDOWS = "windows", "Windows"
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"
        OTHER = "other", "Other"

    external_pos_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.WINDOWS)
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        on_delete=models.PROTECT,
        related_name="pos_list",
        verbose_name="Skladiste",
    )
    is_active = models.BooleanField(default=True)
    config = models.JSONField(blank=True, default=dict)

    def __str__(self) -> str:
        return f"{self.name} ({self.external_pos_id})"

    class Meta:
        verbose_name = "POS"
        verbose_name_plural = "POS"


User = get_user_model()


class PosProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="pos_profile",
    )
    pin_hash = models.CharField(max_length=128, blank=True, default="")
    pin_fail_count = models.PositiveIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)
    is_registered = models.BooleanField(default=False, verbose_name="registriran")
    registered_device_id = models.CharField(max_length=128, blank=True, default="")
    registered_at = models.DateTimeField(null=True, blank=True)

    def set_pin(self, raw_pin: str) -> None:
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin: str) -> bool:
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

    def __str__(self) -> str:
        return f"POS profil: {self.user}"

    class Meta:
        verbose_name = "POS profil"
        verbose_name_plural = "POS profili"


class PosDevice(models.Model):
    device_id = models.CharField(max_length=128, unique=True)
    pos = models.ForeignKey(
        "pos.Pos",
        on_delete=models.PROTECT,
        related_name="devices",
        verbose_name="POS",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        label = self.name or self.device_id
        return f"{label} -> {self.pos}"

    class Meta:
        verbose_name = "POS uređaj"
        verbose_name_plural = "POS uređaji"


class PosReceipt(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        FISCALIZED = "fiscalized", "Fiscalized"
        STORNO = "storno", "Storno"
        ERROR = "error", "Error"

    class PaymentType(models.TextChoices):
        CASH = "cash", "Gotovina"

    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receipts",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_receipts",
    )
    operator = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_receipts",
    )
    receipt_number = models.IntegerField()
    issued_on = models.DateField()
    issued_at = models.DateTimeField()
    office_code = models.CharField(max_length=20)
    device_code = models.CharField(max_length=20)
    payment_type = models.CharField(max_length=10, choices=PaymentType.choices, default=PaymentType.CASH)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    currency = models.CharField(max_length=10, default="EUR")

    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    zki = models.CharField(max_length=64, blank=True, default="")
    jir = models.CharField(max_length=64, blank=True, default="")
    qr_payload = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    storno_of = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="storno_receipt",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "POS račun"
        verbose_name_plural = "POS računi"
        constraints = [
            models.UniqueConstraint(
                fields=["office_code", "device_code", "issued_on", "receipt_number"],
                name="uq_pos_receipt_number",
            )
        ]

    def __str__(self) -> str:
        return f"POS {self.receipt_number}/{self.office_code}/{self.device_code} ({self.issued_on:%Y-%m-%d})"

    def recalc_totals(self, *, save: bool = True) -> None:
        net_total = Decimal("0.00")
        vat_total = Decimal("0.00")
        total_total = Decimal("0.00")
        for item in self.items.all():
            net_total += item.net_amount or Decimal("0.00")
            vat_total += item.vat_amount or Decimal("0.00")
            total_total += item.total_amount or Decimal("0.00")

        self.net_amount = net_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.vat_amount = vat_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.total_amount = total_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if save:
            self.save(update_fields=["net_amount", "vat_amount", "total_amount", "updated_at"])


class PosReceiptItem(models.Model):
    receipt = models.ForeignKey(
        "pos.PosReceipt",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_receipt_items",
    )
    product_name = models.CharField(max_length=255, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_price = models.DecimalField(max_digits=12, decimal_places=4)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0000"))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        verbose_name = "Stavka POS računa"
        verbose_name_plural = "Stavke POS računa"

    def __str__(self) -> str:
        return f"{self.product_name} x {self.quantity}"


class PosScreen(models.Model):
    name = models.CharField(max_length=150, verbose_name="Naziv")
    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="screens",
        verbose_name="POS",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_screens",
        verbose_name="Skladiste",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktivan")
    columns = models.PositiveIntegerField(default=6, verbose_name="Stupci")
    rows = models.PositiveIntegerField(default=8, verbose_name="Redci")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Redoslijed")
    note = models.TextField(blank=True, default="", verbose_name="Napomena")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "POS ekran"
        verbose_name_plural = "POS ekrani"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class PosScreenItem(models.Model):
    screen = models.ForeignKey(
        "pos.PosScreen",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Ekran",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="pos_screen_items",
        verbose_name="Artikl",
    )
    label = models.CharField(max_length=150, blank=True, default="", verbose_name="Naziv na tipki")
    row = models.PositiveIntegerField(default=1, verbose_name="Red")
    col = models.PositiveIntegerField(default=1, verbose_name="Stupac")
    row_span = models.PositiveIntegerField(default=1, verbose_name="Visina")
    col_span = models.PositiveIntegerField(default=1, verbose_name="Širina")
    bg_color = models.CharField(max_length=20, blank=True, default="", verbose_name="Boja pozadine")
    text_color = models.CharField(max_length=20, blank=True, default="", verbose_name="Boja teksta")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Redoslijed")

    class Meta:
        verbose_name = "Stavka POS ekrana"
        verbose_name_plural = "Stavke POS ekrana"
        ordering = ["sort_order", "row", "col"]
        constraints = [
            models.UniqueConstraint(
                fields=["screen", "row", "col"],
                name="uniq_pos_screen_position",
            )
        ]

    def __str__(self) -> str:
        return f"{self.screen}: {self.artikl}"


class PosMode(models.Model):
    name = models.CharField(max_length=150, verbose_name="Naziv")
    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="modes",
        verbose_name="POS",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pos_modes",
        verbose_name="Skladiste",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktivan")
    is_default = models.BooleanField(default=False, verbose_name="Zadani")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Redoslijed")
    note = models.TextField(blank=True, default="", verbose_name="Napomena")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "POS mod rada"
        verbose_name_plural = "POS modovi rada"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class PosModeScreen(models.Model):
    mode = models.ForeignKey(
        "pos.PosMode",
        on_delete=models.CASCADE,
        related_name="screens",
        verbose_name="Mod rada",
    )
    screen = models.ForeignKey(
        "pos.PosScreen",
        on_delete=models.CASCADE,
        related_name="modes",
        verbose_name="Ekran",
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Redoslijed")

    class Meta:
        verbose_name = "Ekran u modu"
        verbose_name_plural = "Ekrani u modu"
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["mode", "screen"],
                name="uniq_pos_mode_screen",
            )
        ]

    def __str__(self) -> str:
        return f"{self.mode} -> {self.screen}"

    def save(self, *args, **kwargs):
        if self.artikl and not self.product_name:
            self.product_name = self.artikl.name

        rate = self.vat_rate or Decimal("0.0000")
        if rate == Decimal("0.0000") and self.artikl and self.artikl.tax_group:
            rate = self.artikl.tax_group.rate or Decimal("0.0000")
            self.vat_rate = rate

        quantity = self.quantity or Decimal("0.0000")
        unit_price = self.unit_price or Decimal("0.0000")
        total = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rate:
            net = (total / (Decimal("1.00") + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            net = total
        vat = (total - net).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.total_amount = total
        self.net_amount = net
        self.vat_amount = vat
        super().save(*args, **kwargs)
