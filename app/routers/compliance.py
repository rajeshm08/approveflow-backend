from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.undertaking import Undertaking
from app.models.user import User
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query
from app.services.audit import create_audit_log

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


class ComplianceSubmitRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, reason: str) -> str:
        if not reason.strip():
            raise ValueError("A reason is required")
        return reason.strip()


@router.get("")
def list_compliance(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Undertaking).join(Application, Undertaking.application_id == Application.id)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    return [
        {
            "id": undertaking.id,
            "application_id": undertaking.application_id,
            "undertaking_type": undertaking.undertaking_type,
            "status": undertaking.status,
            "submitted_at": undertaking.submitted_at,
            "signed_at": undertaking.signed_at,
        }
        for undertaking in query.order_by(Undertaking.id).all()
    ]


@router.post("/{compliance_id}/submit")
def submit_compliance(
    compliance_id: int,
    payload: ComplianceSubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    undertaking = (
        db.query(Undertaking)
        .join(Application, Undertaking.application_id == Application.id)
        .filter(Undertaking.id == compliance_id)
    )
    if user.role == "institution":
        undertaking = undertaking.filter(Application.institution_id == user.institution_id)
    record = undertaking.one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Compliance record not found")
    if user.role != "institution" and user.role not in {"admin", "bureau_officer"}:
        raise HTTPException(status_code=403, detail="Insufficient role")
    if record.status == "submitted":
        raise HTTPException(status_code=409, detail="Compliance record is already submitted")
    old_values = {
        "status": record.status,
        "submitted_at": record.submitted_at.isoformat() if record.submitted_at else None,
    }
    record.status = "submitted"
    record.submitted_at = datetime.utcnow()
    create_audit_log(
        db,
        actor_id=user.id,
        action="compliance.submitted",
        entity_type="undertaking",
        entity_id=record.id,
        details={
            "old_values": old_values,
            "new_values": {"status": record.status, "submitted_at": record.submitted_at.isoformat()},
            "reason": payload.reason,
        },
    )
    db.commit()
    return {
        "id": record.id,
        "application_id": record.application_id,
        "undertaking_type": record.undertaking_type,
        "status": record.status,
        "submitted_at": record.submitted_at,
        "signed_at": record.signed_at,
    }
