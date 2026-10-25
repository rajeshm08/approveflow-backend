from datetime import datetime, timedelta

from app.config import settings
from app.models import Application, AuditLog, Document, Escalation, Notification
from app.services.deadlines import process_deadlines
from tests.conftest import token_for


def test_ping_get_and_head_return_empty_204(client):
    for method in ("GET", "HEAD"):
        response = client.request(method, "/ping")
        assert response.status_code == 204
        assert response.content == b""


def test_running_deadline_scheduler_twice_deduplicates_notifications(client):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with client.testing_session_factory() as db:
        application = db.query(Application).filter(Application.id == client.application_ids["a"]).one()
        application.due_at = now + timedelta(days=3)
        db.commit()

        first_count = process_deadlines(db, now=now)
        second_count = process_deadlines(db, now=now)
        notification_count = (
            db.query(Notification)
            .filter(Notification.application_id == application.id)
            .count()
        )

    assert first_count == 1
    assert second_count == 0
    assert notification_count == 1


def test_completed_application_does_not_receive_deadline_alerts(client):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with client.testing_session_factory() as db:
        application = db.query(Application).filter(Application.id == client.application_ids["a"]).one()
        application.due_at = now - timedelta(days=1)
        application.current_stage = "completed"
        application.status = "completed"
        db.commit()

        assert process_deadlines(db, now=now) == 0
        assert db.query(Notification).filter(Notification.application_id == application.id).count() == 0


def add_document(db, application_id, *, document_type, uploaded_at, expires_at, status="verified"):
    document = Document(
        application_id=application_id,
        name=f"{document_type}.pdf",
        document_type=document_type,
        storage_key=f"test-{document_type}-{uploaded_at.timestamp()}",
        content_type="application/pdf",
        size_bytes=20,
        status=status,
        uploaded_at=uploaded_at,
        expires_at=expires_at,
    )
    db.add(document)
    db.flush()
    return document


def test_document_expiry_offsets_and_notifications_are_deduplicated(client):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with client.testing_session_factory() as db:
        application_id = client.application_ids["a"]
        document = add_document(
            db,
            application_id,
            document_type="operating_license",
            uploaded_at=now - timedelta(days=60),
            expires_at=now + timedelta(days=30),
        )
        document_id = document.id
        db.commit()

        for offset, days_after_seed in ((30, 0), (15, 15), (7, 23), ("expired_plus_1", 31)):
            alert_time = now + timedelta(days=days_after_seed)
            process_deadlines(db, now=alert_time)
            process_deadlines(db, now=alert_time)

        notifications = (
            db.query(Notification)
            .filter(
                Notification.application_id == application_id,
                Notification.deduplication_key.like(f"doc:{document_id}:%"),
            )
            .all()
        )
        assert {row.deduplication_key for row in notifications} == {
            f"doc:{document_id}:30",
            f"doc:{document_id}:15",
            f"doc:{document_id}:7",
            f"doc:{document_id}:expired_plus_1",
        }
        assert db.query(AuditLog).filter(
            AuditLog.action == "document.expiry_alert_created",
            AuditLog.entity_id == str(document_id),
        ).count() == 4
        assert all(log.details["actor"] == "system" for log in db.query(AuditLog).filter(
            AuditLog.action == "document.expiry_alert_created",
            AuditLog.entity_id == str(document_id),
        ).all())


def test_verified_renewal_stops_alerts_and_escalations_for_old_document(client):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with client.testing_session_factory() as db:
        application_id = client.application_ids["a"]
        old_document = add_document(
            db,
            application_id,
            document_type="operating_license",
            uploaded_at=now - timedelta(days=90),
            expires_at=now - timedelta(days=10),
        )
        old_document_id = old_document.id
        add_document(
            db,
            application_id,
            document_type="operating_license",
            uploaded_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=365),
            status="verified",
        )
        db.commit()

        process_deadlines(db, now=now)
        process_deadlines(db, now=now + timedelta(days=1))

        assert db.query(Notification).filter(
            Notification.deduplication_key.like(f"doc:{old_document_id}:%")
        ).count() == 0
        assert db.query(Escalation).filter(Escalation.document_id == old_document_id).count() == 0


