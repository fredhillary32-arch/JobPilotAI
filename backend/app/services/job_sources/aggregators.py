"""Free public job-board aggregator APIs (discovery sources, never eligibility authorities).

Each adapter reads one documented, keyless public endpoint through the shared
host-pinned fetcher (timeouts, bounded retries with backoff, size limits). Terms
were read on 2026-10-17 and are recorded in the source registry:

- Jobicy  https://jobicy.com/jobs-rss-feed — public API, no token; "Start a new
  automated pass no more than once per hour"; listings must keep the canonical
  Jobicy URL and credit Jobicy. The feed covers the last 7 days, cursor-paged.
- Arbeitnow  https://www.arbeitnow.com/blog/job-board-api — free public API, no
  key; "please do not abuse ... linking back"; ``?page=`` pagination, newest first.
- Remote OK  https://remoteok.com/api and https://remoteok.com/legal — link back to
  the Remote OK URL and name Remote OK as the source; element 0 is a legal notice.

These feeds are windows onto recent postings, not complete snapshots, so a job
absent from one response is never marked as removed (``complete_snapshot`` is
False). The date stored as ``posted_at`` is the board's own publication date,
which the API reports as ``job_board``-sourced; it is never JobPilot's discovery
time. Every listing links to the aggregator's canonical page, as their terms
require. Nothing about the candidate is ever sent to these services.
"""
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode, urlsplit

from app.services.job_discovery import SourceFetchError, SourceListing
from app.services.job_sources.greenhouse import MAX_DESCRIPTION_CHARACTERS, html_to_text
from app.services.job_sources.http import fetch_json

JsonFetcher = Callable[[str], Any]
# Hard caps per run: incremental refresh normally stops much earlier.
JOBICY_MAX_PAGES = 10
JOBICY_PAGE_SIZE = 200
ARBEITNOW_MAX_PAGES = 5
# How far before the last successful run an incremental Arbeitnow pass still reads.
INCREMENTAL_OVERLAP = timedelta(hours=24)


