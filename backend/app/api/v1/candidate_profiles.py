from datetime import date
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.v1.dependencies import (
    AuthenticatedSession,
    get_authenticated_session,
    require_authenticated_resource_access,
)
from app.db import Base, DatabaseSession
from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)
from app.schemas.candidate_profile import (
    CandidateCertificationCreate,
    CandidateCertificationRead,
    CandidateCertificationUpdate,
    CandidateEducationCreate,
    CandidateEducationRead,
    CandidateEducationUpdate,
    CandidateProfileCreate,
    CandidateProfileRead,
    CandidateProfileUpdate,
    CandidateSkillCreate,
    CandidateSkillRead,
    CandidateSkillUpdate,
    CandidateWorkExperienceCreate,
    CandidateWorkExperienceRead,
    CandidateWorkExperienceUpdate,
)

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["candidate profiles"],
    dependencies=[Depends(require_authenticated_resource_access)],
)
RecordT = TypeVar("RecordT", bound=Base)


def get_profile_or_404(session: DatabaseSession, profile_id: UUID) -> CandidateProfile:
    profile = session.get(CandidateProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        )
    return profile


def _get_owned_record(
    session: DatabaseSession,
    model: type[RecordT],
    profile_id: UUID,
    record_id: UUID,
    record_name: str,
) -> RecordT:
    record = session.scalar(
        select(model).where(
            model.id == record_id,  # type: ignore[attr-defined]
            model.candidate_profile_id == profile_id,  # type: ignore[attr-defined]
        )
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{record_name} not found for candidate profile",
        )
    return record


def _validate_merged_dates(
    start_date: date,
    end_date: date | None,
    *,
    current_role: bool = False,
    start_field: str = "start_date",
    expiry_field: str = "end_date",
) -> None:
    if end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{expiry_field} must be on or after {start_field}",
        )
    if current_role and end_date is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="current roles cannot have an end_date",
        )


def _commit_skill(session: DatabaseSession) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        message = str(exc.orig)
        is_duplicate = (
            constraint_name == "uq_candidate_skills_profile_name_ci"
            or "uq_candidate_skills_profile_name_ci" in message
            or ("candidate_skills.candidate_profile_id" in message and "candidate_skills.normalized_name" in message)
        )
        if not is_duplicate:
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This skill already exists for the candidate profile",
        ) from exc


