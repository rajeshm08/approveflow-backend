from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), index=True)
    institution_id: Mapped[int | None] = mapped_column(ForeignKey("institutions.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    institution = relationship("Institution", back_populates="users")
