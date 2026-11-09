from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.investigation import Investigation


class RootCauseAnalysis(Base):
    __tablename__ = "root_cause_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), unique=True
    )
    five_whys: Mapped[list[Any]] = mapped_column(JSON, default=list)
    fishbone: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    suggestions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    extraction_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    investigation: Mapped["Investigation"] = relationship(back_populates="rca")
