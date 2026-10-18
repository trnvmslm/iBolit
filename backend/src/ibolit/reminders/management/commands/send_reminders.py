"""Send due reminder notifications."""

from typing import Any

from django.core.management.base import BaseCommand

from ibolit.reminders.services import send_due


class Command(BaseCommand):
    help = "Create notifications for appointments starting in 15 minutes and for due reminders."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(f"Sent {send_due()} reminder notification(s)")
