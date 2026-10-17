from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.v1.dependencies import (
    AuthenticatedSession,
    get_authenticated_session,
    require_authenticated_resource_access,
)
from app.db import DatabaseSession
from app.models import JobListing, ListingEligibilityAssessment
from app.schemas.job_listing import (
    EligibilityAssessmentCreate,
    EligibilityAssessmentRead,
    ListingEligibilityAssessmentRead,
)
from app.services.auth import utc_now
from app.services.eligibility import effective_eligibility
from app.services.eligibility_evidence import eligibility_passages

# Reviewed Kenya-eligibility judgements about stored listings. Kept apart from
# the read-only listings router: nothing here contacts an external source.
router = APIRouter(
    tags=["job eligibility"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def _get_listing_or_404(listing_id: UUID, session: DatabaseSession) -> JobListing:
    row = session.get(JobListing, listing_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")
    return row


@router.get("/job-listings/{listing_id}/eligibility-evidence")
def read_eligibility_evidence(listing_id: UUID, session: DatabaseSession) -> dict:
    """Passages to review before recording eligibility; suggestions, not a decision."""
    listing = _get_listing_or_404(listing_id, session)
    return eligibility_passages(listing.description_text, listing.location_text)


@router.get(
    "/job-listings/{listing_id}/eligibility-assessments",
    response_model=list[ListingEligibilityAssessmentRead],
)
def list_eligibility_assessments(
    listing_id: UUID,
    session: DatabaseSession,
) -> list[ListingEligibilityAssessment]:
    _get_listing_or_404(listing_id, session)
    return list(
        session.scalars(
            select(ListingEligibilityAssessment)
            .where(ListingEligibilityAssessment.job_listing_id == listing_id)
            .order_by(
                ListingEligibilityAssessment.assessed_at.desc(),
                ListingEligibilityAssessment.id.desc(),
            )
        )
    )


@router.post(
    "/job-listings/{listing_id}/eligibility-assessments",
    response_model=EligibilityAssessmentRead,
    status_code=status.HTTP_201_CREATED,
)
def record_eligibility_assessment(
    listing_id: UUID,
    payload: EligibilityAssessmentCreate,
    session: DatabaseSession,
    authenticated: Annotated[AuthenticatedSession, Depends(get_authenticated_session)],
) -> EligibilityAssessmentRead:
    """Record a reviewed judgement backed by an exact quotation from the listing."""
    listing = _get_listing_or_404(listing_id, session)
    if listing.source_status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This listing is no longer listed by its source, so it is not reassessed.",
        )
    evidence = eligibility_passages(listing.description_text, listing.location_text)
    if payload.outcome == "eligible_confirmed" and evidence["conflicts"]:
        exclusion = next((p["sentence"] for p in evidence["passages"] if p["kind"] in ("kenya_exclusion", "residency_restriction")), None)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{evidence['conflicts'][0]} Record it as conflicting or not established"
                + (f": \"{exclusion}\"" if exclusion else ".")
            ),
        )
    quote_start = None
    if payload.quotation is not None:
        source_text = (
            listing.description_text if payload.evidence_field == "description" else listing.location_text
        ) or ""
        quote_start = source_text.find(payload.quotation)
        if quote_start < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "The quotation must be copied exactly from the listing's "
                    f"{payload.evidence_field} text."
                ),
            )
    assessment = ListingEligibilityAssessment(
        job_listing_id=listing.id,
        assessed_by_user_id=authenticated.user.id,
        outcome=payload.outcome,
        explanation=payload.explanation,
        quotation=payload.quotation,
        evidence_field=payload.evidence_field,
        quote_start=quote_start,
        statement_scope=payload.statement_scope,
        role_applicability=payload.role_applicability,
        geographic_scope=payload.geographic_scope,
        # Snapshot of the examined text: later wording changes make this stale.
        examined_description=listing.description_text,
        examined_location=listing.location_text,
        listing_content_hash=listing.content_hash,
        listing_source_updated_at=listing.source_updated_at,
        listing_last_verified_at=listing.last_verified_at,
        assessed_at=utc_now(),
    )
    session.add(assessment)
    session.commit()
    session.refresh(assessment)
    return EligibilityAssessmentRead(**effective_eligibility(listing, assessment))
