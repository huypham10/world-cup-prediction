from __future__ import annotations

from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .group_wager import GroupWager
    from .membership import Membership
    from .settlement import Settlement
    from .user import User


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    join_code: Mapped[str] = mapped_column(
        String(12), unique=True, index=True, nullable=False
    )
    # When True, matches played before a member joined count as a loss for them.
    # When False (default), those matches are simply excluded from their settlement.
    late_join_counts_as_loss: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    memberships: Mapped[List["Membership"]] = relationship(back_populates="group")
    settlements: Mapped[List["Settlement"]] = relationship(back_populates="group")
    wagers: Mapped[List["GroupWager"]] = relationship(back_populates="group")
