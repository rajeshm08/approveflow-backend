from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.application import Application
from app.models.document import Document
from app.models.escalation import Escalation
from app.models.institution import Institution
from app.models.notification import Notification
from app.models.user import User
from app.services.audit import create_audit_log

COMPLETED_STATUSES = {"approved", "rejected", "completed"}
# Illustrative demo values only; they are not official AICTE document-validity rules.
DOCUMENT_EXPIRY_ALERT_OFFSETS_DAYS = settings.document_expiry_alert_offsets_days
DOCUMENT_EXPIRY_ESCALATION_GRACE_DAYS = settings.document_expiry_escalation_grace_days


def process_deadlines(db: Session, now: datetime | None = None) -> int:
    """Create deadline alerts idempotently; offsets are illustrative demo values."""
    current_time = now or datetime.utcnow()
    applications = (
        db.query(Application)
        .filter(
            Application.due_at.is_not(None),
            Application.status.notin_(COMPLETED_STATUSES),
            Application.current_stage.notin_(COMPLETED_STATUSES),
        )
        .all()
    )
    created = 0
    for application in applications:
        due_at = application.due_at
        alert_kind = None
        if due_at - timedelta(days=3) <= current_time < due_at - timedelta(days=3) + timedelta(minutes=1):
            alert_kind = "reminder_t_minus_3"
            title = "Demo application deadline in 3 days"
        elif due_at - timedelta(days=1) <= current_time < due_at - timedelta(days=1) + timedelta(minutes=1):
            alert_kind = "reminder_t_minus_1"
            title = "Demo application deadline tomorrow"
        elif due_at + timedelta(days=1) <= current_time < due_at + timedelta(days=1) + timedelta(minutes=1):
            alert_kind = "overdue_t_plus_1"
            title = "Demo application overdue"
        elif due_at + timedelta(days=3) <= current_time < due_at + timedelta(days=3) + timedelta(minutes=1):
            alert_kind = "escalation_t_plus_3"
            title = "Demo application deadline escalation"
        else:
            continue

        recipients = (
            db.query(User)
            .join(Institution, User.institution_id == Institution.id)
            .filter(User.institution_id == application.institution_id, User.is_active.is_(True))
            .all()
        )
        for recipient in recipients:
            key = f"{alert_kind}:application:{application.id}:user:{recipient.id}"
            if db.query(Notification.id).filter(Notification.deduplication_key == key).first():
                continue
            notification_type = {
                "reminder_t_minus_3": "deadline_approaching",
                "reminder_t_minus_1": "deadline_approaching",
                "overdue_t_plus_1": "overdue",
                "escalation_t_plus_3": "escalation_issued",
            }[alert_kind]
            notification = Notification(
                user_id=recipient.id,
                application_id=application.id,
                title=title,
                message=f"DEMO DATA: {application.application_number} is at stage {application.current_stage}.",
                notification_type=notification_type,
                delivery_status="sent",
                deduplication_key=key,
            )
            try:
                with db.begin_nested():
                    db.add(notification)
                    db.flush()
            except IntegrityError:
                continue
            create_audit_log(
                db,
                actor_id=None,
                action="deadline.alert_created",
                entity_type="notification",
                entity_id=key,
                details={
                    "actor": "system",
                    "old_values": {},
                    "new_values": {"alert_kind": alert_kind, "application_id": application.id},
                    "reason": "Scheduled demo deadline alert",
                },
            )
            created += 1

        if alert_kind == "escalation_t_plus_3":
            escalation_key = f"{alert_kind}:application:{application.id}"
            if not db.query(Escalation.id).filter(Escalation.deduplication_key == escalation_key).first():
                escalation = Escalation(
                    application_id=application.id,
                    reason="DEMO DATA: Application remained overdue for 3 days.",
                    escalation_level="senior_officer",
                    deduplication_key=escalation_key,
                )
                db.add(escalation)
                db.flush()
                create_audit_log(
                    db,
                    actor_id=None,
                    action="deadline.escalation_created",
                    entity_type="escalation",
                    entity_id=escalation.id,
                    details={
                        "actor": "system",
                        "old_values": {},
                        "new_values": {"application_id": application.id, "status": "open"},
                        "reason": escalation.reason,
                    },
                )

    created += process_document_expiries(db, current_time)
    db.commit()
    return created


