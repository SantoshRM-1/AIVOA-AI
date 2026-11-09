# Project notes

The frontend calls the versioned FastAPI API at `/api/v1`. PostgreSQL connection settings and Gemini credentials are read by FastAPI from `backend/.env`.

Incident analysis runs through `app.ai.graph` as a LangGraph `StateGraph`. Gemini returns Pydantic-validated structured output. Supporting quotes are checked against the submitted source and page references are checked against extracted PDF page text before the results are returned. The second Alembic revision stores extracted equipment/category fields, PDF bytes, and extraction JSON alongside the original investigation, evidence, and root cause records.

Automated tests mock Gemini responses and use an in-memory SQLite database only as a test fixture. A real deployment should configure PostgreSQL and apply `alembic upgrade head` before using saved investigations.
