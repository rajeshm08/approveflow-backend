from datetime import datetime, timedelta
from uuid import uuid4

from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_extension_columns
from app.models import (
    Application,
    ApplicationStage,
    AuditLog,
    Document,
    Escalation,
    EVCEvent,
    Institution,
    Notification,
    Undertaking,
    User,
    WorkflowStage,
    WorkflowTemplate,
)
from app.security.auth import hash_password
from app.services.deadlines import run_deadline_check

REGIONS = ["North", "South", "East", "West", "Central"]
ROLES = [
    "institution",
    "regional_officer",
    "bureau_officer",
    "evc_coordinator",
    "committee",
    "admin",
    "auditor",
]
NOTIFICATION_TYPES = [
    "new_assignment",
    "deadline_approaching",
    "evc_due",
    "compliance_required",
    "document_expiry_approaching",
    "overdue",
    "escalation_issued",
]

# SLA values below are illustrative and are not official AICTE deadlines.
STAGE_DEFINITIONS = [
    ("draft", "Draft", ["institution"], ["submitted"], 2),
    ("submitted", "Submitted", ["regional_officer"], ["regional_review"], 5),
    ("regional_review", "Regional Review", ["regional_officer"], ["bureau_review"], 7),
    ("bureau_review", "Bureau Review", ["bureau_officer"], ["evc_scheduling"], 7),
    ("evc_scheduling", "EVC Scheduling", ["evc_coordinator"], ["evc_review"], 3),
    ("evc_review", "EVC Review", ["evc_coordinator"], ["committee_review"], 10),
    ("committee_review", "Committee Review", ["committee"], ["approved", "rejected"], 14),
    ("approved", "Approved", [], [], 0),
    ("rejected", "Rejected", [], [], 0),
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_extension_columns()
    with SessionLocal() as db:
        if db.query(User).count() or db.query(Application).count():
            print("Demo data already exists; no changes made.")
            return

        institutions = []
        for index in range(25):
            institution = Institution(
                name=f"ApproveFlow Demo Institute {index + 1:02d}",
                region=REGIONS[index % len(REGIONS)],
                state=f"Demo State {index % len(REGIONS) + 1}",
            )
            db.add(institution)
            institutions.append(institution)
        db.flush()

        users = []
        for role in ROLES:
            email = f"{role}@approveflow.example.com"
            user = User(
                email=email,
                full_name=f"Demo {role.replace('_', ' ').title()}",
                hashed_password=hash_password("Demo@123"),
                role=role,
                institution_id=institutions[0].id if role == "institution" else None,
            )
            db.add(user)
            users.append(user)
        db.flush()
        users_by_role = {user.role: user for user in users}

        template = WorkflowTemplate(name="Standard Demo Approval Workflow", is_active=True)
        db.add(template)
        db.flush()
        for sequence, (key, name, allowed_roles, next_keys, sla_days) in enumerate(STAGE_DEFINITIONS):
            db.add(
                WorkflowStage(
                    template_id=template.id,
                    stage_key=key,
                    name=name,
                    sequence=sequence,
                    allowed_roles=allowed_roles,
                    next_stage_keys=next_keys,
                    sla_days=sla_days,
                )
            )
        db.flush()

        seeded_at = datetime.utcnow().replace(second=0, microsecond=0)
        stage_keys = [definition[0] for definition in STAGE_DEFINITIONS[:-2]]
        stage_roles = {definition[0]: definition[2] for definition in STAGE_DEFINITIONS}
        applications = []
        for index in range(25):
            stage_key = "evc_scheduling" if index == 1 else stage_keys[index % len(stage_keys)]
            due_offsets = {
                0: 0,
                1: -3,
                2: -1,
                3: -1,
                4: -1,
                5: -3,
                6: -3,
                7: -3,
                8: 0,
            }
            due_offset = due_offsets.get(index, index - 8)
            application = Application(
                application_number=f"APP-{1001 + index}",
                institution_id=institutions[index].id,
                workflow_template_id=template.id,
                program_name=f"Demo Applied Sciences Program {index + 1:02d}",
                application_type="new_approval" if index % 2 == 0 else "extension",
                current_stage=stage_key,
                status="draft" if stage_key == "draft" else "in_review",
                due_at=seeded_at + timedelta(days=due_offset),
            )
            db.add(application)
            db.flush()
            applications.append(application)

            stage_index = next(
                i for i, definition in enumerate(STAGE_DEFINITIONS) if definition[0] == stage_key
            )
            if stage_key != "draft":
                prior_stage = STAGE_DEFINITIONS[stage_index - 1][0]
                actor_role = (stage_roles[prior_stage] or ["admin"])[0]
                db.add(
                    ApplicationStage(
                        application_id=application.id,
                        from_stage="draft",
                        to_stage=stage_key,
                        status=application.status,
                        reason="Synthetic demo workflow history.",
                        actor_id=users_by_role[actor_role].id,
                    )
                )

        app_1002 = applications[1]
        db.add(
            EVCEvent(
                application_id=app_1002.id,
                event_type="site_visit_pending",
                scheduled_at=seeded_at + timedelta(days=2),
                notes="Demo data: pending EVC visit; awaiting coordinator confirmation.",
            )
        )
        for application in (app_1002, applications[7], applications[12], applications[17]):
            db.add(
                Undertaking(
                    application_id=application.id,
                    undertaking_type="Demo institutional compliance undertaking",
                    status="pending",
                )
            )

        settings.upload_directory.mkdir(parents=True, exist_ok=True)
        for application in (app_1002, applications[4], applications[9]):
            storage_key = uuid4().hex
            content = b"%PDF-1.7\nApproveFlow demo evidence.\n"
            (settings.upload_directory / storage_key).write_bytes(content)
            db.add(
                Document(
                    application_id=application.id,
                    name=f"Demo evidence {application.application_number}.pdf",
                    storage_key=storage_key,
                    content_type="application/pdf",
                    size_bytes=len(content),
                    status="uploaded",
                    expires_at=seeded_at + timedelta(days=14),
                )
            )

        # Seed both escalation levels explicitly; the deadline job creates
        # deduplicated notifications and will not duplicate existing T+3 rows.
        for application in (applications[2], applications[3], applications[4]):
            db.add(
                Escalation(
                    application_id=application.id,
                    reason="DEMO DATA: T+1 overdue alert awaiting regional officer action.",
                    escalation_level="regional_officer",
                    deduplication_key=f"demo:t_plus_1:application:{application.id}",
                    escalated_at=seeded_at,
                )
            )
        for application in (applications[5], applications[6], applications[7]):
            db.add(
                Escalation(
                    application_id=application.id,
                    reason="DEMO DATA: T+3 escalation awaiting senior officer review.",
                    escalation_level="senior_officer",
                    deduplication_key=f"escalation_t_plus_3:application:{application.id}",
                    escalated_at=seeded_at,
                )
            )

        for notification_type in NOTIFICATION_TYPES:
            for index in range(15):
                application = applications[(index + NOTIFICATION_TYPES.index(notification_type)) % 25]
                recipient = users[index % len(users)]
                db.add(
                    Notification(
                        user_id=recipient.id,
                        application_id=application.id,
                        title=f"Demo {notification_type.replace('_', ' ').title()}",
                        message=(
                            f"DEMO DATA: {application.application_number} has a "
                            f"{notification_type.replace('_', ' ')} update."
                        ),
                        notification_type=notification_type,
                        delivery_status="sent" if index % 2 == 0 else "pending",
                        deduplication_key=f"demo-seed:{notification_type}:{index + 1}",
                        created_at=seeded_at - timedelta(hours=index),
                    )
                )

        admin = users_by_role["admin"]
        for index, application in enumerate((applications[8], applications[13], applications[18])):
            escalation = Escalation(
                application_id=application.id,
                reason="DEMO DATA: Resolved senior officer escalation.",
                status="resolved",
                escalation_level="senior_officer",
                deduplication_key=f"demo:resolved:application:{application.id}",
                resolved_by=admin.id,
                resolved_at=seeded_at - timedelta(days=index + 1),
                escalated_at=seeded_at - timedelta(days=index + 2),
            )
            db.add(escalation)
            db.flush()
            db.add(
                AuditLog(
                    actor_id=admin.id,
                    action="escalation.resolved",
                    entity_type="escalation",
                    entity_id=str(escalation.id),
                    details={
                        "old_values": {"status": "open"},
                        "new_values": {"status": "resolved", "resolved_by": admin.id},
                        "reason": "DEMO DATA: Seeded resolved escalation for demonstration.",
                    },
                    created_at=escalation.resolved_at,
                )
            )

        db.commit()

    run_deadline_check()
    with SessionLocal() as db:
        open_escalations = db.query(Escalation).filter(Escalation.status == "open").count()
        notifications = db.query(Notification).count()
    print(
        "Seeded demo users, 25 applications (APP-1001 to APP-1025), "
        f"{open_escalations} open escalations, and {notifications} notifications; "
        "the deadline job ran once."
    )


if __name__ == "__main__":
    seed()
