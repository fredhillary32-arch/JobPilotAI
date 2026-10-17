from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateEligibilityDetails, CandidateWorkAuthorization
from app.schemas.candidate_eligibility import (
    CandidateEligibilityDetailsInput,
    CandidateEligibilityDetailsRead,
    CountryRead,
    WorkAuthorizationRead,
    country_name,
)
from app.services.auth import utc_now
from app.services.countries import COUNTRIES

router = APIRouter(
    tags=["candidate eligibility"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def read_eligibility_details(session: Session, profile_id: UUID) -> CandidateEligibilityDetailsRead:
    details = session.get(CandidateEligibilityDetails, profile_id)
    if details is None:
        return CandidateEligibilityDetailsRead(confirmation_status="not_confirmed")
    authorizations = session.scalars(
        select(CandidateWorkAuthorization)
        .where(CandidateWorkAuthorization.candidate_profile_id == profile_id)
        .order_by(CandidateWorkAuthorization.country_code)
    )
    return CandidateEligibilityDetailsRead(
        confirmation_status="confirmed",
        confirmed_at=details.confirmed_at,
        country_of_residence=details.country_of_residence,
        country_of_residence_name=country_name(details.country_of_residence),
        relocation_willingness=details.relocation_willingness,
        relocation_countries=details.relocation_countries,
        accepted_work_arrangements=details.accepted_work_arrangements,
        work_authorizations=[
            WorkAuthorizationRead(
                country_code=item.country_code,
                country_name=COUNTRIES[item.country_code],
                status=item.status,
                confirmed_at=item.confirmed_at,
            )
            for item in authorizations
        ],
    )


@router.get("/countries", response_model=list[CountryRead])
def list_countries() -> list[CountryRead]:
    return [CountryRead(code=code, name=name) for code, name in sorted(COUNTRIES.items(), key=lambda item: item[1])]


@router.get(
    "/candidate-profiles/{profile_id}/eligibility-details",
    response_model=CandidateEligibilityDetailsRead,
)
def get_eligibility_details(profile_id: UUID, session: DatabaseSession) -> CandidateEligibilityDetailsRead:
    get_profile_or_404(session, profile_id)
    return read_eligibility_details(session, profile_id)


@router.put(
    "/candidate-profiles/{profile_id}/eligibility-details",
    response_model=CandidateEligibilityDetailsRead,
)
def confirm_eligibility_details(
    profile_id: UUID,
    payload: CandidateEligibilityDetailsInput,
    session: DatabaseSession,
) -> CandidateEligibilityDetailsRead:
    """Replace the candidate's confirmed details; every value is re-confirmed now."""
    get_profile_or_404(session, profile_id)
    now = utc_now()
    details = session.get(CandidateEligibilityDetails, profile_id)
    if details is None:
        details = CandidateEligibilityDetails(candidate_profile_id=profile_id, confirmed_at=now)
        session.add(details)
    details.country_of_residence = payload.country_of_residence
    details.relocation_willingness = payload.relocation_willingness
    details.relocation_countries = payload.relocation_countries
    details.accepted_work_arrangements = payload.accepted_work_arrangements
    details.confirmed_at = now
    session.execute(
        delete(CandidateWorkAuthorization).where(
            CandidateWorkAuthorization.candidate_profile_id == profile_id
        )
    )
    session.add_all(
        CandidateWorkAuthorization(
            candidate_profile_id=profile_id,
            country_code=item.country_code,
            status=item.status,
            confirmed_at=now,
        )
        for item in payload.work_authorizations
    )
    session.commit()
    return read_eligibility_details(session, profile_id)
