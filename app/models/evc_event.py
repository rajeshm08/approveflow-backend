from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EVCEvent(Base):
    __tablename__ = "evc_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
