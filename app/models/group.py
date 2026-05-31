from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
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
    stake: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Relationships
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    memberships: Mapped[List["Membership"]] = relationship(back_populates="group")
    settlements: Mapped[List["Settlement"]] = relationship(back_populates="group")
