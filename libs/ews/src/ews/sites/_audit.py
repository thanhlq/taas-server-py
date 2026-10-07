"""Site audit trail (Site-0003): who, what, when, source (``visual`` · ``markdown`` · ``ai`` …)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from db.models.sites import SiteAudit
from foundation.db.types import DBAsyncScopedSession

from ews.security import RequestScope
from ews.shared import utcnow


def audit(
    session: DBAsyncScopedSession,
    scope: RequestScope | None,
    action: str,
    *,
    tenant_id: UUID | None = None,
    site_id: UUID | None = None,
    target_type: str | None = None,
    target_id: object | None = None,
    source: str | None = None,
    **detail: Any,
) -> None:
    session.add(
        SiteAudit(
            tenant_id=tenant_id or (scope.tenant_id if scope else None),
            site_id=site_id,
            actor_id=scope.user_id if scope else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            source=source,
            detail={k: v for k, v in detail.items() if v is not None},
            created_at=utcnow(),
        )
    )
