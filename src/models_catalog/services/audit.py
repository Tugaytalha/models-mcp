from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import AuditLog


def record(session: Session, *, deployment_id: uuid.UUID, action: str, actor: str, source: str,
           before: dict[str, Any] | None, after: dict[str, Any] | None) -> None:
    session.add(AuditLog(deployment_id=deployment_id, action=action, actor=actor, source=source,
                         before=before, after=after))


def query(session: Session, *, deployment_id: uuid.UUID | None = None, actor: str | None = None,
          since: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc()).limit(max(1, min(limit, 500)))
    if deployment_id:
        stmt = stmt.where(AuditLog.deployment_id == deployment_id)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if since:
        stmt = stmt.where(AuditLog.at >= since)
    return [
        {"id": r.id, "deployment_id": str(r.deployment_id), "action": r.action, "actor": r.actor,
         "source": r.source, "at": r.at.isoformat(), "changed_fields": _diff(r.before, r.after),
         "before": r.before, "after": r.after}
        for r in session.scalars(stmt)
    ]


def _diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[str]:
    if before is None or after is None:
        return []
    return sorted(k for k in after if before.get(k) != after.get(k))
