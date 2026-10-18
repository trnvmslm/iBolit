"""Per-request context for mocked providers (X-Provider-Mode header, forced demo scenarios)."""

from __future__ import annotations

import contextvars

mock_providers_var: contextvars.ContextVar[frozenset[str]] = contextvars.ContextVar("mock_providers", default=frozenset())
mock_scenario_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("mock_scenario", default=None)


def mark_mock_used(provider: str) -> None:
    mock_providers_var.set(mock_providers_var.get() | {provider})
