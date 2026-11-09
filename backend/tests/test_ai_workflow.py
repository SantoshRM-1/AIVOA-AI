from io import BytesIO
from types import SimpleNamespace

import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.genai import errors as gemini_errors
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.datastructures import UploadFile

from app.ai import gemini
from app.ai.capa import CapaRecommendations
from app.ai.graph import run_analysis
from app.ai.pdf import PdfInputError, extract_pdf
from app.ai.schemas import (
    IncidentExtraction,
    InvestigationSuggestionsResult,
    RootCauseModelResponse,
    RootCauseSuggestion,
)
from app.api import ai as ai_api
from app.api.router import (
    create_capa,
    dashboard_metrics,
    investigation_report,
    list_capa,
    update_capa,
    update_investigation,
)
from app.core.config import settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models import CapaAction, Investigation, InvestigationEvidence, RootCauseAnalysis
from app.schemas.investigation import CapaActionWrite, InvestigationUpdate, RootCauseAnalysisWrite


def pdf_bytes(text: str | None = None) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    result = document.tobytes()
    document.close()
    return result


def extraction(**updates) -> IncidentExtraction:
    value = IncidentExtraction(
        deviation_id={
            "value": "DEV-FICTIONAL-001",
            "status": "Extracted",
            "supporting_text": "Deviation ID: DEV-FICTIONAL-001",
        },
        incident_title={
            "value": "Impeller speed excursion",
            "status": "Extracted",
            "supporting_text": "records 26 rpm",
        },
        actual_condition={
            "value": "26 rpm for approximately 90 seconds",
            "status": "Extracted",
            "supporting_text": "records 26 rpm for approximately 90 seconds",
        },
        batch_number={
            "value": "LOT-TRAIN-2401",
            "status": "Extracted",
            "supporting_text": "Batch: LOT-TRAIN-2401",
        },
        available_evidence=[
            {
                "description": "Batch record",
                "source_reference": "Page 1",
                "source_page": 1,
                "excerpt": "records 26 rpm",
            }
        ],
    )
    data = value.model_dump()
    data.update(updates)
    return IncidentExtraction.model_validate(data)


def install_graph_mocks(monkeypatch, source_text: str):
    captured = {}

    def extract(text, source_type, page_count):
        captured["source_type"] = source_type
        captured["text"] = text
        return extraction()

    monkeypatch.setattr("app.ai.graph.extract_incident", extract)

    def generate_suggestions(text, info):
        captured["suggestion_calls"] = captured.get("suggestion_calls", 0) + 1
        captured["suggestion_extraction"] = info
        return InvestigationSuggestionsResult()

    monkeypatch.setattr("app.ai.graph.generate_investigation_suggestions", generate_suggestions)
    return captured


def install_gemini_client(monkeypatch, outcomes):
    calls = []
    client_options = []

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    class Client:
        def __init__(self, **kwargs):
            client_options.append(kwargs)
            self.models = Models()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(gemini.genai, "Client", Client)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key-not-a-real-secret")
    monkeypatch.setattr(settings, "gemini_model", "models/gemini-test")
    return calls, client_options


def test_pdf_extraction_preserves_page_numbers():
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "first page evidence")
    document.new_page().insert_text((72, 72), "second page evidence")
    data = document.tobytes()
    document.close()
    result = extract_pdf(data)
    assert result.pages == [
        {"page_number": 1, "text": "first page evidence"},
        {"page_number": 2, "text": "second page evidence"},
    ]
    assert "[Page 2]" in result.text


def test_invalid_pdf_is_rejected():
    with pytest.raises(PdfInputError, match="valid PDF"):
        extract_pdf(b"not a pdf")


def test_text_only_pdf_is_reported_without_claiming_ocr():
    with pytest.raises(PdfInputError, match="not OCR processed"):
        extract_pdf(pdf_bytes())


@pytest.mark.parametrize("source_type", ["text", "email"])
def test_langgraph_executes_text_and_email_paths(monkeypatch, source_type):
    source = "Fictional deviation: recorded speed was 26 rpm."
    captured = install_graph_mocks(monkeypatch, source)
    result = run_analysis({"source_type": source_type, "content": source})
    assert result.source_type == source_type
    assert captured["source_type"] == source_type
    assert captured["text"] == source