def _text(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _https_on(url: Any, hosts: tuple[str, ...]) -> str | None:
    """The URL when it is https on one of the board's own hosts, else None."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not any(host == item or host.endswith(f".{item}") for item in hosts):
        return None
    return url.strip()


def _iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _epoch(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _description(value: Any) -> str | None:
    text = html_to_text(value) if isinstance(value, str) else None
    return text[:MAX_DESCRIPTION_CHARACTERS] if text else None


def _amount(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value in (None, "", 0):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


class AggregatorSource:
    """Common shape: kind, a fixed key, category and the snapshot flag."""

    kind = ""
    key = "public"
    category = "aggregator"
    complete_snapshot = False
    # The minimum gap between automatic passes this source's terms ask for.
    min_interval = timedelta(minutes=0)

    def __init__(self, *, fetcher: JsonFetcher | None = None, since: datetime | None = None) -> None:
        self._fetch = fetcher or (lambda url: fetch_json(url, allowed_hosts=frozenset(self.api_hosts)))
        self.since = since
        self.pages_read = 0

    api_hosts: tuple[str, ...] = ()
    page_hosts: tuple[str, ...] = ()


class JobicySource(AggregatorSource):
    kind = "jobicy"
    api_hosts = ("jobicy.com",)
    page_hosts = ("jobicy.com",)
    min_interval = timedelta(hours=1)
    base_url = "https://jobicy.com/api/v2/remote-jobs"

    def fetch(self) -> list[SourceListing]:
        listings: list[SourceListing] = []
        cursor = None
        for _ in range(JOBICY_MAX_PAGES):
            params = {"count": JOBICY_PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
            url = f"{self.base_url}?{urlencode(params)}"
            payload = self._fetch(url)
            self.pages_read += 1
            jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if isinstance(payload, dict) and jobs is None and payload.get("jobCount") == 0:
                break  # an empty feed is a valid, successful answer
            if not isinstance(jobs, list):
                raise SourceFetchError("invalid_response")
            listings += [self._to_listing(job, url) for job in jobs if isinstance(job, dict)]
            cursor = payload.get("nextCursor")
            if not cursor or payload.get("hasMore") is False or not isinstance(cursor, str):
                break
        return listings

    def _to_listing(self, job: dict[str, Any], source_url: str) -> SourceListing:
        page = _https_on(job.get("url"), self.page_hosts) or ""
        currency = _text(job.get("salaryCurrency")).upper()
        low, high = _amount(job.get("salaryMin")), _amount(job.get("salaryMax"))
        salary_ok = len(currency) == 3 and currency.isalpha() and (low is None or high is None or high >= low)
        identifier = job.get("id")
        return SourceListing(
            source_listing_id=str(identifier) if isinstance(identifier, (int, str)) and not isinstance(identifier, bool) else "",
            source_url=source_url,
            listing_url=page or None,
            application_url=page,
            employer_name=_text(job.get("companyName")),
            title=_text(job.get("jobTitle")),
            description_text=_description(job.get("jobDescription")) or _description(job.get("jobExcerpt")),
            location_text=_text(job.get("jobGeo")) or None,
            # Jobicy publishes remote jobs only ("Remote Jobs API").
            stated_workplace_type="remote",
            posted_at=_iso(job.get("pubDate")),
            salary_min=low if salary_ok else None,
            salary_max=high if salary_ok else None,
            salary_currency=currency if salary_ok and (low or high) else None,
            salary_period=(_text(job.get("salaryPeriod")).lower()[:20] or None) if salary_ok and (low or high) else None,
        )


class ArbeitnowSource(AggregatorSource):
    kind = "arbeitnow"
    api_hosts = ("www.arbeitnow.com",)
    # Arbeitnow's own country sites, as returned in its API's listing URLs (observed 2026-10-17).
    page_hosts = ("arbeitnow.com", "arbeitnow.nl", "arbeitnow.co.uk", "arbeitnow.fr", "arbeitnow.ch")
    base_url = "https://www.arbeitnow.com/api/job-board-api"

    def fetch(self) -> list[SourceListing]:
        listings: list[SourceListing] = []
        cutoff = self.since - INCREMENTAL_OVERLAP if self.since else None
        for page in range(1, ARBEITNOW_MAX_PAGES + 1):
            url = f"{self.base_url}?page={page}"
            payload = self._fetch(url)
            self.pages_read += 1
            jobs = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(jobs, list):
                raise SourceFetchError("invalid_response")
            batch = [self._to_listing(job, url) for job in jobs if isinstance(job, dict)]
            listings += batch
            # Newest first: once a page reaches jobs older than the last successful run
            # (with overlap), later pages hold nothing new.
            older = cutoff is not None and any(item.posted_at and item.posted_at < cutoff for item in batch)
            links = payload.get("links") if isinstance(payload.get("links"), dict) else {}
            if not jobs or older or not links.get("next"):
                break
        return listings

    def _to_listing(self, job: dict[str, Any], source_url: str) -> SourceListing:
        page = _https_on(job.get("url"), self.page_hosts) or ""
        return SourceListing(
            source_listing_id=_text(job.get("slug")),
            source_url=source_url,
            listing_url=page or None,
            application_url=page,
            employer_name=_text(job.get("company_name")),
            title=_text(job.get("title")),
            description_text=_description(job.get("description")),
            location_text=_text(job.get("location")) or None,
            # Only a stated remote flag is used; false does not mean on-site.
            stated_workplace_type="remote" if job.get("remote") is True else None,
            posted_at=_epoch(job.get("created_at")),
        )


class RemoteOkSource(AggregatorSource):
    kind = "remoteok"
    api_hosts = ("remoteok.com",)
    page_hosts = ("remoteok.com",)
    base_url = "https://remoteok.com/api"

    def fetch(self) -> list[SourceListing]:
        payload = self._fetch(self.base_url)
        self.pages_read += 1
        if not isinstance(payload, list):
            raise SourceFetchError("invalid_response")
        # Element 0 is Remote OK's legal notice, not a job.
        jobs = [item for item in payload if isinstance(item, dict) and "legal" not in item]
        return [self._to_listing(job) for job in jobs]

    def _to_listing(self, job: dict[str, Any]) -> SourceListing:
        page = _https_on(job.get("url"), self.page_hosts) or ""
        apply = _https_on(job.get("apply_url"), self.page_hosts) or page
        identifier = job.get("id")
        return SourceListing(
            source_listing_id=str(identifier) if isinstance(identifier, (int, str)) and not isinstance(identifier, bool) else "",
            source_url=self.base_url,
            listing_url=page or None,
            application_url=apply,
            employer_name=_text(job.get("company")),
            title=_text(job.get("position")),
            description_text=_description(job.get("description")),
            location_text=_text(job.get("location")) or None,
            # Remote OK lists remote jobs only.
            stated_workplace_type="remote",
            posted_at=_iso(job.get("date")) or _epoch(job.get("epoch")),
        )


AGGREGATOR_SOURCES: dict[str, type[AggregatorSource]] = {
    source.kind: source for source in (JobicySource, ArbeitnowSource, RemoteOkSource)
}
