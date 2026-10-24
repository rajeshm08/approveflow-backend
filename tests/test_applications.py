from tests.conftest import token_for


def test_valid_transition_creates_history_and_audit(client):
    token = token_for(client, "officer@example.com")
    response = client.post(
        f"/api/applications/{client.application_ids['a']}/transition",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "expected_current_stage": "submitted",
            "next_stage": "regional_review",
            "reason": "Initial review completed",
        },
    )
    assert response.status_code == 200
    assert response.json()["current_stage"] == "regional_review"

    timeline = client.get(
        f"/api/applications/{client.application_ids['a']}/timeline",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert timeline.status_code == 200
    assert timeline.json()[0]["reason"] == "Initial review completed"

    admin_token = token_for(client, "admin@example.com")
    audit = client.get(
        "/api/audit-logs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert audit.status_code == 200
    assert audit.json()[0]["action"] == "application.transition"
    assert audit.json()[0]["details"]["new_values"]["current_stage"] == "regional_review"


def test_invalid_transition_is_rejected_without_changes(client):
    token = token_for(client, "officer@example.com")
    response = client.post(
        f"/api/applications/{client.application_ids['a']}/transition",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "expected_current_stage": "submitted",
            "next_stage": "approved",
            "reason": "Attempt to skip required reviews",
        },
    )
    assert response.status_code == 422
    application = client.get(
        f"/api/applications/{client.application_ids['a']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert application.json()["current_stage"] == "submitted"


def test_institution_cannot_access_another_institutions_application(client):
    token = token_for(client, "institution@example.com")
    response = client.get(
        f"/api/applications/{client.application_ids['b']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_auditor_can_read_transition_audit_entry(client):
    token = token_for(client, "officer@example.com")
    response = client.post(
        f"/api/applications/{client.application_ids['a']}/transition",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "expected_current_stage": "submitted",
            "next_stage": "regional_review",
            "reason": "Review recorded",
        },
    )
    assert response.status_code == 200
    auditor_token = token_for(client, "auditor@example.com")
    audit = client.get("/api/audit-logs", headers={"Authorization": f"Bearer {auditor_token}"})
    assert audit.status_code == 200
    assert audit.json()[0]["details"]["reason"] == "Review recorded"