def test_langgraph_extracts_pdf_content_before_model(monkeypatch):
    source = "Fictional deviation: 26 rpm."
    captured = install_graph_mocks(monkeypatch, source)
    result = run_analysis(
        {
            "source_type": "pdf",
            "content": "",
            "file_bytes": pdf_bytes(source),
            "file_name": "fixture.pdf",
        }
    )
    assert result.page_count == 1
    assert result.file_name == "fixture.pdf"
    assert captured["source_type"] == "pdf"
    assert "[Page 1]" in captured["text"]


def test_langgraph_runs_one_extraction_and_one_combined_suggestion_stage(monkeypatch):
    source = "Fictional deviation: recorded speed was 26 rpm."
    captured = install_graph_mocks(monkeypatch, source)

    response = run_analysis({"source_type": "text", "content": source})

    assert response.source_type == "text"
    assert captured["text"] == source
    assert captured["suggestion_calls"] == 1
    assert captured["suggestion_extraction"].actual_condition.value == "26 rpm for approximately 90 seconds"


def test_langgraph_routes_empty_text_to_validation_result():
    with pytest.raises(gemini.AIServiceError, match="cannot be empty"):
        run_analysis({"source_type": "text", "content": "   "})


def test_missing_information_and_conflicts_are_retained(monkeypatch):
    conflicted = extraction(
        batch_number={"value": None, "status": "Conflicting"},
        department={"value": None, "status": "Missing"},
    )
    monkeypatch.setattr("app.ai.graph.extract_incident", lambda *args: conflicted)
    monkeypatch.setattr(
        "app.ai.graph.generate_investigation_suggestions",
        lambda *args: InvestigationSuggestionsResult(),
    )
    response = run_analysis({"source_type": "text", "content": "Fictional event details"})
    gaps = {gap.field_name: gap.reason for gap in response.missing_information}
    assert "batch_number" in gaps and "conflicting" in gaps["batch_number"].lower()
    assert "department" in gaps


def test_structured_extraction_rejects_invalid_status():
    with pytest.raises(ValueError):
        IncidentExtraction(deviation_id={"value": "x", "status": "Verified"})


def test_supporting_excerpt_must_match_source():
    item = extraction()
    checked = gemini.validate_extraction_references(item, "A different source", None)
    assert checked.deviation_id.supporting_text is None
    assert checked.deviation_id.status == "Uncertain"


def test_page_references_must_match_the_same_pdf_page():
    source = "[Page 1]\nfirst-page text\n\n[Page 2]\nsecond-page text"
    assert gemini.reference_is_grounded({"source_page": 2, "excerpt": "second-page text"}, source)
    assert not gemini.reference_is_grounded(
        {"source_page": 1, "excerpt": "second-page text"}, source
    )


def test_fishbone_category_validation():
    with pytest.raises(ValueError):
        RootCauseSuggestion(
            cause_description="Unsupported category",
            category="Operator process",
            explanation="test",
            verification_question="What evidence?",
        )


def test_gemini_rca_and_capa_schemas_avoid_unsupported_dynamic_objects():
    def contains_additional_properties(value):
        if isinstance(value, dict):
            return "additionalProperties" in value or any(
                contains_additional_properties(item) for item in value.values()
            )
        if isinstance(value, list):
            return any(contains_additional_properties(item) for item in value)
        return False

    assert not contains_additional_properties(RootCauseModelResponse.model_json_schema())
    assert not contains_additional_properties(CapaRecommendations.model_json_schema())
    assert not contains_additional_properties(InvestigationSuggestionsResult.model_json_schema())


def test_generate_rca_maps_model_fishbone_to_frontend_categories(monkeypatch):
    response = RootCauseModelResponse(
        fishbone={"Man / People": ["Training record requires review."]}
    )
    monkeypatch.setattr(gemini, "_generate", lambda prompt, schema: response)

    result = gemini.generate_rca("A synthetic training incident.")

    assert result.fishbone == {"Man / People": ["Training record requires review."]}


def test_combined_suggestion_prompt_uses_extracted_quotes_not_repeated_source(monkeypatch):
    prompts = []
    monkeypatch.setattr(
        gemini,
        "_generate",
        lambda prompt, schema: prompts.append(prompt) or schema(),
    )
    original_source = "RAW-PDF-CONTENT-SHOULD-NOT-BE-SENT-AGAIN"

    result = gemini.generate_investigation_suggestions(original_source, extraction())

    assert len(prompts) == 1
    assert "records 26 rpm" in prompts[0]
    assert original_source not in prompts[0]
    assert result.root_cause_suggestions == []
    assert result.five_whys == []


