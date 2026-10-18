"""Services catalog: segments (Specialists, Laboratory, Vaccination, ...) and services."""

from __future__ import annotations

from typing import ClassVar

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from ibolit.core.models import BaseModel


class ServiceSegment(BaseModel):
    slug = models.SlugField(max_length=40, unique=True)
    name_i18n = models.JSONField()
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_bookable = models.BooleanField(default=True)
    # Segment hidden unless this feature flag is on (e.g. "veterinary").
    feature_flag = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        db_table = "catalog_service_segment"
        ordering: ClassVar[list[str]] = ["sort_order"]

    def __str__(self) -> str:
        return self.slug


class Service(BaseModel):
    class Mode(models.TextChoices):
        VIDEO = "video"
        IN_CLINIC = "in_clinic"

    code = models.SlugField(max_length=60, unique=True)
    segment = models.ForeignKey(ServiceSegment, on_delete=models.PROTECT, related_name="services")
    specialty = models.ForeignKey(
        "directory.Specialty", null=True, blank=True, on_delete=models.PROTECT, related_name="services"
    )
    name_i18n = models.JSONField()
    tagline_i18n = models.JSONField(default=dict, blank=True)
    description_i18n = models.JSONField(default=dict, blank=True)
    included_i18n = models.JSONField(default=dict, blank=True)  # {"en": ["...", ...]}
    preparation_i18n = models.JSONField(default=dict, blank=True)
    modes = ArrayField(models.CharField(max_length=10, choices=Mode.choices), default=list)
    default_duration_minutes = models.PositiveSmallIntegerField(default=30)
    base_price_minor = models.PositiveIntegerField(default=0)
    is_recommended = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    search_text = models.TextField(blank=True, default="")

    class Meta:
        db_table = "catalog_service"
        ordering: ClassVar[list[str]] = ["sort_order"]
        indexes: ClassVar[list[models.Index]] = [
            GinIndex(fields=["search_text"], name="service_search_trgm", opclasses=["gin_trgm_ops"]),
        ]

    def __str__(self) -> str:
        return self.code
