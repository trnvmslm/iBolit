"""Locale helpers for translatable content stored as JSONB maps."""

from __future__ import annotations

from collections.abc import Mapping

from django.utils import translation

SUPPORTED = ("en", "ru", "kk")
FALLBACK = "en"


def current_language() -> str:
    lang = (translation.get_language() or FALLBACK).split("-")[0].lower()
    return lang if lang in SUPPORTED else FALLBACK


def localize(value: Mapping[str, str] | None, lang: str | None = None) -> str:
    """Pick the requested language, fall back to English, then to any value."""
    if not value:
        return ""
    lang = lang or current_language()
    if value.get(lang):
        return value[lang]
    if value.get(FALLBACK):
        return value[FALLBACK]
    return next(iter(value.values()), "")


def localize_list(value: Mapping[str, list[str]] | None, lang: str | None = None) -> list[str]:
    if not value:
        return []
    lang = lang or current_language()
    return list(value.get(lang) or value.get(FALLBACK) or next(iter(value.values()), []))


def all_text(value: Mapping[str, str] | None) -> str:
    """All translations concatenated (used to build multilingual search vectors)."""
    return " ".join(v for v in (value or {}).values() if v)
