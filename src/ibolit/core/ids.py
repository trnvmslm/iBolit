"""Identifiers: time-ordered UUIDv7 primary keys and random human-friendly codes."""

from __future__ import annotations

import os
import secrets
import time
import uuid

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # no I, L, O, U


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit millisecond timestamp + random bits (non-enumerable ids in URLs)."""
    value = (time.time_ns() // 1_000_000) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 4122 variant
    return uuid.UUID(int=value)


def human_code(prefix: str, length: int = 6) -> str:
    """Random code such as ``IB-7K3QDX``; stored under a UNIQUE constraint (retry on collision)."""
    return f"{prefix}-" + "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(length))
