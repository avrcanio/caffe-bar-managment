from decimal import Decimal, ROUND_HALF_UP
import secrets

from django.db import models
from django.utils import timezone


class PurchaseOrder(models.Model):
    STATUS_CREATED = "created"
    STATUS_SENT = "sent"
    STATUS_CONFIRMED = "confirmed"
    STATUS_RECEIVED = "received"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = (
        (STATUS_CREATED, "Kreirana"),
        (STATUS_SENT, "Poslana"),
        (STATUS_CONFIRMED, "Potvrđena"),
        (STATUS_RECEIVED, "Zaprimljena"),
        (STATUS_CANCELED, "Otkazana"),
    )

    supplier = models.ForeignKey(
        "contacts.Supplier",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        verbose_name="dobavljač",
    )
    ordered_at = models.DateTimeField(verbose_name="datum narudžbe")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_CREATED,
        verbose_name="status narudžbe",
    )
    confirmation_token = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        unique=True,
        verbose_name="token potvrde",
    )
    confirmation_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="vrijeme slanja potvrde",
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="vrijeme potvrde",
    )
    total_net = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="netto iznos",
    )
    total_gross = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="bruto iznos",
    )
    total_deposit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="povratna naknada",
    )
    payment_type = models.ForeignKey(
        "configuration.PaymentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders",
        verbose_name="tip placanja",
    )
    primka_created = models.BooleanField(default=False, verbose_name="primka kreirana")

    def __str__(self) -> str:
        return f"PurchaseOrder {self.id}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.recalculate_totals()

    def ensure_confirmation_token(self):
        if self.confirmation_token:
            return self.confirmation_token
        while True:
            token = secrets.token_urlsafe(32)
            if not PurchaseOrder.objects.filter(confirmation_token=token).exists():
                break
        self.confirmation_token = token
        self.confirmation_sent_at = timezone.now()
        self.save(update_fields=["confirmation_token", "confirmation_sent_at"])
        return token

    def recalculate_totals(self):
        items = self.items.select_related("artikl__tax_group", "artikl__deposit")
        total_net = Decimal("0")
        total_deposit = Decimal("0")
        total_tax = Decimal("0")
        for item in items:
            if item.quantity is None:
                continue
            if item.price is None:
                line_net = Decimal("0")
            else:
                line_net = Decimal(item.price) * Decimal(item.quantity)
            rate = item.artikl.tax_group.rate if item.artikl and item.artikl.tax_group else Decimal("0")
            total_net += line_net
            total_tax += line_net * Decimal(rate)
            deposit_amount = None
            if item.artikl and item.artikl.deposit:
                deposit_amount = item.artikl.deposit.amount_eur
            if deposit_amount:
                total_deposit += Decimal(deposit_amount) * Decimal(item.quantity)

        total_net = total_net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_deposit = total_deposit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_tax = total_tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_gross = (total_net + total_tax + total_deposit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        PurchaseOrder.objects.filter(pk=self.pk).update(
            total_net=total_net,
            total_gross=total_gross,
            total_deposit=total_deposit,
        )

    def get_tax_group_totals(self):
        totals = {}
        items = self.items.select_related("artikl__tax_group")
        for item in items:
            if item.quantity is None:
                continue
            tax_group = item.artikl.tax_group if item.artikl else None
            if not tax_group:
                continue
            line_net = Decimal(item.price or 0) * Decimal(item.quantity)
            rate = Decimal(tax_group.rate)
            data = totals.setdefault(tax_group, {"base": Decimal("0"), "tax": Decimal("0")})
            data["base"] += line_net
            data["tax"] += line_net * rate

        results = []
        for tax_group, data in totals.items():
            base = data["base"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax = data["tax"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if tax == Decimal("0"):
                continue
            results.append(
                {
                    "tax_group": tax_group,
                    "rate": Decimal(tax_group.rate),
                    "base": base,
                    "tax": tax,
                }
            )
        results.sort(key=lambda item: (item["rate"], item["tax_group"].name))
        return results

    class Meta:
        verbose_name = "Narudzba"
        verbose_name_plural = "Narudzbe"


class PurchaseOrderItem(models.Model):
    order = models.ForeignKey(
        "PurchaseOrder",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="narudzba",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="artikl",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="kolicina")
    unit_of_measure = models.ForeignKey(
        "artikli.UnitOfMeasureData",
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="jedinica mjere",
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="cijena",
    )

    def __str__(self) -> str:
        return f"{self.artikl} x {self.quantity}"

    def save(self, *args, **kwargs):
        if self.price is None and self.order_id and self.artikl_id:
            self.price = self._resolve_price()
        super().save(*args, **kwargs)
        if self.order_id:
            self.order.recalculate_totals()

    def _resolve_price(self):
        from django.utils import timezone

        order_date = self.order.ordered_at.date() if self.order_id else timezone.now().date()
        qs = SupplierPriceItem.objects.select_related("price_list").filter(
            price_list__supplier=self.order.supplier,
            price_list__is_active=True,
        )
        qs = qs.filter(
            models.Q(price_list__valid_from__isnull=True)
            | models.Q(price_list__valid_from__lte=order_date),
            models.Q(price_list__valid_to__isnull=True)
            | models.Q(price_list__valid_to__gte=order_date),
        )
        qs = qs.filter(artikl=self.artikl)

        if self.unit_of_measure_id:
            exact = qs.filter(unit_of_measure=self.unit_of_measure).order_by(
                "-price_list__valid_from",
                "-price_list__created_at",
            ).first()
            if exact:
                return exact.price

        fallback = qs.filter(unit_of_measure__isnull=True).order_by(
            "-price_list__valid_from",
            "-price_list__created_at",
        ).first()
        return fallback.price if fallback else None

    class Meta:
        verbose_name = "Stavka narudzbe"
        verbose_name_plural = "Stavke narudzbi"

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        if order and order.pk:
            order.recalculate_totals()


class SupplierPriceList(models.Model):
    supplier = models.ForeignKey(
        "contacts.Supplier",
        on_delete=models.CASCADE,
        related_name="price_lists",
        verbose_name="dobavljac",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="datum kreiranja")
    valid_from = models.DateField(null=True, blank=True, verbose_name="vrijedi od")
    valid_to = models.DateField(null=True, blank=True, verbose_name="vrijedi do")
    currency = models.CharField(max_length=3, default="EUR", verbose_name="valuta")
    is_active = models.BooleanField(default=True, verbose_name="aktivno")

    def __str__(self) -> str:
        return f"{self.supplier} ({self.created_at:%Y-%m-%d})"

    class Meta:
        verbose_name = "Cjenik dobavljača"
        verbose_name_plural = "Cjenici dobavljača"


class SupplierPriceItem(models.Model):
    price_list = models.ForeignKey(
        "SupplierPriceList",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="cjenik",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.CASCADE,
        related_name="supplier_price_items",
        verbose_name="artikl",
    )
    unit_of_measure = models.ForeignKey(
        "artikli.UnitOfMeasureData",
        on_delete=models.PROTECT,
        related_name="supplier_price_items",
        null=True,
        blank=True,
        verbose_name="jedinica mjere",
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="cijena")

    def __str__(self) -> str:
        return f"{self.artikl} ({self.price})"

    class Meta:
        verbose_name = "Stavka cjenika"
        verbose_name_plural = "Stavke cjenika"
        constraints = [
            models.UniqueConstraint(
                fields=["price_list", "artikl"],
                name="uniq_supplier_pricelist_artikl",
            )
        ]


class WarehouseInput(models.Model):
    order = models.ForeignKey(
        "PurchaseOrder",
        on_delete=models.CASCADE,
        related_name="warehouse_inputs",
        verbose_name="narudzba",
    )
    supplier = models.ForeignKey(
        "contacts.Supplier",
        on_delete=models.PROTECT,
        related_name="warehouse_inputs",
        verbose_name="dobavljac",
    )
    payment_type = models.ForeignKey(
        "configuration.PaymentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouse_inputs",
        verbose_name="tip placanja",
    )
    remaris_id = models.IntegerField(null=True, blank=True, unique=True, verbose_name="remaris id")
    date = models.DateField(verbose_name="datum")
    date_modified = models.DateTimeField(null=True, blank=True, verbose_name="datum izmjene")
    document_type_code = models.CharField(max_length=10, default="10", verbose_name="tip dokumenta (sifra)")
    document_type = models.ForeignKey(
        "configuration.DocumentType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouse_inputs",
        verbose_name="tip dokumenta",
    )
    is_in_pdv_system = models.BooleanField(default=True, verbose_name="u PDV sustavu")
    warehouse = models.ForeignKey(
        "stock.WarehouseId",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouse_inputs",
        verbose_name="skladiste",
    )
    export_document_type_id = models.IntegerField(null=True, blank=True, verbose_name="export tip dokumenta id")
    invoice_code = models.CharField(max_length=100, blank=True, default="", verbose_name="broj racuna")
    delivery_note = models.CharField(max_length=100, blank=True, default="", verbose_name="broj otpremnice")
    is_r_invoice = models.BooleanField(default=True, verbose_name="R racun")
    is_internal_input = models.BooleanField(default=False, verbose_name="interni ulaz")
    is_nonmaterial_input = models.BooleanField(default=False, verbose_name="nematerijalni ulaz")
    purchase_order = models.ForeignKey(
        "PurchaseOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouse_inputs_purchase_orders",
        verbose_name="narudzbenica",
    )
    description = models.TextField(blank=True, default="", verbose_name="opis")
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ukupno")
    is_canceled = models.BooleanField(default=False, verbose_name="stornirano")
    submit_command = models.CharField(max_length=50, default="_save_", verbose_name="submit")
    raw_payload = models.JSONField(null=True, blank=True, verbose_name="raw payload")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="kreirano")
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="warehouse_inputs",
        verbose_name="temeljnica",
    )
    stock_move = models.OneToOneField(
        "stock.StockMove",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="warehouse_input",
        verbose_name="skladisno kretanje",
    )

    def __str__(self) -> str:
        return f"Primka {self.id} ({self.order_id})"

    class Meta:
        verbose_name = "Primka"
        verbose_name_plural = "Primke"


class WarehouseInputItem(models.Model):
    warehouse_input = models.ForeignKey(
        "WarehouseInput",
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="primka",
    )
    artikl = models.ForeignKey(
        "artikli.Artikl",
        on_delete=models.PROTECT,
        related_name="warehouse_input_items",
        verbose_name="artikl",
    )
    product_id = models.IntegerField(null=True, blank=True, verbose_name="product id")
    product_name = models.CharField(max_length=255, blank=True, default="", verbose_name="naziv artikla")
    unit_of_measure = models.ForeignKey(
        "artikli.UnitOfMeasureData",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="warehouse_input_items",
        verbose_name="jedinica mjere",
    )
    unit_name = models.CharField(max_length=100, blank=True, default="", verbose_name="naziv jedinice")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, verbose_name="kolicina")
    price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="cijena")
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="ukupno")
    buying_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="nabavna cijena")
    gross_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="bruto")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, verbose_name="pdv stopa")
    calculate_tax = models.BooleanField(default=True, verbose_name="racunaj pdv")
    rebate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="rabat")
    margin = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="marza")
    sales_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="prodajna cijena")
    ordinal = models.IntegerField(null=True, blank=True, verbose_name="redni broj")
    base_quantity = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True, verbose_name="bazna kolicina")
    vat_prepayment = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="predujam pdv")
    calculate_spillage = models.BooleanField(null=True, blank=True, verbose_name="izljev")
    price_on_stock_card = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="cijena na kartici")
    last_input_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="zadnja nabavna cijena")
    guid = models.CharField(max_length=100, blank=True, default="", verbose_name="guid")
    parent_guid = models.CharField(max_length=100, blank=True, default="", verbose_name="parent guid")

    def __str__(self) -> str:
        return f"{self.artikl} x {self.quantity}"

    class Meta:
        verbose_name = "Stavka primke"
        verbose_name_plural = "Stavke primke"
