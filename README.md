# AIVOA AI — Root Cause Analysis & CAPA Assistant

A local investigation workflow for pharmaceutical API manufacturing deviations, with Gemini assisted extraction and RCA, human review, CAPA tracking, PostgreSQL persistence, and PDF reports.

## Run locally

1. Start PostgreSQL and create an empty database.
2. Backend: use Python 3.12, install `.[test,lint]`, copy `.env.example` to `.env`, set `DATABASE_URL`, `GEMINI_API_KEY`, and `GEMINI_MODEL`, run `alembic upgrade head`, then start Uvicorn.
3. Frontend: install npm dependencies and run Vite.

Windows PowerShell startup from the repository root:

```powershell
Set-Location .\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test,lint]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env with PostgreSQL DATABASE_URL and Gemini GEMINI_API_KEY / GEMINI_MODEL.
alembic upgrade head
uvicorn app.main:app --reload
```

In a second PowerShell window from the repository root:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

The frontend runs at http://localhost:5173. API docs are at http://localhost:8000/docs. `DATABASE_URL` must use a PostgreSQL SQLAlchemy URL such as `postgresql+psycopg://user:password@localhost:5432/aivoa`. Keep the Gemini key in `backend/.env`; it is read only by FastAPI and never sent to the browser.

## AI incident analysis

The AI workflow uses Google Gen AI structured output through LangGraph. It accepts incident text, email content, and selectable-text PDFs (maximum 20 MB). PDF page numbers are preserved and the original uploaded PDF is stored with its investigation evidence in PostgreSQL. Scanned PDFs are reported as unreadable because OCR is not included. AI extraction, root cause suggestions, Five Whys, evidence gaps, and user edits are stored on the investigation for later retrieval. CAPA suggestions are generated separately as AI suggestions; accepted/edited actions and statuses are persisted in PostgreSQL. The report endpoint creates a PDF from saved investigation and CAPA records. A human reviewer remains responsible for confirming or rejecting root causes and accepting actions.

The Gemini health endpoint reports whether `GEMINI_API_KEY` and `GEMINI_MODEL` are configured without returning the key; provider access and quota are checked only when analysis runs. Each model call has a 60-second timeout and at most two bounded retries for transient errors; daily quota exhaustion, invalid keys, and invalid models are reported without retrying. The main analysis uses two Gemini calls: one to extract source facts and one for evidence gaps, RCA, Fishbone, and Five Whys. Re-analysis uses the saved source when available. If Google AI Studio reports exhausted daily quota, check the project's request/token limits and billing in AI Studio; waiting for a reset or changing the project's quota/plan is required before another successful analysis.

Run backend checks with `python -m pytest` and `python -m ruff check app tests alembic`. The fictional training input in `sample_documents/fictional_deviation.txt` is synthetic; automated tests mock Gemini and do not return fabricated AI results from the application.
