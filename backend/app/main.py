from fastapi import FastAPI
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.auth import router as auth_router
from app.api.v1.candidate_documents import router as candidate_documents_router
from app.api.v1.candidate_eligibility import router as candidate_eligibility_router
from app.api.v1.candidate_evidence import router as candidate_evidence_router
from app.api.v1.candidate_profiles import router as candidate_profiles_router
from app.api.v1.cv_exports import router as cv_exports_router
from app.api.v1.cv_generation import router as cv_generation_router
from app.api.v1.cv_review import router as cv_review_router
from app.db import DatabaseSchemaNotCurrentError, check_database_connection
from app.request_limits import BodySizeLimitMiddleware
from app.api.v1.document_extractions import router as document_extractions_router
from app.api.v1.job_applications import router as job_applications_router
from app.api.v1.job_fit import router as job_fit_router
from app.api.v1.job_pipeline import router as job_pipeline_router
from app.api.v1.job_listings import router as job_listings_router
from app.api.v1.job_discovery import router as job_discovery_router
from app.api.v1.skill_confirmations import router as skill_confirmations_router
from app.api.v1.listing_eligibility import router as listing_eligibility_router

app = FastAPI(
    title="JobPilot AI API",
    version="0.1.0",
    description="API for the JobPilot AI platform.",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(BodySizeLimitMiddleware)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(candidate_profiles_router, prefix="/api/v1")
app.include_router(candidate_eligibility_router, prefix="/api/v1")
app.include_router(candidate_documents_router, prefix="/api/v1")
app.include_router(document_extractions_router, prefix="/api/v1")
app.include_router(candidate_evidence_router, prefix="/api/v1")
app.include_router(cv_generation_router, prefix="/api/v1")
app.include_router(cv_exports_router, prefix="/api/v1")
app.include_router(cv_review_router, prefix="/api/v1")
app.include_router(job_listings_router, prefix="/api/v1")
app.include_router(job_discovery_router, prefix="/api/v1")
app.include_router(skill_confirmations_router, prefix="/api/v1")
app.include_router(listing_eligibility_router, prefix="/api/v1")
app.include_router(job_applications_router, prefix="/api/v1")
app.include_router(job_fit_router, prefix="/api/v1")
app.include_router(job_pipeline_router, prefix="/api/v1")


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
        ) from None
    except DatabaseSchemaNotCurrentError:
        raise HTTPException(
            status_code=503,
            detail="Database schema is not current",
        ) from None

    return {"status": "ok"}
