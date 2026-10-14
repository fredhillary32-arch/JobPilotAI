from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.db import DatabaseSession
from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)
from app.schemas.candidate_profile import (
    CandidateCertificationRead,
    CandidateEducationRead,
    CandidateProfileCreate,
    CandidateProfileRead,
    CandidateProfileUpdate,
    CandidateSkillRead,
    CandidateWorkExperienceRead,
)

router = APIRouter(prefix="/candidate-profiles", tags=["candidate profiles"])


def get_profile_or_404(session: DatabaseSession, profile_id: UUID) -> CandidateProfile:
    profile = session.get(CandidateProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        )
    return profile


@router.post(
    "",
    response_model=CandidateProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate_profile(
    payload: CandidateProfileCreate,
    session: DatabaseSession,
) -> CandidateProfile:
    profile = CandidateProfile(**payload.model_dump())
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=CandidateProfileRead)
def read_candidate_profile(
    profile_id: UUID,
    session: DatabaseSession,
) -> CandidateProfile:
    return get_profile_or_404(session, profile_id)


@router.patch("/{profile_id}", response_model=CandidateProfileRead)
def update_candidate_profile(
    profile_id: UUID,
    payload: CandidateProfileUpdate,
    session: DatabaseSession,
) -> CandidateProfile:
    profile = get_profile_or_404(session, profile_id)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field_name, value)
    session.commit()
    session.refresh(profile)
    return profile


@router.get(
    "/{profile_id}/experiences",
    response_model=list[CandidateWorkExperienceRead],
)
def list_work_experiences(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateWorkExperience]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateWorkExperience)
            .where(CandidateWorkExperience.candidate_profile_id == profile_id)
            .order_by(CandidateWorkExperience.start_date.desc())
        )
    )


@router.get("/{profile_id}/education", response_model=list[CandidateEducationRead])
def list_education(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateEducation]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateEducation)
            .where(CandidateEducation.candidate_profile_id == profile_id)
            .order_by(CandidateEducation.start_date.desc())
        )
    )


@router.get("/{profile_id}/skills", response_model=list[CandidateSkillRead])
def list_skills(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateSkill]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateSkill)
            .where(CandidateSkill.candidate_profile_id == profile_id)
            .order_by(CandidateSkill.name)
        )
    )


@router.get(
    "/{profile_id}/certifications",
    response_model=list[CandidateCertificationRead],
)
def list_certifications(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateCertification]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateCertification)
            .where(CandidateCertification.candidate_profile_id == profile_id)
            .order_by(CandidateCertification.issue_date.desc())
        )
    )
