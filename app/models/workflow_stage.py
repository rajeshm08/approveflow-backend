from sqlalchemy import ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class WorkflowStage(Base):
    __tablename__ = "workflow_stages"
    __table_args__ = (UniqueConstraint("template_id", "stage_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("workflow_templates.id"), index=True)
    stage_key: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    sequence: Mapped[int] = mapped_column(Integer)
    allowed_roles: Mapped[list[str]] = mapped_column(JSON)
    next_stage_keys: Mapped[list[str]] = mapped_column(JSON)
    sla_days: Mapped[int] = mapped_column(Integer, default=7)

    template = relationship("WorkflowTemplate", back_populates="stages")
