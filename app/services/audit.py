from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def create_audit_log(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: str | int,
    details: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details or {},
    )
    db.add(entry)
    db.flush()
    return entry
