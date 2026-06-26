from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .group import Group

# Canonical round order — must match _round_label() in scoreboard router
TOURNAMENT_ROUNDS = [
    "Group Stage",
    "Round of 32",
    "Round of 16",
    "Quarterfinals",
    "Semifinals",
    "Match for 3rd place",
    "Final",
]


class GroupWager(Base, TimestampMixin):
    __tablename__ = "group_wagers"
    __table_args__ = (
        UniqueConstraint("group_id", "round_name", name="uq_group_wager_round"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id"), nullable=False, index=True
    )
    round_name: Mapped[str] = mapped_column(String(50), nullable=False)
    win_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    loss_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    # Separate wager for the final winner prediction (knockout rounds only)
    final_win_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    final_loss_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    group: Mapped["Group"] = relationship(back_populates="wagers")
