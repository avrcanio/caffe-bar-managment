from datetime import date as date_cls
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import DEFERRED
from django.db.models import Q, Sum
from django.utils import timezone


class Ledger(models.Model):
    """
    Minimalni subjekt (firma/obrt) kojem pripada kontni plan i knjizenja.
    Kasnije ga mozes zamijeniti FK-om na svoj Company model.
    """
    name = models.CharField(max_length=200)
    oib = models.CharField(max_length=11, blank=True, default="")

    def clean(self):
        qs = Ledger.objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if qs.exists():
            raise ValidationError("U ovoj bazi smije postojati samo jedan Ledger (1 firma = 1 baza).")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Ledger"
        verbose_name_plural = "Ledgers"

    def __str__(self) -> str:
        return f"{self.name}"


class Account(models.Model):
    class AccountType(models.TextChoices):
        ASSET = "ASSET", "Imovina"
        LIABILITY = "LIABILITY", "Obveze"
        EQUITY = "EQUITY", "Kapital"
        INCOME = "INCOME", "Prihodi"
        EXPENSE = "EXPENSE", "Rashodi"

    class NormalSide(models.TextChoices):
        DEBIT = "D", "Duguje"
        CREDIT = "P", "Potrazuje"

    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="accounts")
    code = models.CharField(max_length=32)  # npr. "1200" (string!)
    name = models.CharField(max_length=255)

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )

    type = models.CharField(max_length=16, choices=AccountType.choices)
    normal_side = models.CharField(max_length=1, choices=NormalSide.choices)

    is_postable = models.BooleanField(default=True)  # smije se knjiziti na ovaj konto?
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Account"
        verbose_name_plural = "Accounts"
        ordering = ["ledger_id", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "code"],
                name="uq_account_code_per_ledger",
            ),
            models.CheckConstraint(
                check=~Q(code=""),
                name="ck_account_code_not_empty",
            ),
        ]
        indexes = [
            models.Index(fields=["ledger", "code"]),
            models.Index(fields=["ledger", "parent"]),
        ]

    def clean(self):
        # parent mora biti iz istog ledgera
        if self.parent and self.parent.ledger_id != self.ledger_id:
            raise ValidationError({"parent": "Parent konto mora biti unutar istog ledgera."})

        # Ako konto ima djecu (u bazi), ne bi trebao biti postable
        if self.pk and self.is_postable and self.children.exists():
            raise ValidationError({"is_postable": "Konto s podkontima ne bi trebao biti postable."})

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Period(models.Model):
    """
    Racunovodstveni period (npr. mjesec) koji mozes zakljucati.
    """
    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="periods")
    name = models.CharField(max_length=50)  # npr. "2026-01"
    start_date = models.DateField()
    end_date = models.DateField()
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Period"
        verbose_name_plural = "Periods"
        ordering = ["ledger_id", "-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "name"],
                name="uq_period_name_per_ledger",
            ),
            models.CheckConstraint(
                check=Q(end_date__gte=models.F("start_date")),
                name="ck_period_date_range_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["ledger", "start_date", "end_date"]),
        ]

    def clean(self):
        qs = Period.objects.filter(ledger=self.ledger)
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        overlap = qs.filter(start_date__lte=self.end_date, end_date__gte=self.start_date).exists()
        if overlap:
            raise ValidationError("Period se preklapa s postojecim periodom u istom ledgeru.")

    def close(self):
        self.is_closed = True
        self.closed_at = timezone.now()
        self.save(update_fields=["is_closed", "closed_at"])

    def __str__(self) -> str:
        return f"{self.ledger}: {self.name}"


