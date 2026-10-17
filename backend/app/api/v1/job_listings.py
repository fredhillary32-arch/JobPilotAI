from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import aliased

from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import JobDiscoveryRun, JobListing, JobListingLinkCheck, ListingEligibilityAssessment
from app.schemas.job_listing import (
    AlternateListingRead,
    EligibilityAssessmentRead,
    EligibilityStatus,
    JobDiscoveryRunRead,
    JobListingDetailRead,
    JobListingPage,
    JobListingRead,
    LinkCheckRead,
    ListingLinksRead,
    ListingSourceRead,
)
from app.services.auth import utc_now
from app.services.discovery_runner import effective_run_status
from app.services.eligibility import (
    effective_eligibility,
    effective_status_sql,
    latest_assessment_ids,
    latest_assessments_for,
)
from app.services.kenya_eligibility import decide_cached
from app.services.link_verification import latest_link_checks
from app.services.role_relevance import CANDIDATE_SUBSTRINGS, classify_title
from app.services.source_registry import entry_for_source, load_registry

# Discovered listings are public source facts shared by the local owner; every
# route still requires an authenticated session. This router never contacts external
# sources; discovery runs from the operator CLI or the background refresh in
# app.api.v1.job_discovery.
router = APIRouter(
    tags=["job discovery"],
    dependencies=[Depends(require_authenticated_resource_access)],
)

# Canonical choice among duplicates: the employer's own posting first, aggregators last.
CATEGORY_PRIORITY = case(
    (JobListing.source_category == "direct_employer", 0),
    (JobListing.source_category == "recruitment_outsourcing", 1),
    (JobListing.source_category == "staffing_agency", 2),
    (JobListing.source_category == "aggregator", 3),
    else_=4,
)


def _get_listing_or_404(listing_id: UUID, session: DatabaseSession) -> JobListing:
    row = session.get(JobListing, listing_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")
    return row


def _latest_check_exists(outcome: str, kind: str | None = None):
    """True when the newest check of a link kind (or of any kind) has this outcome."""
    check = aliased(JobListingLinkCheck)
    conditions = [
        check.job_listing_id == JobListing.id,
        check.outcome == outcome,
        check.checked_at
        == (
            select(func.max(JobListingLinkCheck.checked_at))
            .where(JobListingLinkCheck.job_listing_id == JobListing.id, JobListingLinkCheck.url_kind == check.url_kind)
            .correlate(JobListing, check)
            .scalar_subquery()
        ),
    ]
    if kind is not None:
        conditions.append(check.url_kind == kind)
    return exists().where(*conditions)


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _source_read(row: JobListing) -> ListingSourceRead:
    entry = entry_for_source(row.source_kind, row.source_key)
    if entry is None:
        return ListingSourceRead(registered=False)
    checked = entry.verification.get("checked_at")
    return ListingSourceRead(
        registered=True,
        registry_id=entry.id,
        name=entry.name,
        category=entry.category,
        official_domain=entry.official_domain,
        verification_outcome=entry.verification.get("outcome"),
        verification_checked_at=checked.replace("Z", "+00:00") if checked else None,
    )


def _enriched(
    row: JobListing, assessment, checks: dict, group_size: int, model=JobListingRead, decision: dict | None = None
):
    links = ListingLinksRead(
        listing=LinkCheckRead.model_validate(checks["listing"]) if "listing" in checks else None,
        application=LinkCheckRead.model_validate(checks["application"]) if "application" in checks else None,
    )
    if row.source_status == "missing_from_source":
        vacancy = "no_longer_listed"
    elif any(check.outcome == "expired" for check in checks.values()):
        vacancy = "link_expired"
    else:
        vacancy = "listed_by_source"
    return model.model_validate(row).model_copy(
        update={
            "eligibility": EligibilityAssessmentRead(**effective_eligibility(row, assessment)),
            "source": _source_read(row),
            "links": links,
            "vacancy_status": vacancy,
            "duplicate_group_size": group_size,
            "kenya_eligibility": decision if decision is not None else decide_cached(row, assessment, None),
            "role_match": _role_match(row.title),
            "posted_at_source": posted_at_source(row),
        }
    )


def posted_at_source(row: JobListing) -> str | None:
    """Where posted_at came from; never JobPilot's discovery time."""
    if row.posted_at is None:
        return None
    if row.source_category == "aggregator":
        return "job_board"  # the board's own publication date, not necessarily the employer's
    return "employer_board"


def _role_match(title: str) -> dict | None:
    match = classify_title(title)
    return match.as_dict() if match else None


def role_candidate_condition():
    """SQL superset of titles classify_title can accept (it never drops a match)."""
    return or_(*(JobListing.title.ilike(_like(term), escape="\\") for term in CANDIDATE_SUBSTRINGS))


RoleGroup = Literal["support_it", "customer_support", "ecommerce_support", "operations_support"]


def keyword_terms(q: str | None) -> list[str]:
    """Comma-separated keywords; a listing matches when any one term appears."""
    return [term.strip() for term in (q or "").split(",") if term.strip()][:10]


def keyword_condition(terms: list[str]):
    return or_(
        *(
            column.ilike(_like(term), escape="\\")
            for term in terms
            for column in (JobListing.title, JobListing.employer_name)
        )
    )


def source_condition(source: str):
    entry = next((item for item in load_registry() if item.id == source), None)
    if entry is None or entry.source_key is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown or manual-only source: {source}"
        )
    return (JobListing.source_kind == entry.source_kind) & (JobListing.source_key == entry.source_key)


