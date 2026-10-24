from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    application_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"), index=True)
    workflow_template_id: Mapped[int] = mapped_column(ForeignKey("workflow_templates.id"))
    program_name: Mapped[str] = mapped_column(String(200))
    application_type: Mapped[str] = mapped_column(String(80), default="new_approval")
    current_stage: Mapped[str] = mapped_column(String(60), default="draft", index=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    institution = relationship("Institution", back_populates="applications")
    workflow_template = relationship("WorkflowTemplate", back_populates="applications")
    stages = relationship("ApplicationStage", back_populates="application", cascade="all, delete-orphan")