def test_five_whys_only_marks_grounded_answer_suggested(monkeypatch):
    item = {
        "question": "Why did the speed exceed the instruction?",
        "answer": "The record shows 26 rpm.",
        "supporting_evidence": [
            {"source_page": None, "source_reference": None, "excerpt": "record shows 26 rpm"}
        ],
        "status": "Suggested",
    }
    monkeypatch.setattr(gemini, "_generate", lambda prompt, schema: schema(items=[item]))
    result = gemini.generate_five_whys("The record shows 26 rpm.")
    assert result.items[0].status == "Suggested"
    monkeypatch.setattr(
        gemini,
        "_generate",
        lambda prompt, schema: schema(
            items=[
                {
                    **item,
                    "supporting_evidence": [
                        {"excerpt": "not present", "source_page": None, "source_reference": None}
                    ],
                }
            ]
        ),
    )
    result = gemini.generate_five_whys("The record shows 26 rpm.")
    assert result.items[0].status == "Needs Investigation"
    assert result.items[0].supporting_evidence == []


def test_root_cause_with_unverified_evidence_is_not_supported(monkeypatch):
    suggestion = RootCauseSuggestion(
        cause_description="Possible control panel issue",
        category="Machine / Equipment",
        explanation="The report mentions a reset.",
        verification_question="What do the maintenance logs show?",
        status="Evidence Supported",
        supporting_evidence=[],
    )
    monkeypatch.setattr(
        gemini, "_generate", lambda prompt, schema: schema(suggestions=[suggestion], fishbone={})
    )
    result = gemini.generate_rca("The source reports a reset.")
    assert result.suggestions[0].status == "Needs Investigation"


def test_ai_never_marks_a_root_cause_human_confirmed(monkeypatch):
    suggestion = RootCauseSuggestion(
        cause_description="Potential controller issue",
        category="Machine / Equipment",
        explanation="This is an AI hypothesis.",
        verification_question="What does the maintenance record show?",
        status="Confirmed by Human Reviewer",
    )
    monkeypatch.setattr(
        gemini,
        "_generate",
        lambda prompt, schema: schema(
            suggestions=[suggestion], fishbone={"Invalid category": ["guess"]}
        ),
    )
    result = gemini.generate_rca("No supporting records were supplied.")
    assert result.suggestions[0].status == "Suggested"
    assert result.fishbone == {}


def test_missing_gemini_key_is_a_clear_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "gemini_model", "gemini-test")
    with pytest.raises(gemini.AIServiceError, match="GEMINI_API_KEY") as error:
        gemini.ensure_configured()
    assert error.value.status_code == 503


def test_gemini_structured_analysis_uses_configured_model_and_timeout(monkeypatch):
    calls, client_options = install_gemini_client(
        monkeypatch, [SimpleNamespace(parsed=extraction(), text=None)]
    )
    monkeypatch.setattr(settings, "ai_request_timeout_seconds", 23)

    result = gemini._generate("synthetic incident", IncidentExtraction)

    assert result.deviation_id.value == "DEV-FICTIONAL-001"
    assert calls[0]["model"] == "models/gemini-test"
    assert client_options[0]["http_options"].timeout == 23_000
    assert client_options[0]["http_options"].retry_options.attempts == 1
    assert calls[0]["config"].response_mime_type == "application/json"


def test_combined_suggestion_schema_is_accepted_by_the_gemini_sdk(monkeypatch):
    calls, _ = install_gemini_client(
        monkeypatch, [SimpleNamespace(parsed=InvestigationSuggestionsResult(), text=None)]
    )

    result = gemini._generate("synthetic extracted facts", InvestigationSuggestionsResult)

    assert result == InvestigationSuggestionsResult()
    assert calls[0]["config"].response_schema is InvestigationSuggestionsResult


def test_gemini_errors_are_sanitized(monkeypatch):
    class BrokenModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("provider returned credential=secret-value")

    class BrokenClient:
        models = BrokenModels()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test-model")
    monkeypatch.setattr(gemini.genai, "Client", lambda **kwargs: BrokenClient())
    with pytest.raises(gemini.AIServiceError) as error:
        gemini._generate("test", IncidentExtraction)
    assert "secret-value" not in error.value.detail


