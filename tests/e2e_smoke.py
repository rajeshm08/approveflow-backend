"""HTTPX smoke checks against an already-running local ApproveFlow API."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Application,
    Document,
    EVCEvent,
    Escalation,
    Institution,
    Notification,
    Undertaking,
    User,
)
from app.security.auth import hash_password  # noqa: E402
from app.services.deadlines import run_deadline_check  # noqa: E402

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
PASSWORD = "Demo@123"
ROLES = [
    "institution",
    "regional_officer",
    "bureau_officer",
    "evc_coordinator",
    "committee",
    "admin",
    "auditor",
]
results: list[tuple[str, str, str]] = []
tokens: dict[str, str] = {}
application_ids: dict[str, int] = {}
document_ids: dict[str, int] = {}
record_ids: dict[str, int] = {}


def check(name, action):
    try:
        action()
        results.append((name, "PASS", ""))
    except Exception as error:  # report independent checks rather than stopping at the first assertion
        results.append((name, "FAIL", f"{type(error).__name__}: {error}"))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def api() -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, timeout=30)


def login(role: str, password: str = PASSWORD) -> httpx.Response:
    with api() as client:
        return client.post(
            "/api/auth/login",
            json={"email": f"{role}@approveflow.example.com", "password": password},
        )


def auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens[role]}"}


def create_test_records():
    with SessionLocal() as db:
        institution_user = db.query(User).filter(User.role == "institution").one()
        institutions = db.query(Institution).order_by(Institution.id).all()
        applications = db.query(Application).order_by(Application.id).all()
        require(len(institutions) >= 2 and len(applications) >= 3, "Seed database is missing demo rows")
        first_institution_application = next(
            row for row in applications if row.institution_id == institution_user.institution_id
        )
        other_application = next(
            row for row in applications if row.institution_id != institution_user.institution_id
        )
        transition_application = next(
            row for row in applications if row.current_stage == "submitted"
        )
        completed_application = next(
            row for row in applications
            if row.id not in {transition_application.id, first_institution_application.id}
        )
        completed_application.status = "completed"
        completed_application.current_stage = "completed"
        completed_application.due_at = datetime.utcnow() + timedelta(days=3)

        other_institution_user = db.query(User).filter(User.email == "e2e.institution@approveflow.example.com").one_or_none()
        if other_institution_user is None:
            other_institution_user = User(
                email="e2e.institution@approveflow.example.com",
                full_name="E2E Other Institution",
                hashed_password=hash_password(PASSWORD),
                role="institution",
                institution_id=other_application.institution_id,
            )
            db.add(other_institution_user)

        expires = datetime.utcnow() + timedelta(days=10)
        expiry_doc = Document(
            application_id=first_institution_application.id,
            name="E2E expiry evidence",
            storage_key="e2e-expiry-record",
            content_type="application/pdf",
            size_bytes=16,
            status="uploaded",
            expires_at=expires,
        )
        undertaking = Undertaking(
            application_id=first_institution_application.id,
            undertaking_type="E2E compliance undertaking",
            status="pending",
        )
        escalation = Escalation(
            application_id=first_institution_application.id,
            reason="E2E escalation",
            status="open",
        )
        other_document = Document(
            application_id=other_application.id,
            name="Other institution private file",
            storage_key="e2e-other-private",
            content_type="application/pdf",
            size_bytes=12,
            status="uploaded",
        )
        db.add_all([expiry_doc, undertaking, escalation, other_document])
        db.flush()
        evc_event = EVCEvent(
            application_id=first_institution_application.id,
            event_type="site_visit",
            scheduled_at=datetime.utcnow() + timedelta(days=5),
            notes="E2E assistant fixture",
        )
        db.add(evc_event)
        db.commit()
        application_ids.update(
            first=first_institution_application.id,
            other=other_application.id,
            transition=transition_application.id,
            scheduler=first_institution_application.id,
            completed_scheduler=completed_application.id,
        )
        document_ids["other"] = other_document.id
        record_ids.update(undertaking=undertaking.id, escalation=escalation.id)


def test_all_logins():
    for role in ROLES:
        response = login(role)
        require(response.status_code == 200, f"{role} login returned {response.status_code}: {response.text}")
        body = response.json()
        require(body.get("access_token"), f"{role} login did not return a token")
        require(body["user"]["role"] == role, f"{role} login returned unexpected user role")
        require("institution_id" in body["user"], f"{role} login omitted institution_id")
        tokens[role] = body["access_token"]
    require(login("admin", "incorrect-password").status_code == 401, "Incorrect password did not return 401")


def test_dashboard_matches_database():
    with SessionLocal() as db:
        expected_total = db.query(func.count(Application.id)).scalar()
        expected_statuses = dict(
            db.query(Application.status, func.count(Application.id))
            .group_by(Application.status)
            .all()
        )
        now = datetime.utcnow()
        terminal = {"approved", "rejected", "completed"}
        expected_overdue = (
            db.query(func.count(Application.id))
            .filter(
                Application.due_at.is_not(None),
                Application.due_at < now,
                Application.status.notin_(terminal),
                Application.current_stage.notin_(terminal),
            )
            .scalar()
        )
        expected_upcoming = (
            db.query(func.count(Application.id))
            .filter(
                Application.due_at.is_not(None),
                Application.due_at >= now,
                Application.due_at <= now + timedelta(days=7),
                Application.status.notin_(terminal),
                Application.current_stage.notin_(terminal),
            )
            .scalar()
        )
    with api() as client:
        response = client.get("/api/dashboard/summary", headers=auth("admin"))
    require(response.status_code == 200, f"Dashboard returned {response.status_code}")
    actual = response.json()
    require(actual["total_applications"] == expected_total, "Dashboard total does not match database")
    require(actual["applications_by_status"] == expected_statuses, "Dashboard status counts do not match database")
    require(actual["overdue_applications"] == expected_overdue, "Dashboard overdue count does not match database")
    require(actual["upcoming_due_7_days"] == expected_upcoming, "Dashboard upcoming count does not match database")


def test_applications_and_transition():
    with api() as client:
        listing = client.get("/api/applications", headers=auth("admin"))
        require(listing.status_code == 200 and listing.json(), "Application list failed or was empty")
        application = listing.json()[0]
        application_id = application["application_id"]
        require(application["application_number"], "application_number missing")
        detail = client.get(f"/api/applications/{application_id}", headers=auth("admin"))
        require(detail.status_code == 200 and detail.json()["application_id"] == application_id, "Application detail failed")
        timeline = client.get(f"/api/applications/{application_id}/timeline", headers=auth("admin"))
        require(timeline.status_code == 200 and isinstance(timeline.json(), list), "Application timeline failed")

        target = application_ids["transition"]
        path = f"/api/applications/{target}/transition"
        payload = {
            "expected_current_stage": "submitted",
            "next_stage": "regional_review",
            "reason": "E2E smoke test review",
        }
        missing_reason = client.post(
            path,
            headers=auth("regional_officer"),
            json={key: value for key, value in payload.items() if key != "reason"},
        )
        require(missing_reason.status_code == 422, f"Whitespace reason returned {missing_reason.status_code}")
        unauthorized = client.post(path, headers=auth("bureau_officer"), json=payload)
        require(unauthorized.status_code == 403, f"Unauthorized transition returned {unauthorized.status_code}")
        invalid = client.post(path, headers=auth("regional_officer"), json={**payload, "next_stage": "approved"})
        require(invalid.status_code == 422, f"Invalid stage returned {invalid.status_code}")
        valid = client.post(path, headers=auth("regional_officer"), json=payload)
        require(valid.status_code == 200 and valid.json()["current_stage"] == "regional_review", "Valid transition failed")
        logs = client.get("/api/audit-logs", headers=auth("admin"), params={"limit": 500})
        require(
            logs.status_code == 200
            and any(
                entry["entity_type"] == "application"
                and entry["entity_id"] == str(target)
                and entry["action"] == "application.transition"
                for entry in logs.json()
            ),
            "Transition did not create an audit entry",
        )


def test_institution_scope():
    with api() as client:
        own_list = client.get("/api/applications", headers=auth("institution"))
        require(
            own_list.status_code == 200
            and all(row["institution_id"] == client_user_institution_id() for row in own_list.json()),
            "Institution list contains another institution's application",
        )
        application = client.get(
            f"/api/applications/{application_ids['other']}",
            headers=auth("institution"),
        )
        require(application.status_code in {403, 404}, f"Cross-institution application returned {application.status_code}")
        document = client.get(
            f"/api/documents/{document_ids['other']}/download",
            headers=auth("institution"),
        )
        require(document.status_code in {403, 404}, f"Cross-institution document returned {document.status_code}")
        answer = client.post(
            "/api/assistant/ask",
            headers=auth("institution"),
            json={"question": f"application id {application_ids['other']}"},
        )
        require(answer.status_code == 200, f"Assistant returned {answer.status_code}")
        require(answer.json().get("answer") == "Information unavailable", "Assistant leaked cross-institution data")


def client_user_institution_id():
    with SessionLocal() as db:
        return db.query(User).filter(User.email == "institution@approveflow.example.com").one().institution_id


def test_evc_schedule():
    with api() as client:
        body = {
            "scheduled_at": (datetime.utcnow() + timedelta(days=8)).isoformat(),
            "event_type": "site_visit",
            "notes": "E2E scheduled event",
            "reason": "E2E coordinator scheduling",
        }
        path = f"/api/evc/{application_ids['first']}/schedule"
        denied = client.post(path, headers=auth("regional_officer"), json=body)
        require(denied.status_code == 403, f"Unauthorized EVC scheduling returned {denied.status_code}")
        created = client.post(path, headers=auth("evc_coordinator"), json=body)
        require(created.status_code == 201, f"Authorized EVC scheduling returned {created.status_code}: {created.text}")
        listing = client.get("/api/evc", headers=auth("admin"))
        require(listing.status_code == 200 and any(row["id"] == created.json()["id"] for row in listing.json()), "Scheduled EVC event missing from list")


def test_compliance_submission():
    with api() as client:
        listing = client.get("/api/compliance", headers=auth("institution"))
        require(
            listing.status_code == 200
            and any(row["id"] == record_ids["undertaking"] for row in listing.json()),
            f"Compliance list failed: {listing.status_code}",
        )
        path = f"/api/compliance/{record_ids['undertaking']}/submit"
        body = {"reason": "E2E compliance submission"}
        denied = client.post(path, headers=auth("auditor"), json=body)
        require(denied.status_code == 403, f"Unauthorized compliance submit returned {denied.status_code}")
        submitted = client.post(path, headers=auth("institution"), json=body)
        require(submitted.status_code == 200 and submitted.json()["status"] == "submitted", f"Compliance submit failed: {submitted.text}")


def test_escalation_resolution():
    with api() as client:
        listing = client.get("/api/escalations", headers=auth("regional_officer"))
        require(listing.status_code == 200, f"Escalation list returned {listing.status_code}")
        path = f"/api/escalations/{record_ids['escalation']}/resolve"
        body = {"reason": "E2E escalation resolved"}
        denied = client.post(path, headers=auth("institution"), json=body)
        require(denied.status_code == 403, f"Unauthorized escalation resolution returned {denied.status_code}")
        resolved = client.post(path, headers=auth("regional_officer"), json=body)
        require(resolved.status_code == 200 and resolved.json()["status"] == "resolved", f"Escalation resolution failed: {resolved.text}")


def upload(client: httpx.Client, filename: str, data: bytes, content_type: str):
    return client.post(
        "/api/documents/upload",
        headers=auth("institution"),
        data={
            "application_id": str(application_ids["first"]),
            "reason": f"E2E upload {filename}",
            "expires_at": (datetime.utcnow() + timedelta(days=14)).isoformat(),
        },
        files={"file": (filename, data, content_type)},
    )


def test_document_upload_and_download():
    valid_files = [
        ("valid.pdf", b"%PDF-1.7\nE2E PDF body", "application/pdf"),
        ("valid.jpg", b"\xff\xd8\xff\xe0E2E JPEG", "image/jpeg"),
        ("valid.png", b"\x89PNG\r\n\x1a\nE2E PNG", "image/png"),
    ]
    with api() as client:
        listing = client.get("/api/documents", headers=auth("institution"))
        require(listing.status_code == 200, f"Document list returned {listing.status_code}")
        expiring = client.get("/api/documents/expiring", headers=auth("institution"))
        require(expiring.status_code == 200, f"Expiring documents returned {expiring.status_code}")
        for filename, content, content_type in valid_files:
            response = upload(client, filename, content, content_type)
            require(response.status_code == 201, f"Valid {filename} upload returned {response.status_code}: {response.text}")
            if filename == "valid.pdf":
                document_ids["own"] = response.json()["id"]

        bad_extension = upload(client, "payload.exe", b"%PDF-1.7\nbody", "application/pdf")
        require(bad_extension.status_code == 415, f"Wrong extension returned {bad_extension.status_code}")
        fake_type = upload(client, "fake.pdf", b"%PDF-1.7\nbody", "image/png")
        require(fake_type.status_code == 415, f"Fake content type returned {fake_type.status_code}")
        oversized = upload(client, "large.pdf", b"%PDF-" + b"x" * (5 * 1024 * 1024 + 1), "application/pdf")
        require(oversized.status_code == 413, f">5 MB upload returned {oversized.status_code}")

        downloaded = client.get(
            f"/api/documents/{document_ids['own']}/download",
            headers=auth("institution"),
        )
        require(downloaded.status_code == 200 and downloaded.content.startswith(b"%PDF-"), "Authorized download failed")
        denied = client.get(
            f"/api/documents/{document_ids['other']}/download",
            headers=auth("institution"),
        )
        require(denied.status_code in {403, 404}, f"Cross-institution download returned {denied.status_code}")


def test_scheduler_dedup_and_completed_skip():
    now = datetime.utcnow().replace(second=0, microsecond=0)
    with SessionLocal() as db:
        active = db.get(Application, application_ids["scheduler"])
        completed = db.get(Application, application_ids["completed_scheduler"])
        active.status = "in_review"
        active.current_stage = "regional_review"
        active.due_at = now + timedelta(days=3)
        completed.status = "completed"
        completed.current_stage = "completed"
        completed.due_at = now + timedelta(days=3)
        db.query(Notification).filter(
            Notification.application_id.in_([active.id, completed.id]),
            Notification.deduplication_key.is_not(None),
        ).delete(synchronize_session=False)
        db.commit()
        active_id, completed_id = active.id, completed.id

    run_deadline_check()
    run_deadline_check()
    with SessionLocal() as db:
        active_count = db.query(Notification).filter(
            Notification.application_id == active_id,
            Notification.deduplication_key.like("reminder_t_minus_3:%"),
        ).count()
        completed_count = db.query(Notification).filter(
            Notification.application_id == completed_id,
            Notification.deduplication_key.is_not(None),
        ).count()
    require(active_count == 1, f"Expected one deduplicated alert, got {active_count}")
    require(completed_count == 0, f"Completed application received {completed_count} alerts")


def test_audit_role_and_secret_safety():
    with api() as client:
        for role in ("admin", "auditor"):
            response = client.get("/api/audit-logs", headers=auth(role), params={"limit": 500})
            require(response.status_code == 200, f"{role} audit access returned {response.status_code}")
            serialized = response.text.lower()
            require("demo@123" not in serialized and "access_token" not in serialized, "Audit response contains a password/token")
            require(all(token.lower() not in serialized for token in tokens.values()), "Audit response contains an issued token")
        for role in ("institution", "regional_officer", "bureau_officer", "evc_coordinator", "committee"):
            denied = client.get("/api/audit-logs", headers=auth(role))
            require(denied.status_code == 403, f"{role} audit access returned {denied.status_code}")


def test_assistant_categories():
    questions = [
        ("overdue applications", lambda body: isinstance(body.get("data"), list)),
        ("document expiry in the next month", lambda body: isinstance(body.get("data"), list)),
        ("EVC visits", lambda body: isinstance(body.get("data"), list)),
        ("compliance undertakings", lambda body: isinstance(body.get("data"), list)),
        (f"application id {application_ids['first']}", lambda body: body.get("data", {}).get("application_id") == application_ids["first"]),
    ]
    with api() as client:
        for question, validate in questions:
            response = client.post("/api/assistant/ask", headers=auth("admin"), json={"question": question})
            require(response.status_code == 200, f"Assistant question '{question}' returned {response.status_code}")
            body = response.json()
            require(body.get("answer") != "Information unavailable" and validate(body), f"Assistant did not answer '{question}'")
        unknown = client.post(
            "/api/assistant/ask",
            headers=auth("admin"),
            json={"question": "application id 999999999"},
        )
        require(unknown.status_code == 200 and unknown.json()["answer"] == "Information unavailable", "Unknown assistant query guessed")


def test_cors_preflight():
    with api() as client:
        response = client.options(
            "/api/applications",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    require(response.status_code == 200, f"CORS preflight returned {response.status_code}")
    require(
        response.headers.get("access-control-allow-origin") == "http://localhost:5173",
        "CORS did not allow http://localhost:5173",
    )


def test_notifications_and_reports():
    with api() as client:
        notifications = client.get("/api/notifications", headers=auth("admin"))
        require(notifications.status_code == 200 and isinstance(notifications.json(), list), "Notification list failed")
        report = client.get("/api/reports/pendency", headers=auth("admin"))
        require(
            report.status_code == 200
            and {"total_pending", "overdue_pending", "by_stage"} <= report.json().keys(),
            "Pendency report failed or returned an unexpected shape",
        )


def main():
    create_test_records()
    checks = [
        ("Login all seven demo roles; wrong password is 401", test_all_logins),
        ("Dashboard counts match SQLite database", test_dashboard_matches_database),
        ("Applications list/detail/timeline and transition validation/audit", test_applications_and_transition),
        ("Institution application/document/assistant data isolation", test_institution_scope),
        ("EVC schedule authorized and unauthorized role checks", test_evc_schedule),
        ("Compliance submit authorized and unauthorized role checks", test_compliance_submission),
        ("Escalation resolve authorized and unauthorized role checks", test_escalation_resolution),
        ("PDF/JPG/PNG upload, rejection cases, and protected download", test_document_upload_and_download),
        ("Deadline scheduler idempotency and completed application exclusion", test_scheduler_dedup_and_completed_skip),
        ("Audit authorization and password/token absence", test_audit_role_and_secret_safety),
        ("Assistant overdue/expiry/EVC/compliance/application/unknown questions", test_assistant_categories),
        ("Notifications and pendency report", test_notifications_and_reports),
        ("CORS preflight for localhost Vite origin", test_cors_preflight),
    ]
    for name, action in checks:
        check(name, action)
    print(f"\nE2E smoke tests against {BASE_URL}")
    print(f"{'RESULT':<7} | CHECK")
    print("-" * 110)
    for name, result, details in results:
        print(f"{result:<7} | {name}" + (f"\n        {details}" if details else ""))
    passed = sum(result == "PASS" for _, result, _ in results)
    failed = len(results) - passed
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
