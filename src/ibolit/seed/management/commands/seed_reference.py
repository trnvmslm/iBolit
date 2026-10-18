"""Load reference data (legal documents, clinic, specialties, services)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from ibolit.seed.reference import seed_reference


class Command(BaseCommand):
    help = "Load reference data (legal documents, clinic, specialties, services)."

    def handle(self, *args: Any, **options: Any) -> None:
        counts = seed_reference()
        self.stdout.write(self.style.SUCCESS(f"Reference data ready: {counts}"))