@router.post(
    "",
    response_model=CandidateProfileRead,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate_profile(
    payload: CandidateProfileCreate,
    session: DatabaseSession,
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(get_authenticated_session),
    ],
) -> CandidateProfile:
    profile = CandidateProfile(
        user_id=authenticated.user.id,
        **payload.model_dump(),
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.get("", response_model=list[CandidateProfileRead])
def list_candidate_profiles(
    session: DatabaseSession,
    authenticated: Annotated[
        AuthenticatedSession,
        Depends(get_authenticated_session),
    ],
) -> list[CandidateProfile]:
    return list(
        session.scalars(
            select(CandidateProfile)
            .where(CandidateProfile.user_id == authenticated.user.id)
            .order_by(CandidateProfile.created_at, CandidateProfile.id)
        )
    )


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


@router.get(
    "/{profile_id}/experiences/{record_id}",
    response_model=CandidateWorkExperienceRead,
)
def get_work_experience(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> CandidateWorkExperience:
    get_profile_or_404(session, profile_id)
    return _get_owned_record(session, CandidateWorkExperience, profile_id, record_id, "Work experience")


@router.post(
    "/{profile_id}/experiences",
    response_model=CandidateWorkExperienceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_work_experience(
    profile_id: UUID,
    payload: CandidateWorkExperienceCreate,
    session: DatabaseSession,
) -> CandidateWorkExperience:
    get_profile_or_404(session, profile_id)
    record = CandidateWorkExperience(
        candidate_profile_id=profile_id,
        **payload.model_dump(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.patch(
    "/{profile_id}/experiences/{record_id}",
    response_model=CandidateWorkExperienceRead,
)
def update_work_experience(
    profile_id: UUID,
    record_id: UUID,
    payload: CandidateWorkExperienceUpdate,
    session: DatabaseSession,
) -> CandidateWorkExperience:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateWorkExperience, profile_id, record_id, "Work experience")
    updates = payload.model_dump(exclude_unset=True)
    _validate_merged_dates(
        updates.get("start_date", record.start_date),
        updates.get("end_date", record.end_date),
        current_role=updates.get("current_role", record.current_role),
    )
    for field_name, value in updates.items():
        setattr(record, field_name, value)
    session.commit()
    session.refresh(record)
    return record


@router.delete(
    "/{profile_id}/experiences/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_work_experience(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> None:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateWorkExperience, profile_id, record_id, "Work experience")
    session.delete(record)
    session.commit()


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


@router.get(
    "/{profile_id}/education/{record_id}",
    response_model=CandidateEducationRead,
)
def get_education(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> CandidateEducation:
    get_profile_or_404(session, profile_id)
    return _get_owned_record(session, CandidateEducation, profile_id, record_id, "Education record")


@router.post(
    "/{profile_id}/education",
    response_model=CandidateEducationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_education(
    profile_id: UUID,
    payload: CandidateEducationCreate,
    session: DatabaseSession,
) -> CandidateEducation:
    get_profile_or_404(session, profile_id)
    record = CandidateEducation(
        candidate_profile_id=profile_id,
        **payload.model_dump(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.patch(
    "/{profile_id}/education/{record_id}",
    response_model=CandidateEducationRead,
)
def update_education(
    profile_id: UUID,
    record_id: UUID,
    payload: CandidateEducationUpdate,
    session: DatabaseSession,
) -> CandidateEducation:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateEducation, profile_id, record_id, "Education record")
    updates = payload.model_dump(exclude_unset=True)
    _validate_merged_dates(
        updates.get("start_date", record.start_date),
        updates.get("end_date", record.end_date),
    )
    for field_name, value in updates.items():
        setattr(record, field_name, value)
    session.commit()
    session.refresh(record)
    return record


@router.delete(
    "/{profile_id}/education/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_education(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> None:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateEducation, profile_id, record_id, "Education record")
    session.delete(record)
    session.commit()


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
    "/{profile_id}/skills/{record_id}",
    response_model=CandidateSkillRead,
)
def get_skill(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> CandidateSkill:
    get_profile_or_404(session, profile_id)
    return _get_owned_record(session, CandidateSkill, profile_id, record_id, "Skill")


@router.post(
    "/{profile_id}/skills",
    response_model=CandidateSkillRead,
    status_code=status.HTTP_201_CREATED,
)
def create_skill(
    profile_id: UUID,
    payload: CandidateSkillCreate,
    session: DatabaseSession,
) -> CandidateSkill:
    get_profile_or_404(session, profile_id)
    record = CandidateSkill(candidate_profile_id=profile_id, **payload.model_dump())
    session.add(record)
    _commit_skill(session)
    session.refresh(record)
    return record


@router.patch(
    "/{profile_id}/skills/{record_id}",
    response_model=CandidateSkillRead,
)
def update_skill(
    profile_id: UUID,
    record_id: UUID,
    payload: CandidateSkillUpdate,
    session: DatabaseSession,
) -> CandidateSkill:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateSkill, profile_id, record_id, "Skill")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field_name, value)
    _commit_skill(session)
    session.refresh(record)
    return record


@router.delete(
    "/{profile_id}/skills/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_skill(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> None:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateSkill, profile_id, record_id, "Skill")
    session.delete(record)
    session.commit()


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


@router.get(
    "/{profile_id}/certifications/{record_id}",
    response_model=CandidateCertificationRead,
)
def get_certification(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> CandidateCertification:
    get_profile_or_404(session, profile_id)
    return _get_owned_record(session, CandidateCertification, profile_id, record_id, "Certification")


@router.post(
    "/{profile_id}/certifications",
    response_model=CandidateCertificationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_certification(
    profile_id: UUID,
    payload: CandidateCertificationCreate,
    session: DatabaseSession,
) -> CandidateCertification:
    get_profile_or_404(session, profile_id)
    record = CandidateCertification(
        candidate_profile_id=profile_id,
        **payload.model_dump(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@router.patch(
    "/{profile_id}/certifications/{record_id}",
    response_model=CandidateCertificationRead,
)
def update_certification(
    profile_id: UUID,
    record_id: UUID,
    payload: CandidateCertificationUpdate,
    session: DatabaseSession,
) -> CandidateCertification:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateCertification, profile_id, record_id, "Certification")
    updates = payload.model_dump(exclude_unset=True)
    _validate_merged_dates(
        updates.get("issue_date", record.issue_date),
        updates.get("expires_on", record.expires_on),
        start_field="issue_date",
        expiry_field="expires_on",
    )
    for field_name, value in updates.items():
        setattr(record, field_name, value)
    session.commit()
    session.refresh(record)
    return record


@router.delete(
    "/{profile_id}/certifications/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_certification(
    profile_id: UUID,
    record_id: UUID,
    session: DatabaseSession,
) -> None:
    get_profile_or_404(session, profile_id)
    record = _get_owned_record(session, CandidateCertification, profile_id, record_id, "Certification")
    session.delete(record)
    session.commit()
