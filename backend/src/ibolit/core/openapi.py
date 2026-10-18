"""drf-spectacular hook: document the problem+json error shape and common errors on every operation."""

from __future__ import annotations

from typing import Any

PROBLEM = {
    "type": "object",
    "properties": {
        "type": {"type": "string"}, "title": {"type": "string"}, "status": {"type": "integer"},
        "code": {"type": "string"}, "detail": {"type": "string"},
        "errors": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "message": {"type": "string"}, "code": {"type": "string"}}}},
    },
    "required": ["type", "title", "status", "code"],
}
EXAMPLES = {
    "401": {"type": "https://docs.ibolit.kz/problems/authentication_failed", "title": "Authentication required.", "status": 401, "code": "authentication_failed"},
    "404": {"type": "https://docs.ibolit.kz/problems/not_found", "title": "Not found.", "status": 404, "code": "not_found"},
    "422": {"type": "https://docs.ibolit.kz/problems/validation_error", "title": "Some fields are invalid.", "status": 422, "code": "validation_error",
            "errors": [{"field": "starts_at", "message": "This field is required.", "code": "required"}]},
}
CONFLICTS = {
    "/api/v1/bookings/hold": {"code": "slot_unavailable", "title": "This time is no longer available."},
    "/api/v1/bookings/{appointment_id}/confirm": {"code": "hold_expired", "title": "Your hold expired. Please pick a time again."},
    "/api/v1/bookings/{appointment_id}/reschedule": {"code": "slot_unavailable", "title": "This time is no longer available."},
    "/api/v1/orders": {"code": "out_of_stock", "title": "Only 2 left of Amlodipine 5 mg."},
}


def _problem(example: dict[str, Any]) -> dict[str, Any]:
    return {"description": example["title"], "content": {"application/problem+json": {
        "schema": {"$ref": "#/components/schemas/Problem"}, "example": example}}}


def add_problem_responses(result: dict[str, Any], generator: Any, request: Any, public: bool) -> dict[str, Any]:
    result.setdefault("components", {}).setdefault("schemas", {})["Problem"] = PROBLEM
    for path, item in result.get("paths", {}).items():
        for method, op in item.items():
            responses = op.setdefault("responses", {})
            if op.get("security") != [] and not any("{}" in str(s) for s in op.get("security", [])):
                responses.setdefault("401", _problem(EXAMPLES["401"]))
            if "{" in path:
                responses.setdefault("404", _problem(EXAMPLES["404"]))
            if method in ("post", "put", "patch"):
                responses.setdefault("422", _problem(EXAMPLES["422"]))
            if path in CONFLICTS and method == "post":
                c = CONFLICTS[path]
                responses["409"] = _problem({"type": f"https://docs.ibolit.kz/problems/{c['code']}", "status": 409, **c})
    return result
