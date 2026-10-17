"""Effective Kenya eligibility for stored listings (docs/JOB_ELIGIBILITY_SPEC.md).

An assessment only stays authoritative while the listing's description and
location are exactly the text it examined. Any change, including whitespace or
a value becoming null, makes it stale and the effective result unknown.
"""
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from app.models import JobListing, ListingEligibilityAssessment

UNKNOWN = "eligibility_unknown"
NOT_ASSESSED_REASON = "Eligibility for Kenya-based applicants has not been assessed."
STALE_REASON = "Eligibility evidence changed; reassessment needed."
OUTCOME_REASONS = {
    "eligible_confirmed": "The employer's own wording accepts applicants based in Kenya.",
    "not_eligible": "The employer's own wording rules out applicants based in Kenya.",
    UNKNOWN: "Kenya eligibility was reviewed but not established.",
}


def evidence_is_current(listing: JobListing, assessment: ListingEligibilityAssessment) -> bool:
    return (
        listing.description_text == assessment.examined_description
        and listing.location_text == assessment.examined_location
    )


def effective_eligibility(
    listing: JobListing,
    assessment: ListingEligibilityAssessment | None,
) -> dict:
    if assessment is None:
        return {"status": UNKNOWN, "reason": NOT_ASSESSED_REASON, "currency": "not_assessed"}
    details = {
        "assessment_id": assessment.id,
        "assessed_at": assessment.assessed_at,
        "explanation": assessment.explanation,
        "quotation": assessment.quotation,
        "evidence_field": assessment.evidence_field,
        "statement_scope": assessment.statement_scope,
        "role_applicability": assessment.role_applicability,
        "geographic_scope": assessment.geographic_scope,
    }
    if not evidence_is_current(listing, assessment):
        return {
            "status": UNKNOWN,
            "reason": STALE_REASON,
            "currency": "stale",
            "previous_status": assessment.outcome,
            **details,
        }
    return {
        "status": assessment.outcome,
        "reason": OUTCOME_REASONS[assessment.outcome],
        "currency": "current",
        **details,
    }


def latest_assessment_ids() -> Subquery:
    ranked = select(
        ListingEligibilityAssessment.id.label("assessment_id"),
        func.row_number()
        .over(
            partition_by=ListingEligibilityAssessment.job_listing_id,
            order_by=(
                ListingEligibilityAssessment.assessed_at.desc(),
                ListingEligibilityAssessment.id.desc(),
            ),
        )
        .label("position"),
    ).subquery()
    return select(ranked.c.assessment_id).where(ranked.c.position == 1).subquery()


def effective_status_sql(assessment) -> ColumnElement[str]:
    """SQL twin of effective_eligibility()['status'] for an outer-joined assessment."""
    current = and_(
        JobListing.description_text.is_not_distinct_from(assessment.examined_description),
        JobListing.location_text.is_not_distinct_from(assessment.examined_location),
    )
    return case(
        (assessment.id.is_(None), UNKNOWN),
        (current, assessment.outcome),
        else_=UNKNOWN,
    )


def latest_assessments_for(
    session: Session,
    listing_ids: Iterable[UUID],
) -> dict[UUID, ListingEligibilityAssessment]:
    ids = list(listing_ids)
    if not ids:
        return {}
    latest = latest_assessment_ids()
    rows = session.scalars(
        select(ListingEligibilityAssessment).where(
            ListingEligibilityAssessment.id.in_(select(latest.c.assessment_id)),
            ListingEligibilityAssessment.job_listing_id.in_(ids),
        )
    )
    return {row.job_listing_id: row for row in rows}
