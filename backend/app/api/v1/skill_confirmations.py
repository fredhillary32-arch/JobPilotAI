"""The candidate's answers about skills and job requirements.

Every route requires an authenticated session and profile ownership. Answers
are the candidate's own statements: they are never marked as independently
verified, and withdrawing one keeps its history.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateJobDescription, CandidateSkillConfirmation, CandidateWorkExperience
from app.schemas.skill_confirmation import SkillConfirmationCreate, SkillConfirmationRead, SkillConfirmationUpdate
from app.services.auth import utc_now
from app.services.job_requirements import extract_requirements

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["skill confirmations"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def _confirmation(session, profile_id: UUID, confirmation_id: UUID) -> CandidateSkillConfirmation:
    item = session.scalar(
        select(CandidateSkillConfirmation).where(
            CandidateSkillConfirmation.id == confirmation_id,
            CandidateSkillConfirmation.candidate_profile_id == profile_id,
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Skill confirmation not found for candidate profile"
        )
    return item


def _check_role(session, profile_id: UUID, work_experience_id: UUID | None) -> None:
    if work_experience_id is None:
        return
    role = session.get(CandidateWorkExperience, work_experience_id)
    if role is None or role.candidate_profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The role must be one of your own recorded roles."
        )


@router.get("/{profile_id}/skill-confirmations", response_model=list[SkillConfirmationRead])
def list_skill_confirmations(
    profile_id: UUID,
    session: DatabaseSession,
    job_description_id: Annotated[UUID | None, Query()] = None,
    include_withdrawn: Annotated[bool, Query()] = False,
) -> list[CandidateSkillConfirmation]:
    get_profile_or_404(session, profile_id)
    query = select(CandidateSkillConfirmation).where(CandidateSkillConfirmation.candidate_profile_id == profile_id)
    if job_description_id is not None:
        query = query.where(CandidateSkillConfirmation.job_description_id == job_description_id)
    if not include_withdrawn:
        query = query.where(CandidateSkillConfirmation.status == "active")
    return list(session.scalars(query.order_by(CandidateSkillConfirmation.created_at)))


@router.post(
    "/{profile_id}/skill-confirmations", response_model=SkillConfirmationRead, status_code=status.HTTP_201_CREATED
)
def create_skill_confirmation(
    profile_id: UUID,
    payload: SkillConfirmationCreate,
    session: DatabaseSession,
) -> CandidateSkillConfirmation:
    get_profile_or_404(session, profile_id)
    _check_role(session, profile_id, payload.work_experience_id)
    requirement_text = None
    if payload.job_description_id is not None:
        job = session.scalar(
            select(CandidateJobDescription).where(
                CandidateJobDescription.id == payload.job_description_id,
                CandidateJobDescription.candidate_profile_id == profile_id,
            )
        )
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Job description not found for candidate profile"
            )
        # The requirement is looked up in the server's own analysis of the saved job.
        requirement = next(
            (
                item
                for item in extract_requirements(job.description, company=job.company)["requirements"]
                if item["key"] == payload.requirement_key
            ),
            None,
        )
        if requirement is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="That requirement is not in the saved job description. Refresh the analysis and try again.",
            )
        requirement_text = requirement["source_text"][:1000]
        existing = session.scalar(
            select(CandidateSkillConfirmation).where(
                CandidateSkillConfirmation.candidate_profile_id == profile_id,
                CandidateSkillConfirmation.job_description_id == job.id,
                CandidateSkillConfirmation.requirement_key == payload.requirement_key,
                CandidateSkillConfirmation.status == "active",
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "You already answered this requirement; edit or withdraw that answer.",
                    "confirmation_id": str(existing.id),
                },
            )
    item = CandidateSkillConfirmation(
        candidate_profile_id=profile_id,
        requirement_text=requirement_text,
        confirmed_at=utc_now(),
        **payload.model_dump(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.put("/{profile_id}/skill-confirmations/{confirmation_id}", response_model=SkillConfirmationRead)
def update_skill_confirmation(
    profile_id: UUID,
    confirmation_id: UUID,
    payload: SkillConfirmationUpdate,
    session: DatabaseSession,
) -> CandidateSkillConfirmation:
    get_profile_or_404(session, profile_id)
    item = _confirmation(session, profile_id, confirmation_id)
    if item.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A withdrawn answer cannot be edited; record a new one."
        )
    if item.job_description_id is None and payload.response in {"not_possessed", "unsure"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="'Not possessed' and 'unsure' answer a job requirement; withdraw this skill instead.",
        )
    _check_role(session, profile_id, payload.work_experience_id)
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    item.confirmed_at = utc_now()
    session.commit()
    session.refresh(item)
    return item


@router.post("/{profile_id}/skill-confirmations/{confirmation_id}/withdraw", response_model=SkillConfirmationRead)
def withdraw_skill_confirmation(
    profile_id: UUID,
    confirmation_id: UUID,
    session: DatabaseSession,
) -> CandidateSkillConfirmation:
    """Stop using an answer; it is kept, marked withdrawn, and never used again."""
    get_profile_or_404(session, profile_id)
    item = _confirmation(session, profile_id, confirmation_id)
    item.status = "withdrawn"
    session.commit()
    session.refresh(item)
    return item
