"""Users, patient profile, devices, Apple identities, legal acceptance."""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import Q

from ibolit.core import clock
from ibolit.core.models import BaseModel
from ibolit.core.roles import Role


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def create_user(self, phone: str, password: str | None = None, **extra: Any) -> User:
        user = self.model(phone=phone, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone: str, password: str | None = None, **extra: Any) -> User:
        extra.update(is_staff=True, is_superuser=True, role=Role.ADMIN)
        return self.create_user(phone, password, **extra)


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    """Patient, doctor, lab specialist, pharmacist or staff."""

    class Roles(models.TextChoices):
        PATIENT = Role.PATIENT, "Patient"
        DOCTOR = Role.DOCTOR, "Doctor"
        LAB_SPECIALIST = Role.LAB_SPECIALIST, "Lab specialist"
        PHARMACIST = Role.PHARMACIST, "Pharmacist"
        INTERN = Role.INTERN, "Medical intern"
        SUPPORT = Role.SUPPORT, "Support"
        ADMIN = Role.ADMIN, "Administrator"

    class Language(models.TextChoices):
        EN = "en", "English"
        RU = "ru", "Russian"
        KK = "kk", "Kazakh"

    phone = models.CharField(max_length=16, unique=True)
    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.PATIENT)
    full_name = models.CharField(max_length=150, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.EN)
    timezone = models.CharField(max_length=64, default="Asia/Almaty")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        db_table = "accounts_user"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=Q(phone__regex=r"^(\+[1-9][0-9]{7,14}|admin)$"), name="user_phone_e164"),
        ]

    def __str__(self) -> str:
        return self.full_name or self.phone

    @property
    def first_name(self) -> str:
        return self.full_name.split(" ")[0] if self.full_name else ""


class PatientProfile(BaseModel):
    class Appearance(models.TextChoices):
        LIGHT = "light"
        DARK = "dark"
        SYSTEM = "system"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="patient_profile")
    emergency_contact_name = models.CharField(max_length=120, blank=True, default="")
    emergency_contact_phone = models.CharField(max_length=16, blank=True, default="")
    personalization_enabled = models.BooleanField(default=False)
    appearance = models.CharField(max_length=16, choices=Appearance.choices, default=Appearance.LIGHT)
    interests = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "accounts_patient_profile"


class Address(BaseModel):
    """Saved delivery address ("125 Abay Ave, Apt 24, Almaty")."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField(max_length=40, default="Home")
    line1 = models.CharField(max_length=200)
    apartment = models.CharField(max_length=40, blank=True, default="")
    city = models.CharField(max_length=80, default="Almaty")
    is_default = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_address"

    @property
    def display(self) -> str:
        return ", ".join(p for p in (self.line1, f"Apt {self.apartment}" if self.apartment else "", self.city) if p)


class Device(BaseModel):
    """Trusted device ("This iPhone · Last active now") with its APNs push token."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    install_id = models.CharField(max_length=128)
    name = models.CharField(max_length=80)
    apns_token = models.CharField(max_length=200, blank=True, default="")
    last_active_at = models.DateTimeField(default=clock.now)
    refresh_jti = models.CharField(max_length=64, blank=True, default="")  # first refresh token of this device

    class Meta:
        db_table = "accounts_device"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user", "install_id"], name="device_unique"),
        ]


class AppleIdentity(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="apple_identity")
    subject = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = "accounts_apple_identity"


class LegalAcceptance(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="legal_acceptances")
    document = models.ForeignKey("core.LegalDocument", on_delete=models.PROTECT)

    class Meta:
        db_table = "accounts_legal_acceptance"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user", "document"], name="legal_acceptance_unique"),
        ]


class SupportMessage(BaseModel):
    """'Contact support' form."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="support_messages")
    topic = models.CharField(max_length=40, default="other")
    text = models.TextField(max_length=2000)

    class Meta:
        db_table = "accounts_support_message"
