from datetime import datetime, timedelta

from app.config import settings
from app.models import Application, Document, Notification
from app.services.deadlines import process_deadlines
from tests.conftest import token_for


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
