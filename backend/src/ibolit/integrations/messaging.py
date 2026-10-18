"""SMS and e-mail providers (OTP codes, account notices)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from ibolit.integrations.base import ProviderError, note_mock, scenario_is


@dataclass(frozen=True)
class SendResult:
    provider_ref: str
    provider_mode: str


class SmsProvider(Protocol):
    def send_sms(
        self, to_e164: str, text: str, *, user_id: uuid.UUID | None = None
    ) -> SendResult: ...


class EmailProvider(Protocol):
    def send_email(
        self, to: str, subject: str, text: str, *, user_id: uuid.UUID | None = None
    ) -> SendResult: ...


def mask_phone(phone: str) -> str:
    return phone[:4] + "*" * max(0, len(phone) - 6) + phone[-2:] if len(phone) > 6 else "***"


class MockSmsProvider:
    """Records the SMS instead of sending it."""

    def send_sms(self, to_e164: str, text: str, *, user_id: uuid.UUID | None = None) -> SendResult:
        from ibolit.integrations.models import MockMessage

        if scenario_is("sms_failure"):
            note_mock("sms")
            raise ProviderError(extra={"provider": "sms"})
        ref = f"mock-sms-{uuid.uuid4().hex[:12]}"
        MockMessage.objects.create(
            channel=MockMessage.Channel.SMS,
            recipient=mask_phone(to_e164),
            user_id=user_id,
            body=text,
            provider_ref=ref,
        )
        note_mock("sms")
        return SendResult(ref, "mock")


class MockEmailProvider:
    def send_email(
        self, to: str, subject: str, text: str, *, user_id: uuid.UUID | None = None
    ) -> SendResult:
        from ibolit.integrations.models import MockMessage

        ref = f"mock-email-{uuid.uuid4().hex[:12]}"
        local, _, domain = to.partition("@")
        MockMessage.objects.create(
            channel=MockMessage.Channel.EMAIL,
            recipient=f"{local[:1]}***@{domain}",
            user_id=user_id,
            title=subject,
            body=text,
            provider_ref=ref,
        )
        note_mock("email")
        return SendResult(ref, "mock")
