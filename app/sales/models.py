from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SalesInvoice(models.Model):
    rm_number = models.IntegerField(unique=True)
    issued_on = models.DateField()
    report_from = models.DateField(null=True, blank=True)
    issued_at = models.DateTimeField()
    location_name = models.CharField(max_length=255, blank=True, default="")
    buyer_name = models.CharField(max_length=255, blank=True, default="")
    waiter_name = models.CharField(max_length=255, blank=True, default="")
    net_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    vat_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    currency = models.CharField(max_length=10, blank=True, default="")
    ledger = models.ForeignKey(
        "accounting.Ledger",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_invoices",
        db_column="organization_id",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_invoices",
        db_column="location_id",
    )
    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_invoices",
        db_column="pos_id",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_invoices",
        verbose_name="konobar",
    )
    is_card = models.BooleanField(default=False, verbose_name="kartica")

    def save(self, *args, **kwargs):
        if self.pk:
            previous = (
                SalesInvoice.objects.filter(pk=self.pk)
                .values_list("is_card", "issued_on", "user_id", "warehouse_id", "pos_id")
                .first()
            )
            if previous and previous[0] != self.is_card:
                issued_on, user_id, warehouse_id, pos_id = previous[1:]
                if user_id and ShiftTurnoverClose.objects.filter(
                    turnover__issued_on=issued_on,
                    turnover__user_id=user_id,
                    turnover__warehouse_id=warehouse_id,
                    turnover__pos_id=pos_id,
                ).exists():
                    raise ValidationError("Kartice se ne mogu mijenjati nakon zatvaranja smjene.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Racun {self.rm_number} ({self.issued_on:%Y-%m-%d})"

    class Meta:
        verbose_name = "Racun (promet)"
        verbose_name_plural = "Racuni (promet)"
        constraints = []


class SalesInvoiceItem(models.Model):
    invoice = models.ForeignKey(
        "sales.SalesInvoice",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoice_items",
    )
    product_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    discount_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    discount_percent = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )
    stock_out_posted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.product_name} x {self.quantity}"

    class Meta:
        verbose_name = "Stavka racuna (promet)"
        verbose_name_plural = "Stavke racuna (promet)"


class ShiftTurnover(models.Model):
    issued_on = models.DateField(verbose_name="datum")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_turnovers",
        verbose_name="konobar",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_turnovers",
        verbose_name="skladiste",
    )
    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_turnovers",
        verbose_name="pos",
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="ukupno",
    )
    invoice_count = models.PositiveIntegerField(default=0, verbose_name="broj racuna")
    invoice_ids = models.JSONField(blank=True, default=list, verbose_name="racuni")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="kreirano")

    def __str__(self) -> str:
        user_label = self.user.username if self.user else "-"
        return f"Promet smjene {self.issued_on} ({user_label})"

    class Meta:
        verbose_name = "Promet smjene"
        verbose_name_plural = "Prometi smjena"
        constraints = [
            models.UniqueConstraint(
                fields=["issued_on", "user", "warehouse", "pos"],
                name="uniq_shift_turnover",
            )
        ]


class ShiftTurnoverClose(models.Model):
    turnover = models.OneToOneField(
        "sales.ShiftTurnover",
        on_delete=models.CASCADE,
        related_name="close",
        verbose_name="promet smjene",
    )
    cash_counted = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="gotovina u novcaniku",
    )
    card_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="kartice",
    )
    note = models.TextField(blank=True, default="", verbose_name="napomena")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_turnover_closes",
        verbose_name="korisnik",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="kreirano")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="azurirano")

    def __str__(self) -> str:
        return f"Zatvaranje smjene {self.turnover_id}"

    class Meta:
        verbose_name = "Zatvaranje smjene"
        verbose_name_plural = "Zatvaranja smjena"


class ShiftTurnoverExpense(models.Model):
    close = models.ForeignKey(
        "sales.ShiftTurnoverClose",
        on_delete=models.CASCADE,
        related_name="expenses",
        verbose_name="zatvaranje smjene",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="iznos",
    )
    note = models.CharField(max_length=255, blank=True, default="", verbose_name="opis")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_turnover_expenses",
        verbose_name="korisnik",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="kreirano")

    def __str__(self) -> str:
        return f"Rashod {self.amount}"

    class Meta:
        verbose_name = "Rashod smjene"
        verbose_name_plural = "Rashodi smjena"


