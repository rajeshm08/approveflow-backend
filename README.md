# ApproveFlow AI backend

FastAPI backend for **ApproveFlow AI**, the AICTE Approval Workflow, Compliance & Alert Intelligence Platform (SIH26262). The API uses SQLAlchemy 2.x and Pydantic v2, SQLite by default, and PostgreSQL when `DATABASE_URL` is configured.

## Render and Neon demo deployment

The repository includes `render.yaml` for a free-tier Render web service running Python 3.12. It installs dependencies with `pip install -r requirements.txt`, starts Uvicorn on Render's `$PORT`, and exposes `/health` for health checks. Add a Neon PostgreSQL connection string to Render as `DATABASE_URL`; `postgres://` and `postgresql://` URLs are normalized to the installed psycopg 3 driver while preserving query parameters such as `sslmode=require`.

Set these Render environment variables:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Neon connection string, including `?sslmode=require` |
| `SECRET_KEY` | A unique, long, random secret |
| `ALLOWED_ORIGINS` | Comma-separated frontend origins, for example `https://your-frontend.example` |
| `UPLOAD_DIR` | `/tmp/approveflow-uploads` (also configured in `render.yaml`) |
| `SEED_DEMO_DATA` | `true` to populate a fresh empty database with demo data; `false` to leave it empty |

Startup creates missing tables. When `SEED_DEMO_DATA=true`, the demo seed runs only if the users table is empty; it is not rerun on deployments with existing users. Demo seeding creates demonstration accounts and synthetic data, so enable it only for a demo database. Production startup refuses the default development `SECRET_KEY`.

**Free-tier limitation:** Render free services sleep after inactivity, and uploaded files on the service filesystem are not persistent. This deployment is for demo use only; do not rely on it for production data or durable uploads.

## Setup

1. Use Python 3.11 or newer. From the project directory, create and activate a virtual environment if needed.
2. Install dependencies:

   ```powershell
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set a strong `SECRET_KEY`. By default the app uses `sqlite:///./approveflow.db`. To use PostgreSQL, install a suitable SQLAlchemy PostgreSQL driver and set `DATABASE_URL` (for example `postgresql+psycopg://...`).
4. Seed sample data and run the API:

   ```powershell
   .\venv\Scripts\python.exe seed_demo_data.py
   .\venv\Scripts\python.exe -m uvicorn app.main:app --reload
   ```

   Open `http://127.0.0.1:8000/docs` for interactive API documentation.

The seed script creates seven demo users, 25 synthetic institutions/applications, five regions, a workflow template, and historical stage data. **All demo passwords and data are for local development only.** Seed SLA values are illustrative, not official AICTE deadlines. The database is seeded only when it contains no users or applications. `DEMO_MODE=true` enables the one-minute APScheduler deadline job; turn it off to disable the background scheduler. Deadline alert offsets are illustrative demo values, not official AICTE deadlines.

The seed includes APP-1001 through APP-1025, escalations, notifications, EVC/compliance/document examples, and runs the deadline job once to create deduplicated alerts. To discard the current demo data, clear uploads, and reseed:

```powershell
.\venv\Scripts\python.exe reset_demo.py
```

Confirm the prompt to continue, or use `--yes` for a non-interactive reset. The tool allows the default `approveflow.db` and clearly named `approveflow` demo/E2E SQLite databases. For PostgreSQL or any other database name, it refuses unless `SEED_DEMO_DATA=true` is set in the environment; only set this for a verified, disposable demo database.

Uploaded files are validated by file signature and declared content type, limited to 5 MB, and stored under a random key in a private directory (`UPLOAD_DIR`, default `private_uploads`). This directory is not mounted as a public static path. The deadline scheduler also monitors document validity: the configurable 30/15/7-day reminders, +1-day expired alert, and 3-day escalation grace period are illustrative demo values, not official AICTE rules. Configure them with `DOCUMENT_EXPIRY_ALERT_OFFSETS_DAYS` and `DOCUMENT_EXPIRY_ESCALATION_GRACE_DAYS`.

## Demo logins

Every listed account uses password `Demo@123`.

| Role | Email |
| --- | --- |
| institution | `institution@approveflow.example.com` |
| regional_officer | `regional_officer@approveflow.example.com` |
| bureau_officer | `bureau_officer@approveflow.example.com` |
| evc_coordinator | `evc_coordinator@approveflow.example.com` |
| committee | `committee@approveflow.example.com` |
| admin | `admin@approveflow.example.com` |
| auditor | `auditor@approveflow.example.com` |

## Endpoints

All application routes use `/api`.

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/auth/login` | Authenticate with JSON `email` and `password`; returns bearer JWT and user role/institution |
| GET | `/api/applications` | List applications (institution users see only their own institution) |
| POST | `/api/applications` | Create an application for the authenticated institution user |
| GET | `/api/applications/{id}` | Get an application, scoped to the institution for institution users |
| POST | `/api/applications/{id}/submit` | Submit a draft; JSON body requires a `reason` |
| GET | `/api/applications/{id}/timeline` | Read stage history, scoped to the institution for institution users |
| POST | `/api/applications/{id}/transition` | Transition stages with `expected_current_stage`, `next_stage`, and mandatory `reason` |
| GET | `/api/dashboard/summary` | Database-derived totals, status counts, overdue and upcoming-due counts |
| GET | `/api/audit-logs` | List append-only audit entries (admin and auditor only) |
| GET | `/api/evc` | List EVC events, scoped for institution users |
| POST | `/api/evc/{application_id}/schedule` | Schedule an EVC event; requires `scheduled_at` and audit `reason` |
| GET | `/api/compliance` | List undertaking/compliance records, scoped for institution users |
| POST | `/api/compliance/{compliance_id}/submit` | Submit a compliance record with an audit `reason` |
| GET | `/api/documents` | List accessible document metadata |
| POST | `/api/documents/upload` | Upload a PDF/JPG/PNG as multipart form data (`application_id`, `file`, `reason`, optional `document_type` and `expires_at`) |
| GET | `/api/documents/expiring` | List documents expiring within the selected `days` window |
| GET | `/api/documents/{document_id}/download` | Download a document after access checks |
| GET | `/api/notifications` | List the current user's notifications |
| GET | `/api/escalations` | List escalations, scoped for institution users |
| POST | `/api/escalations/{escalation_id}/resolve` | Resolve an escalation with an audit `reason` |
| GET | `/api/reports/pendency` | Database-derived pending and overdue counts by stage |
| POST | `/api/assistant/ask` | Rule-based database answers for application, overdue, expiry, EVC, and compliance questions |
| GET | `/health` | Liveness check |

Login returns `access_token`; send it on protected requests as `Authorization: Bearer <token>`. CORS origins are configurable with `CORS_ORIGINS` and `FRONTEND_URL`; localhost Vite (`http://localhost:5173`) and the demo Vercel URL are allowed by default.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest
```