def test_gemini_rate_limit_is_reported_without_provider_details(monkeypatch, caplog):
    calls, _ = install_gemini_client(
        monkeypatch,
        [
            gemini_errors.APIError(
                429,
                {
                    "error": {
                        "message": (
                            "You exceeded your current quota, please check your plan and billing "
                            "details. Quota exceeded for metric: "
                            "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
                            "limit: 20, model: gemini-2.5-flash, description: Generate content "
                            "requests per day limit exceeded. Please retry in 20h56m52s."
                        )
                    }
                },
            )
        ],
    )
    monkeypatch.setattr(settings, "gemini_max_retries", 2)

    with pytest.raises(gemini.AIServiceError) as error:
        gemini._generate("sensitive incident text", IncidentExtraction)
    assert error.value.status_code == 429
    assert error.value.category == "quota_exhausted"
    assert "not a temporary rate limit" in error.value.detail
    assert len(calls) == 1
    assert "category=quota_exhausted status=429" in caplog.text
    assert "quota_metric=generativelanguage.googleapis.com/generate_content_free_tier_requests" in caplog.text
    assert "test-key-not-a-real-secret" not in caplog.text
    assert "sensitive incident text" not in caplog.text


def test_gemini_timeout_is_reported_clearly(monkeypatch):
    import httpx

    install_gemini_client(monkeypatch, [httpx.ReadTimeout("private timeout detail")])
    monkeypatch.setattr(settings, "gemini_max_retries", 0)
    with pytest.raises(gemini.AIServiceError) as error:
        gemini._generate("test", IncidentExtraction)
    assert error.value.status_code == 504
    assert "private" not in error.value.detail


def test_gemini_retries_transient_service_error_then_succeeds(monkeypatch):
    calls, _ = install_gemini_client(
        monkeypatch,
        [
            gemini_errors.APIError(503, {"error": {"message": "service unavailable"}}),
            SimpleNamespace(parsed=extraction(), text=None),
        ],
    )
    sleeps = []
    monkeypatch.setattr(settings, "gemini_max_retries", 2)
    monkeypatch.setattr(gemini.random, "uniform", lambda _start, _end: 0.1)
    monkeypatch.setattr(gemini.time, "sleep", sleeps.append)

    result = gemini._generate("synthetic incident", IncidentExtraction)

    assert result.deviation_id.value == "DEV-FICTIONAL-001"
    assert len(calls) == 2
    assert sleeps == [0.1]


def test_gemini_respects_retry_after_header(monkeypatch):
    retry_error = gemini_errors.APIError(
        429,
        {"error": {"message": "rate limit reached"}},
        response=SimpleNamespace(headers={"Retry-After": "0.25"}),
    )
    calls, _ = install_gemini_client(
        monkeypatch, [retry_error, SimpleNamespace(parsed=extraction(), text=None)]
    )
    sleeps = []
    monkeypatch.setattr(settings, "gemini_max_retries", 1)
    monkeypatch.setattr(settings, "gemini_max_retry_wait_seconds", 1)
    monkeypatch.setattr(gemini.time, "sleep", sleeps.append)

    gemini._generate("synthetic incident", IncidentExtraction)

    assert len(calls) == 2
    assert sleeps == [0.25]


def test_gemini_retry_count_is_bounded(monkeypatch):
    calls, _ = install_gemini_client(
        monkeypatch,
        [gemini_errors.APIError(503, {"error": {"message": "unavailable"}}) for _ in range(4)],
    )
    monkeypatch.setattr(settings, "gemini_max_retries", 2)
    monkeypatch.setattr(gemini.random, "uniform", lambda _start, _end: 0)
    monkeypatch.setattr(gemini.time, "sleep", lambda _delay: None)

    with pytest.raises(gemini.AIServiceError) as error:
        gemini._generate("synthetic incident", IncidentExtraction)

    assert error.value.status_code == 503
    assert len(calls) == 3


