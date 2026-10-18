"""Health articles ("Picked for you", "Small habits, healthier days")."""

from __future__ import annotations

from typing import ClassVar

from django.db import models

from ibolit.core.models import BaseModel


class Article(BaseModel):
    class Category(models.TextChoices):
        PREVENTION = "prevention", "Prevention"
        NUTRITION = "nutrition", "Nutrition"
        MENTAL_HEALTH = "mental_health", "Mental health"
        FITNESS = "fitness", "Fitness"
        MEDICINE = "medicine", "Medicine"
        FAMILY_HEALTH = "family_health", "Family health"
        VETERINARY = "veterinary", "Veterinary"

    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160, unique=True)
    summary = models.CharField(max_length=300)
    sections = models.JSONField(default=list, blank=True)  # [{"heading": "...", "body": "..."}]
    category = models.CharField(max_length=20, choices=Category.choices)
    read_minutes = models.PositiveSmallIntegerField(default=3)
    published_at = models.DateTimeField(null=True, blank=True)  # null = draft
    reviewed_by = models.ForeignKey("directory.Provider", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cover = models.ImageField(upload_to="articles/", blank=True)

    class Meta:
        db_table = "articles_article"
        ordering: ClassVar[list[str]] = ["-published_at"]

    def __str__(self) -> str:
        return self.title
