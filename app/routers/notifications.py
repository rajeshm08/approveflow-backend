from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .all()
    )
    return [
        {
            "id": item.id,
            "application_id": item.application_id,
            "title": item.title,
            "message": item.message,
            "is_read": item.is_read,
            "created_at": item.created_at,
        }
        for item in notifications
    ]
