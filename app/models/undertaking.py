from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Undertaking(Base):
    __tablename__ = "undertakings"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    undertaking_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
