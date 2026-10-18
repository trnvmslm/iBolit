"""Courier (mock): a fixed demo courier is assigned when an order reaches courier_assigned."""

from __future__ import annotations

from ibolit.integrations.base import note_mock


def assign_courier(order_code: str) -> dict[str, str]:
    note_mock("courier")
    return {"name": "Yerlan (demo courier)", "phone": "+7 700 000 00 00", "vehicle": "Scooter"}
