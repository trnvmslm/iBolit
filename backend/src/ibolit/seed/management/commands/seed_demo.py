"""Create the demo data (idempotent)."""

from typing import Any

from django.core.management.base import BaseCommand

from ibolit.seed.demo import seed_demo


class Command(BaseCommand):
    help = "Create demo users, doctors, bookings, MedCard data, pharmacy and articles (fake data)."

    def handle(self, *args: Any, **options: Any) -> None:
        for key, value in seed_demo().items():
            self.stdout.write(f"{key}: {value}")
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
