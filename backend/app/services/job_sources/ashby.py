"""Ashby public job posting API adapter.

Docs: https://developers.ashbyhq.com/docs/public-job-posting-api — GET
/posting-api/job-board/{jobBoardName} is public and returns the board's
postings. Only postings with ``isListed`` true are stored. ``publishedAt`` is
the publication date Ashby reports; it is stored as the posting date.
"""
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit

from app.services.job_discovery import SourceFetchError, SourceListing
from app.services.job_sources.greenhouse import MAX_DESCRIPTION_CHARACTERS, html_to_text
from app.services.job_sources.http import fetch_json

HOST = "api.ashbyhq.com"
BOARD_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite"}
UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

JsonFetcher = Callable[[str], Any]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


class AshbyJobBoardSource:
    kind = "ashby"

    def __init__(self, board: str, employer_name: str, *, fetcher: JsonFetcher | None = None) -> None:
        board = board.strip()
        if not BOARD_PATTERN.fullmatch(board):
            raise ValueError("Ashby job board names contain only letters, digits, '.', '-' and '_'.")
        if not employer_name.strip():
            raise ValueError("An employer name is required for an Ashby job board.")
        self.key = board.lower()
        self.board = board
        self.employer_name = employer_name.strip()
        self.api_url = f"https://{HOST}/posting-api/job-board/{quote(board, safe='.-_')}?includeCompensation=true"
        self._fetch = fetcher or (lambda url: fetch_json(url, allowed_hosts=frozenset({HOST})))

    def fetch(self) -> list[SourceListing]:
        payload = self._fetch(self.api_url)
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise SourceFetchError("invalid_response")
        return [self._to_listing(job) for job in jobs if isinstance(job, dict) and job.get("isListed", True) is True]

    def _to_listing(self, job: dict[str, Any]) -> SourceListing:
        job_url = _text(job.get("jobUrl"))
        # Ashby's public API may omit an id; the posting UUID in its own jobUrl identifies it.
        identifier = _text(job.get("id"))
        if not identifier and job_url:
            match = UUID_PATTERN.search(urlsplit(job_url).path)
            identifier = match.group(0).lower() if match else ""
        locations = [_text(job.get("location"))]
        for extra in job.get("secondaryLocations") if isinstance(job.get("secondaryLocations"), list) else []:
            if isinstance(extra, dict):
                locations.append(_text(extra.get("location")))
        location_text = "; ".join(dict.fromkeys(item for item in locations if item)) or None
        description = (_text(job.get("descriptionPlain")) or html_to_text(job.get("descriptionHtml")) or "")
        workplace = WORKPLACE.get(_text(job.get("workplaceType")).replace("-", "").lower())
        if workplace is None and job.get("isRemote") is True:
            workplace = "remote"
        return SourceListing(
            source_listing_id=identifier,
            source_url=self.api_url,
            listing_url=job_url or None,
            application_url=_text(job.get("applyUrl")) or job_url,
            employer_name=self.employer_name,
            title=_text(job.get("title")),
            description_text=description[:MAX_DESCRIPTION_CHARACTERS] or None,
            location_text=location_text,
            stated_workplace_type=workplace,
            posted_at=_parse_datetime(job.get("publishedAt")),
        )
