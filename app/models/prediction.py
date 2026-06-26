from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .match import Match
    from .user import User


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("user_id", "match_id", name="uq_prediction_user_match"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id"), index=True, nullable=False
    )
    # "A", "B", or "draw"
    pick: Mapped[str] = mapped_column(String(10), nullable=False)
    # "A" or "B" — knockout final winner prediction; null for group stage or not submitted
    final_pick: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    odds_visible: Mapped[bool] = mapped_column(Boolean, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="predictions")
    match: Mapped["Match"] = relationship(back_populates="predictions")
