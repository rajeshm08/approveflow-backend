import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.application import Application
from app.models.document import Document
from app.models.user import User
from app.security.auth import get_current_user
from app.security.permissions import visible_applications_query
from app.services.audit import create_audit_log

router = APIRouter(prefix="/api/documents", tags=["documents"])
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = {
    ".pdf": ("application/pdf", b"%PDF-"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
}


def identify_content(prefix: bytes) -> tuple[str, str] | None:
    for extension, (media_type, signature) in ALLOWED_TYPES.items():
        if prefix.startswith(signature):
            return extension, media_type
    return None


def visible_documents_query(user: User, db: Session):
    query = db.query(Document).join(Application, Document.application_id == Application.id)
    if user.role == "institution":
        query = query.filter(Application.institution_id == user.institution_id)
    return query


def serialize_document(document: Document) -> dict:
    return {
        "id": document.id,
        "application_id": document.application_id,
        "name": document.name,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "status": document.status,
        "uploaded_at": document.uploaded_at,
        "expires_at": document.expires_at,
    }


@router.get("")
def list_documents(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return [
        serialize_document(document)
        for document in visible_documents_query(user, db).order_by(Document.uploaded_at.desc()).all()
    ]


@router.post("/upload", status_code=201)
async def upload_document(
    application_id: int = Form(...),
    reason: str = Form(..., min_length=1, max_length=2000),
    file: UploadFile = File(...),
    expires_at: datetime | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role not in {"institution", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient role")
    reason = reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail="A reason is required")
    application = visible_applications_query(user, db).filter(Application.id == application_id).one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only PDF, JPG, and PNG files are allowed")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 5 MB limit")
    detected = identify_content(data)
    if detected is None:
        raise HTTPException(status_code=415, detail="File content is not a supported PDF, JPG, or PNG")
    detected_extension, detected_type = detected
    extension_matches = (suffix == ".jpeg" and detected_extension == ".jpg") or suffix == detected_extension
    if not extension_matches or file.content_type != detected_type:
        raise HTTPException(status_code=415, detail="File extension, content type, and file content must match")

    storage_key = uuid.uuid4().hex
    settings.upload_directory.mkdir(parents=True, exist_ok=True)
    destination = settings.upload_directory / storage_key
    destination.write_bytes(data)
    document = Document(
        application_id=application.id,
        name=Path(file.filename or "document").name,
        storage_key=storage_key,
        content_type=detected_type,
        size_bytes=len(data),
        status="uploaded",
        expires_at=expires_at,
    )
    try:
        db.add(document)
        db.flush()
        create_audit_log(
            db,
            actor_id=user.id,
            action="document.uploaded",
            entity_type="document",
            entity_id=document.id,
            details={
                "old_values": {},
                "new_values": {
                    "application_id": application.id,
                    "name": document.name,
                    "content_type": detected_type,
                    "size_bytes": len(data),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                "reason": reason,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    db.refresh(document)
    return serialize_document(document)


@router.get("/expiring")
def expiring_documents(
    days: int = 30,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if days < 1 or days > 365:
        raise HTTPException(status_code=422, detail="days must be between 1 and 365")
    current_time = datetime.utcnow()
    documents = (
        visible_documents_query(user, db)
        .filter(
            Document.expires_at.is_not(None),
            Document.expires_at >= current_time,
            Document.expires_at <= current_time + timedelta(days=days),
        )
        .order_by(Document.expires_at.asc())
        .all()
    )
    return [serialize_document(document) for document in documents]


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = visible_documents_query(user, db).filter(Document.id == document_id).one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.storage_key:
        raise HTTPException(status_code=404, detail="Stored document is unavailable")
    file_path = settings.upload_directory / document.storage_key
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Stored document is unavailable")
    return FileResponse(file_path, media_type=document.content_type, filename=document.name)
