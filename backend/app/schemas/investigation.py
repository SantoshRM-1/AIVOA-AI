from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceWrite(BaseModel):
    description: str
    source_reference: str | None = None
    available: bool = True


class EvidenceRead(EvidenceWrite):
    id: int
    file_name: str | None = None
    mime_type: str | None = None
    model_config = ConfigDict(from_attributes=True)


class RootCauseAnalysisWrite(BaseModel):
    five_whys: list[dict[str, Any]] = Field(default_factory=list)
    fishbone: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    extraction_data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_human_review_note(self):
        for suggestion in self.suggestions:
            if suggestion.get("status") in {"Confirmed by Human Reviewer", "Rejected"} and not str(
                suggestion.get("reviewer_note", "")
            ).strip():
                raise ValueError("Confirmed or rejected root causes require a human review explanation.")
        return self


class RootCauseAnalysisRead(RootCauseAnalysisWrite):
    id: int
    model_config = ConfigDict(from_attributes=True)


class InvestigationBase(BaseModel):
    deviation_id: str = Field(min_length=1, max_length=100)
    incident_title: str = Field(min_length=1, max_length=255)
    product_name: str = Field(default="", max_length=255)
    batch_number: str = Field(default="", max_length=120)
    department: str = Field(default="", max_length=120)
    manufacturing_stage: str = Field(default="", max_length=160)
    deviation_category: str = Field(default="", max_length=160)
    equipment_involved: str = ""
    incident_date: date | None = None
    expected_condition: str = ""
    actual_condition: str = ""
    incident_description: str = ""
    immediate_actions: str = ""
    potential_quality_impact: str = ""
    status: str = Field(default="Open", max_length=40)
    evidence: list[EvidenceWrite] = Field(default_factory=list)
    rca: RootCauseAnalysisWrite | None = None


class InvestigationCreate(InvestigationBase):
    pass


class InvestigationUpdate(InvestigationBase):
    pass


class InvestigationRead(InvestigationBase):
    id: int
    created_at: datetime
    updated_at: datetime
    evidence: list[EvidenceRead] = Field(default_factory=list)
    rca: RootCauseAnalysisRead | None = None
    model_config = ConfigDict(from_attributes=True)


class CapaActionWrite(BaseModel):
    action_type: str = Field(pattern="^(Corrective|Preventive)$")
    action_description: str = Field(min_length=1, max_length=10000)
    reason: str = ""
    related_root_cause: str = ""
    responsible_person: str = ""
    due_date: date | None = None
    status: str = Field(default="Proposed", pattern="^(Proposed|Accepted|In Progress|Completed|Rejected)$")
    verification_method: str = ""
    effectiveness_criteria: str = ""
    expected_outcome: str = ""
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)


class CapaActionRead(CapaActionWrite):
    id: int
    investigation_id: int
    model_config = ConfigDict(from_attributes=True)
