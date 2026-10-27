"""Provider plumbing: pick the implementation from settings.PROVIDERS, flag mock answers with ``X-Provider-Mode``."""

from __future__ import annotations

from functools import cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from ibolit.core import context
from ibolit.core.problems import ApiError


class ProviderError(ApiError):
    status_code = 502
    code = "provider_unavailable"


class ProviderTimeout(ProviderError):
    status_code = 504
    code = "provider_timeout"


REGISTRY: dict[str, dict[str, str]] = {
    "ai": {"mock": "ibolit.integrations.ai.MockAIProvider"},
    "payment": {"mock": "ibolit.integrations.payments.MockPaymentProvider"},
    "apple": {"mock": "ibolit.integrations.apple.MockAppleVerifier"},
}


@cache
def get_provider(kind: str) -> Any:
    mode = settings.PROVIDERS[kind]
    path = REGISTRY[kind].get(mode)
    if path is None:
        raise ImproperlyConfigured(f"No '{mode}' implementation for provider '{kind}'.")
    return import_string(path)()


def note_mock(kind: str) -> None:
    context.mark_mock_used(kind)


def scenario_is(*names: str) -> bool:
    return context.mock_scenario_var.get() in names
