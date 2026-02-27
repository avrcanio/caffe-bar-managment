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

    class SettlementStatus(models.TextChoices):
        NONE = "NONE", "None"
        PREPARED = "PREPARED", "Prepared"
        CARD_CONFIRMED = "CARD_CONFIRMED", "Card confirmed"
        READY_FOR_ISSUE = "READY_FOR_ISSUE", "Ready for issue"
        COMPLETE = "COMPLETE", "Complete"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"

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
    settlement_status = models.CharField(
        max_length=20,
        choices=SettlementStatus.choices,
        default=SettlementStatus.NONE,
        verbose_name="Settlement status",
    )
    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID,
        verbose_name="Payment status",
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

    @property
    def pos_receipt_ids(self) -> list[int]:
        receipt_ids: set[int] = set()
        settlement_receipts = self.settlement_parts.exclude(confirmed_receipt_id__isnull=True).values_list(
            "confirmed_receipt_id",
            flat=True,
        )
        receipt_ids.update(int(rid) for rid in settlement_receipts if rid)
        return sorted(receipt_ids)

    @property
    def pos_receipt_id(self) -> int | None:
        receipt_ids = self.pos_receipt_ids
        if not receipt_ids:
            return None
        return receipt_ids[-1]

    @property
    def pos_receipt(self):
        receipt_id = self.pos_receipt_id
        if not receipt_id:
            return None
        from pos.models import PosReceipt

        return PosReceipt.objects.filter(id=receipt_id).first()


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
    paid_quantity = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
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

        quantity = Decimal(str(self.quantity or "0.0000")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if quantity != quantity.quantize(Decimal("1")):
            raise ValidationError("quantity mora biti cijeli broj komada.")
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
        if self.paid_amount < Decimal("0.00"):
            self.paid_amount = Decimal("0.00")
        if self.paid_amount > total:
            self.paid_amount = total
        if unit_price > Decimal("0.0000"):
            implied_paid_qty = (self.paid_amount / unit_price).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        else:
            implied_paid_qty = Decimal("0.0000")
        max_paid_qty = max(Decimal("0.0000"), quantity)
        self.paid_quantity = min(max(implied_paid_qty, Decimal("0.0000")), max_paid_qty)
        super().save(*args, **kwargs)


class SettlementPart(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"

    class Status(models.TextChoices):
        PREPARED = "PREPARED", "Prepared"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"

    barion_check = models.ForeignKey(
        "barion.Check",
        on_delete=models.CASCADE,
        related_name="settlement_parts",
        verbose_name="Check",
        db_column="check_id",
    )
    method = models.CharField(max_length=10, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    tip_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_charged = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    fiscal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PREPARED)
    external_txn_id = models.CharField(max_length=100, blank=True, default="")
    provider_ref = models.CharField(max_length=100, blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_settlement_parts_confirmed",
    )
    confirmed_receipt = models.ForeignKey(
        "pos.PosReceipt",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_settlement_parts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Settlement part"
        verbose_name_plural = "Settlement parts"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["barion_check", "status"], name="idx_barion_sp_check_status"),
            models.Index(fields=["barion_check", "method"], name="idx_barion_sp_check_method"),
            models.Index(fields=["external_txn_id"], name="idx_barion_sp_ext_txn"),
        ]

    def __str__(self) -> str:
        return f"{self.barion_check_id} {self.method} {self.amount}"

    def clean(self):
        amount = Decimal(str(self.amount or "0.00"))
        tip = Decimal(str(self.tip_amount or "0.00"))
        if amount <= 0:
            raise ValidationError("amount mora biti > 0.")
        if tip < 0:
            raise ValidationError("tip_amount mora biti >= 0.")
        if self.method == self.Method.CASH and tip != Decimal("0.00"):
            raise ValidationError("CASH settlement ne podržava tip_amount.")
        if self.method == self.Method.CARD and tip > amount:
            raise ValidationError("tip_amount ne može biti veći od amount.")

    def save(self, *args, **kwargs):
        amount = Decimal(str(self.amount or "0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tip = Decimal(str(self.tip_amount or "0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.amount = amount
        self.tip_amount = tip
        if self.method == self.Method.CARD:
            self.total_charged = (amount + tip).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            self.fiscal_amount = self.total_charged
        else:
            self.tip_amount = Decimal("0.00")
            self.total_charged = amount
            self.fiscal_amount = amount
        self.full_clean()
        super().save(*args, **kwargs)


class ProductPopularitySnapshot(models.Model):
    artikl = models.OneToOneField(
        "artikli.Artikl",
        on_delete=models.CASCADE,
        related_name="barion_popularity_snapshot",
    )
    sold_qty_30d = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    sold_qty_night_weekend = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0.0000"))
    window_days = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Product popularity snapshot"
        verbose_name_plural = "Product popularity snapshots"
        indexes = [
            models.Index(fields=["-sold_qty_30d"], name="idx_barion_pop_qty_desc"),
            models.Index(fields=["-sold_qty_night_weekend"], name="idx_barion_pop_night_qty_desc"),
            models.Index(fields=["updated_at"], name="idx_barion_pop_updated"),
        ]

    def __str__(self) -> str:
        return f"{self.artikl_id}: {self.sold_qty_30d}"


class BarionRuntimeMode(models.Model):
    class Mode(models.TextChoices):
        DAY = "day", "Day"
        NIGHT = "night", "Night"

    active_mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.DAY)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="barion_runtime_mode_updates",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Runtime mode"
        verbose_name_plural = "Runtime mode"

    def save(self, *args, **kwargs):
        # Singleton row used as runtime source-of-truth.
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        instance, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "active_mode": cls.Mode.DAY,
            },
        )
        return instance

    def __str__(self) -> str:
        return f"Runtime mode: {self.active_mode}"


