from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateJobDescription, JobApplication, JobApplicationEvent, TailoredCvDraft
from app.models.job_application import ALLOWED_TRANSITIONS, SUBMITTED_STATUSES
from app.schemas.job_application import (
    ApplicationStatus,
    JobApplicationCreate,
    JobApplicationRead,
    JobApplicationStatusChange,
    JobApplicationUpdate,
)
from app.services.auth import utc_now

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["job applications"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def _latest_allowed_date() -> date:
    # The candidate's local date may be ahead of UTC (Kenya is UTC+3); allow the
    # furthest real timezone, but never a genuinely future date.
    return (utc_now() + timedelta(hours=14)).date()


def _get_application_or_404(
    profile_id: UUID,
    application_id: UUID,
    session: DatabaseSession,
) -> JobApplication:
    application = session.scalar(
        select(JobApplication).where(
            JobApplication.id == application_id,
            JobApplication.candidate_profile_id == profile_id,
        )
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    return application


def _require_job(profile_id: UUID, job_id: UUID, session: DatabaseSession) -> None:
    exists = session.scalar(
        select(CandidateJobDescription.id).where(
            CandidateJobDescription.id == job_id,
            CandidateJobDescription.candidate_profile_id == profile_id,
        )
    )
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job description not found for candidate profile",
        )


def _require_usable_draft(
    profile_id: UUID,
    job_id: UUID,
    draft_id: UUID,
    session: DatabaseSession,
) -> None:
    draft = session.scalar(
        select(TailoredCvDraft).where(
            TailoredCvDraft.id == draft_id,
            TailoredCvDraft.candidate_profile_id == profile_id,
        )
    )
    if draft is None or draft.job_description_id != job_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The CV draft must be a generated draft for this application's job.",
        )
    if draft.status not in {"generated", "needs_review"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only a successfully generated CV draft can be linked to an application.",
        )


def _check_applied_on(target_status: str, applied_on: date | None) -> None:
    if target_status in SUBMITTED_STATUSES and applied_on is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Record the date you submitted the application.",
        )
    if applied_on is not None and applied_on > _latest_allowed_date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The application date cannot be in the future.",
        )


@router.get("/{profile_id}/applications", response_model=list[JobApplicationRead])
def list_applications(
    profile_id: UUID,
    session: DatabaseSession,
    status_filter: Annotated[ApplicationStatus | None, Query(alias="status")] = None,
) -> list[JobApplication]:
    get_profile_or_404(session, profile_id)
    query = select(JobApplication).where(JobApplication.candidate_profile_id == profile_id)
    if status_filter is not None:
        query = query.where(JobApplication.status == status_filter)
    return list(
        session.scalars(query.order_by(JobApplication.updated_at.desc(), JobApplication.id))
    )


@router.post(
    "/{profile_id}/applications",
    response_model=JobApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_application(
    profile_id: UUID,
    payload: JobApplicationCreate,
    session: DatabaseSession,
) -> JobApplication:
    get_profile_or_404(session, profile_id)
    _require_job(profile_id, payload.job_description_id, session)
    if payload.cv_draft_id is not None:
        _require_usable_draft(profile_id, payload.job_description_id, payload.cv_draft_id, session)
    _check_applied_on(payload.status, payload.applied_on)
    if payload.status not in SUBMITTED_STATUSES and payload.applied_on is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An application date is only recorded once the application is submitted.",
        )

    application = JobApplication(
        candidate_profile_id=profile_id,
        **payload.model_dump(),
    )
    application.events.append(
        JobApplicationEvent(from_status=None, to_status=payload.status, occurred_at=utc_now())
    )
    session.add(application)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job is already being tracked as an application.",
        ) from None
    session.refresh(application)
    return application


@router.get(
    "/{profile_id}/applications/{application_id}",
    response_model=JobApplicationRead,
)
def read_application(
    profile_id: UUID,
    application_id: UUID,
    session: DatabaseSession,
) -> JobApplication:
    get_profile_or_404(session, profile_id)
    return _get_application_or_404(profile_id, application_id, session)


@router.patch(
    "/{profile_id}/applications/{application_id}",
    response_model=JobApplicationRead,
)
def update_application(
    profile_id: UUID,
    application_id: UUID,
    payload: JobApplicationUpdate,
    session: DatabaseSession,
) -> JobApplication:
    get_profile_or_404(session, profile_id)
    application = _get_application_or_404(profile_id, application_id, session)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("cv_draft_id") is not None:
        _require_usable_draft(
            profile_id, application.job_description_id, changes["cv_draft_id"], session
        )
    for field, value in changes.items():
        setattr(application, field, value)
    session.commit()
    session.refresh(application)
    return application


@router.post(
    "/{profile_id}/applications/{application_id}/status",
    response_model=JobApplicationRead,
)
def change_application_status(
    profile_id: UUID,
    application_id: UUID,
    payload: JobApplicationStatusChange,
    session: DatabaseSession,
) -> JobApplication:
    get_profile_or_404(session, profile_id)
    application = session.scalar(
        select(JobApplication)
        .where(
            JobApplication.id == application_id,
            JobApplication.candidate_profile_id == profile_id,
        )
        .with_for_update()
    )
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    current = application.status
    if payload.status not in ALLOWED_TRANSITIONS[current]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An application cannot move from {current} to {payload.status}.",
        )
    if payload.status == "applied":
        _check_applied_on(payload.status, payload.applied_on)
        application.applied_on = payload.applied_on
    elif payload.applied_on is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="An application date is only recorded when marking it as applied.",
        )

    application.status = payload.status
    application.events.append(
        JobApplicationEvent(
            from_status=current,
            to_status=payload.status,
            note=payload.note,
            occurred_at=utc_now(),
        )
    )
    session.commit()
    session.refresh(application)
    return application