def role_filter(groups: list[str] | None, excluded: list[str] | None):
    """A predicate on titles for the selected and excluded role groups, or None."""
    if not groups and not excluded:
        return None
    wanted, unwanted = set(groups or []), set(excluded or [])

    def keep(title: str) -> bool:
        match = classify_title(title)
        if wanted and (match is None or match.group not in wanted):
            return False
        return not (match is not None and match.group in unwanted)

    return keep


@router.get("/job-listings", response_model=JobListingPage)
def list_job_listings(
    session: DatabaseSession,
    source_status: Annotated[Literal["active", "missing_from_source", "all"], Query()] = "active",
    posted_within_hours: Annotated[int | None, Query(ge=1, le=24 * 90)] = None,
    eligibility: Annotated[EligibilityStatus | None, Query()] = None,
    eligible_scope: Annotated[Literal["kenya_named", "africa", "emea", "worldwide"] | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    role_family: Annotated[list[RoleGroup] | None, Query()] = None,
    exclude_role_family: Annotated[list[RoleGroup] | None, Query()] = None,
    source_category: Annotated[
        Literal["direct_employer", "staffing_agency", "recruitment_outsourcing", "aggregator"] | None, Query()
    ] = None,
    source: Annotated[str | None, Query(max_length=64)] = None,
    workplace: Annotated[Literal["remote", "hybrid", "onsite"] | None, Query()] = None,
    verified_application_link: Annotated[bool, Query()] = False,
    include_expired_links: Annotated[bool, Query()] = False,
    collapse_duplicates: Annotated[bool, Query()] = True,
    kenya: Annotated[Literal["eligible", "ineligible", "unverified", "needs_candidate_input"] | None, Query()] = None,
    sort: Annotated[Literal["posted", "discovered", "relevance"], Query()] = "posted",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JobListingPage:
    latest = latest_assessment_ids()
    assessment = aliased(ListingEligibilityAssessment)
    conditions = []
    if source_status != "all":
        conditions.append(JobListing.source_status == source_status)
    if posted_within_hours is not None:
        # Only a source-stated posting date counts; undated listings are never treated as fresh.
        # Future-dated timestamps are unreliable, so they are excluded too.
        now = utc_now()
        conditions += [JobListing.posted_at >= now - timedelta(hours=posted_within_hours), JobListing.posted_at <= now]
    effective = effective_status_sql(assessment)
    if eligibility is not None:
        conditions.append(effective == eligibility)
    if eligible_scope is not None:
        conditions += [effective == "eligible_confirmed", assessment.geographic_scope == eligible_scope]
    terms = keyword_terms(q)
    if terms:
        conditions.append(keyword_condition(terms))
    keep_role = role_filter(role_family, exclude_role_family)
    if role_family:
        # Database-side narrowing only; classify_title decides below, before totals and paging.
        conditions.append(role_candidate_condition())
    if source_category is not None:
        conditions.append(JobListing.source_category == source_category)
    if source is not None:
        conditions.append(source_condition(source))
    if workplace is not None:
        conditions.append(JobListing.stated_workplace_type == workplace)
    if verified_application_link:
        conditions.append(_latest_check_exists("reachable", "application"))
    if not include_expired_links:
        conditions.append(~_latest_check_exists("expired"))

    # Duplicates are the same vacancy reached through different sources. Listings
    # from the same source are separate openings even when their titles match.
    source_label = func.concat(JobListing.source_kind, ":", JobListing.source_key)
    ranked = (
        select(
            JobListing.id.label("id"),
            source_label.label("source_label"),
            func.first_value(source_label)
            .over(
                partition_by=JobListing.dedupe_key,
                order_by=(CATEGORY_PRIORITY, JobListing.first_seen_at, JobListing.id),
            )
            .label("preferred_source"),
            (
                func.count().over(partition_by=JobListing.dedupe_key)
                - func.count().over(partition_by=(JobListing.dedupe_key, JobListing.source_kind, JobListing.source_key))
                + 1
            ).label("group_size"),
        )
        .select_from(JobListing)
        .outerjoin(
            assessment,
            (assessment.job_listing_id == JobListing.id) & assessment.id.in_(select(latest.c.assessment_id)),
        )
        .where(*conditions)
        .subquery()
    )
    query = select(JobListing, ranked.c.group_size).join(ranked, ranked.c.id == JobListing.id)
    if collapse_duplicates:
        query = query.where(ranked.c.source_label == ranked.c.preferred_source)
    if sort == "discovered":
        ordered = query.order_by(JobListing.first_seen_at.desc(), JobListing.id)
    else:
        ordered = query.order_by(
            JobListing.posted_at.desc().nulls_last(), JobListing.first_seen_at.desc(), JobListing.id
        )
    decisions: dict = {}
    if kenya is None and keep_role is None and sort != "relevance":
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = session.execute(ordered.limit(limit).offset(offset)).all()
    else:
        # Role relevance and the strict Kenya state are decided in Python from the
        # text, so every candidate row is judged before totals and paging. The
        # candidate set is already narrowed by the SQL filters above.
        matching = session.execute(ordered).all()
        if keep_role is not None:
            matching = [(row, size) for row, size in matching if keep_role(row.title)]
        if kenya is not None:
            every_assessments = latest_assessments_for(session, [row.id for row, _ in matching])
            decisions = {row.id: decide_cached(row, every_assessments.get(row.id), None) for row, _ in matching}
            matching = [(row, size) for row, size in matching if decisions[row.id]["state"] == kenya]
        if sort == "relevance":
            # Role matches first (in the selected groups when any), then by posting date (stable sort).
            wanted = set(role_family or [])

            def relevance(item) -> int:
                match = classify_title(item[0].title)
                return 0 if match and (not wanted or match.group in wanted) else 1

            matching = sorted(matching, key=relevance)
        total, rows = len(matching), matching[offset : offset + limit]
    ids = [row.id for row, _ in rows]
    assessments = latest_assessments_for(session, ids)
    checks = latest_link_checks(session, ids)
    return JobListingPage(
        items=[
            _enriched(row, assessments.get(row.id), checks.get(row.id, {}), size, decision=decisions.get(row.id))
            for row, size in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/job-listings/{listing_id}", response_model=JobListingDetailRead)
def read_job_listing(listing_id: UUID, session: DatabaseSession) -> JobListingDetailRead:
    row = _get_listing_or_404(listing_id, session)
    alternates = list(
        session.scalars(
            select(JobListing)
            .where(
                JobListing.dedupe_key == row.dedupe_key,
                (JobListing.source_kind != row.source_kind) | (JobListing.source_key != row.source_key),
            )
            .order_by(CATEGORY_PRIORITY, JobListing.first_seen_at, JobListing.id)
        )
    )
    detail = _enriched(
        row,
        latest_assessments_for(session, [row.id]).get(row.id),
        latest_link_checks(session, [row.id]).get(row.id, {}),
        len(alternates) + 1,
        JobListingDetailRead,
    )
    return detail.model_copy(
        update={"alternates": [AlternateListingRead.model_validate(a, from_attributes=True) for a in alternates]}
    )


@router.get("/job-discovery/runs", response_model=list[JobDiscoveryRunRead])
def list_discovery_runs(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[JobDiscoveryRunRead]:
    runs = session.scalars(
        select(JobDiscoveryRun).order_by(JobDiscoveryRun.started_at.desc(), JobDiscoveryRun.id).limit(limit)
    )
    now = utc_now()
    reads = []
    for run in runs:
        entry = entry_for_source(run.source_kind, run.source_key)
        reads.append(
            JobDiscoveryRunRead.model_validate(run).model_copy(
                update={
                    "display_status": effective_run_status(run, now),
                    "source_id": entry.id if entry else None,
                    "source_name": entry.name if entry else None,
                }
            )
        )
    return reads


@router.get("/job-sources")
def list_job_sources(session: DatabaseSession) -> list[dict]:
    """The verified source registry with each source's recent run health."""
    runs = session.scalars(select(JobDiscoveryRun).order_by(JobDiscoveryRun.started_at.desc())).all()
    by_source: dict[tuple[str, str], list[JobDiscoveryRun]] = {}
    for run in runs:
        by_source.setdefault((run.source_kind, run.source_key), []).append(run)
    counts = dict(
        session.execute(
            select(func.concat(JobListing.source_kind, ":", JobListing.source_key), func.count())
            .where(JobListing.source_status == "active")
            .group_by(JobListing.source_kind, JobListing.source_key)
        ).all()
    )
    now = utc_now()
    sources = []
    for entry in load_registry():
        history = by_source.get((entry.source_kind, entry.source_key or ""), [])
        last_success = next((run for run in history if run.status == "succeeded"), None)
        failures = 0
        for run in history:
            if run.status == "succeeded":
                break
            failures += run.status == "failed"
        last_success_at = last_success.started_at if last_success else None
        if last_success_at is not None and last_success_at.tzinfo is None:
            last_success_at = last_success_at.replace(tzinfo=now.tzinfo)
        if entry.method == "manual":
            health = "manual_only"
        elif not entry.enabled:
            health = "disabled"
        elif not history:
            health = "never_run"
        elif failures >= 3:
            health = "failing"
        elif last_success_at is None or now - last_success_at > timedelta(days=7):
            health = "stale"
        else:
            health = "healthy"
        sources.append(
            {
                "id": entry.id,
                "name": entry.name,
                "category": entry.category,
                "official_domain": entry.official_domain,
                "careers_url": entry.careers_url,
                "method": entry.method,
                "board": entry.board,
                "enabled": entry.enabled,
                "verification": entry.verification,
                "terms": entry.terms,
                "limitations": entry.limitations,
                "health": health,
                "consecutive_failures": failures,
                "last_run_at": history[0].started_at if history else None,
                "last_run_status": history[0].status if history else None,
                "last_error_category": history[0].error_category if history else None,
                "last_success_at": last_success_at,
                "active_listings": counts.get(f"{entry.source_kind}:{entry.source_key}", 0),
            }
        )
    return sources
