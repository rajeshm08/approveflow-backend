import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.document import Document
from app.models.evc_event import EVCEvent
from app.models.undertaking import Undertaking
from app.models.user import User
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
UNAVAILABLE = "Information unavailable"


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def application_scope(user: User, db: Session):
    return visible_applications_query(user, db)


def format_rows(rows: list[dict]) -> dict | str:
    return {"answer": "Database information found", "data": rows} if rows else {"answer": UNAVAILABLE, "data": []}


@router.post("/ask")
def ask_assistant(
    payload: AssistantQuestion,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    question = payload.question.lower()
    application_number_match = re.search(r"\bapp-\d+\b", question, re.IGNORECASE)
    if application_number_match:
        application = application_scope(user, db).filter(
            Application.application_number == application_number_match.group(0).upper()
        ).one_or_none()
        if application is None:
            return {"answer": UNAVAILABLE, "data": []}
        answer = (
            f"Application {application.application_number} is at stage "
            f"{application.current_stage} with status {application.status}."
        )
        if "why" in question and application.current_stage == "evc_scheduling":
            answer = (
                f"{answer} It is pending because the EVC site visit is awaiting coordinator "
                "scheduling or confirmation."
            )
        elif "why" in question and application.due_at and application.due_at < datetime.utcnow():
            answer = f"{answer} Its deadline is overdue."
        return {
            "answer": answer,
            "data": {
                "application_id": application.id,
                "application_number": application.application_number,
                "institution_id": application.institution_id,
                "current_stage": application.current_stage,
                "status": application.status,
                "due_at": application.due_at,
            },
        }

    application_match = re.search(r"\bapplication\s*(?:id|#)?\s*(\d+)\b", question)
    application_id = (
        int(application_match.group(1))
        if application_match
        else int(question.strip())
        if question.strip().isdigit()
        else None
    )
    if application_id is not None:
        application = application_scope(user, db).filter(Application.id == application_id).one_or_none()
        if application is None:
            return {"answer": UNAVAILABLE, "data": []}
        return {
            "answer": f"Application {application.application_number} is at stage {application.current_stage} with status {application.status}.",
            "data": {
                "application_id": application.id,
                "application_number": application.application_number,
                "institution_id": application.institution_id,
                "current_stage": application.current_stage,
                "status": application.status,
                "due_at": application.due_at,
            },
        }

    now = datetime.utcnow()
    if "overdue" in question or "past due" in question:
        rows = (
            application_scope(user, db)
            .filter(
                Application.due_at.is_not(None),
                Application.due_at < now,
                Application.status.notin_(["approved", "rejected", "completed"]),
                Application.current_stage.notin_(["approved", "rejected", "completed"]),
            )
            .order_by(Application.due_at.asc())
            .all()
        )
        return format_rows(
            [
                {
                    "application_id": row.id,
                    "application_number": row.application_number,
                    "current_stage": row.current_stage,
                    "due_at": row.due_at,
                }
                for row in rows
            ]
        )

    if "document" in question or "expiry" in question or "expir" in question:
        expired_only = "expired" in question
        query = (
            db.query(Document)
            .join(Application, Document.application_id == Application.id)
            .filter(
                Document.expires_at.is_not(None),
            )
        )
        if expired_only:
            query = query.filter(Document.expires_at < now)
        else:
            query = query.filter(Document.expires_at >= now, Document.expires_at <= now + timedelta(days=30))
        if user.role == "institution":
            query = query.filter(Application.institution_id == user.institution_id)
        rows = query.order_by(Document.expires_at.asc()).all()
        return format_rows(
            [
                {
                    "document_id": row.id,
                    "application_id": row.application_id,
                    "name": row.name,
                    "expires_at": row.expires_at,
                }
                for row in rows
            ]
        )

    if "evc" in question or "visit" in question:
        query = db.query(EVCEvent).join(Application, EVCEvent.application_id == Application.id)
        if user.role == "institution":
            query = query.filter(Application.institution_id == user.institution_id)
        rows = query.order_by(EVCEvent.scheduled_at.asc()).all()
        return format_rows(
            [
                {
                    "application_id": row.application_id,
                    "event_type": row.event_type,
                    "scheduled_at": row.scheduled_at,
                    "notes": row.notes,
                }
                for row in rows
            ]
        )

    if "compliance" in question or "undertaking" in question:
        query = db.query(Undertaking).join(Application, Undertaking.application_id == Application.id)
        if user.role == "institution":
            query = query.filter(Application.institution_id == user.institution_id)
        rows = query.order_by(Undertaking.id.asc()).all()
        return format_rows(
            [
                {
                    "application_id": row.application_id,
                    "undertaking_type": row.undertaking_type,
                    "status": row.status,
                    "submitted_at": row.submitted_at,
                    "signed_at": row.signed_at,
                }
                for row in rows
            ]
        )
    return {"answer": UNAVAILABLE, "data": []}