@pytest.mark.parametrize(
    ("status_code", "message", "category", "status"),
    [
        (504, "gateway timeout", "request_timeout", 504),
        (401, "API key not valid", "invalid_api_key", 503),
        (403, "permission denied", "permission_denied", 503),
        (404, "models/missing-model is not found for generateContent", "invalid_model", 503),
        (400, "invalid response configuration", "invalid_request", 400),
    ],
)
def test_gemini_configuration_and_gateway_errors_are_not_retried(
    monkeypatch, status_code, message, category, status
):
    calls, _ = install_gemini_client(
        monkeypatch,
        [gemini_errors.APIError(status_code, {"error": {"message": message}})],
    )
    monkeypatch.setattr(settings, "gemini_max_retries", 0)

    with pytest.raises(gemini.AIServiceError) as error:
        gemini._generate("synthetic incident", IncidentExtraction)

    assert error.value.status_code == status
    assert error.value.category == category
    assert len(calls) == 1


def test_gemini_missing_model_is_reported_by_health_and_request(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "")
    status = ai_api.ai_health()

    assert status["gemini_api_key_configured"] is True
    assert status["gemini_model_configured"] is False
    assert status["configuration_issue"] == "Missing GEMINI_MODEL."
    with pytest.raises(gemini.AIServiceError, match="GEMINI_MODEL"):
        gemini.ensure_configured()


def test_gemini_invalid_structured_json_is_reported(monkeypatch):
    class InvalidModels:
        def generate_content(self, **kwargs):
            return type("Response", (), {"parsed": None, "text": "not-json"})()

    class InvalidClient:
        models = InvalidModels()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test-model")
    monkeypatch.setattr(gemini.genai, "Client", lambda **kwargs: InvalidClient())
    with pytest.raises(gemini.AIServiceError, match="required format") as error:
        gemini._generate("test", IncidentExtraction)
    assert error.value.status_code == 502


def test_analyze_text_endpoint_reports_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "gemini_model", "")
    from app.ai.schemas import TextAnalysisRequest

    with pytest.raises(HTTPException) as error:
        ai_api.analyze_text(TextAnalysisRequest(text="a fictional incident"), db=None)
    assert error.value.status_code == 503
    assert "GEMINI_API_KEY" in error.value.detail


def test_analyze_text_endpoint_calls_analysis_graph(monkeypatch):
    from app.ai.schemas import AnalysisResponse, TextAnalysisRequest

    called = {}
    result = AnalysisResponse(
        source_type="text",
        extraction=extraction(),
        missing_information=[],
        missing_evidence=[],
        root_cause_suggestions=[],
        fishbone={},
        five_whys=[],
    )
    monkeypatch.setattr(ai_api, "ensure_configured", lambda: None)
    monkeypatch.setattr(ai_api, "run_analysis", lambda state: called.update(state=state) or result)
    response = ai_api.analyze_text(TextAnalysisRequest(text="incident text"), db=None)
    assert response == result
    assert called["state"]["source_type"] == "text"


def test_analyze_email_endpoint_routes_email_content(monkeypatch):
    from app.ai.schemas import AnalysisResponse, EmailAnalysisRequest

    called = {}
    result = AnalysisResponse(
        source_type="email",
        extraction=extraction(),
        missing_information=[],
        missing_evidence=[],
        root_cause_suggestions=[],
        fishbone={},
        five_whys=[],
    )
    monkeypatch.setattr(ai_api, "ensure_configured", lambda: None)
    monkeypatch.setattr(ai_api, "run_analysis", lambda state: called.update(state=state) or result)
    response = ai_api.analyze_email(
        EmailAnalysisRequest(email_content="Subject: fictional deviation"), db=None
    )
    assert response.source_type == "email"
    assert called["state"]["content"] == "Subject: fictional deviation"


def test_pdf_upload_endpoint_rejects_invalid_content():
    file = UploadFile(
        file=BytesIO(b"not a pdf"),
        filename="report.pdf",
        headers={"content-type": "application/pdf"},
    )
    with pytest.raises(HTTPException) as error:
        ai_api.analyze_document(file=file, investigation_id=None, db=None)
    assert error.value.status_code == 422


