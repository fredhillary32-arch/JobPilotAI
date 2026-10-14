from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.db import DatabaseSession
from app.models import CandidateJobDescription, TailoredCvDraft
from app.schemas.cv_generation import (
    CandidateJobDescriptionCreate,
    CandidateJobDescriptionRead,
    TailoredCvDraftRead,
)
from app.services.cv_generation import generate_cv_draft, persist_cv_draft

router = APIRouter(prefix="/candidate-profiles", tags=["CV generation"])


def _get_job_or_404(
    profile_id: UUID,
    job_id: UUID,
    session: DatabaseSession,
) -> CandidateJobDescription:
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
    return job


def _get_draft_or_404(
    profile_id: UUID,
    draft_id: UUID,
    session: DatabaseSession,
) -> TailoredCvDraft:
    draft = session.scalar(
        select(TailoredCvDraft).where(
            TailoredCvDraft.id == draft_id,
            TailoredCvDraft.candidate_profile_id == profile_id,
        )
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV draft not found for candidate profile",
        )
    return draft


@router.post(
    "/{profile_id}/job-descriptions",
    response_model=CandidateJobDescriptionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_job_description(
    profile_id: UUID,
    payload: CandidateJobDescriptionCreate,
    session: DatabaseSession,
) -> CandidateJobDescription:
    get_profile_or_404(session, profile_id)
    job = CandidateJobDescription(
        candidate_profile_id=profile_id,
        **payload.model_dump(mode="json"),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get(
    "/{profile_id}/job-descriptions",
    response_model=list[CandidateJobDescriptionRead],
)
def list_job_descriptions(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateJobDescription]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateJobDescription)
            .where(CandidateJobDescription.candidate_profile_id == profile_id)
            .order_by(CandidateJobDescription.created_at.desc())
        )
    )


@router.get(
    "/{profile_id}/job-descriptions/{job_id}",
    response_model=CandidateJobDescriptionRead,
)
def read_job_description(
    profile_id: UUID,
    job_id: UUID,
    session: DatabaseSession,
) -> CandidateJobDescription:
    get_profile_or_404(session, profile_id)
    return _get_job_or_404(profile_id, job_id, session)


@router.post(
    "/{profile_id}/job-descriptions/{job_id}/cv-drafts",
    response_model=TailoredCvDraftRead,
    status_code=status.HTTP_201_CREATED,
)
def create_cv_draft(
    profile_id: UUID,
    job_id: UUID,
    session: DatabaseSession,
) -> TailoredCvDraft:
    get_profile_or_404(session, profile_id)
    job = _get_job_or_404(profile_id, job_id, session)
    outcome = generate_cv_draft(session, profile_id, job)
    draft = persist_cv_draft(session, profile_id, job, outcome)
    if outcome.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "CV draft failed validation. Add or confirm the evidence described below.",
                "draft_id": str(draft.id),
                "validation_results": outcome.validation_results.model_dump(mode="json"),
            },
        )
    return draft


@router.get(
    "/{profile_id}/cv-drafts",
    response_model=list[TailoredCvDraftRead],
)
def list_cv_drafts(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[TailoredCvDraft]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(TailoredCvDraft)
            .where(TailoredCvDraft.candidate_profile_id == profile_id)
            .order_by(TailoredCvDraft.created_at.desc())
        )
    )


@router.get(
    "/{profile_id}/cv-drafts/{draft_id}",
    response_model=TailoredCvDraftRead,
)
def read_cv_draft(
    profile_id: UUID,
    draft_id: UUID,
    session: DatabaseSession,
) -> TailoredCvDraft:
    get_profile_or_404(session, profile_id)
    return _get_draft_or_404(profile_id, draft_id, session)
