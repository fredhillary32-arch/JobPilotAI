from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateJobDescription
from app.schemas.job_fit import JobFitRead
from app.services.job_fit import compute_job_fit

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["job fit"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


@router.get(
    "/{profile_id}/job-descriptions/{job_id}/fit",
    response_model=JobFitRead,
)
def read_job_fit(profile_id: UUID, job_id: UUID, session: DatabaseSession) -> dict:
    """Explain how a saved job fits the candidate's own information (read-only)."""
    get_profile_or_404(session, profile_id)
    job = session.scalar(
        select(CandidateJobDescription).where(
            CandidateJobDescription.id == job_id,
            CandidateJobDescription.candidate_profile_id == profile_id,
        )
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job description not found for candidate profile",
        )
    return compute_job_fit(session, job)
