"""HTTP caching helpers for catalog-type GETs (ETag / If-None-Match / Cache-Control)."""

from __future__ import annotations

import hashlib
from typing import Any

from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response


def cached_response(
    request: Request,
    data: Any,
    *,
    max_age: int = 60,
    public: bool = True,
    vary_language: bool = True,
) -> Response:
    """Return ``data`` with a strong ETag; 304 when the client already has it."""
    body = JSONRenderer().render(data)
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    headers = {
        "ETag": etag,
        "Cache-Control": f"{'public' if public else 'private'}, max-age={max_age}",
    }
    if vary_language:
        headers["Vary"] = "Accept-Language"
    inbound = request.headers.get("If-None-Match", "")
    if etag in {tag.strip() for tag in inbound.split(",")}:
        return Response(status=304, headers=headers)
    return Response(data, headers=headers)
