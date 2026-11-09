from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from threading import Lock

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.gemini import (
    AIServiceError,
    ensure_configured,
    generate_five_whys,
    generate_rca,
)
from app.ai.graph import AnalysisState, run_analysis
from app.ai.pdf import PdfInputError, extract_pdf
from app.ai.schemas import (
    AnalysisResponse,
    EmailAnalysisRequest,
    FiveWhysRequest,
    FiveWhysResult,
    MissingInformation,
    RcaRequest,
    RootCauseResult,
    TextAnalysisRequest,
)
from app.core.config import settings
from app.database.session import get_db
from app.models import Investigation, InvestigationEvidence, RootCauseAnalysis

router = APIRouter(prefix="/api/v1/ai", tags=["AI analysis"])
_active_investigations: set[int] = set()
_analysis_guard_lock = Lock()


@contextmanager
def _analysis_guard(
    investigation_id: int | None, db: Session | None = None
) -> Generator[None, None, None]:
    if investigation_id is None:
        yield
        return
    with _analysis_guard_lock:
        if investigation_id in _active_investigations:
            raise HTTPException(
                status_code=409,
                detail="Analysis is already running for this investigation. Wait for it to finish.",
            )
        _active_investigations.add(investigation_id)
    connection = None
    lock_acquired = False
    try:
        if db is not None:
            bind = db.get_bind()
            if bind.dialect.name == "postgresql":
                connection = bind.connect()
                lock_acquired = bool(
                    connection.execute(
                        text("SELECT pg_try_advisory_lock(:namespace, :investigation_id)"),
                        {"namespace": 1825641051, "investigation_id": investigation_id},
                    ).scalar_one()
                )
                if not lock_acquired:
                    raise HTTPException(
                        status_code=409,
                        detail="Analysis is already running for this investigation. Wait for it to finish.",
                    )
        yield
    finally:
        try:
            if connection is not None and lock_acquired:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:namespace, :investigation_id)"),
                    {"namespace": 1825641051, "investigation_id": investigation_id},
                )
        finally:
            try:
                if connection is not None:
                    connection.close()
            finally:
                with _analysis_guard_lock:
                    _active_investigations.discard(investigation_id)


def _investigation_or_404(db: Session, investigation_id: int) -> Investigation:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return investigation


def _replace_source_evidence(
    investigation: Investigation,
    *,
    description: str,
    source_reference: str,
    file_name: str | None = None,
    file_content: bytes | None = None,
) -> None:
    investigation.evidence = [
        evidence
        for evidence in investigation.evidence
        if evidence.source_reference != source_reference
        and not (file_name and evidence.file_name == file_name)
    ]
    investigation.evidence.append(
        InvestigationEvidence(
            description=description,
            source_reference=source_reference,
            file_name=file_name,
            mime_type="application/pdf" if file_content is not None else None,
            file_content=file_content,
            available=True,
        )
    )


def _save_source(
    db: Session,
    investigation_id: int | None,
    *,
    source_type: str,
    source_text: str,
    file_name: str | None = None,
    file_content: bytes | None = None,
) -> None:
    if investigation_id is None:
        return
    investigation = _investigation_or_404(db, investigation_id)
    source_reference = file_name or (
        "Email content" if source_type == "email" else "Incident description"
    )
    description = (
        f"Uploaded source document ({len(source_text)} extracted characters)."
        if file_content is not None
        else source_text
    )
    _replace_source_evidence(
        investigation,
        description=description,
        source_reference=source_reference,
        file_name=file_name,
        file_content=file_content,
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="The source could not be saved to the investigation."
        ) from exc


