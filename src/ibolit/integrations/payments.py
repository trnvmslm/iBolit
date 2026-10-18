"""Payment provider (Apple Pay via a payment service provider) — mocked."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from django.core.cache import cache

from ibolit.integrations.base import ProviderError, ProviderTimeout, note_mock, scenario_is

ChargeStatus = Literal["succeeded", "failed", "processing"]


@dataclass(frozen=True)
class ChargeResult:
    provider_ref: str
    status: ChargeStatus
    card_brand: str
    card_last4: str
    failure_code: str
    provider_mode: str


@dataclass(frozen=True)
class RefundResult:
    provider_ref: str
    status: Literal["succeeded", "failed"]
    provider_mode: str


class PaymentProvider(Protocol):
    def charge(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_token: str,
        idempotency_key: str,
        description: str,
    ) -> ChargeResult: ...

    def refund(
        self, *, provider_ref: str, amount_minor: int, idempotency_key: str
    ) -> RefundResult: ...


DECLINED_TEST_TOKENS = frozenset({"tok_declined"})


def _parse_token(token: str) -> tuple[str, str]:
    """``mock_applepay_<brand>_<last4>`` → (brand, last4); default card visa ••4582."""
    parts = token.split("_")
    if len(parts) == 4 and parts[0] == "mock" and parts[3].isdigit() and len(parts[3]) == 4:
        return parts[2], parts[3]
    return "visa", "4582"


class MockPaymentProvider:
    """Deterministic PSP simulator."""

    TTL = 24 * 3600


    def charge(
        self,
        *,
        amount_minor: int,
        currency: str,
        payment_token: str,
        idempotency_key: str,
        description: str,
    ) -> ChargeResult:
        if amount_minor <= 0:
            raise ValueError("amount must be positive")
        key = f"ibolit:mockpay:charge:{idempotency_key}"
        cached = cache.get(key)
        if cached:
            note_mock("payment")
            return ChargeResult(**json.loads(cached))
        brand, last4 = _parse_token(payment_token)
        ref = f"mock_ch_{uuid.uuid4().hex[:16]}"
        if payment_token in DECLINED_TEST_TOKENS or scenario_is("payment_declined"):
            result = ChargeResult(ref, "failed", brand, last4, "card_declined", "mock")
        else:
            result = ChargeResult(ref, "succeeded", brand, last4, "", "mock")
        cache.set(key, json.dumps(asdict(result)), self.TTL)
        if scenario_is("payment_timeout"):
            note_mock("payment")
            raise ProviderTimeout(extra={"provider": "payment"})
        note_mock("payment")
        return result

    def refund(self, *, provider_ref: str, amount_minor: int, idempotency_key: str) -> RefundResult:
        key = f"ibolit:mockpay:refund:{idempotency_key}"
        cached = cache.get(key)
        if cached:
            note_mock("payment")
            return RefundResult(**json.loads(cached))
        if scenario_is("refund_failure"):
            note_mock("payment")
            raise ProviderError(extra={"provider": "payment"})
        result = RefundResult(f"mock_re_{uuid.uuid4().hex[:16]}", "succeeded", "mock")
        cache.set(key, json.dumps(asdict(result)), self.TTL)
        note_mock("payment")
        return result
