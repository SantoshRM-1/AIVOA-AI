from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.capa import CapaAction
    from app.models.evidence import InvestigationEvidence
    from app.models.rca import RootCauseAnalysis


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    deviation_id: Mapped[str] = mapped_column(String(100), unique=True)
    incident_title: Mapped[str] = mapped_column(String(255))
    product_name: Mapped[str] = mapped_column(String(255), default="")
    batch_number: Mapped[str] = mapped_column(String(120), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    manufacturing_stage: Mapped[str] = mapped_column(String(160), default="")
    deviation_category: Mapped[str] = mapped_column(String(160), default="")
    equipment_involved: Mapped[str] = mapped_column(Text, default="")
    incident_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_condition: Mapped[str] = mapped_column(Text, default="")
    actual_condition: Mapped[str] = mapped_column(Text, default="")
    incident_description: Mapped[str] = mapped_column(Text, default="")
    immediate_actions: Mapped[str] = mapped_column(Text, default="")
    potential_quality_impact: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="Open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    evidence: Mapped[list["InvestigationEvidence"]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
    rca: Mapped["RootCauseAnalysis | None"] = relationship(
        back_populates="investigation", cascade="all, delete-orphan", uselist=False
    )
    capa_actions: Mapped[list["CapaAction"]] = relationship(
        back_populates="investigation", cascade="all, delete-orphan"
    )
