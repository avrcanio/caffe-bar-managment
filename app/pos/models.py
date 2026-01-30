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
