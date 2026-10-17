from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateJobDescription, JobListing, TailoredCvDraft
from app.schemas.cv_generation import (
    CandidateJobDescriptionCreate,
    CandidateJobDescriptionRead,
    CvDraftCreate,
    TailoredCvDraftRead,
)
from app.services.cv_generation import generate_cv_draft, persist_cv_draft
from app.services.documents import DocumentStorage, get_document_storage
from app.services.job_pipeline import ImportRefused, import_listing, imported_job_for, write_reviewed_draft

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["CV generation"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


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


@router.post(
    "/{profile_id}/job-descriptions/from-listing/{listing_id}",
    response_model=CandidateJobDescriptionRead,
    status_code=status.HTTP_201_CREATED,
)
def import_job_description_from_listing(
    profile_id: UUID,
    listing_id: UUID,
    session: DatabaseSession,
    response: Response,
) -> CandidateJobDescription:
    """Copy a stored discovered listing into this profile's job descriptions.

    The server copies the stored source text verbatim, so it is never relayed or
    edited by the browser. Importing the same listing again returns the existing
    job description (HTTP 200) instead of creating a duplicate.
    """
    get_profile_or_404(session, profile_id)
    existing = imported_job_for(session, profile_id, listing_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    listing = session.get(JobListing, listing_id)
    if listing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job listing not found",
        )
    try:
        job, created = import_listing(session, profile_id, listing)
    except ImportRefused as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
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
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
    payload: Annotated[CvDraftCreate | None, Body()] = None,
) -> TailoredCvDraft:
    get_profile_or_404(session, profile_id)
    job = _get_job_or_404(profile_id, job_id, session)
    settings = payload or CvDraftCreate()
    if settings.writer == "reviewed":
        try:
            draft = write_reviewed_draft(
                session, profile_id, job, storage, source_document_id=settings.source_document_id
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    else:
        draft = persist_cv_draft(session, profile_id, job, generate_cv_draft(session, profile_id, job))
    if draft.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "CV draft failed validation. Add or confirm the evidence described below.",
                "draft_id": str(draft.id),
                "validation_results": draft.validation_results,
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
