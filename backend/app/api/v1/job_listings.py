from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import JobDiscoveryRun, JobListing
from app.schemas.job_listing import (
    JobDiscoveryRunRead,
    JobListingDetailRead,
    JobListingPage,
    JobListingRead,
)
from app.services.auth import utc_now

# Discovered listings are public source facts shared by the local owner; every
# route still requires an authenticated session. Discovery itself runs from the
# operator CLI, so this router has no endpoint that contacts external sources.
router = APIRouter(
    tags=["job discovery"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


@router.get("/job-listings", response_model=JobListingPage)
def list_job_listings(
    session: DatabaseSession,
    source_status: Annotated[Literal["active", "missing_from_source", "all"], Query()] = "active",
    posted_within_hours: Annotated[int | None, Query(ge=1, le=24 * 90)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListingPage:
    query = select(JobListing)
    if source_status != "all":
        query = query.where(JobListing.source_status == source_status)
    if posted_within_hours is not None:
        # Listings without a source-stated posting date are excluded, never guessed.
        query = query.where(
            JobListing.posted_at >= utc_now() - timedelta(hours=posted_within_hours)
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(
            JobListing.posted_at.desc().nulls_last(),
            JobListing.first_seen_at.desc(),
            JobListing.id,
        )
        .limit(limit)
        .offset(offset)
    )
    return JobListingPage(
        items=[JobListingRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/job-listings/{listing_id}", response_model=JobListingDetailRead)
def read_job_listing(listing_id: UUID, session: DatabaseSession) -> JobListingDetailRead:
    row = session.get(JobListing, listing_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")
    return JobListingDetailRead.model_validate(row)


@router.get("/job-discovery/runs", response_model=list[JobDiscoveryRunRead])
def list_discovery_runs(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[JobDiscoveryRun]:
    return list(
        session.scalars(
            select(JobDiscoveryRun)
            .order_by(JobDiscoveryRun.started_at.desc(), JobDiscoveryRun.id)
            .limit(limit)
        )
    )