class JournalEntry(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Nacrt"
        POSTED = "POSTED", "Proknjizeno"
        VOID = "VOID", "Stornirano"

    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="entries")
    number = models.PositiveIntegerField()  # broj temeljnice, unique po ledgeru
    date = models.DateField()
    description = models.CharField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    reversed_entry = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reversal",
    )

    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_journal_entries",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        status = self.__dict__.get("status", DEFERRED)
        date = self.__dict__.get("date", DEFERRED)
        self._orig_status = None if status is DEFERRED else status
        self._orig_date = None if date is DEFERRED else date

    class Meta:
        verbose_name = "Journal entry"
        verbose_name_plural = "Journal entries"
        ordering = ["ledger_id", "-date", "-number"]
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "number"],
                name="uq_entry_number_per_ledger",
            ),
        ]
        indexes = [
            models.Index(fields=["ledger", "date"]),
            models.Index(fields=["ledger", "number"]),
        ]

    def clean(self):
        period = Period.objects.filter(
            ledger=self.ledger,
            start_date__lte=self.date,
            end_date__gte=self.date,
            is_closed=True,
        ).exists()
        if period and self.status != self.Status.DRAFT:
            raise ValidationError("Ne mozes knjiziti u zakljucani period.")

    def _is_in_closed_period(self) -> bool:
        return Period.objects.filter(
            ledger=self.ledger,
            start_date__lte=self.date,
            end_date__gte=self.date,
            is_closed=True,
        ).exists()

    def save(self, *args, **kwargs):
        is_update = self.pk is not None

        if is_update:
            if self._orig_status is None or self._orig_date is None:
                original = (
                    JournalEntry.objects.filter(pk=self.pk)
                    .values("status", "date")
                    .first()
                )
                if original:
                    if self._orig_status is None:
                        self._orig_status = original.get("status")
                    if self._orig_date is None:
                        self._orig_date = original.get("date")
            if self._orig_status == self.Status.POSTED:
                if self.status != self._orig_status:
                    raise ValidationError("Ne mozes mijenjati status proknjizene temeljnice.")
                if self.date != self._orig_date:
                    raise ValidationError("Ne mozes mijenjati datum proknjizene temeljnice.")

        if self.ledger_id and self.date:
            if self.status == self.Status.POSTED and self._is_in_closed_period():
                raise ValidationError("Ne mozes spremiti proknjizenu temeljnicu u zakljucani period.")

        super().save(*args, **kwargs)

        self._orig_status = self.status
        self._orig_date = self.date

    def delete(self, *args, **kwargs):
        if self.status == self.Status.POSTED:
            raise ValidationError("Ne mozes obrisati proknjizenu temeljnicu.")
        return super().delete(*args, **kwargs)

    def is_balanced(self) -> bool:
        totals = self.items.aggregate(
            d=Sum("debit", default=Decimal("0.00")),
            c=Sum("credit", default=Decimal("0.00")),
        )
        return (totals["d"] or Decimal("0.00")) == (totals["c"] or Decimal("0.00"))

    def post(self, user=None):
        """
        Jedino mjesto gdje prelazi u POSTED.
        Tu radis provjere: balans, zakljucani period, postable konto.
        """
        if self.status != self.Status.DRAFT:
            raise ValidationError("Mozes knjiziti samo temeljnice u statusu DRAFT.")

        if not self.items.exists():
            raise ValidationError("Temeljnica mora imati barem jednu stavku (realno: barem 2).")

        if not self.is_balanced():
            raise ValidationError("Temeljnica nije uravnotezena (D != P).")

        closed = Period.objects.filter(
            ledger=self.ledger,
            start_date__lte=self.date,
            end_date__gte=self.date,
            is_closed=True,
        ).exists()
        if closed:
            raise ValidationError("Datum temeljnice je u zakljucanom periodu.")

        self.status = self.Status.POSTED
        self.posted_at = timezone.now()
        if user is not None:
            self.posted_by = user
        self.save(update_fields=["status", "posted_at", "posted_by"])

    def __str__(self) -> str:
        return f"{self.ledger} #{self.number} ({self.date})"

    def reverse(self, *, reverse_date: date_cls | None = None, user=None) -> "JournalEntry":
        if self.status != self.Status.POSTED:
            raise ValidationError("Mozes stornirati samo proknjizenu temeljnicu.")

        if hasattr(self, "reversal"):
            raise ValidationError("Ova temeljnica je vec stornirana.")

        reverse_date = reverse_date or date_cls.today()

        reversal = JournalEntry.objects.create(
            ledger=self.ledger,
            number=self._next_reversal_number(),
            date=reverse_date,
            description=f"Storno temeljnice #{self.number}",
            status=self.Status.DRAFT,
            reversed_entry=self,
        )

        for item in self.items.all():
            JournalItem.objects.create(
                entry=reversal,
                account=item.account,
                debit=item.credit,
                credit=item.debit,
                description=f"Storno: {item.description}",
            )

        reversal.post(user=user)
        return reversal

    def _next_reversal_number(self) -> int:
        last = JournalEntry.objects.filter(ledger=self.ledger).aggregate(
            max_number=models.Max("number")
        )["max_number"]
        return (last or 0) + 1


class JournalItem(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="items")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_items")

    description = models.CharField(max_length=500, blank=True, default="")

    debit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig_entry_id = self.entry_id

    class Meta:
        verbose_name = "Journal item"
        verbose_name_plural = "Journal items"
        ordering = ["entry_id", "id"]
        constraints = [
            models.CheckConstraint(
                check=Q(debit__gte=0) & Q(credit__gte=0),
                name="ck_item_non_negative",
            ),
            models.CheckConstraint(
                check=(
                    (Q(debit=0) & Q(credit__gt=0)) |
                    (Q(credit=0) & Q(debit__gt=0))
                ),
                name="ck_item_one_sided_amount",
            ),
        ]
        indexes = [
            models.Index(fields=["entry", "account"]),
        ]

    def clean(self):
        if self.account_id and self.entry_id:
            if self.account.ledger_id != self.entry.ledger_id:
                raise ValidationError("Konto i temeljnica moraju biti u istom ledgeru.")

        if self.account_id and not self.account.is_postable:
            raise ValidationError({"account": "Ne mozes knjiziti na konto koji nije postable (grupni konto)."})

        if self.entry_id and self.entry.status == JournalEntry.Status.POSTED:
            raise ValidationError("Ne mozes mijenjati stavke na proknjizenoj temeljnici.")

    def save(self, *args, **kwargs):
        if self.entry_id:
            status = (
                JournalEntry.objects.filter(pk=self.entry_id)
                .values_list("status", flat=True)
                .first()
            )
            if status == JournalEntry.Status.POSTED:
                raise ValidationError("Ne mozes spremati stavke na proknjizenoj temeljnici.")

        super().save(*args, **kwargs)
        self._orig_entry_id = self.entry_id

    def delete(self, *args, **kwargs):
        if self.entry_id:
            status = (
                JournalEntry.objects.filter(pk=self.entry_id)
                .values_list("status", flat=True)
                .first()
            )
            if status == JournalEntry.Status.POSTED:
                raise ValidationError("Ne mozes obrisati stavku proknjizene temeljnice.")
        return super().delete(*args, **kwargs)

    def __str__(self) -> str:
        side = "D" if self.debit > 0 else "P"
        amt = self.debit if self.debit > 0 else self.credit
        return f"{self.entry} {self.account.code} {side} {amt}"

# Create your models here.
