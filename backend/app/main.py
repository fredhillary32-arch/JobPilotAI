from fastapi import FastAPI
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.db import check_database_connection

app = FastAPI(
    title="JobPilot AI API",
    version="0.1.0",
    description="API for the JobPilot AI platform.",
)


@app.get("/healthz", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readiness_check() -> dict[str, str]:
    try:
        check_database_connection()
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc

    return {"status": "ok"}
