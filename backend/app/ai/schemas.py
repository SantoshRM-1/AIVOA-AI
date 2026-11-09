from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FieldStatus = Literal["Extracted", "Uncertain", "Missing", "Conflicting"]
FishboneCategory = Literal[
    "Man / People",
    "Machine / Equipment",
    "Method / Process",
    "Material",
    "Measurement",
    "Mother Nature / Environment",
]
RcaStatus = Literal[
    "Suggested",
    "Needs Investigation",
    "Evidence Supported",
    "Confirmed by Human Reviewer",
    "Rejected",
]


class ExtractedField(BaseModel):
    value: str | None = None
    source_page: int | None = None
    supporting_text: str | None = None
    status: FieldStatus = "Missing"


class EvidenceReference(BaseModel):
    source_page: int | None = None
    source_reference: str | None = None
    excerpt: str | None = None


class AvailableEvidence(BaseModel):
    description: str
    source_reference: str | None = None
    source_page: int | None = None
    excerpt: str | None = None
    available: bool = True


class MissingInformation(BaseModel):
    field_name: str
    reason: str
    suggested_followup: str | None = None


class MissingEvidenceSuggestion(BaseModel):
    description: str
    reason: str
    suggested_source: str | None = None
    status: Literal["Suggested", "Needs Investigation"] = "Suggested"


class IncidentExtraction(BaseModel):
    deviation_id: ExtractedField = Field(default_factory=ExtractedField)
    incident_title: ExtractedField = Field(default_factory=ExtractedField)
    product_api_name: ExtractedField = Field(default_factory=ExtractedField)
    batch_number: ExtractedField = Field(default_factory=ExtractedField)
    department: ExtractedField = Field(default_factory=ExtractedField)
    manufacturing_stage: ExtractedField = Field(default_factory=ExtractedField)
    incident_date: ExtractedField = Field(default_factory=ExtractedField)
    deviation_category: ExtractedField = Field(default_factory=ExtractedField)
    expected_condition: ExtractedField = Field(default_factory=ExtractedField)
    actual_condition: ExtractedField = Field(default_factory=ExtractedField)
    incident_description: ExtractedField = Field(default_factory=ExtractedField)
    immediate_actions: ExtractedField = Field(default_factory=ExtractedField)
    potential_quality_impact: ExtractedField = Field(default_factory=ExtractedField)
    equipment_involved: ExtractedField = Field(default_factory=ExtractedField)
    available_evidence: list[AvailableEvidence] = Field(default_factory=list)
    missing_information: list[MissingInformation] = Field(default_factory=list)


class RootCauseSuggestion(BaseModel):
    cause_description: str
    category: FishboneCategory
    explanation: str
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    verification_question: str
    status: RcaStatus = "Suggested"


class FishboneModelResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    man_people: list[str] = Field(default_factory=list, alias="Man / People")
    machine_equipment: list[str] = Field(default_factory=list, alias="Machine / Equipment")
    method_process: list[str] = Field(default_factory=list, alias="Method / Process")
    material: list[str] = Field(default_factory=list, alias="Material")
    measurement: list[str] = Field(default_factory=list, alias="Measurement")
    mother_nature_environment: list[str] = Field(
        default_factory=list, alias="Mother Nature / Environment"
    )


class RootCauseModelResponse(BaseModel):
    suggestions: list[RootCauseSuggestion] = Field(default_factory=list)
    fishbone: FishboneModelResponse = Field(default_factory=FishboneModelResponse)


class FiveWhyItem(BaseModel):
    question: str
    answer: str | None = None
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    status: Literal["Suggested", "Needs Investigation"] = "Needs Investigation"


class MissingEvidenceResult(BaseModel):
    items: list[MissingEvidenceSuggestion] = Field(default_factory=list)


class RootCauseResult(BaseModel):
    suggestions: list[RootCauseSuggestion] = Field(default_factory=list)
    fishbone: dict[str, list[str]] = Field(default_factory=dict)


class FiveWhysResult(BaseModel):
    items: list[FiveWhyItem] = Field(default_factory=list)


class InvestigationSuggestionsResult(BaseModel):
    missing_evidence: list[MissingEvidenceSuggestion] = Field(default_factory=list)
    root_cause_suggestions: list[RootCauseSuggestion] = Field(default_factory=list)
    fishbone: FishboneModelResponse = Field(default_factory=FishboneModelResponse)
    five_whys: list[FiveWhyItem] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    source_type: Literal["text", "email", "pdf"]
    file_name: str | None = None
    page_count: int | None = None
    extraction: IncidentExtraction
    missing_information: list[MissingInformation]
    missing_evidence: list[MissingEvidenceSuggestion]
    root_cause_suggestions: list[RootCauseSuggestion]
    fishbone: dict[str, list[str]]
    five_whys: list[FiveWhyItem]


class TextAnalysisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    investigation_id: int | None = None


class EmailAnalysisRequest(BaseModel):
    email_content: str = Field(min_length=1, max_length=200_000)
    investigation_id: int | None = None


class RcaRequest(BaseModel):
    source_text: str = Field(min_length=1, max_length=200_000)
    extraction: IncidentExtraction | None = None
    available_evidence: list[AvailableEvidence] = Field(default_factory=list)
    missing_evidence: list[MissingEvidenceSuggestion] = Field(default_factory=list)


class FiveWhysRequest(BaseModel):
    incident_description: str = Field(min_length=1, max_length=200_000)
    extraction: IncidentExtraction | None = None
    available_evidence: list[AvailableEvidence] = Field(default_factory=list)
