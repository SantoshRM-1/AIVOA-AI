from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Response, status
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.capa import capa_graph
from app.ai.gemini import AIServiceError
from app.database.session import get_db
from app.models import CapaAction, Investigation, InvestigationEvidence, RootCauseAnalysis
from app.schemas import (
    CapaActionRead,
    CapaActionWrite,
    InvestigationCreate,
    InvestigationRead,
    InvestigationUpdate,
)

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard/metrics")
def dashboard_metrics(db: Session = Depends(get_db)) -> dict[str, int]:
    pending_capa_actions = db.scalar(
        select(func.count(CapaAction.id)).where(
            CapaAction.status.in_(("Proposed", "Accepted", "In Progress"))
        )
    )
    return {"pending_capa_actions": pending_capa_actions or 0}


@router.post(
    "/investigations", response_model=InvestigationRead, status_code=status.HTTP_201_CREATED
)
def create_investigation(payload: InvestigationCreate, db: Session = Depends(get_db)):
    data = payload.model_dump(exclude={"evidence", "rca"})
    investigation = Investigation(**data)
    investigation.evidence = [
        InvestigationEvidence(**item.model_dump()) for item in payload.evidence
    ]
    if payload.rca:
        investigation.rca = RootCauseAnalysis(**payload.rca.model_dump())
    db.add(investigation)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An investigation with this deviation ID already exists."
        ) from exc
    db.refresh(investigation)
    return investigation


@router.get("/investigations", response_model=list[InvestigationRead])
def list_investigations(db: Session = Depends(get_db)):
    return db.scalars(select(Investigation).order_by(Investigation.updated_at.desc())).all()


@router.get("/investigations/{investigation_id}", response_model=InvestigationRead)
def get_investigation(investigation_id: int, db: Session = Depends(get_db)):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return investigation


@router.put("/investigations/{investigation_id}", response_model=InvestigationRead)
def update_investigation(
    investigation_id: int, payload: InvestigationUpdate, db: Session = Depends(get_db)
):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    for key, value in payload.model_dump(exclude={"evidence", "rca"}).items():
        setattr(investigation, key, value)
    uploaded_files = [item for item in investigation.evidence if item.file_content is not None]
    investigation.evidence = uploaded_files + [
        InvestigationEvidence(**item.model_dump()) for item in payload.evidence
    ]
    if payload.rca is None:
        investigation.rca = None
    elif investigation.rca is None:
        investigation.rca = RootCauseAnalysis(**payload.rca.model_dump())
    else:
        for key, value in payload.rca.model_dump().items():
            setattr(investigation.rca, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An investigation with this deviation ID already exists."
        ) from exc
    db.refresh(investigation)
    return investigation


@router.get("/investigations/{investigation_id}/capa", response_model=list[CapaActionRead])
def list_capa(investigation_id: int, db: Session = Depends(get_db)):
    if db.get(Investigation, investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    return db.scalars(select(CapaAction).where(CapaAction.investigation_id == investigation_id).order_by(CapaAction.id)).all()


@router.post("/investigations/{investigation_id}/capa", response_model=CapaActionRead, status_code=201)
def create_capa(investigation_id: int, payload: CapaActionWrite, db: Session = Depends(get_db)):
    if db.get(Investigation, investigation_id) is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    action = CapaAction(investigation_id=investigation_id, **payload.model_dump())
    db.add(action)
    try:
        db.commit()
        db.refresh(action)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="CAPA action could not be saved. Check the database connection.") from exc
    return action


@router.put("/capa/{action_id}", response_model=CapaActionRead)
def update_capa(action_id: int, payload: CapaActionWrite, db: Session = Depends(get_db)):
    action = db.get(CapaAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="CAPA action not found.")
    for key, value in payload.model_dump().items():
        setattr(action, key, value)
    try:
        db.commit()
        db.refresh(action)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="CAPA action could not be updated. Check the database connection.") from exc
    return action


