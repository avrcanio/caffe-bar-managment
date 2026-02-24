from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class Table(models.Model):
    class Shape(models.TextChoices):
        ROUND = "round", "Round"
        SQUARE = "square", "Square"
        RECTANGLE = "rectangle", "Rectangle"
        OTHER = "other", "Other"

    label = models.CharField(max_length=64, verbose_name="Label")
    capacity = models.PositiveIntegerField(default=4, verbose_name="Capacity")
    shape = models.CharField(max_length=20, choices=Shape.choices, default=Shape.SQUARE, verbose_name="Shape")
    is_vip = models.BooleanField(default=False, verbose_name="VIP")
    width = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        verbose_name="Width",
    )
    height = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        verbose_name="Height",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class Layout(models.Model):
    name = models.CharField(max_length=120, verbose_name="Name")
    is_active = models.BooleanField(default=False, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Layout"
        verbose_name_plural = "Layouts"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)


class UserLayoutAccess(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="barion_layout_accesses",
        verbose_name="User",
    )
    layout = models.ForeignKey(
        "barion.Layout",
        on_delete=models.CASCADE,
        related_name="user_accesses",
        verbose_name="Layout",
    )
    is_default = models.BooleanField(default=False, verbose_name="Default")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User layout access"
        verbose_name_plural = "User layout accesses"
        ordering = ["user_id", "-is_default", "layout_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "layout"],
                name="uniq_barion_user_layout_access",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(is_default=True, is_active=True),
                name="uniq_barion_user_default_layout_access",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.layout}"


class Zone(models.Model):
    layout = models.ForeignKey(
        "barion.Layout",
        on_delete=models.CASCADE,
        related_name="zones",
        verbose_name="Layout",
    )
    name = models.CharField(max_length=120, verbose_name="Name")
    order = models.PositiveIntegerField(default=0, verbose_name="Order")
    color = models.CharField(max_length=20, blank=True, default="", verbose_name="Color")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Zone"
        verbose_name_plural = "Zones"
        ordering = ["layout_id", "order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["layout", "name"], name="uniq_barion_zone_layout_name"),
        ]

    def __str__(self) -> str:
        return f"{self.layout}: {self.name}"


class LayoutTable(models.Model):
    layout = models.ForeignKey(
        "barion.Layout",
        on_delete=models.CASCADE,
        related_name="layout_tables",
        verbose_name="Layout",
    )
    table = models.ForeignKey(
        "barion.Table",
        on_delete=models.PROTECT,
        related_name="layout_tables",
        verbose_name="Table",
    )
    zone = models.ForeignKey(
        "barion.Zone",
        on_delete=models.PROTECT,
        related_name="layout_tables",
        verbose_name="Zone",
    )
    x = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(1000)],
        verbose_name="X",
    )
    y = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(1000)],
        verbose_name="Y",
    )
    w = models.PositiveIntegerField(
        default=90,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        verbose_name="Width",
    )
    h = models.PositiveIntegerField(
        default=90,
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
        verbose_name="Height",
    )
    rotation = models.IntegerField(
        default=0,
        validators=[MinValueValidator(-360), MaxValueValidator(360)],
        verbose_name="Rotation",
    )
    is_enabled = models.BooleanField(default=True, verbose_name="Enabled")
    z_index = models.IntegerField(default=0, verbose_name="Z-index")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Layout table"
        verbose_name_plural = "Layout tables"
        ordering = ["layout_id", "z_index", "id"]
        constraints = [
            models.UniqueConstraint(fields=["layout", "table"], name="uniq_barion_layout_table"),
        ]

    def __str__(self) -> str:
        return f"{self.layout}: {self.table}"


class TableState(models.Model):
    class State(models.TextChoices):
        FREE = "FREE", "Free"
        OPEN = "OPEN", "Open"
        RESERVED = "RESERVED", "Reserved"
        PAYMENT_PENDING = "PAYMENT_PENDING", "Payment pending"
        BLOCKED = "BLOCKED", "Blocked"

    layout_table = models.OneToOneField(
        "barion.LayoutTable",
        on_delete=models.CASCADE,
        related_name="state",
        verbose_name="Layout table",
    )
    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.FREE,
        verbose_name="State",
    )
    open_check_id = models.BigIntegerField(null=True, blank=True, verbose_name="Open check ID")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_table_states",
        verbose_name="Updated by",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Table state"
        verbose_name_plural = "Table states"
        indexes = [
            models.Index(fields=["state"], name="idx_barion_ts_state"),
            models.Index(fields=["updated_at"], name="idx_barion_ts_updated"),
        ]

    def clean(self):
        if self.state in {self.State.OPEN, self.State.PAYMENT_PENDING} and not self.open_check_id:
            raise ValidationError("open_check_id je obavezan kada je stanje OPEN ili PAYMENT_PENDING.")
        if self.state == self.State.FREE and self.open_check_id is not None:
            raise ValidationError("open_check_id mora biti prazan kada je stanje FREE.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.layout_table} [{self.state}]"


class Check(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    table = models.ForeignKey(
        "barion.Table",
        on_delete=models.PROTECT,
        related_name="checks",
        verbose_name="Table",
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
        verbose_name="Status",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_checks_opened",
        verbose_name="Opened by",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_checks_closed",
        verbose_name="Closed by",
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    pos_receipt = models.OneToOneField(
        "pos.PosReceipt",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_check",
        verbose_name="POS receipt",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Check"
        verbose_name_plural = "Checks"
        ordering = ["-opened_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["table"],
                condition=Q(status="OPEN"),
                name="uniq_barion_open_check_per_table",
            )
        ]
        indexes = [
            models.Index(fields=["table", "status"], name="idx_barion_check_table_status"),
            models.Index(fields=["status", "updated_at"], name="idx_barion_chk_status_upd"),
        ]

    def __str__(self) -> str:
        return f"Check {self.id} - {self.table} ({self.status})"


class CheckItem(models.Model):
    class LineType(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        STORNO = "STORNO", "Storno"
        GRATIS = "GRATIS", "Gratis"
        OTPIS = "OTPIS", "Otpis"

    barion_check = models.ForeignKey(
        "barion.Check",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Check",
        db_column="check_id",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="barion_check_items",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    unit_price = models.DecimalField(max_digits=12, decimal_places=4)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0000"))
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    round_number = models.PositiveIntegerField(null=True, blank=True)
    sent_to_bar = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    line_type = models.CharField(
        max_length=10,
        choices=LineType.choices,
        default=LineType.NORMAL,
        db_index=True,
    )
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Check item"
        verbose_name_plural = "Check items"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["barion_check", "id"], name="idx_barion_ci_check_id"),
            models.Index(fields=["barion_check", "sent_to_bar"], name="idx_barion_ci_check_sent"),
            models.Index(fields=["barion_check", "round_number"], name="idx_barion_ci_check_round"),
        ]

    def __str__(self) -> str:
        return f"{self.artikl.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        rate = Decimal(str(self.vat_rate or "0.0000"))
        if rate == Decimal("0.0000") and getattr(self.artikl, "tax_group", None):
            rate = self.artikl.tax_group.rate or Decimal("0.0000")
            self.vat_rate = rate

        quantity = Decimal(str(self.quantity or "0.0000"))
        unit_price = Decimal(str(self.unit_price or "0.0000"))
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
