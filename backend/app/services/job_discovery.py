"""Source-independent job discovery: store, deduplicate and verify listings.

Source adapters only translate a source's response into ``SourceListing`` facts.
This module never infers values a source did not state.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import JobDiscoveryRun, JobListing
from app.models.job_listing import DISCOVERY_ERROR_CATEGORIES
from app.services.auth import utc_now

MAX_TITLE_LENGTH = 300
MAX_EMPLOYER_LENGTH = 200
MAX_LOCATION_LENGTH = 500
MAX_URL_LENGTH = 2048


class SourceFetchError(Exception):
    def __init__(self, category: str) -> None:
        if category not in DISCOVERY_ERROR_CATEGORIES:
            raise ValueError(f"Unknown discovery error category: {category}")
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class SourceListing:
    source_listing_id: str
    source_url: str
    application_url: str
    employer_name: str
    title: str
    description_text: str | None = None
    location_text: str | None = None
    stated_workplace_type: str | None = None
    stated_countries: Sequence[str] = field(default_factory=tuple)
    posted_at: datetime | None = None
    source_updated_at: datetime | None = None
    application_deadline: date | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    # The public vacancy page, when the source states one separately from the
    # application form. Kept distinct: a working page does not prove a working form.
    listing_url: str | None = None


class JobSource(Protocol):
    kind: str
    key: str
    # Optional: complete_snapshot = False for feeds that show only a recent window
    # (aggregators). Their absent listings are never marked missing_from_source.

    def fetch(self) -> list[SourceListing]:
        """Return every listing currently published, or raise SourceFetchError."""


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())


def _normalize_for_key(value: str | None) -> str:
    return _clean(value).casefold()


def dedupe_key(employer_name: str, title: str, location_text: str | None) -> str:
    """Fallback cross-source duplicate grouping; not a uniqueness constraint."""
    parts = [_normalize_for_key(employer_name), _normalize_for_key(title), _normalize_for_key(location_text)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def content_hash(listing: SourceListing) -> str:
    payload = {
        "application_url": listing.application_url,
        "listing_url": listing.listing_url,
        "employer_name": listing.employer_name,
        "title": listing.title,
        "description_text": listing.description_text,
        "location_text": listing.location_text,
        "stated_workplace_type": listing.stated_workplace_type,
        "stated_countries": sorted(listing.stated_countries),
        "posted_at": listing.posted_at.isoformat() if listing.posted_at else None,
        "source_updated_at": listing.source_updated_at.isoformat() if listing.source_updated_at else None,
        "application_deadline": listing.application_deadline.isoformat() if listing.application_deadline else None,
        "salary": [str(listing.salary_min), str(listing.salary_max), listing.salary_currency, listing.salary_period],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def invalid_reason(listing: SourceListing) -> str | None:
    """Why a source entry cannot be stored, or None when it is usable."""
    if not _clean(listing.source_listing_id):
        return "missing source listing id"
    if not _clean(listing.title):
        return "missing title"
    if not _clean(listing.employer_name):
        return "missing employer name"
    if not listing.application_url.startswith("https://") or len(listing.application_url) > MAX_URL_LENGTH:
        return "no usable https application URL"
    if listing.listing_url is not None and (
        not listing.listing_url.startswith("https://") or len(listing.listing_url) > MAX_URL_LENGTH
    ):
        return "listing URL is not a usable https URL"
    if len(listing.source_url) > MAX_URL_LENGTH:
        return "source URL too long"
    if len(_clean(listing.title)) > MAX_TITLE_LENGTH or len(_clean(listing.employer_name)) > MAX_EMPLOYER_LENGTH:
        return "title or employer name too long"
    if len(_clean(listing.location_text)) > MAX_LOCATION_LENGTH:
        return "location text too long"
    if listing.stated_workplace_type not in (None, "remote", "hybrid", "onsite"):
        return "unrecognised workplace type"
    if not (listing.salary_min is None and listing.salary_max is None or listing.salary_currency):
        return "salary without currency"
    return None


def _is_valid(listing: SourceListing) -> bool:
    return invalid_reason(listing) is None


def _apply_facts(row: JobListing, listing: SourceListing, digest: str) -> None:
    row.source_url = listing.source_url
    row.listing_url = listing.listing_url
    row.application_url = listing.application_url
    row.employer_name = _clean(listing.employer_name)
    row.title = _clean(listing.title)
    row.description_text = listing.description_text
    row.location_text = _clean(listing.location_text) or None
    row.stated_workplace_type = listing.stated_workplace_type
    row.stated_countries = sorted(set(listing.stated_countries))
    row.posted_at = listing.posted_at
    row.source_updated_at = listing.source_updated_at
    row.application_deadline = listing.application_deadline
    row.salary_min = listing.salary_min
    row.salary_max = listing.salary_max
    row.salary_currency = listing.salary_currency
    row.salary_period = listing.salary_period
    row.content_hash = digest
    row.dedupe_key = dedupe_key(listing.employer_name, listing.title, listing.location_text)


def run_discovery(session: Session, source: JobSource, now: datetime | None = None) -> JobDiscoveryRun:
    """Fetch one source and reconcile its listings.

    The run row is committed before fetching so an interrupted or failed run is
    still recorded. Listings are only marked missing after a fully successful
    fetch; a failed fetch leaves every stored listing untouched.
    """
    started = utc_now() if now is None else now
    run = JobDiscoveryRun(
        source_kind=source.kind, source_key=source.key, status="running", started_at=started
    )
    session.add(run)
    session.commit()

    try:
        fetched = source.fetch()
    except SourceFetchError as exc:
        run.status = "failed"
        run.error_category = exc.category
        run.finished_at = utc_now() if now is None else now
        session.commit()
        return run

    try:
        return _reconcile(session, source, run, fetched, started, now)
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        # IntegrityError here means another run stored the same listing first.
        run.error_category = "conflict" if isinstance(exc, IntegrityError) else "internal_error"
        run.finished_at = utc_now() if now is None else now
        session.commit()
        raise


def _reconcile(
    session: Session,
    source: JobSource,
    run: JobDiscoveryRun,
    fetched: list[SourceListing],
    started: datetime,
    now: datetime | None,
) -> JobDiscoveryRun:
    seen_ids: set[str] = set()
    created = updated = unchanged = skipped = 0
    skip_reasons: dict[str, int] = {}
    existing = {
        row.source_listing_id: row
        for row in session.scalars(
            select(JobListing).where(
                JobListing.source_kind == source.kind, JobListing.source_key == source.key
            )
        )
    }
    for listing in fetched:
        listing_id = _clean(listing.source_listing_id)
        reason = invalid_reason(listing) or ("duplicate in response" if listing_id in seen_ids else None)
        if reason is not None:
            skipped += 1
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        seen_ids.add(listing_id)
        digest = content_hash(listing)
        row = existing.get(listing_id)
        if row is None:
            row = JobListing(
                source_kind=source.kind,
                source_key=source.key,
                source_listing_id=listing_id,
                first_seen_at=started,
                last_seen_at=started,
                last_verified_at=started,
                source_status="active",
            )
            _apply_facts(row, listing, digest)
            row.source_category = getattr(source, "category", None)
            session.add(row)
            created += 1
            continue
        if row.content_hash != digest:
            _apply_facts(row, listing, digest)
            updated += 1
        else:
            unchanged += 1
        if row.source_status == "missing_from_source":
            # Resurfaced after the source had dropped it; the posting date is left as stated.
            row.relisted_at = started
        row.source_category = getattr(source, "category", None) or row.source_category
        row.last_seen_at = started
        row.last_verified_at = started
        row.source_status = "active"

    missing = 0
    # A windowed feed (aggregators) dropping a job proves nothing about the vacancy.
    complete = getattr(source, "complete_snapshot", True)
    for listing_id, row in existing.items() if complete else ():
        if listing_id not in seen_ids and row.source_status != "missing_from_source":
            row.source_status = "missing_from_source"
            row.last_verified_at = started
            missing += 1

    run.status = "succeeded"
    run.fetched_count = len(fetched)
    run.created_count = created
    run.updated_count = updated
    run.unchanged_count = unchanged
    run.missing_count = missing
    run.skipped_count = skipped
    run.skip_reasons = skip_reasons
    run.finished_at = utc_now() if now is None else now
    session.commit()
    return run
