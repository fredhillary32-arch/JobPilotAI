from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ELIGIBILITY_OUTCOMES = ("eligible_confirmed", "not_eligible", "eligibility_unknown")
EVIDENCE_FIELDS = ("description", "location")
STATEMENT_SCOPES = ("role", "company", "team", "market_or_customer", "unclear")
ROLE_APPLICABILITIES = ("direct", "established_by_wording", "unclear", "not_applicable")
# What the reviewed wording establishes geographically; recorded alongside the outcome.
GEOGRAPHIC_SCOPES = (
    "kenya_named",
    "africa",
    "emea",
    "worldwide",
    "other_countries",
    "restricted",
    "conflicting",
    "unclear",
    "awaiting_employer",
)
SCOPES_BY_OUTCOME = {
    "eligible_confirmed": ("kenya_named", "africa", "emea", "worldwide"),
    "not_eligible": ("other_countries", "restricted"),
    "eligibility_unknown": ("conflicting", "unclear", "awaiting_employer"),
}
# Only these may support a definite outcome (spec: company-wide statements).
DECIDING_APPLICABILITIES = ("direct", "established_by_wording")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class ListingEligibilityAssessment(Base):
    """A reviewed Kenya-eligibility judgement about one stored listing.

    Append-only: the newest row for a listing is its assessment. The examined
    description and location are copied so later wording changes are detected
    and quotations stay verifiable.
    """

    __tablename__ = "listing_eligibility_assessments"
    __table_args__ = (
        CheckConstraint(_in("outcome", ELIGIBILITY_OUTCOMES), name="ck_eligibility_outcome"),
        CheckConstraint(
            f"evidence_field IS NULL OR {_in('evidence_field', EVIDENCE_FIELDS)}",
            name="ck_eligibility_evidence_field",
        ),
        CheckConstraint(
            f"statement_scope IS NULL OR {_in('statement_scope', STATEMENT_SCOPES)}",
            name="ck_eligibility_statement_scope",
        ),
        CheckConstraint(
            f"role_applicability IS NULL OR {_in('role_applicability', ROLE_APPLICABILITIES)}",
            name="ck_eligibility_role_applicability",
        ),
        CheckConstraint(
            "outcome = 'eligibility_unknown' OR (quotation IS NOT NULL AND evidence_field IS NOT "
            f"NULL AND quote_start IS NOT NULL AND {_in('role_applicability', DECIDING_APPLICABILITIES)})",
            name="ck_eligibility_definite_needs_evidence",
        ),
        CheckConstraint("length(trim(explanation)) > 0", name="ck_eligibility_explanation"),
        CheckConstraint(
            f"geographic_scope IS NULL OR {_in('geographic_scope', GEOGRAPHIC_SCOPES)}",
            name="ck_eligibility_geographic_scope",
        ),
        Index(
            "ix_eligibility_listing_assessed",
            "job_listing_id",
            "assessed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_listing_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("job_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    assessed_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    quotation: Mapped[str | None] = mapped_column(Text)
    evidence_field: Mapped[str | None] = mapped_column(String(16))
    quote_start: Mapped[int | None] = mapped_column(Integer)
    statement_scope: Mapped[str | None] = mapped_column(String(24))
    role_applicability: Mapped[str | None] = mapped_column(String(32))
    geographic_scope: Mapped[str | None] = mapped_column(String(24))
    examined_description: Mapped[str | None] = mapped_column(Text)
    examined_location: Mapped[str | None] = mapped_column(String(500))
    listing_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    listing_source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    listing_last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
