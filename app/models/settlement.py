from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .group import Group
    from .match import Match
    from .user import User


class Settlement(TimestampMixin, Base):
    __tablename__ = "settlements"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "user_id", "match_id", name="uq_settlement_group_user_match"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    match_id: Mapped[int] = mapped_column(
        ForeignKey("matches.id"), index=True, nullable=False
    )
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)

    # Relationships
    group: Mapped["Group"] = relationship(back_populates="settlements")
    user: Mapped["User"] = relationship()
    match: Mapped["Match"] = relationship(back_populates="settlements")
