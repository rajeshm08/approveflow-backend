from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    region: Mapped[str] = mapped_column(String(100), index=True)
    state: Mapped[str] = mapped_column(String(100))

    users = relationship("User", back_populates="institution")
    applications = relationship("Application", back_populates="institution")