def process_document_expiries(db: Session, current_time: datetime) -> int:
    """Create idempotent expiry alerts/escalations for non-completed applications."""
    document_rows = (
        db.query(Document, Application)
        .join(Application, Document.application_id == Application.id)
        .filter(Document.expires_at.is_not(None))
        .all()
    )
    documents_by_application: dict[int, list[Document]] = {}
    for document, _application in document_rows:
        documents_by_application.setdefault(document.application_id, []).append(document)

    recipients_by_institution: dict[int, User | None] = {}
    created = 0
    for document, application in document_rows:
        if (
            application.status in COMPLETED_STATUSES
            or application.current_stage in COMPLETED_STATUSES
        ):
            continue

        document_type = document.document_type or document.content_type
        renewed = any(
            other.id != document.id
            and other.uploaded_at > document.uploaded_at
            and other.status.lower() == "verified"
            and (other.document_type or other.content_type) == document_type
            for other in documents_by_application[document.application_id]
        )
        if renewed:
            continue

        if application.institution_id not in recipients_by_institution:
            recipients_by_institution[application.institution_id] = (
                db.query(User)
                .filter(
                    User.institution_id == application.institution_id,
                    User.is_active.is_(True),
                )
                .order_by(User.id.asc())
                .first()
            )
        recipient = recipients_by_institution[application.institution_id]
        if recipient is not None:
            alert_offsets = [
                (offset, document.expires_at - timedelta(days=offset), f"Document expires in {offset} days")
                for offset in DOCUMENT_EXPIRY_ALERT_OFFSETS_DAYS
            ]
            alert_offsets.append(
                (
                    "expired_plus_1",
                    document.expires_at + timedelta(days=1),
                    "Document expired yesterday",
                )
            )
            for offset, threshold, title in alert_offsets:
                if current_time < threshold:
                    continue
                key = f"doc:{document.id}:{offset}"
                if db.query(Notification.id).filter(Notification.deduplication_key == key).first():
                    continue
                notification = Notification(
                    user_id=recipient.id,
                    application_id=application.id,
                    title=f"Demo {title}",
                    message=(
                        f"DEMO DATA: {document.name} for {application.application_number} "
                        f"expires at {document.expires_at.isoformat()}."
                    ),
                    notification_type=(
                        "document_expiry_approaching" if offset != "expired_plus_1" else "document_expired"
                    ),
                    delivery_status="sent",
                    deduplication_key=key,
                )
                try:
                    with db.begin_nested():
                        db.add(notification)
                        db.flush()
                except IntegrityError:
                    continue
                create_audit_log(
                    db,
                    actor_id=None,
                    action="document.expiry_alert_created",
                    entity_type="document",
                    entity_id=document.id,
                    details={
                        "actor": "system",
                        "old_values": {},
                        "new_values": {
                            "notification_id": notification.id,
                            "application_id": application.id,
                            "offset": offset,
                        },
                        "reason": "Scheduled demo document-expiry alert.",
                    },
                )
                created += 1

        escalation_threshold = document.expires_at + timedelta(
            days=DOCUMENT_EXPIRY_ESCALATION_GRACE_DAYS
        )
        if current_time < escalation_threshold:
            continue
        escalation_key = (
            f"doc:{document.id}:escalation:grace_{DOCUMENT_EXPIRY_ESCALATION_GRACE_DAYS}"
        )
        if db.query(Escalation.id).filter(Escalation.deduplication_key == escalation_key).first():
            continue
        escalation = Escalation(
            application_id=application.id,
            document_id=document.id,
            reason=(
                f"DEMO DATA: {document.name} remained expired beyond the configured "
                f"{DOCUMENT_EXPIRY_ESCALATION_GRACE_DAYS}-day grace period."
            ),
            escalation_level="senior_officer",
            deduplication_key=escalation_key,
        )
        try:
            with db.begin_nested():
                db.add(escalation)
                db.flush()
                create_audit_log(
                    db,
                    actor_id=None,
                    action="document.expiry_escalation_created",
                    entity_type="escalation",
                    entity_id=escalation.id,
                    details={
                        "actor": "system",
                        "old_values": {},
                        "new_values": {
                            "application_id": application.id,
                            "document_id": document.id,
                            "status": escalation.status,
                            "escalation_level": escalation.escalation_level,
                        },
                        "reason": escalation.reason,
                    },
                )
        except IntegrityError:
            continue

    return created


def run_deadline_check() -> int:
    with SessionLocal() as db:
        return process_deadlines(db)


def start_deadline_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_deadline_check, "interval", minutes=1, id="deadline-alerts", replace_existing=True)
    scheduler.start()
    return scheduler
