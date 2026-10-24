from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.escalation import Escalation
from app.models.user import User
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query
from app.services.audit import create_audit_log

router = APIRouter(prefix="/api/escalations", tags=["escalations"])


class ResolveRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, reason: str) -> str:
        if not reason.strip():
            raise ValueError("A reason is required")
        return reason.strip()


@router.get("")
def list_escalations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Escalation).join(Application, Escalation.application_id == Application.id)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    return [
        {
            "id": row.id,
            "application_id": row.application_id,
            "reason": row.reason,
            "status": row.status,
            "escalated_at": row.escalated_at,
            "resolved_at": row.resolved_at,
            "resolved_by": row.resolved_by,
        }
        for row in query.order_by(Escalation.escalated_at.desc()).all()
    ]


@router.post("/{escalation_id}/resolve")
def resolve_escalation(
    escalation_id: int,
    payload: ResolveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in {"regional_officer", "bureau_officer", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient role")
    query = db.query(Escalation).join(Application, Escalation.application_id == Application.id)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    escalation = query.filter(Escalation.id == escalation_id).one_or_none()
    if escalation is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    if escalation.status == "resolved":
        raise HTTPException(status_code=409, detail="Escalation is already resolved")
    old_values = {"status": escalation.status, "resolved_by": escalation.resolved_by}
    escalation.status = "resolved"
    escalation.resolved_by = user.id
    escalation.resolved_at = datetime.utcnow()
    create_audit_log(
        db,
        actor_id=user.id,
        action="escalation.resolved",
        entity_type="escalation",
        entity_id=escalation.id,
        details={
            "old_values": old_values,
            "new_values": {"status": escalation.status, "resolved_by": user.id},
            "reason": payload.reason,
        },
    )
    db.commit()
    return {"id": escalation.id, "status": escalation.status, "resolved_at": escalation.resolved_at}
