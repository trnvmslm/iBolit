from __future__ import annotations

from django.apps import AppConfig


class SeedConfig(AppConfig):
    name = "ibolit.seed"
    label = "seed"
    verbose_name = "Seed data (reference + demo data)"
