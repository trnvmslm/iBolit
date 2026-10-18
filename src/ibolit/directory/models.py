"""Directory: clinics, specialties, providers (doctors, lab specialists, vaccination clinicians), licence."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q

from ibolit.core.models import BaseModel


class Clinic(BaseModel):
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=80, default="Almaty")
    district = models.CharField(max_length=80, blank=True, default="")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        db_table = "directory_clinic"

    def __str__(self) -> str:
        return self.name


class Specialty(BaseModel):
    slug = models.SlugField(max_length=40, unique=True)
    name_i18n = models.JSONField()
    blurb_i18n = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    search_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "directory_specialty"
        ordering: ClassVar[list[str]] = ["sort_order"]
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(fields=["search_text"], name="specialty_search_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.slug


class Provider(BaseModel):
    """A bookable clinician."""

    class Kind(models.TextChoices):
        DOCTOR = "doctor"
        LAB_SPECIALIST = "lab_specialist"
        VACCINATION_CLINICIAN = "vaccination_clinician"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="provider")
    kind = models.CharField(max_length=24, choices=Kind.choices, default=Kind.DOCTOR)
    display_name = models.CharField(max_length=120)
    specialty = models.ForeignKey(Specialty, null=True, blank=True, on_delete=models.PROTECT, related_name="providers")
    clinic = models.ForeignKey(Clinic, null=True, blank=True, on_delete=models.PROTECT, related_name="providers")
    headline_i18n = models.JSONField(default=dict, blank=True)
    bio_i18n = models.JSONField(default=dict, blank=True)
    education = models.CharField(max_length=200, blank=True, default="")
    residency = models.CharField(max_length=200, blank=True, default="")
    languages = ArrayField(models.CharField(max_length=2), default=list)
    experience_years = models.PositiveSmallIntegerField(default=0)
    rating_avg = models.DecimalField(max_digits=2, decimal_places=1, default=0)
    rating_count = models.PositiveIntegerField(default=0)
    recommend_pct = models.PositiveSmallIntegerField(default=0)
    accepts_on_demand = models.BooleanField(default=False)
    # Presence: heartbeat sets online_until = now + 2 min ("Online now", "2 doctors online now").
    online_until = models.DateTimeField(null=True, blank=True)
    is_listed = models.BooleanField(default=True)
    # "Every clinician's license is verified before joining iBolit": staff check the licence
    # number in the admin and set verified_at. Unverified providers can't be booked.
    license_number = models.CharField(max_length=60, blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)
    search_vector = SearchVectorField(null=True, editable=False)
    search_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "directory_provider"
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(fields=["search_vector"], name="provider_search_fts"),
            GinIndex(fields=["search_text"], name="provider_search_trgm", opclasses=["gin_trgm_ops"]),
            models.Index(fields=["specialty", "-rating_avg"], name="provider_specialty_rating"),
            models.Index(fields=["online_until"], name="provider_online_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=Q(rating_avg__gte=0) & Q(rating_avg__lte=5), name="provider_rating_range"),
            models.CheckConstraint(condition=Q(recommend_pct__lte=100), name="provider_recommend_pct_range"),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def is_verified(self) -> bool:
        return self.verified_at is not None


class ProviderOffering(BaseModel):
    """Price and duration of one service in one mode for one provider."""

    class Mode(models.TextChoices):
        VIDEO = "video"
        IN_CLINIC = "in_clinic"

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="offerings")
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="offerings")
    mode = models.CharField(max_length=10, choices=Mode.choices)
    price_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="KZT")
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "directory_provider_offering"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["provider", "service", "mode"], name="offering_unique"),
            models.CheckConstraint(condition=Q(duration_minutes__gte=5), name="offering_min_duration"),
        ]

    def __str__(self) -> str:
        return f"{self.provider_id} {self.service_id} {self.mode}"


class Review(BaseModel):
    """Verified-patient review: only for a completed appointment, one per appointment."""

    class Moderation(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    appointment = models.OneToOneField("scheduling.Appointment", on_delete=models.PROTECT, related_name="review")
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="reviews")
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    recommends = models.BooleanField(default=True)
    body = models.TextField(max_length=1000, blank=True, default="")
    author_display = models.CharField(max_length=40)
    moderation_status = models.CharField(max_length=10, choices=Moderation.choices, default=Moderation.PENDING)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    moderated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "directory_review"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=Q(rating__gte=1) & Q(rating__lte=5), name="review_rating_range"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["provider", "-created_at"], condition=Q(moderation_status="approved"), name="review_approved_idx"),
        ]

    def __str__(self) -> str:
        return f"Review {self.pk} ({self.rating}★)"
