"""Rate-limited checks of a listing's vacancy page and application link.

Links are only requested over HTTPS on hosts that belong to the listing's source
(its ATS platform or the employer's official domain). Redirects are followed
manually and must stay on those hosts. A "reachable" result means the page
answered; it does not prove the vacancy is open or that the application form
works. No form is submitted and no candidate data is sent.
"""
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import JobListing, JobListingLinkCheck
from app.services.auth import utc_now
from app.services.source_registry import ATS_PAGE_HOSTS, SourceEntry, entry_for_source

TIMEOUT_SECONDS = 20
MAX_REDIRECTS = 5
READ_BYTES = 64 * 1024
USER_AGENT = "JobPilotAI/0.1 (personal local job search; link check)"
LOGIN_HINTS = ("/login", "/signin", "/sign_in", "/sign-in", "/users/sign_in", "/auth/")


@dataclass(frozen=True)
class LinkResult:
    outcome: str
    final_url: str | None
    http_status: int | None
    detail: str


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # surface 3xx as HTTPError so each hop is validated here


def open_once(url: str):
    """Network seam: one GET without following redirects. Tests replace this."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    return build_opener(_NoRedirect()).open(request, timeout=TIMEOUT_SECONDS)


def _owner(kind: str, entry: SourceEntry | None) -> Callable[[str | None], bool]:
    if entry is not None:
        return entry.owns_host
    hosts = ATS_PAGE_HOSTS.get(kind, ())
    return lambda host: bool(host) and host.lower() in hosts


def check_link(url: str, owns_host: Callable[[str | None], bool], *, opener=None) -> LinkResult:
    opener = opener or open_once
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        if parts.scheme != "https":
            return LinkResult("insecure", current, None, "Only https links are checked.")
        if not owns_host(parts.hostname):
            outcome = "unverified_domain" if current == url else "redirected_off_domain"
            return LinkResult(outcome, current, None, f"Host {parts.hostname} does not belong to this source.")
        try:
            with opener(current) as response:
                response.read(READ_BYTES)
                status = getattr(response, "status", 200)
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                location = exc.headers.get("Location") if exc.headers else None
                if not location:
                    return LinkResult("broken", current, exc.code, "Redirect without a location.")
                current = urljoin(current, location)
                continue
            if exc.code in (404, 410):
                return LinkResult("expired", current, exc.code, "The page is gone at the source.")
            if exc.code in (401, 403):
                return LinkResult("auth_required", current, exc.code, "The page requires sign-in or refused access.")
            if exc.code == 429:
                return LinkResult("rate_limited", current, exc.code, "The site asked to slow down; not verified.")
            return LinkResult("broken", current, exc.code, f"The site answered HTTP {exc.code}.")
        except (TimeoutError, socket.timeout, URLError, OSError):
            return LinkResult("unreachable", current, None, "The page could not be reached.")
        final = urlsplit(current)
        if "error" in parse_qs(final.query) and final.hostname in ATS_PAGE_HOSTS["greenhouse"]:
            return LinkResult("expired", current, status, "Greenhouse redirected to the board with an error: posting not found.")
        if any(hint in final.path.lower() for hint in LOGIN_HINTS):
            return LinkResult("auth_required", current, status, "The link leads to a sign-in page.")
        return LinkResult("reachable", current, status, "The page answered on the source's own host.")
    return LinkResult("broken", current, None, "Too many redirects.")


def verify_listing_links(
    session: Session,
    listing: JobListing,
    *,
    opener=None,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
    delay_seconds: float = 0.0,
) -> list[JobListingLinkCheck]:
    owns = _owner(listing.source_kind, entry_for_source(listing.source_kind, listing.source_key))
    checked_at = now or utc_now()
    rows: list[JobListingLinkCheck] = []
    page_result = None
    if listing.listing_url:
        page_result = check_link(listing.listing_url, owns, opener=opener)
        rows.append(_row(listing, "listing", listing.listing_url, page_result, checked_at))
    if listing.listing_url and listing.application_url == listing.listing_url and page_result is not None:
        detail = page_result.detail + " The application form is on this page; the form itself was not tested."
        rows.append(_row(listing, "application", listing.application_url, LinkResult(page_result.outcome, page_result.final_url, page_result.http_status, detail[:500]), checked_at))
    else:
        if page_result is not None and delay_seconds:
            sleep(delay_seconds)
        result = check_link(listing.application_url, owns, opener=opener)
        rows.append(_row(listing, "application", listing.application_url, result, checked_at))
    session.add_all(rows)
    return rows


def _row(listing: JobListing, kind: str, url: str, result: LinkResult, checked_at: datetime) -> JobListingLinkCheck:
    return JobListingLinkCheck(
        job_listing_id=listing.id, url_kind=kind, url=url, final_url=result.final_url,
        outcome=result.outcome, http_status=result.http_status, detail=result.detail[:500], checked_at=checked_at,
    )


def latest_link_checks(session: Session, listing_ids) -> dict:
    """{listing_id: {"listing": check, "application": check}} for the newest check of each kind."""
    ids = list(listing_ids)
    if not ids:
        return {}
    ranked = select(
        JobListingLinkCheck.id,
        func.row_number().over(
            partition_by=(JobListingLinkCheck.job_listing_id, JobListingLinkCheck.url_kind),
            order_by=(JobListingLinkCheck.checked_at.desc(), JobListingLinkCheck.id.desc()),
        ).label("position"),
    ).where(JobListingLinkCheck.job_listing_id.in_(ids)).subquery()
    rows = session.scalars(
        select(JobListingLinkCheck).where(
            JobListingLinkCheck.id.in_(select(ranked.c.id).where(ranked.c.position == 1))
        )
    )
    result: dict = {}
    for row in rows:
        result.setdefault(row.job_listing_id, {})[row.url_kind] = row
    return result


def listings_due_for_check(session: Session, limit: int, source_kind: str | None = None, source_key: str | None = None) -> list[JobListing]:
    """Active listings, never-checked first, then those checked longest ago."""
    last_checked = (
        select(JobListingLinkCheck.job_listing_id, func.max(JobListingLinkCheck.checked_at).label("checked_at"))
        .group_by(JobListingLinkCheck.job_listing_id)
        .subquery()
    )
    query = (
        select(JobListing)
        .outerjoin(last_checked, last_checked.c.job_listing_id == JobListing.id)
        .where(JobListing.source_status == "active")
    )
    if source_kind is not None:
        query = query.where(JobListing.source_kind == source_kind, JobListing.source_key == source_key)
    return list(
        session.scalars(
            query.order_by(last_checked.c.checked_at.asc().nulls_first(), JobListing.first_seen_at, JobListing.id).limit(limit)
        )
    )
