from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogResponse
from app.security.permissions import require_roles

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@router.get("", response_model=list[AuditLogResponse])
def list_audit_logs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(require_roles("admin", "auditor")),
):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()
