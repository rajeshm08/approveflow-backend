from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.user import User
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
COMPLETED_STATUSES = ["approved", "rejected", "completed"]


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    scoped_query = visible_applications_query(user, db)
    now = datetime.utcnow()
    totals = scoped_query.with_entities(func.count(Application.id)).scalar() or 0
    status_rows = (
        visible_applications_query(user, db)
        .with_entities(Application.status, func.count(Application.id))
        .group_by(Application.status)
        .all()
    )
    overdue = (
        visible_applications_query(user, db)
        .filter(
            Application.due_at.is_not(None),
            Application.due_at < now,
            Application.status.notin_(COMPLETED_STATUSES),
            Application.current_stage.notin_(COMPLETED_STATUSES),
        )
        .count()
    )
    upcoming = (
        visible_applications_query(user, db)
        .filter(
            Application.due_at.is_not(None),
            Application.due_at >= now,
            Application.due_at <= now + timedelta(days=7),
            Application.status.notin_(COMPLETED_STATUSES),
            Application.current_stage.notin_(COMPLETED_STATUSES),
        )
        .count()
    )
    return {
        "total_applications": totals,
        "applications_by_status": {key: count for key, count in status_rows},
        "overdue_applications": overdue,
        "upcoming_due_7_days": upcoming,
    }
