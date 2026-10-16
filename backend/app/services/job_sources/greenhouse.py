"""Greenhouse Job Board API adapter (official employer-published job boards).

Docs: https://docs.greenhouse.io/job-board.html — "Job Board data is publicly
available, so authentication is not required for any GET endpoints."
The list endpoint documents ``updated_at`` but not a first-published date, so
``posted_at`` is only set when the response actually contains ``first_published``.
"""
from collections.abc import Callable
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
import json
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.job_discovery import SourceFetchError, SourceListing

API_HOST = "https://boards-api.greenhouse.io"
BOARD_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}\Z")
REQUEST_TIMEOUT_SECONDS = 20
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_DESCRIPTION_CHARACTERS = 100_000
USER_AGENT = "JobPilotAI/0.1 (personal local job search)"

Fetcher = Callable[[str], bytes]


class _TextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    # Greenhouse entity-encodes the HTML (sometimes twice); decode until stable.
    decoded = value
    for _ in range(3):
        next_value = unescape(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    parser = _TextExtractor()
    parser.feed(decoded)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    return text[:MAX_DESCRIPTION_CHARACTERS] or None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _parse_date(value: Any) -> date | None:
    parsed = _parse_datetime(value)
    return parsed.date() if parsed else None


def default_fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https host
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            raise SourceFetchError("not_found") from None
        if exc.code == 429:
            raise SourceFetchError("rate_limited") from None
        raise SourceFetchError("unavailable") from None
    except (TimeoutError, socket.timeout):
        raise SourceFetchError("timeout") from None
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise SourceFetchError("timeout") from None
        raise SourceFetchError("unavailable") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise SourceFetchError("too_large")
    return body


class GreenhouseBoardSource:
    kind = "greenhouse"

    def __init__(self, board_token: str, employer_name: str, fetcher: Fetcher = default_fetch) -> None:
        token = board_token.strip().lower()
        if not BOARD_TOKEN_PATTERN.fullmatch(token):
            raise ValueError("Greenhouse board tokens contain only letters, digits, '-' and '_'.")
        if not employer_name.strip():
            raise ValueError("An employer name is required for a Greenhouse board.")
        self.key = token
        # The list endpoint does not document company_name; the operator states it.
        self.employer_name = employer_name.strip()
        self.api_url = f"{API_HOST}/v1/boards/{token}/jobs?content=true"
        self._fetch = fetcher

    def fetch(self) -> list[SourceListing]:
        try:
            payload = json.loads(self._fetch(self.api_url))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SourceFetchError("invalid_response") from None
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            raise SourceFetchError("invalid_response")
        return [self._to_listing(job) for job in jobs if isinstance(job, dict)]

    def _to_listing(self, job: dict[str, Any]) -> SourceListing:
        location = job.get("location")
        location_name = location.get("name") if isinstance(location, dict) else None
        company_name = job.get("company_name")
        return SourceListing(
            source_listing_id=str(job.get("id") or "").strip(),
            source_url=self.api_url,
            application_url=str(job.get("absolute_url") or "").strip(),
            employer_name=company_name.strip() if isinstance(company_name, str) and company_name.strip() else self.employer_name,
            title=str(job.get("title") or ""),
            description_text=html_to_text(job.get("content") if isinstance(job.get("content"), str) else None),
            location_text=location_name if isinstance(location_name, str) else None,
            posted_at=_parse_datetime(job.get("first_published")),
            source_updated_at=_parse_datetime(job.get("updated_at")),
            application_deadline=_parse_date(job.get("application_deadline")),
        )
