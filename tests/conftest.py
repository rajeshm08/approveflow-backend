import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Application, Document, Institution, User, WorkflowStage, WorkflowTemplate
from app.security.auth import hash_password
from app.config import settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSession() as db:
        institution_a = Institution(name="Institute A", region="North", state="State A")
        institution_b = Institution(name="Institute B", region="South", state="State B")
        db.add_all([institution_a, institution_b])
        db.flush()
        institution_user = User(
            email="institution@example.com",
            full_name="Institution User",
            hashed_password=hash_password("password"),
            role="institution",
            institution_id=institution_a.id,
        )
        officer = User(
            email="officer@example.com",
            full_name="Regional Officer",
            hashed_password=hash_password("password"),
            role="regional_officer",
        )
        admin = User(
            email="admin@example.com",
            full_name="Administrator",
            hashed_password=hash_password("password"),
            role="admin",
        )
        auditor = User(
            email="auditor@example.com",
            full_name="Auditor",
            hashed_password=hash_password("password"),
            role="auditor",
        )
        template = WorkflowTemplate(name="Test workflow", is_active=True)
        db.add_all([institution_user, officer, admin, auditor, template])
        db.flush()
        db.add_all(
            [
                WorkflowStage(
                    template_id=template.id,
                    stage_key="draft",
                    name="Draft",
                    sequence=0,
                    allowed_roles=["institution"],
                    next_stage_keys=["submitted"],
                    sla_days=2,
                ),
                WorkflowStage(
                    template_id=template.id,
                    stage_key="submitted",
                    name="Submitted",
                    sequence=1,
                    allowed_roles=["regional_officer"],
                    next_stage_keys=["regional_review"],
                    sla_days=5,
                ),
                WorkflowStage(
                    template_id=template.id,
                    stage_key="regional_review",
                    name="Regional Review",
                    sequence=2,
                    allowed_roles=["regional_officer"],
                    next_stage_keys=[],
                    sla_days=0,
                ),
            ]
        )
        application_a = Application(
            application_number="AF-TEST-1",
            institution_id=institution_a.id,
            workflow_template_id=template.id,
            program_name="Test program A",
            current_stage="submitted",
            status="in_review",
        )
        application_b = Application(
            application_number="AF-TEST-2",
            institution_id=institution_b.id,
            workflow_template_id=template.id,
            program_name="Test program B",
            current_stage="draft",
            status="draft",
        )
        db.add_all([application_a, application_b])
        db.commit()
        user_ids = {
            "institution": institution_user.id,
            "officer": officer.id,
            "admin": admin.id,
            "auditor": auditor.id,
        }
        application_ids = {"a": application_a.id, "b": application_b.id}

    def override_get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.user_ids = user_ids
        test_client.application_ids = application_ids
        test_client.testing_session_factory = TestingSession
        test_client.institution_ids = {"a": institution_a.id, "b": institution_b.id}
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def token_for(client, email, password="password"):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]
