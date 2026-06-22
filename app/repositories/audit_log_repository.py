"""AuditLog repository — write-only by design.

The only allowed operation is inserting new entries. There is no update or
delete method because audit logs are immutable by policy (CLAUDE.md rule 5).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


class AuditLogRepository:
    @staticmethod
    async def log(
        db: AsyncSession,
        *,
        action: str,
        user_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Append a new audit entry and flush to obtain the assigned id."""
        entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            metadata_=metadata,
        )
        db.add(entry)
        await db.flush()
        return entry
