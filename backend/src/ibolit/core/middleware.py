"""Adds ``X-Provider-Mode: mock`` when a mocked provider answered, and lets the iOS developer force demo."""

from __future__ import annotations

import re
from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from ibolit.core import context


class MockProviderMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        scenario = request.headers.get("X-Mock-Scenario", "")
        allowed = settings.ENV != "prod" and re.fullmatch(r"[a-z_]{1,40}", scenario)
        tokens = (
            context.mock_providers_var.set(frozenset()),
            context.mock_scenario_var.set(scenario if allowed else None),
        )
        try:
            response = self.get_response(request)
            mocks = context.mock_providers_var.get()
        finally:
            context.mock_providers_var.reset(tokens[0])
            context.mock_scenario_var.reset(tokens[1])
        if mocks:
            response["X-Provider-Mode"] = "mock"
        if request.path.startswith("/api/") and "Cache-Control" not in response:
            response["Cache-Control"] = "no-store"  # medical data must not be cached
        return response
