"""Serializer building blocks."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from ibolit.core.money import format_money


class StrictSerializer(serializers.Serializer[Any]):
    """Base for request bodies: unknown fields are a validation error, not ignored."""

    def to_internal_value(self, data: Any) -> Any:
        if hasattr(data, "keys"):
            unknown = set(data.keys()) - set(self.fields.keys())
            if unknown:
                raise serializers.ValidationError(
                    {key: ["Unknown field."] for key in sorted(unknown)}
                )
        return super().to_internal_value(data)


class MoneySerializer(serializers.Serializer[Any]):
    amount_minor = serializers.IntegerField(
        help_text="Integer minor units (tiyn). 12,000 ₸ = 1200000."
    )
    currency = serializers.CharField(help_text="ISO 4217, always KZT today.")
    display = serializers.CharField(help_text='Ready-to-show string, e.g. "12,000 ₸".')


def money(amount_minor: int, currency: str = "KZT") -> dict[str, Any]:
    return {
        "amount_minor": amount_minor,
        "currency": currency,
        "display": format_money(amount_minor, currency),
    }


class PageSerializer(serializers.Serializer[Any]):
    next_cursor = serializers.CharField(allow_null=True)
