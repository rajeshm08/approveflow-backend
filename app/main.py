from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine, ensure_extension_columns
from app import models  # noqa: F401
from app.routers import (
    applications,
    assistant,
    audit,
    auth,
    compliance,
    dashboard,
    documents,
    escalations,
    evc,
    notifications,
    reports,
)
from app.services.deadlines import start_deadline_scheduler

@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_extension_columns()
    scheduler = start_deadline_scheduler() if settings.demo_mode else None
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(
    title="ApproveFlow AI API",
    description="AICTE approval workflow, compliance, and alert intelligence API.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(applications.router)
app.include_router(dashboard.router)
app.include_router(audit.router)
app.include_router(evc.router)
app.include_router(compliance.router)
app.include_router(documents.router)
app.include_router(notifications.router)
app.include_router(escalations.router)
app.include_router(reports.router)
app.include_router(assistant.router)
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
