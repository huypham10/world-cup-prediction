from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Index, Integer, Numeric, String
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
    league_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
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
    # Round info from the football API
    round_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    round_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Bookmaker decimal odds (home / draw / away); null until fetched
    odds_a: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    odds_draw: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    odds_b: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    odds_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Extra time / penalty scores (null when match didn't go to ET/PK)
    et_score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    et_score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pk_score_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pk_score_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Winner after ET/PK for knockout matches; null for group stage or undecided
    final_winner: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Relationships
    predictions: Mapped[List["Prediction"]] = relationship(back_populates="match")
    settlements: Mapped[List["Settlement"]] = relationship(back_populates="match")