class ShiftCashHandover(models.Model):
    class Kind(models.TextChoices):
        OPENING = "OPENING", "Preuzimanje"
        CLOSING = "CLOSING", "Predaja"

    turnover = models.ForeignKey(
        "sales.ShiftTurnover",
        on_delete=models.CASCADE,
        related_name="cash_handovers",
        verbose_name="promet smjene",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    counted_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    difference_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.TextField(blank=True, default="", verbose_name="napomena")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shift_cash_handovers",
        verbose_name="korisnik",
    )
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cash_handover",
        verbose_name="temeljnica",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="kreirano")

    def save(self, *args, **kwargs):
        if self.expected_amount is not None and self.counted_amount is not None:
            self.difference_amount = self.counted_amount - self.expected_amount
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.turnover_id} {self.kind} {self.counted_amount}"

    class Meta:
        verbose_name = "Primopredaja blagajne"
        verbose_name_plural = "Primopredaje blagajne"
        constraints = [
            models.UniqueConstraint(
                fields=["turnover", "kind"],
                name="uniq_shift_cash_handover",
            )
        ]


class SalesZPosting(models.Model):
    issued_on = models.DateField()
    ledger = models.ForeignKey(
        "accounting.Ledger",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_z_postings",
    )
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_z_postings",
        db_column="location_id",
    )
    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_z_postings",
    )
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    pnp_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cash_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    revenue_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    vat_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    pnp_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_z_postings",
    )
    posted_by = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_z_postings",
    )
    posted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        loc = self.warehouse.name if self.warehouse_id else "?"
        pos = self.pos.name if self.pos_id else "?"
        return f"Z {self.issued_on} (lok {loc}, POS {pos})"

    class Meta:
        verbose_name = "Z knjiženje (promet)"
        verbose_name_plural = "Z knjiženja (promet)"
        constraints = [
            models.UniqueConstraint(
                fields=["issued_on", "ledger", "warehouse", "pos"],
                name="uq_sales_z_posting",
            )
        ]


class FiscalReceipt(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        ERROR = "error", "Error"

    invoice = models.OneToOneField(
        "sales.SalesInvoice",
        on_delete=models.CASCADE,
        related_name="fiscal_receipt",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    zki = models.CharField(max_length=64, blank=True, default="")
    jir = models.CharField(max_length=64, blank=True, default="")
    payment_type = models.CharField(max_length=20, blank=True, default="CASH")
    xml_request = models.TextField(blank=True, default="")
    xml_response = models.TextField(blank=True, default="")
    qr_payload = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Fiskalni racun"
        verbose_name_plural = "Fiskalni racuni"

    def __str__(self) -> str:
        return f"FiscalReceipt {self.invoice_id} ({self.status})"


class Representation(models.Model):
    occurred_at = models.DateTimeField(auto_now_add=True, verbose_name="Vrijeme")
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        to_field="rm_id",
        on_delete=models.PROTECT,
        related_name="representations",
        verbose_name="Skladiste",
    )
    user = models.ForeignKey(
        "auth.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="representations",
        verbose_name="Korisnik",
    )
    reason = models.ForeignKey(
        "sales.RepresentationReason",
        on_delete=models.PROTECT,
        related_name="representations",
        verbose_name="Razlog reprezentacije",
    )
    note = models.TextField(blank=True, default="", verbose_name="Napomena")

    def __str__(self) -> str:
        return f"Reprezentacija {self.occurred_at:%Y-%m-%d %H:%M}"

    class Meta:
        verbose_name = "Reprezentacija"
        verbose_name_plural = "Reprezentacije"


class RepresentationReason(models.Model):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Razlog reprezentacije"
        verbose_name_plural = "Razlozi reprezentacije"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class RepresentationItem(models.Model):
    representation = models.ForeignKey(
        "sales.Representation",
        on_delete=models.CASCADE,
        related_name="items",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="representation_items",
        limit_choices_to={"is_sellable": True},
        verbose_name="Artikl",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Kolicina")
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Cijena",
    )
    transfer_posted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.artikl} x {self.quantity}"

    class Meta:
        verbose_name = "Stavka reprezentacije"
        verbose_name_plural = "Stavke reprezentacije"


