from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.application_stage import ApplicationStage
from app.models.user import User
from app.models.workflow_stage import WorkflowStage
from app.services.audit import create_audit_log


def transition_application(
    db: Session,
    *,
    application: Application,
    actor: User,
    expected_current_stage: str,
    next_stage: str,
    reason: str,
) -> Application:
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A transition reason is required")

    with db.begin_nested():
        if application.current_stage != expected_current_stage:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Expected stage '{expected_current_stage}', found '{application.current_stage}'",
            )

        source_stage = (
            db.query(WorkflowStage)
            .filter(
                WorkflowStage.template_id == application.workflow_template_id,
                WorkflowStage.stage_key == application.current_stage,
            )
            .one_or_none()
        )
        destination_stage = (
            db.query(WorkflowStage)
            .filter(
                WorkflowStage.template_id == application.workflow_template_id,
                WorkflowStage.stage_key == next_stage,
            )
            .one_or_none()
        )
        if source_stage is None or destination_stage is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Stage is not in the workflow template")
        if actor.role not in source_stage.allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role cannot transition from this stage")
        if next_stage not in source_stage.next_stage_keys:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid next stage")

        old_stage = application.current_stage
        application.current_stage = destination_stage.stage_key
        application.status = (
            "approved" if next_stage == "approved"
            else "rejected" if next_stage == "rejected"
            else "in_review" if next_stage != "draft"
            else "draft"
        )
        application.updated_at = datetime.utcnow()
        application.due_at = (
            datetime.utcnow() + timedelta(days=destination_stage.sla_days)
            if destination_stage.next_stage_keys
            else None
        )
        db.add(
            ApplicationStage(
                application_id=application.id,
                from_stage=old_stage,
                to_stage=destination_stage.stage_key,
                status=application.status,
                reason=reason,
                actor_id=actor.id,
            )
        )
        create_audit_log(
            db,
            actor_id=actor.id,
            action="application.transition",
            entity_type="application",
            entity_id=application.id,
            details={
                "old_values": {"current_stage": old_stage},
                "new_values": {
                    "current_stage": destination_stage.stage_key,
                    "status": application.status,
                },
                "reason": reason,
            },
        )
        db.flush()

    return application
