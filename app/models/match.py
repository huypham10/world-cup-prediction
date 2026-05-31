from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .prediction import Prediction
    from .settlement import Settlement


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_kickoff_status", "kickoff_time", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[Optional[str]] = mapped_column(
        String(40), unique=True, index=True, nullable=True
    )
    team_a: Mapped[str] = mapped_column(String(80), nullable=False)
    team_b: Mapped[str] = mapped_column(String(80), nullable=False)
    kickoff_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", index=True
    )
    score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # "A" / "B" / "draw"; null until finished
    result: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # True = settlement done; prevents double-settling
    settled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Relationships
    predictions: Mapped[List["Prediction"]] = relationship(back_populates="match")
    settlements: Mapped[List["Settlement"]] = relationship(back_populates="match")