class SalesPriceList(models.Model):
    name = models.CharField(max_length=150, verbose_name="Naziv")
    is_active = models.BooleanField(default=True, verbose_name="Aktivan")
    is_default = models.BooleanField(default=False, verbose_name="Zadani")
    valid_from = models.DateTimeField(verbose_name="Vrijedi od")
    valid_to = models.DateTimeField(null=True, blank=True, verbose_name="Vrijedi do")
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_price_lists",
        verbose_name="Skladiste",
    )
    pos = models.ForeignKey(
        "pos.Pos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_price_lists",
        verbose_name="POS",
    )
    note = models.TextField(blank=True, default="", verbose_name="Napomena")
    remaris_applied_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Remaris primijenjen",
    )
    remaris_reverted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Remaris vracen",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Prodajni cjenik"
        verbose_name_plural = "Prodajni cjenici"
        ordering = ["-valid_from", "name"]

    def __str__(self) -> str:
        scope = []
        if self.warehouse:
            scope.append(f"Skladiste: {self.warehouse}")
        if self.pos:
            scope.append(f"POS: {self.pos}")
        scope_str = f" ({', '.join(scope)})" if scope else ""
        return f"{self.name}{scope_str}"


class SalesPriceItem(models.Model):
    price_list = models.ForeignKey(
        "sales.SalesPriceList",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Cjenik",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="sales_price_items",
        verbose_name="Artikl",
    )
    unit_price_gross = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Cijena (bruto)",
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktivno")
    note = models.TextField(blank=True, default="", verbose_name="Napomena")

    class Meta:
        verbose_name = "Stavka prodajnog cjenika"
        verbose_name_plural = "Stavke prodajnog cjenika"
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "artikl"],
                name="uniq_sales_pricelist_artikl",
            )
        ]

    def __str__(self) -> str:
        return f"{self.artikl} ({self.unit_price_gross})"


class SalesPriceRule(models.Model):
    class RuleType(models.TextChoices):
        HAPPY_HOUR = "happy_hour", "Happy hour"
        PROMO = "promo", "Promocija"
        EVENT = "event", "Događaj"

    class AdjustType(models.TextChoices):
        PERCENT = "percent", "Postotak"
        AMOUNT = "amount", "Iznos"
        SET_PRICE = "set_price", "Fiksna cijena"

    price_list = models.ForeignKey(
        "sales.SalesPriceList",
        on_delete=models.CASCADE,
        related_name="rules",
        verbose_name="Cjenik",
    )
    name = models.CharField(max_length=150, verbose_name="Naziv")
    rule_type = models.CharField(max_length=20, choices=RuleType.choices, verbose_name="Tip")
    is_active = models.BooleanField(default=True, verbose_name="Aktivno")
    valid_from = models.DateTimeField(verbose_name="Vrijedi od")
    valid_to = models.DateTimeField(null=True, blank=True, verbose_name="Vrijedi do")
    priority = models.PositiveIntegerField(default=0, verbose_name="Prioritet")
    adjust_type = models.CharField(max_length=20, choices=AdjustType.choices, verbose_name="Model")
    value = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="Vrijednost")
    note = models.TextField(blank=True, default="", verbose_name="Napomena")

    class Meta:
        verbose_name = "Pravilo cijena"
        verbose_name_plural = "Pravila cijena"
        ordering = ["-priority", "valid_from"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_rule_type_display()})"


class SalesPriceRuleItem(models.Model):
    rule = models.ForeignKey(
        "sales.SalesPriceRule",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Pravilo",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="sales_price_rule_items",
        verbose_name="Artikl",
    )

    class Meta:
        verbose_name = "Stavka pravila cijena"
        verbose_name_plural = "Stavke pravila cijena"
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "artikl"],
                name="uniq_sales_pricerule_artikl",
            )
        ]

    def __str__(self) -> str:
        return f"{self.rule} -> {self.artikl}"
