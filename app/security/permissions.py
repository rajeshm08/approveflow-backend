from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.application import Application
from app.models.user import User
from app.security.auth import get_current_user

ROLES = {
    "institution",
    "regional_officer",
    "bureau_officer",
    "evc_coordinator",
    "committee",
    "admin",
    "auditor",
}


def require_roles(*roles: str):
    def role_dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return role_dependency


def get_visible_application(application_id: int, user: User, db: Session) -> Application:
    query = db.query(Application).filter(Application.id == application_id)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    application = query.first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


def visible_applications_query(user: User, db: Session):
    query = db.query(Application)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    return query