def _save_analysis(db: Session, investigation_id: int | None, result: AnalysisResponse) -> None:
    if investigation_id is None:
        return
    investigation = _investigation_or_404(db, investigation_id)
    extraction = result.extraction
    field_map = {
        "incident_title": "incident_title",
        "product_api_name": "product_name",
        "batch_number": "batch_number",
        "department": "department",
        "manufacturing_stage": "manufacturing_stage",
        "deviation_category": "deviation_category",
        "equipment_involved": "equipment_involved",
        "expected_condition": "expected_condition",
        "actual_condition": "actual_condition",
        "incident_description": "incident_description",
        "immediate_actions": "immediate_actions",
        "potential_quality_impact": "potential_quality_impact",
    }
    for source_key, field_name in field_map.items():
        value = getattr(extraction, source_key).value
        current_value = getattr(investigation, field_name)
        if value and (
            current_value
            in {"", "New investigation", "Email incident report", "PDF incident report"}
            or field_name == "incident_description"
        ):
            setattr(investigation, field_name, value)
    if extraction.deviation_id.value:
        duplicate = db.scalar(
            select(Investigation.id).where(
                Investigation.deviation_id == extraction.deviation_id.value,
                Investigation.id != investigation.id,
            )
        )
        if duplicate:
            extraction.deviation_id.status = "Conflicting"
            conflict = MissingInformation(
                field_name="deviation_id",
                reason="This deviation ID is already assigned to another investigation in the database.",
                suggested_followup="Verify the ID and update it manually before saving.",
            )
            extraction.missing_information.append(conflict)
            result.missing_information.append(conflict)
        else:
            investigation.deviation_id = extraction.deviation_id.value
    date_value = extraction.incident_date.value
    if date_value:
        try:
            investigation.incident_date = date.fromisoformat(date_value)
        except ValueError:
            extraction.incident_date.status = "Uncertain"
    rca_values = {
        "five_whys": [item.model_dump(mode="json") for item in result.five_whys],
        "fishbone": result.fishbone,
        "suggestions": [item.model_dump(mode="json") for item in result.root_cause_suggestions],
        "extraction_data": extraction.model_dump(mode="json"),
    }
    if investigation.rca is None:
        investigation.rca = RootCauseAnalysis(**rca_values)
    else:
        for key, value in rca_values.items():
            setattr(investigation.rca, key, value)

    # Refresh machine-generated evidence rows for repeat analyses while preserving uploaded source files.
    investigation.evidence = [
        evidence
        for evidence in investigation.evidence
        if evidence.file_content is not None
        or evidence.source_reference in {result.file_name, "Incident description", "Email content"}
    ]
    for item in result.extraction.available_evidence:
        investigation.evidence.append(
            InvestigationEvidence(
                description=item.description,
                source_reference=item.source_reference
                or (f"Page {item.source_page}" if item.source_page else None),
                available=True,
            )
        )
    for item in result.missing_evidence:
        investigation.evidence.append(
            InvestigationEvidence(
                description=f"Suggested evidence: {item.description} — {item.reason}",
                source_reference=item.suggested_source,
                available=False,
            )
        )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503, detail="AI results could not be saved to the investigation."
        ) from exc


def _analyze_and_persist(
    state: AnalysisState, db: Session, investigation_id: int | None
) -> AnalysisResponse:
    try:
        ensure_configured()
        result = run_analysis(state)
        _save_analysis(db, investigation_id, result)
        return result
    except AIServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/health")
def ai_health() -> dict[str, str | bool]:
    key_configured = bool(settings.gemini_api_key.strip())
    model_configured = bool(settings.gemini_model.strip())
    configured = key_configured and model_configured
    issue = (
        "Missing GEMINI_API_KEY."
        if not key_configured
        else "Missing GEMINI_MODEL."
        if not model_configured
        else ""
    )
    return {
        "status": "configured" if configured else "configuration_error",
        "gemini_configured": configured,
        "gemini_api_key_configured": key_configured,
        "gemini_model_configured": model_configured,
        "gemini_model": settings.gemini_model.strip(),
        "configuration_issue": issue,
        "provider_validation": "not_checked",
    }


@router.post("/analyze-text", response_model=AnalysisResponse)
def analyze_text(payload: TextAnalysisRequest, db: Session = Depends(get_db)) -> AnalysisResponse:
    with _analysis_guard(payload.investigation_id, db):
        _save_source(
            db,
            payload.investigation_id,
            source_type="text",
            source_text=payload.text,
        )
        state: AnalysisState = {"source_type": "text", "content": payload.text}
        return _analyze_and_persist(state, db, payload.investigation_id)