@router.delete("/capa/{action_id}", status_code=204)
def delete_capa(action_id: int, db: Session = Depends(get_db)):
    action = db.get(CapaAction, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="CAPA action not found.")
    db.delete(action)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="CAPA action could not be deleted. Check the database connection.") from exc
    return Response(status_code=204)


@router.post("/investigations/{investigation_id}/capa/recommendations")
def recommend_capa(investigation_id: int, db: Session = Depends(get_db)):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    data = {
        "deviation_id": investigation.deviation_id, "incident_title": investigation.incident_title,
        "product_name": investigation.product_name, "batch_number": investigation.batch_number,
        "incident_description": investigation.incident_description, "expected_condition": investigation.expected_condition,
        "actual_condition": investigation.actual_condition, "immediate_actions": investigation.immediate_actions,
        "potential_quality_impact": investigation.potential_quality_impact,
        "evidence": [{"description": e.description, "source_reference": e.source_reference, "available": e.available} for e in investigation.evidence],
        "rca": {"five_whys": investigation.rca.five_whys, "fishbone": investigation.rca.fishbone,
                "suggestions": investigation.rca.suggestions} if investigation.rca else None,
    }
    try:
        return capa_graph.invoke({"investigation": data})["recommendations"]
    except AIServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get("/investigations/{investigation_id}/report")
def investigation_report(investigation_id: int, db: Session = Depends(get_db)):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found.")
    actions = db.scalars(select(CapaAction).where(CapaAction.investigation_id == investigation_id).order_by(CapaAction.id)).all()
    story = []
    styles = getSampleStyleSheet()
    def section(title, value):
        story.extend([Paragraph(title, styles["Heading2"]), Paragraph(str(value or "Not recorded").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>"), styles["BodyText"]), Spacer(1, 8)])
    story.append(Paragraph("AIVOA Investigation Report", styles["Title"]))
    section("Investigation ID and title", f"{investigation.deviation_id} — {investigation.incident_title}")
    section("Deviation details", f"Product: {investigation.product_name}; Batch: {investigation.batch_number}; Department: {investigation.department}<br/>Description: {investigation.incident_description}<br/>Expected: {investigation.expected_condition}<br/>Actual: {investigation.actual_condition}")
    section("Extracted information", investigation.rca.extraction_data if investigation.rca else {})
    section("Evidence summary", [{"description": e.description, "source": e.source_reference, "available": e.available} for e in investigation.evidence])
    section("Five Whys analysis", investigation.rca.five_whys if investigation.rca else [])
    section("Fishbone analysis", investigation.rca.fishbone if investigation.rca else {})
    suggestions = investigation.rca.suggestions if investigation.rca else []
    section("Potential and reviewer-confirmed root causes", suggestions)
    def action_summary(action: CapaAction) -> dict[str, object]:
        return {
            "Action": action.action_description,
            "Reason": action.reason,
            "Related root cause": action.related_root_cause,
            "Responsible person": action.responsible_person,
            "Due date": action.due_date.isoformat() if action.due_date else "",
            "Status": action.status,
            "Expected outcome": action.expected_outcome,
            "Verification method": action.verification_method,
            "Effectiveness criteria": action.effectiveness_criteria,
            "Supporting evidence": action.supporting_evidence,
        }

    section(
        "Corrective actions",
        [action_summary(action) for action in actions if action.action_type == "Corrective"],
    )
    section(
        "Preventive actions",
        [action_summary(action) for action in actions if action.action_type == "Preventive"],
    )
    section("Human review notes", [{"cause": s.get("cause_description"), "status": s.get("status"), "reviewer_note": s.get("reviewer_note", "")} for s in suggestions if s.get("status") in {"Confirmed by Human Reviewer", "Rejected"}])
    output = BytesIO()
    SimpleDocTemplate(output, pagesize=letter, title=f"Investigation {investigation.deviation_id}").build(story)
    return Response(output.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="investigation-{investigation.id}-report.pdf"'})
