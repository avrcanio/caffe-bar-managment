from django.db import models


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