def test_expired_document_past_grace_creates_one_audited_senior_escalation(client):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with client.testing_session_factory() as db:
        document = add_document(
            db,
            client.application_ids["a"],
            document_type="safety_certificate",
            uploaded_at=now - timedelta(days=90),
            expires_at=now - timedelta(days=3),
        )
        document_id = document.id
        db.commit()

        process_deadlines(db, now=now)
        process_deadlines(db, now=now + timedelta(minutes=1))

        escalations = db.query(Escalation).filter(Escalation.document_id == document_id).all()
        assert len(escalations) == 1
        assert escalations[0].application_id == client.application_ids["a"]
        assert escalations[0].escalation_level == "senior_officer"
        audit = db.query(AuditLog).filter(
            AuditLog.action == "document.expiry_escalation_created",
            AuditLog.entity_id == str(escalations[0].id),
        ).one()
        assert audit.actor_id is None
        assert audit.details["actor"] == "system"


def test_completed_application_receives_no_document_expiry_actions(client):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with client.testing_session_factory() as db:
        application = db.get(Application, client.application_ids["a"])
        application.status = "completed"
        application.current_stage = "completed"
        document = add_document(
            db,
            application.id,
            document_type="expired_license",
            uploaded_at=now - timedelta(days=90),
            expires_at=now - timedelta(days=30),
        )
        document_id = document.id
        db.commit()

        process_deadlines(db, now=now)

        assert db.query(Notification).filter(
            Notification.deduplication_key.like(f"doc:{document_id}:%")
        ).count() == 0
        assert db.query(Escalation).filter(Escalation.document_id == document_id).count() == 0


def test_upload_rejects_unsupported_and_mismatched_content(client):
    token = token_for(client, "institution@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "/api/documents/upload"

    unsupported = client.post(
        endpoint,
        headers=headers,
        data={"application_id": str(client.application_ids["a"]), "reason": "Upload test"},
        files={"file": ("malware.exe", b"MZ-content", "application/octet-stream")},
    )
    assert unsupported.status_code == 415

    mismatched = client.post(
        endpoint,
        headers=headers,
        data={"application_id": str(client.application_ids["a"]), "reason": "Upload test"},
        files={"file": ("report.pdf", b"not really a pdf", "application/pdf")},
    )
    assert mismatched.status_code == 415

    forged_type = client.post(
        endpoint,
        headers=headers,
        data={"application_id": str(client.application_ids["a"]), "reason": "Upload test"},
        files={"file": ("report.pdf", b"%PDF-1.7\ncontent", "image/png")},
    )
    assert forged_type.status_code == 415


def test_valid_document_upload_uses_private_random_storage_key(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_directory", tmp_path)
    token = token_for(client, "institution@example.com")
    response = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"application_id": str(client.application_ids["a"]), "reason": "Required supporting document"},
        files={"file": ("evidence.pdf", b"%PDF-1.7\nvalid fixture", "application/pdf")},
    )
    assert response.status_code == 201
    assert "storage_key" not in response.json()
    with client.testing_session_factory() as db:
        document = db.query(Document).filter(Document.id == response.json()["id"]).one()
        assert len(document.storage_key) == 32
        assert (tmp_path / document.storage_key).is_file()


def test_institution_cannot_download_another_institutions_document(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_directory", tmp_path)
    storage_key = "private-random-test-key"
    (tmp_path / storage_key).write_bytes(b"%PDF-1.7\nprivate")
    with client.testing_session_factory() as db:
        document = Document(
            application_id=client.application_ids["b"],
            name="private.pdf",
            storage_key=storage_key,
            content_type="application/pdf",
            size_bytes=15,
            status="uploaded",
        )
        db.add(document)
        db.commit()
        document_id = document.id

    token = token_for(client, "institution@example.com")
    response = client.get(
        f"/api/documents/{document_id}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_pendency_report_and_assistant_respect_database_scope(client):
    token = token_for(client, "institution@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    report = client.get("/api/reports/pendency", headers=headers)
    assert report.status_code == 200
    assert report.json()["total_pending"] == 1

    own_application = client.post(
        "/api/assistant/ask",
        headers=headers,
        json={"question": f"application id {client.application_ids['a']}"},
    )
    other_application = client.post(
        "/api/assistant/ask",
        headers=headers,
        json={"question": f"application id {client.application_ids['b']}"},
    )
    assert own_application.json()["data"]["application_id"] == client.application_ids["a"]
    assert other_application.json()["answer"] == "Information unavailable"