def test_analyze_document_extracts_pdf_once_before_langgraph(monkeypatch):
    source = "Fictional deviation: recorded speed was 26 rpm."
    captured = install_graph_mocks(monkeypatch, source)
    original_extract_pdf = ai_api.extract_pdf
    extraction_calls = []

    def count_extract(data):
        extraction_calls.append(data)
        return original_extract_pdf(data)

    monkeypatch.setattr(ai_api, "extract_pdf", count_extract)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test-model")
    file = UploadFile(file=BytesIO(pdf_bytes(source)), filename="synthetic-report.pdf")

    result = ai_api.analyze_document(file=file, investigation_id=None, db=None)

    assert result.source_type == "pdf"
    assert len(extraction_calls) == 1
    assert captured["text"] == "[Page 1]\nFictional deviation: recorded speed was 26 rpm."


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_duplicate_analysis_for_same_investigation_is_rejected():
    with ai_api._analysis_guard(77):
        with pytest.raises(HTTPException) as error, ai_api._analysis_guard(77):
            pass
        assert error.value.status_code == 409
    with ai_api._analysis_guard(77):
        pass


def test_failed_pdf_analysis_preserves_draft_and_retry_uses_saved_pdf(
    db_session, monkeypatch
):
    from app.ai.schemas import AnalysisResponse

    record = Investigation(deviation_id="DEV-RETRY-PDF", incident_title="Synthetic retry")
    db_session.add(record)
    db_session.commit()
    result = AnalysisResponse(
        source_type="pdf",
        file_name="synthetic-report.pdf",
        page_count=1,
        extraction=extraction(),
        missing_information=[],
        missing_evidence=[],
        root_cause_suggestions=[],
        fishbone={},
        five_whys=[],
    )
    run_calls = []

    def run(state):
        run_calls.append(state)
        if len(run_calls) == 1:
            raise gemini.AIServiceError(
                503, "Gemini is temporarily unavailable after bounded retries.", "service_unavailable"
            )
        return result

    original_extract_pdf = ai_api.extract_pdf
    extraction_calls = []

    def count_extract(data):
        extraction_calls.append(data)
        return original_extract_pdf(data)

    monkeypatch.setattr(ai_api, "extract_pdf", count_extract)
    monkeypatch.setattr(ai_api, "run_analysis", run)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(settings, "gemini_model", "test-model")
    file_data = pdf_bytes("Fictional deviation: recorded speed was 26 rpm.")
    file = UploadFile(file=BytesIO(file_data), filename="synthetic-report.pdf")

    with pytest.raises(HTTPException) as error:
        ai_api.analyze_document(file=file, investigation_id=record.id, db=db_session)

    assert error.value.status_code == 503
    db_session.expire_all()
    stored = db_session.get(Investigation, record.id)
    saved_file = next(item for item in stored.evidence if item.file_content is not None)
    assert saved_file.file_content == file_data

    retried = ai_api.retry_analysis(record.id, db_session)

    assert retried.file_name == "synthetic-report.pdf"
    assert len(run_calls) == 2
    assert len(extraction_calls) == 2
    assert all("file_bytes" not in state for state in run_calls)
    assert all("[Page 1]" in state["source_text"] for state in run_calls)
    db_session.expire_all()
    assert db_session.get(Investigation, record.id).rca is not None


def test_pdf_source_and_analysis_persist_with_review_record(db_session, monkeypatch):
    record = Investigation(deviation_id="DEV-TEST-1", incident_title="Fictional review")
    db_session.add(record)
    db_session.commit()
    ai_api._save_source(
        db_session,
        record.id,
        source_type="pdf",
        source_text="page text",
        file_name="fixture.pdf",
        file_content=pdf_bytes("page text"),
    )
    from app.ai.schemas import AnalysisResponse

    result = AnalysisResponse(
        source_type="pdf",
        file_name="fixture.pdf",
        page_count=1,
        extraction=extraction(),
        missing_information=[],
        missing_evidence=[],
        root_cause_suggestions=[],
        fishbone={},
        five_whys=[],
    )
    ai_api._save_analysis(db_session, record.id, result)
    db_session.expire_all()
    stored = db_session.get(Investigation, record.id)
    source = next(item for item in stored.evidence if item.file_content is not None)
    assert source.file_content.startswith(b"%PDF-")
    assert stored.rca.extraction_data["deviation_id"]["value"] == "DEV-FICTIONAL-001"


