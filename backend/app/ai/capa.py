from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.ai.gemini import _generate
from app.ai.schemas import EvidenceReference


class CapaRecommendation(BaseModel):
    action_type: Literal["Corrective", "Preventive"]
    action_description: str
    reason: str
    related_root_cause: str = ""
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    expected_outcome: str
    verification_method: str = ""
    effectiveness_criteria: str = ""


class CapaRecommendations(BaseModel):
    corrective_actions: list[CapaRecommendation] = Field(default_factory=list)
    preventive_actions: list[CapaRecommendation] = Field(default_factory=list)


class CapaState(TypedDict):
    investigation: dict[str, Any]
    recommendations: dict[str, Any]


def recommend_actions(state: CapaState) -> dict[str, Any]:
    data = state["investigation"]
    prompt = f"""Recommend specific corrective and preventive actions for this quality deviation. Use only facts in the investigation below. Each action must clearly relate to an incident finding or potential/reviewer-confirmed root cause. Do not invent supporting evidence; references must be verbatim excerpts or source references in the supplied investigation. If the cause remains uncertain, describe the action as investigation/verification work and say so. Corrective actions address this event; preventive actions reduce recurrence. Keep each list to at most four useful recommendations. These are suggestions only, never approvals.
Investigation JSON: {data}
Return corrective_actions and preventive_actions, each with action_type, action_description, reason, related_root_cause, supporting_evidence, expected_outcome, verification_method, effectiveness_criteria."""
    result = _generate(prompt, CapaRecommendations)
    existing_evidence = data.get("evidence", [])
    known_references = {item.get("source_reference") for item in existing_evidence if item.get("source_reference")}
    known_quotes = {item.get("excerpt") for item in existing_evidence if item.get("excerpt")}
    for item in (data.get("rca") or {}).get("suggestions", []):
        known_references.update(ref.get("source_reference") for ref in item.get("supporting_evidence", []) if ref.get("source_reference"))
        known_quotes.update(ref.get("excerpt") for ref in item.get("supporting_evidence", []) if ref.get("excerpt"))
    def grounded(action: CapaRecommendation, kind: str) -> CapaRecommendation:
        references = [
            reference
            for reference in action.supporting_evidence
            if reference.source_reference in known_references or reference.excerpt in known_quotes
        ]
        return action.model_copy(update={"action_type": kind, "supporting_evidence": references})
    result.corrective_actions = [grounded(item, "Corrective") for item in result.corrective_actions]
    result.preventive_actions = [grounded(item, "Preventive") for item in result.preventive_actions]
    return {"recommendations": result.model_dump(mode="json")}


def build_capa_graph():
    graph = StateGraph(CapaState)
    graph.add_node("Recommend CAPA actions", recommend_actions)
    graph.add_edge(START, "Recommend CAPA actions")
    graph.add_edge("Recommend CAPA actions", END)
    return graph.compile()


capa_graph = build_capa_graph()
