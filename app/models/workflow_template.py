from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    stages = relationship("WorkflowStage", back_populates="template", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="workflow_template")
