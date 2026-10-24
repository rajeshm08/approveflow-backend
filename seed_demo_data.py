from datetime import datetime, timedelta

from app.database import Base, SessionLocal, engine
from app.models import Application, ApplicationStage, Institution, User, WorkflowStage, WorkflowTemplate
from app.security.auth import hash_password

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

# SLA values below are illustrative and are not official AICTE deadlines.
STAGE_DEFINITIONS = [
    ("draft", "Draft", ["institution"], ["submitted"], 2),
    ("submitted", "Submitted", ["regional_officer"], ["regional_review"], 5),
    ("regional_review", "Regional Review", ["regional_officer"], ["bureau_review"], 7),
    ("bureau_review", "Bureau Review", ["bureau_officer"], ["evc_review"], 7),
    ("evc_review", "EVC Review", ["evc_coordinator"], ["committee_review"], 10),
    ("committee_review", "Committee Review", ["committee"], ["approved", "rejected"], 14),
    ("approved", "Approved", [], [], 0),
    ("rejected", "Rejected", [], [], 0),
]


def seed() -> None:
    Base.metadata.create_all(bind=engine)
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

        institution_id = institutions[0].id
        for role in ROLES:
            email = f"{role}@approveflow.example.com"
            db.add(
                User(
                    email=email,
                    full_name=f"Demo {role.replace('_', ' ').title()}",
                    hashed_password=hash_password("Demo@123"),
                    role=role,
                    institution_id=institution_id if role == "institution" else None,
                )
            )
        template = WorkflowTemplate(name="Standard Approval Workflow", is_active=True)
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

        current_date = datetime.utcnow()
        active_stages = STAGE_DEFINITIONS[:-2]
        for index in range(25):
            stage_key = active_stages[index % len(active_stages)][0]
            stage_index = next(i for i, definition in enumerate(STAGE_DEFINITIONS) if definition[0] == stage_key)
            status_value = "draft" if stage_key == "draft" else "in_review"
            due_at = current_date + timedelta(days=(index % 15) - 5)
            application = Application(
                application_number=f"AF-DEMO-{index + 1:04d}",
                institution_id=institutions[index].id,
                workflow_template_id=template.id,
                program_name=f"Applied Sciences Program {index + 1:02d}",
                application_type="new_approval" if index % 2 == 0 else "extension",
                current_stage=stage_key,
                status=status_value,
                due_at=due_at,
            )
            db.add(application)
            db.flush()
            actor_role = STAGE_DEFINITIONS[max(stage_index - 1, 0)][2]
            actor_email = f"{(actor_role or ['institution'])[0]}@approveflow.example.com"
            actor = db.query(User).filter(User.email == actor_email).one()
            if stage_key != "draft":
                db.add(
                    ApplicationStage(
                        application_id=application.id,
                        from_stage="draft",
                        to_stage=stage_key,
                        status=status_value,
                        reason="Synthetic demo workflow history",
                        actor_id=actor.id,
                    )
                )
        db.commit()
        print("Seeded 7 demo users, 5 regions, and 25 synthetic applications.")


if __name__ == "__main__":
    seed()
