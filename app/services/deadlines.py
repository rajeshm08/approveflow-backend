from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.application import Application
from app.models.escalation import Escalation
from app.models.institution import Institution
from app.models.notification import Notification
from app.models.user import User
from app.services.audit import create_audit_log

COMPLETED_STATUSES = {"approved", "rejected", "completed"}


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
                        "old_values": {},
                        "new_values": {"application_id": application.id, "status": "open"},
                        "reason": escalation.reason,
                    },
                )

    db.commit()
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
