from __future__ import annotations

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = "ibolit.integrations"
    label = "integrations"
    verbose_name = "External providers (mocks and real)"
