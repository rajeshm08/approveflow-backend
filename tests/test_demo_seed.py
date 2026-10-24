from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.main as main_module
import app.services.deadlines as deadlines
import seed_demo_data
from app.config import settings
from app.database import Base, get_db
from app.models import Application, AuditLog, Escalation, EVCEvent, Notification, User
from app.security.auth import create_access_token


def test_seed_contains_demo_escalations_notifications_and_assistant_answer(monkeypatch, tmp_path):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessions = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_sessions)
    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(seed_demo_data, "engine", test_engine)
    monkeypatch.setattr(seed_demo_data, "SessionLocal", test_sessions)
    monkeypatch.setattr(deadlines, "SessionLocal", test_sessions)
    monkeypatch.setattr(settings, "upload_directory", tmp_path / "private_uploads")
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "seed_demo_data", True)

    def override_get_db():
        with test_sessions() as db:
            yield db

    main_module.app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main_module.app) as client:
            with test_sessions() as db:
                application_numbers = [
                    row[0]
                    for row in db.query(Application.application_number)
                    .order_by(Application.application_number)
                    .all()
                ]
                assert application_numbers == [f"APP-{number}" for number in range(1001, 1026)]
                application = db.query(Application).filter_by(application_number="APP-1002").one()
                assert application.current_stage == "evc_scheduling"
                assert application.due_at is not None
                assert application.due_at < seed_demo_data.datetime.utcnow()
                open_escalations = db.query(Escalation).filter_by(status="open").all()
                assert len(open_escalations) >= 6
                assert {row.escalation_level for row in open_escalations} >= {
                    "regional_officer",
                    "senior_officer",
                }
                assert all(
                    db.get(Application, row.application_id).due_at < seed_demo_data.datetime.utcnow()
                    for row in open_escalations
                )
                assert db.query(Escalation).filter_by(status="resolved").count() >= 3
                assert db.query(AuditLog).filter_by(action="escalation.resolved").count() >= 3
                for notification_type in seed_demo_data.NOTIFICATION_TYPES:
                    rows = db.query(Notification).filter_by(notification_type=notification_type).all()
                    assert len(rows) >= 15
                    assert {row.delivery_status for row in rows} >= {"sent", "pending"}
                assert db.query(EVCEvent).filter_by(application_id=application.id).count() == 1
                admin = db.query(User).filter_by(role="admin").one()
                institution_user = db.query(User).filter_by(role="institution").one()
                seeded_counts = (
                    db.query(Application).count(),
                    db.query(Notification).count(),
                    db.query(Escalation).count(),
                )

            token = create_access_token(admin)
            institution_token = create_access_token(institution_user)
            response = client.post(
                "/api/assistant/ask",
                headers={"Authorization": f"Bearer {token}"},
                json={"question": "Why is APP-1002 pending?"},
            )
            scoped_response = client.post(
                "/api/assistant/ask",
                headers={"Authorization": f"Bearer {institution_token}"},
                json={"question": "Why is APP-1002 pending?"},
            )
        assert response.status_code == 200
        assert response.json()["answer"] != "Information unavailable"
        assert "EVC" in response.json()["answer"]
        assert scoped_response.status_code == 200
        assert scoped_response.json()["answer"] == "Information unavailable"

        with TestClient(main_module.app):
            with test_sessions() as db:
                assert (
                    db.query(Application).count(),
                    db.query(Notification).count(),
                    db.query(Escalation).count(),
                ) == seeded_counts
    finally:
        main_module.app.dependency_overrides.clear()
        test_engine.dispose()
