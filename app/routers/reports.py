from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query
from app.models.user import User

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/pendency")
def pendency_report(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        visible_applications_query(user, db)
        .filter(Application.status.notin_(["approved", "rejected", "completed"]))
        .with_entities(
            Application.current_stage,
            func.count(Application.id),
            func.sum(
                case(
                    (Application.due_at.is_not(None) & (Application.due_at < datetime.utcnow()), 1),
                    else_=0,
                )
            ),
        )
        .group_by(Application.current_stage)
        .order_by(Application.current_stage)
        .all()
    )
    return {
        "total_pending": sum(row[1] for row in rows),
        "overdue_pending": sum(row[2] or 0 for row in rows),
        "by_stage": [
            {"current_stage": stage, "count": count, "overdue_count": overdue or 0}
            for stage, count, overdue in rows
        ],
    }
