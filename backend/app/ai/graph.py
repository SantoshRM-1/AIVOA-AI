from typing import Any, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from app.ai.gemini import (
    AIServiceError,
    extract_incident,
    generate_investigation_suggestions,
)
from app.ai.pdf import PdfInputError, extract_pdf
from app.ai.schemas import AnalysisResponse, IncidentExtraction
from app.core.config import settings


class AnalysisState(TypedDict):
    source_type: Literal["text", "email", "pdf"]
    content: str
    file_bytes: NotRequired[bytes | None]
    file_name: NotRequired[str | None]
    source_text: NotRequired[str]
    pages: NotRequired[list[dict[str, int | str]]]
    page_count: NotRequired[int | None]
    extraction: NotRequired[IncidentExtraction]
    available_evidence: NotRequired[list[dict[str, Any]]]
    missing_information: NotRequired[list[dict[str, Any]]]
    missing_evidence: NotRequired[list[dict[str, Any]]]
    root_cause_suggestions: NotRequired[list[dict[str, Any]]]
    fishbone: NotRequired[dict[str, list[str]]]
    five_whys: NotRequired[list[dict[str, Any]]]
    error: NotRequired[str | None]
    response: NotRequired[dict[str, Any]]


def validate_input(state: AnalysisState) -> dict[str, Any]:
    kind = state.get("source_type")
    if kind not in {"text", "email", "pdf"}:
        return {"error": "Choose incident text, email content, or a PDF document."}
    if kind == "pdf":
        if state.get("source_text") is not None and state.get("pages") is not None:
            if len(state["source_text"]) > settings.max_text_characters:
                return {"error": "Extracted PDF text exceeds the 200,000 character limit."}
            return {
                "error": None,
                "page_count": state.get("page_count", len(state["pages"])),
            }
        data = state.get("file_bytes") or b""
        if not data:
            return {"error": "Choose a non-empty PDF document."}
        if len(data) > settings.max_pdf_bytes:
            return {"error": "PDF documents must be 20 MB or smaller."}
    else:
        content = (state.get("content") or "").strip()
        if not content:
            return {"error": "Incident information cannot be empty."}
        if len(content) > settings.max_text_characters:
            return {"error": "Incident information exceeds the 200,000 character limit."}
        return {"content": content, "source_text": content}
    return {"error": None}


def extract_document_content(state: AnalysisState) -> dict[str, Any]:
    try:
        pdf = extract_pdf(state.get("file_bytes") or b"")
    except PdfInputError as exc:
        return {"error": str(exc)}
    if len(pdf.text) > settings.max_text_characters:
        return {"error": "Extracted PDF text exceeds the 200,000 character limit."}
    return {
        "source_text": pdf.text,
        "pages": pdf.pages,
        "page_count": len(pdf.pages),
        "error": None,
    }


def extract_incident_information(state: AnalysisState) -> dict[str, Any]:
    extraction = extract_incident(
        state.get("source_text", ""), state["source_type"], state.get("page_count")
    )
    return {"extraction": extraction}


def identify_available_evidence(state: AnalysisState) -> dict[str, Any]:
    extraction = state["extraction"]
    evidence = [item.model_dump() for item in extraction.available_evidence]
    return {"available_evidence": evidence}


def identify_missing_information(state: AnalysisState) -> dict[str, Any]:
    extraction = state["extraction"]
    missing = [item.model_dump() for item in extraction.missing_information]
    for field_name in IncidentExtraction.model_fields:
        if field_name in {"available_evidence", "missing_information"}:
            continue
        field = getattr(extraction, field_name)
        if field.status in {"Missing", "Conflicting"}:
            already_listed = any(item["field_name"] == field_name for item in missing)
            if not already_listed:
                reason = (
                    "The source contains conflicting values."
                    if field.status == "Conflicting"
                    else "This information was not present in the supplied source."
                )
                missing.append(
                    {"field_name": field_name, "reason": reason, "suggested_followup": None}
                )
    return {"missing_information": missing}


def generate_investigation_suggestions_node(state: AnalysisState) -> dict[str, Any]:
    result = generate_investigation_suggestions(
        state.get("source_text", ""), state["extraction"]
    )
    return {
        "missing_evidence": [item.model_dump() for item in result.missing_evidence],
        "root_cause_suggestions": [
            item.model_dump() for item in result.root_cause_suggestions
        ],
        "fishbone": result.fishbone.model_dump(
            mode="json", by_alias=True, exclude_defaults=True
        ),
        "five_whys": [item.model_dump() for item in result.five_whys],
    }


def validate_and_return_results(state: AnalysisState) -> dict[str, Any]:
    if state.get("error"):
        return {}
    result = AnalysisResponse(
        source_type=state["source_type"],
        file_name=state.get("file_name"),
        page_count=state.get("page_count"),
        extraction=state["extraction"],
        missing_information=state.get("missing_information", []),
        missing_evidence=state.get("missing_evidence", []),
        root_cause_suggestions=state.get("root_cause_suggestions", []),
        fishbone=state.get("fishbone", {}),
        five_whys=state.get("five_whys", []),
    )
    return {"response": result.model_dump(mode="json")}


def _after_validation(state: AnalysisState) -> str:
    if state.get("error"):
        return "Validate and Return Results"
    if state["source_type"] == "pdf" and state.get("source_text") is None:
        return "Extract Document Content"
    return "Extract Incident Information"


def _after_document(state: AnalysisState) -> str:
    return "Validate and Return Results" if state.get("error") else "Extract Incident Information"


def build_analysis_graph():
    builder = StateGraph(AnalysisState)
    builder.add_node("Validate Input", validate_input)
    builder.add_node("Extract Document Content", extract_document_content)
    builder.add_node("Extract Incident Information", extract_incident_information)
    builder.add_node("Identify Available Evidence", identify_available_evidence)
    builder.add_node("Identify Missing Information", identify_missing_information)
    builder.add_node("Generate Evidence and RCA Suggestions", generate_investigation_suggestions_node)
    builder.add_node("Validate and Return Results", validate_and_return_results)
    builder.add_edge(START, "Validate Input")
    builder.add_conditional_edges(
        "Validate Input",
        _after_validation,
        {
            "Extract Document Content": "Extract Document Content",
            "Extract Incident Information": "Extract Incident Information",
            "Validate and Return Results": "Validate and Return Results",
        },
    )
    builder.add_conditional_edges(
        "Extract Document Content",
        _after_document,
        {
            "Validate and Return Results": "Validate and Return Results",
            "Extract Incident Information": "Extract Incident Information",
        },
    )
    builder.add_edge("Extract Incident Information", "Identify Available Evidence")
    builder.add_edge("Identify Available Evidence", "Identify Missing Information")
    builder.add_edge("Identify Missing Information", "Generate Evidence and RCA Suggestions")
    builder.add_edge("Generate Evidence and RCA Suggestions", "Validate and Return Results")
    builder.add_edge("Validate and Return Results", END)
    return builder.compile()


analysis_graph = build_analysis_graph()


def run_analysis(state: AnalysisState) -> AnalysisResponse:
    result = analysis_graph.invoke(state)
    if result.get("error"):
        raise AIServiceError(422, result["error"])
    return AnalysisResponse.model_validate(result["response"])