def test_investigation_update_preserves_uploaded_pdf_and_saves_edited_rca(db_session):
    record = Investigation(deviation_id="DEV-TEST-2", incident_title="Fictional review")
    record.evidence.append(
        InvestigationEvidence(
            description="Source PDF",
            source_reference="report.pdf",
            file_name="report.pdf",
            mime_type="application/pdf",
            file_content=b"%PDF-content",
        )
    )
    record.rca = RootCauseAnalysis(extraction_data={}, suggestions=[], fishbone={}, five_whys=[])
    db_session.add(record)
    db_session.commit()
    payload = InvestigationUpdate(
        deviation_id=record.deviation_id,
        incident_title="Edited title",
        product_name="",
        batch_number="",
        department="",
        manufacturing_stage="",
        deviation_category="",
        equipment_involved="",
        incident_date=None,
        expected_condition="",
        actual_condition="",
        incident_description="Edited after review",
        immediate_actions="",
        potential_quality_impact="",
        evidence=[],
        rca=RootCauseAnalysisWrite(extraction_data={}, suggestions=[], fishbone={}, five_whys=[]),
    )
    updated = update_investigation(record.id, payload, db_session)
    assert updated.incident_title == "Edited title"
    assert any(item.file_content == b"%PDF-content" for item in updated.evidence)


def test_capa_action_status_persists_after_reload(db_session):
    record = Investigation(deviation_id="DEV-TEST-CAPA", incident_title="Synthetic CAPA review")
    db_session.add(record)
    db_session.commit()
    payload = CapaActionWrite(
        action_type="Corrective",
        action_description="Inspect the mixer setpoint history.",
    )

    created = create_capa(record.id, payload, db_session)
    updated = update_capa(
        created.id,
        payload.model_copy(update={"status": "In Progress"}),
        db_session,
    )
    db_session.expire_all()

    assert updated.status == "In Progress"
    assert list_capa(record.id, db_session)[0].status == "In Progress"


def test_dashboard_metrics_count_pending_capa_actions(db_session):
    record = Investigation(deviation_id="DEV-TEST-METRICS", incident_title="Synthetic metrics")
    record.capa_actions.extend(
        [
            CapaAction(action_type="Corrective", action_description="Open action"),
            CapaAction(
                action_type="Preventive",
                action_description="Completed action",
                status="Completed",
            ),
            CapaAction(
                action_type="Corrective",
                action_description="Rejected action",
                status="Rejected",
            ),
        ]
    )
    db_session.add(record)
    db_session.commit()

    assert dashboard_metrics(db_session) == {"pending_capa_actions": 1}


def test_investigation_report_contains_saved_review_and_capa_data(db_session):
    record = Investigation(
        deviation_id="DEV-TEST-REPORT",
        incident_title="Synthetic report review",
        incident_description="A fictional mixer speed excursion.",
    )
    record.rca = RootCauseAnalysis(
        five_whys=[{"question": "Why?", "answer": "A synthetic answer."}],
        fishbone={"Man / People": ["Training record requires review."]},
        suggestions=[
            {
                "cause_description": "Training documentation may be incomplete.",
                "status": "Confirmed by Human Reviewer",
                "reviewer_note": "Verified against the training register.",
            }
        ],
        extraction_data={"batch_number": {"value": "LOT-TRAIN-2401"}},
    )
    record.capa_actions.append(
        CapaAction(
            action_type="Corrective",
            action_description="Inspect the mixer setpoint history.",
            status="Accepted",
        )
    )
    db_session.add(record)
    db_session.commit()

    response = investigation_report(record.id, db_session)
    with pymupdf.open(stream=response.body, filetype="pdf") as document:
        report_text = "\n".join(page.get_text() for page in document)

    assert response.media_type == "application/pdf"
    for expected in (
        "DEV-TEST-REPORT",
        "LOT-TRAIN-2401",
        "A synthetic answer.",
        "Training record requires review.",
        "Confirmed by Human Reviewer",
        "Verified against the training register.",
        "Inspect the mixer setpoint history.",
    ):
        assert expected in report_text


def test_database_errors_return_cors_accessible_service_unavailable():
    def database_failure():
        raise OperationalError(
            "select 1",
            {},
            RuntimeError("password authentication failed for user 'YOUR_USER'"),
        )

    original = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = database_failure
    try:
        response = TestClient(app).get(
            "/api/v1/investigations",
            headers={"Origin": "http://127.0.0.1:5174"},
        )
    finally:
        if original is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = original

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"
    assert "rejected the DATABASE_URL credentials" in response.json()["detail"]
    assert "YOUR_USER" not in response.json()["detail"]
