"""Money as integer minor units + ISO currency."""

from __future__ import annotations

from dataclasses import dataclass

CURRENCY_SYMBOLS = {"KZT": "₸"}
MINOR_UNITS = {"KZT": 100}


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str = "KZT"

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("amount_minor must be an int")
        if self.currency not in MINOR_UNITS:
            raise ValueError(f"Unsupported currency {self.currency}")

    @classmethod
    def from_major(cls, major: int, currency: str = "KZT") -> Money:
        return cls(major * MINOR_UNITS[currency], currency)

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __mul__(self, qty: int) -> Money:
        if not isinstance(qty, int) or isinstance(qty, bool):
            raise TypeError("Money can only be multiplied by an int quantity")
        return Money(self.amount_minor * qty, self.currency)

    def _check(self, other: Money) -> None:
        if other.currency != self.currency:
            raise ValueError("Currency mismatch")

    @property
    def display(self) -> str:
        return format_money(self.amount_minor, self.currency)

    def as_dict(self) -> dict[str, object]:
        return {
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "display": self.display,
        }


def zero(currency: str = "KZT") -> Money:
    return Money(0, currency)


def format_money(amount_minor: int, currency: str = "KZT") -> str:
    """``1_200_000`` → ``"12,000 ₸"``."""
    unit = MINOR_UNITS[currency]
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(amount_minor), unit)
    text = f"{major:,}"
    if minor:
        text += f".{minor:02d}"
    return f"{sign}{text} {CURRENCY_SYMBOLS.get(currency, currency)}"
