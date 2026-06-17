from __future__ import annotations

from sqlalchemy import Boolean
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SiteConfig(Base):
    __tablename__ = "site_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    show_odds: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
