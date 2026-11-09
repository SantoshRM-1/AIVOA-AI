from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.ai import router as ai_router
from app.api.router import router
from app.core.config import settings

app = FastAPI(title="AIVOA AI — RCA & CAPA Assistant", version="0.1.0")


def _database_error_detail(exc: SQLAlchemyError) -> str:
    cause = exc.orig
    message = str(cause).casefold() if cause is not None else ""
    if "password authentication failed" in message or "no password supplied" in message:
        return (
            "PostgreSQL rejected the DATABASE_URL credentials. Replace the placeholder "
            "username and password in backend/.env with valid local PostgreSQL credentials, "
            "then restart the backend."
        )
    if "role" in message and "does not exist" in message:
        return (
            "The PostgreSQL role in DATABASE_URL does not exist. Set a valid local role "
            "in backend/.env, then restart the backend."
        )
    if "database" in message and "does not exist" in message:
        return (
            "The database in DATABASE_URL does not exist. Set an existing database name "
            "in backend/.env, then restart the backend."
        )
    return "Database unavailable. Verify PostgreSQL connectivity and backend DATABASE_URL."


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_: Request, _exc: SQLAlchemyError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": _database_error_detail(_exc)},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
app.include_router(ai_router)
