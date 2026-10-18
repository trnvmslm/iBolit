"""Access log ("Medical record access log — view who accessed your information")."""

from __future__ import annotations

import uuid
from typing import Any

from ibolit.core.models import AccessLog


def record(
    *,
    actor_id: uuid.UUID | None,
    actor_role: str,
    action: str,
    resource_type: str,
    resource_id: str | uuid.UUID = "",
    patient_id: uuid.UUID | None = None,
    consent_id: uuid.UUID | None = None,
    purpose: str = "",
    metadata: dict[str, Any] | None = None,
) -> AccessLog:
    return AccessLog.objects.create(
        actor_id=actor_id, actor_role=actor_role, action=action, resource_type=resource_type,
        resource_id=str(resource_id), patient_id=patient_id, consent_id=consent_id, purpose=purpose,
        metadata=metadata or {},
    )
