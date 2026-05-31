from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .membership import Membership
    from .prediction import Prediction


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    pin_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[List["Membership"]] = relationship(back_populates="user")
    predictions: Mapped[List["Prediction"]] = relationship(back_populates="user")
