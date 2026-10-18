"""Keyset (cursor) pagination."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from django.core import signing
from django.db import models
from django.db.models import Q

from ibolit.core.problems import ApiError

M = TypeVar("M", bound=models.Model)
_SALT = "ibolit.cursor.v1"
MAX_LIMIT = 100


def _encode_value(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        return {"t": "dt", "v": value.isoformat()}
    if isinstance(value, dt.date):
        return {"t": "d", "v": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return {"t": "u", "v": str(value)}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        kind, raw = value.get("t"), value.get("v")
        if kind == "dt":
            return dt.datetime.fromisoformat(str(raw))
        if kind == "d":
            return dt.date.fromisoformat(str(raw))
        if kind == "u":
            return uuid.UUID(str(raw))
        raise ValueError("bad cursor value")
    return value


def encode_cursor(values: Sequence[Any]) -> str:
    return signing.dumps([_encode_value(v) for v in values], salt=_SALT, compress=True)


def decode_cursor(cursor: str) -> list[Any]:
    try:
        raw = signing.loads(cursor, salt=_SALT)
        return [_decode_value(v) for v in raw]
    except (signing.BadSignature, ValueError, TypeError, AttributeError):
        raise ApiError("Invalid cursor.", code="validation_error", status_code=400) from None


def parse_limit(raw: str | None, default: int = 20) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(
            "limit must be an integer.", code="validation_error", status_code=400
        ) from None
    return max(1, min(value, MAX_LIMIT))


def _after_q(ordering: Sequence[str], values: Sequence[Any]) -> Q:
    """``WHERE (a, b, c) after (va, vb, vc)`` honouring each column's direction."""
    clauses = Q()
    for i, field in enumerate(ordering):
        name = field.lstrip("-")
        op = "lt" if field.startswith("-") else "gt"
        clause = Q(**{f"{name}__{op}": values[i]})
        for prev_field, prev_value in zip(ordering[:i], values[:i], strict=True):
            clause &= Q(**{prev_field.lstrip("-"): prev_value})
        clauses |= clause
    return clauses


def paginate[M: models.Model](
    queryset: models.QuerySet[M],
    *,
    ordering: Sequence[str],
    cursor: str | None,
    limit: int,
) -> tuple[list[M], str | None]:
    """Return one page and the ``next_cursor`` (``None`` on the last page)."""
    if cursor:
        values = decode_cursor(cursor)
        if len(values) != len(ordering):
            raise ApiError("Invalid cursor.", code="validation_error", status_code=400)
        queryset = queryset.filter(_after_q(ordering, values))
    rows = list(queryset.order_by(*ordering)[: limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor([_resolve(last, f.lstrip("-")) for f in ordering])
    return rows, next_cursor


def _resolve(obj: Any, path: str) -> Any:
    for part in path.split("__"):
        obj = getattr(obj, part)
    return obj