@router.post("/analyze-email", response_model=AnalysisResponse)
def analyze_email(payload: EmailAnalysisRequest, db: Session = Depends(get_db)) -> AnalysisResponse:
    with _analysis_guard(payload.investigation_id, db):
        _save_source(
            db,
            payload.investigation_id,
            source_type="email",
            source_text=payload.email_content,
        )
        state: AnalysisState = {"source_type": "email", "content": payload.email_content}
        return _analyze_and_persist(state, db, payload.investigation_id)


@router.post("/analyze-document", response_model=AnalysisResponse)
def analyze_document(
    file: UploadFile = File(...),
    investigation_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
) -> AnalysisResponse:
    with _analysis_guard(investigation_id, db):
        file_name = (file.filename or "incident-report.pdf").replace("\\", "/").split("/")[-1][:255]
        if not file_name:
            file_name = "incident-report.pdf"
        if not file_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Upload a PDF document.")
        data = file.file.read(settings.max_pdf_bytes + 1)
        if len(data) > settings.max_pdf_bytes:
            raise HTTPException(status_code=413, detail="PDF documents must be 20 MB or smaller.")
        try:
            pdf = extract_pdf(data)
        except PdfInputError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _save_source(
            db,
            investigation_id,
            source_type="pdf",
            source_text=pdf.text,
            file_name=file_name,
            file_content=data,
        )
        state: AnalysisState = {
            "source_type": "pdf",
            "content": "",
            "source_text": pdf.text,
            "pages": pdf.pages,
            "page_count": len(pdf.pages),
            "file_name": file_name,
        }
        return _analyze_and_persist(state, db, investigation_id)


@router.post("/investigations/{investigation_id}/retry-analysis", response_model=AnalysisResponse)
def retry_analysis(
    investigation_id: int, db: Session = Depends(get_db)
) -> AnalysisResponse:
    with _analysis_guard(investigation_id, db):
        investigation = _investigation_or_404(db, investigation_id)
        uploaded_pdf = max(
            (item for item in investigation.evidence if item.file_content is not None),
            key=lambda item: item.id or 0,
            default=None,
        )
        if uploaded_pdf is not None:
            data = uploaded_pdf.file_content or b""
            if len(data) > settings.max_pdf_bytes:
                raise HTTPException(
                    status_code=413, detail="The saved PDF exceeds the 20 MB analysis limit."
                )
            try:
                pdf = extract_pdf(data)
            except PdfInputError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            state: AnalysisState = {
                "source_type": "pdf",
                "content": "",
                "source_text": pdf.text,
                "pages": pdf.pages,
                "page_count": len(pdf.pages),
                "file_name": uploaded_pdf.file_name,
            }
        else:
            saved_source = min(
                (
                    item
                    for item in investigation.evidence
                    if item.source_reference in {"Incident description", "Email content"}
                    and item.file_content is None
                ),
                key=lambda item: item.id or 0,
                default=None,
            )
            if saved_source is None:
                raise HTTPException(
                    status_code=404,
                    detail="No saved incident source was found. Upload or enter the source again.",
                )
            source_type = (
                "email" if saved_source.source_reference == "Email content" else "text"
            )
            state = {"source_type": source_type, "content": saved_source.description}
        return _analyze_and_persist(state, db, investigation_id)


@router.post("/rca", response_model=RootCauseResult)
def rca_suggestions(payload: RcaRequest) -> RootCauseResult:
    try:
        return generate_rca(
            payload.source_text,
            payload.extraction,
            [item.model_dump(mode="json") for item in payload.available_evidence],
            [item.model_dump(mode="json") for item in payload.missing_evidence],
        )
    except AIServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/five-whys", response_model=FiveWhysResult)
def five_whys(payload: FiveWhysRequest) -> FiveWhysResult:
    try:
        return generate_five_whys(
            payload.incident_description,
            payload.extraction,
            [item.model_dump(mode="json") for item in payload.available_evidence],
        )
    except AIServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