class ItemModifierGroup(models.Model):
    class Type(models.TextChoices):
        SIMPLE = "simple", "Simple"
        BUNDLE = "bundle", "Bundle"

    class SelectionMode(models.TextChoices):
        SINGLE = "single", "Single"
        MULTIPLE = "multiple", "Multiple"

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.SIMPLE)
    selection_mode = models.CharField(max_length=20, choices=SelectionMode.choices, default=SelectionMode.MULTIPLE)
    min_select = models.PositiveIntegerField(default=0)
    max_select = models.PositiveIntegerField(default=10)
    allow_note = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item modifier group"
        verbose_name_plural = "Item modifier groups"
        ordering = ["sort_order", "name", "id"]

    def clean(self):
        if self.selection_mode == self.SelectionMode.SINGLE:
            self.max_select = 1
            if self.min_select > 1:
                raise ValidationError("Single group ne može imati min_select > 1.")
        if self.max_select < self.min_select:
            raise ValidationError("max_select mora biti >= min_select.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class ItemModifierOption(models.Model):
    group = models.ForeignKey(
        "barion.ItemModifierGroup",
        on_delete=models.CASCADE,
        related_name="options",
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item modifier option"
        verbose_name_plural = "Item modifier options"
        ordering = ["group_id", "sort_order", "name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["group", "code"], name="uniq_barion_modifier_option_group_code"),
            models.UniqueConstraint(fields=["group", "name"], name="uniq_barion_modifier_option_group_name"),
        ]

    def clean(self):
        if self.group_id and self.group.type != ItemModifierGroup.Type.SIMPLE:
            raise ValidationError("ItemModifierOption je dozvoljen samo za group.type=simple.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.group.name}: {self.name}"


class ItemBundleOption(models.Model):
    group = models.ForeignKey(
        "barion.ItemModifierGroup",
        on_delete=models.CASCADE,
        related_name="bundle_options",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="barion_bundle_options",
    )
    price_delta = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item bundle option"
        verbose_name_plural = "Item bundle options"
        ordering = ["group_id", "sort_order", "artikl__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["group", "artikl"], name="uniq_barion_bundle_option_group_artikl"),
        ]

    def clean(self):
        if self.group_id and self.group.type != ItemModifierGroup.Type.BUNDLE:
            raise ValidationError("ItemBundleOption je dozvoljen samo za group.type=bundle.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.group.name}: {self.artikl.name}"


class ItemModifierGroupAssignment(models.Model):
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.CASCADE,
        related_name="barion_modifier_group_assignments",
    )
    group = models.ForeignKey(
        "barion.ItemModifierGroup",
        on_delete=models.CASCADE,
        related_name="artikl_assignments",
    )
    is_active = models.BooleanField(default=True)
    is_required = models.BooleanField(default=False)
    min_select_override = models.PositiveIntegerField(null=True, blank=True)
    max_select_override = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item modifier group assignment"
        verbose_name_plural = "Item modifier group assignments"
        ordering = ["artikl_id", "group_id"]
        constraints = [
            models.UniqueConstraint(fields=["artikl", "group"], name="uniq_barion_modifier_assignment_artikl_group"),
        ]

    def clean(self):
        min_select = self.min_select_override if self.min_select_override is not None else self.group.min_select
        max_select = self.max_select_override if self.max_select_override is not None else self.group.max_select
        if max_select < min_select:
            raise ValidationError("max_select_override mora biti >= min_select_override.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.artikl_id} -> {self.group.code}"


class CheckItemModifierSelection(models.Model):
    check_item = models.ForeignKey(
        "barion.CheckItem",
        on_delete=models.CASCADE,
        related_name="modifier_selections",
    )
    group = models.ForeignKey(
        "barion.ItemModifierGroup",
        on_delete=models.PROTECT,
        related_name="check_item_selections",
    )
    option = models.ForeignKey(
        "barion.ItemModifierOption",
        on_delete=models.PROTECT,
        related_name="check_item_selections",
        null=True,
        blank=True,
    )
    bundle_option = models.ForeignKey(
        "barion.ItemBundleOption",
        on_delete=models.PROTECT,
        related_name="check_item_selections",
        null=True,
        blank=True,
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Check item modifier selection"
        verbose_name_plural = "Check item modifier selections"
        ordering = ["check_item_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["check_item", "option"],
                condition=Q(option__isnull=False),
                name="uniq_barion_check_item_modifier_option",
            ),
            models.UniqueConstraint(
                fields=["check_item", "bundle_option"],
                condition=Q(bundle_option__isnull=False),
                name="uniq_barion_check_item_bundle_option",
            ),
            models.CheckConstraint(
                check=(
                    (Q(option__isnull=False) & Q(bundle_option__isnull=True))
                    | (Q(option__isnull=True) & Q(bundle_option__isnull=False))
                ),
                name="chk_barion_check_item_one_option_source",
            ),
        ]

    def __str__(self) -> str:
        if self.option_id:
            return f"{self.check_item_id}: {self.option.name}"
        if self.bundle_option_id:
            return f"{self.check_item_id}: {self.bundle_option.artikl.name} x{self.quantity}"
        return f"{self.check_item_id}: -"

    def clean(self):
        if self.option_id and self.quantity != 1:
            raise ValidationError("Simple modifier selection quantity mora biti 1.")
