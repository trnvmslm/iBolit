"""``Idempotency-Key`` support for unsafe endpoints."""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, TypeVar

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from ibolit.core import clock
from ibolit.core.models import IdempotencyRecord
from ibolit.core.problems import ApiError

_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{8,255}$")
F = TypeVar("F", bound=Callable[..., Response])


def _canonical_payload(request: Request) -> bytes:
    data = request.data
    if hasattr(data, "lists"):
        items = dict(data.lists())
        files = {
            name: [{"size": f.size, "sha256": _sha256_file(f)} for f in request.FILES.getlist(name)]
            for name in request.FILES
        }
        payload: Any = {"fields": items, "files": files}
    else:
        payload = data
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sha256_file(uploaded: Any) -> str:
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    return digest.hexdigest()


def request_fingerprint(request: Request) -> str:
    digest = hashlib.sha256()
    digest.update((request.method or "").encode() + b"\n")
    digest.update(request.path.encode() + b"\n")
    digest.update(_canonical_payload(request))
    return digest.hexdigest()


def idempotent(scope: str) -> Callable[[F], F]:
    def decorator(view_method: F) -> F:
        @functools.wraps(view_method)
        def wrapper(self: Any, request: Request, *args: Any, **kwargs: Any) -> Response:
            key = request.headers.get("Idempotency-Key", "")
            if not key:  # optional: without a key the request simply runs
                return view_method(self, request, *args, **kwargs)
            if not _KEY_RE.match(key):
                raise ApiError(
                    "Idempotency-Key must be 8-255 characters [A-Za-z0-9_-:.] (a UUID is ideal).",
                    code="validation_error",
                    status_code=400,
                )
            user = getattr(request, "user", None)
            user_id = user.pk if user is not None and user.is_authenticated else None
            fingerprint = request_fingerprint(request)
            now = clock.now()

            with transaction.atomic():
                record = _claim(user_id, scope, key, fingerprint, now)
                if record.response_status is not None:
                    return _replay(record)
                response = view_method(self, request, *args, **kwargs)
                if response.status_code >= 500:
                    transaction.set_rollback(True)
                    return response
                record.response_status = response.status_code
                record.response_body = json.loads(JSONRenderer().render(response.data) or b"null")
                record.save(update_fields=["response_status", "response_body"])
            return response

        return wrapper  # type: ignore[return-value]

    return decorator


def _claim(user_id: Any, scope: str, key: str, fingerprint: str, now: Any) -> IdempotencyRecord:
    for _ in range(2):
        try:
            with transaction.atomic():
                return IdempotencyRecord.objects.create(
                    user_id=user_id,
                    scope=scope,
                    key=key,
                    request_hash=fingerprint,
                    expires_at=now + settings.IDEMPOTENCY_TTL,
                )
        except IntegrityError:
            existing = IdempotencyRecord.objects.select_for_update().get(
                user_id=user_id, scope=scope, key=key
            )
            if existing.expires_at <= now:
                existing.delete()
                continue
            if existing.request_hash != fingerprint:
                raise ApiError(code="idempotency_key_reused", status_code=422) from None
            return existing
    raise ApiError(code="conflict", status_code=409)


def _replay(record: IdempotencyRecord) -> Response:
    response = Response(record.response_body, status=record.response_status)
    response["Idempotent-Replayed"] = "true"
    return response


def purge_expired() -> int:
    deleted, _ = IdempotencyRecord.objects.filter(expires_at__lte=clock.now()).delete()
    return deleted
