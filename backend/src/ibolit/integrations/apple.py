"""Sign in with Apple."""

from __future__ import annotations

from typing import Protocol

from ibolit.integrations.base import note_mock


class AppleVerifier(Protocol):
    def verify(self, identity_token: str) -> str | None:
        """Return the Apple user id (``sub``) or None if the token is invalid."""
        ...


class MockAppleVerifier:
    """Accepts ``mock-apple:<subject>`` tokens only."""

    def verify(self, identity_token: str) -> str | None:
        note_mock("apple")
        if not identity_token.startswith("mock-apple:"):
            return None
        return identity_token.split(":", 2)[1] or None
