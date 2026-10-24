from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.evc_event import EVCEvent
from app.models.user import User
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query
from app.services.audit import create_audit_log

router = APIRouter(prefix="/api/evc", tags=["evc"])


class EvcScheduleRequest(BaseModel):
    scheduled_at: datetime
    event_type: str = Field(default="site_visit", min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, reason: str) -> str:
        if not reason.strip():
            raise ValueError("A reason is required")
        return reason.strip()


@router.get("")
def list_evc_events(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(EVCEvent).join(Application, EVCEvent.application_id == Application.id)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    return [
        {
            "id": event.id,
            "application_id": event.application_id,
            "event_type": event.event_type,
            "scheduled_at": event.scheduled_at,
            "notes": event.notes,
        }
        for event in query.order_by(EVCEvent.scheduled_at.asc()).all()
    ]


@router.post("/{application_id}/schedule", status_code=201)
def schedule_evc(
    application_id: int,
    payload: EvcScheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in {"evc_coordinator", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient role")
    application = visible_applications_query(user, db).filter(Application.id == application_id).one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    event = EVCEvent(
        application_id=application.id,
        event_type=payload.event_type,
        scheduled_at=payload.scheduled_at,
        notes=payload.notes,
    )
    db.add(event)
    db.flush()
    create_audit_log(
        db,
        actor_id=user.id,
        action="evc.scheduled",
        entity_type="evc_event",
        entity_id=event.id,
        details={
            "old_values": {},
            "new_values": {
                "application_id": event.application_id,
                "event_type": event.event_type,
                "scheduled_at": event.scheduled_at.isoformat(),
            },
            "reason": payload.reason,
        },
    )
    db.commit()
    return {"id": event.id, "application_id": event.application_id, "event_type": event.event_type, "scheduled_at": event.scheduled_at}
