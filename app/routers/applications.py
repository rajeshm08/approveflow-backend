from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.application_stage import ApplicationStage
from app.models.institution import Institution
from app.models.user import User
from app.models.workflow_template import WorkflowTemplate
from app.schemas.application import (
    ApplicationCreate,
    ApplicationResponse,
    SubmitRequest,
    TimelineEntry,
    TransitionRequest,
)
from app.security.auth import get_current_user
from app.security.permissions import get_visible_application, require_roles, visible_applications_query
from app.services.audit import create_audit_log
from app.services.workflow import transition_application

router = APIRouter(prefix="/api/applications", tags=["applications"])


def serialize_application(application: Application) -> dict:
    return {
        "id": application.id,
        "application_id": application.id,
        "application_number": application.application_number,
        "institution_id": application.institution_id,
        "institution_name": application.institution.name,
        "program_name": application.program_name,
        "application_type": application.application_type,
        "current_stage": application.current_stage,
        "status": application.status,
        "due_at": application.due_at,
        "created_at": application.created_at,
        "updated_at": application.updated_at,
    }


@router.get("", response_model=list[ApplicationResponse])
def list_applications(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = visible_applications_query(user, db)
    if status_filter:
        query = query.filter(Application.status == status_filter)
    applications = query.order_by(Application.created_at.desc()).all()
    return [serialize_application(application) for application in applications]


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("institution")),
):
    if user.institution_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Institution user has no institution")
    if payload.workflow_template_id is None:
        template = db.query(WorkflowTemplate).filter(WorkflowTemplate.is_active.is_(True)).order_by(WorkflowTemplate.id).first()
    else:
        template = (
            db.query(WorkflowTemplate)
            .filter(WorkflowTemplate.id == payload.workflow_template_id, WorkflowTemplate.is_active.is_(True))
            .first()
        )
    if template is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active workflow template found")
    institution = db.get(Institution, user.institution_id)
    if institution is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Institution not found")
    application = Application(
        application_number=f"AF-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid4().hex[:8].upper()}",
        institution_id=user.institution_id,
        workflow_template_id=template.id,
        program_name=payload.program_name,
        application_type=payload.application_type,
        current_stage="draft",
        status="draft",
    )
    db.add(application)
    db.flush()
    create_audit_log(
        db,
        actor_id=user.id,
        action="application.created",
        entity_type="application",
        entity_id=application.id,
        details={
            "old_values": {},
            "new_values": {
                "institution_id": application.institution_id,
                "program_name": application.program_name,
                "current_stage": application.current_stage,
            },
            "reason": "Application created",
        },
    )
    db.commit()
    db.refresh(application)
    return serialize_application(application)


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = get_visible_application(application_id, user, db)
    return serialize_application(application)


@router.post("/{application_id}/submit", response_model=ApplicationResponse)
def submit_application(
    application_id: int,
    payload: SubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = get_visible_application(application_id, user, db)
    transition_application(
        db,
        application=application,
        actor=user,
        expected_current_stage="draft",
        next_stage="submitted",
        reason=payload.reason,
    )
    db.commit()
    db.refresh(application)
    return serialize_application(application)


@router.post("/{application_id}/transition", response_model=ApplicationResponse)
def transition(
    application_id: int,
    payload: TransitionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = get_visible_application(application_id, user, db)
    transition_application(
        db,
        application=application,
        actor=user,
        expected_current_stage=payload.expected_current_stage,
        next_stage=payload.next_stage,
        reason=payload.reason,
    )
    db.commit()
    db.refresh(application)
    return serialize_application(application)


@router.get("/{application_id}/timeline", response_model=list[TimelineEntry])
def application_timeline(
    application_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    application = get_visible_application(application_id, user, db)
    return (
        db.query(ApplicationStage)
        .filter(ApplicationStage.application_id == application.id)
        .order_by(ApplicationStage.created_at.asc(), ApplicationStage.id.asc())
        .all()
    )
