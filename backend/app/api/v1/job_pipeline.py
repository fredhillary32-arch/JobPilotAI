"""The candidate's job pipeline: queued listings and application preparation."""
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.api.v1.job_listings import (
    RoleGroup, keyword_condition, keyword_terms, role_candidate_condition, role_filter, source_condition,
)
from app.db import DatabaseSession
from app.models import JobListing
from app.services.auth import utc_now
from app.services.documents import DocumentStorage, get_document_storage
from app.services.job_pipeline import PrepareRefused, build_pipeline, prepare_application

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["job pipeline"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


@router.get("/{profile_id}/job-pipeline")
def read_job_pipeline(
    profile_id: UUID,
    session: DatabaseSession,
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
    posted_within_hours: Annotated[int | None, Query(ge=1, le=24 * 90)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    role_family: Annotated[list[RoleGroup] | None, Query()] = None,
    exclude_role_family: Annotated[list[RoleGroup] | None, Query()] = None,
    source: Annotated[str | None, Query(max_length=64)] = None,
    workplace: Annotated[Literal["remote", "hybrid", "onsite"] | None, Query()] = None,
    include_fit: Annotated[bool, Query()] = True,
) -> dict:
    """Read-only: sorts stored listings into queues for this candidate; contacts no external site."""
    get_profile_or_404(session, profile_id)
    conditions = []
    if posted_within_hours is not None:
        # Only the source's own posting date counts; discovery date is never used instead.
        now = utc_now()
        conditions += [JobListing.posted_at >= now - timedelta(hours=posted_within_hours), JobListing.posted_at <= now]
    terms = keyword_terms(q)
    if terms:
        conditions.append(keyword_condition(terms))
    if role_family:
        conditions.append(role_candidate_condition())  # narrowing only; classified below
    if source is not None:
        conditions.append(source_condition(source))
    if workplace is not None:
        conditions.append(JobListing.stated_workplace_type == workplace)
    listings = list(session.scalars(select(JobListing).where(*conditions)))
    keep_role = role_filter(role_family, exclude_role_family)
    if keep_role is not None:
        listings = [listing for listing in listings if keep_role(listing.title)]
    return build_pipeline(session, profile_id, listings, storage, include_fit=include_fit)


@router.post("/{profile_id}/job-listings/{listing_id}/prepare-application")
def prepare_listing_application(
    profile_id: UUID,
    listing_id: UUID,
    session: DatabaseSession,
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
) -> dict:
    """Prepare (never submit) an application for an eligible listing."""
    get_profile_or_404(session, profile_id)
    listing = session.get(JobListing, listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")
    try:
        return prepare_application(session, profile_id, listing, storage)
    except PrepareRefused as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"message": str(exc), "reasons": exc.reasons}) from exc
