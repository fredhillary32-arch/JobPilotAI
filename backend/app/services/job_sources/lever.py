"""Lever public postings API adapter.

Docs: https://github.com/lever/postings-api — "the Postings API is public and
does not require authentication". GET /v0/postings/{site}?mode=json returns the
site's published postings. ``createdAt`` (epoch milliseconds) is the posting's
creation time as Lever reports it; it is stored as the posting date and nothing
else is inferred.
"""

import re
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.job_discovery import SourceFetchError, SourceListing
from app.services.job_sources.greenhouse import MAX_DESCRIPTION_CHARACTERS, html_to_text
from app.services.job_sources.http import fetch_json

HOSTS = {"global": "api.lever.co", "eu": "api.eu.lever.co"}
SITE_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,99}\Z")
WORKPLACE = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}

JsonFetcher = Callable[[str], Any]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


class LeverPostingsSource:
    kind = "lever"

    def __init__(
        self, site: str, employer_name: str, *, instance: str = "global", fetcher: JsonFetcher | None = None
    ) -> None:
        site = site.strip().lower()
        if not SITE_PATTERN.fullmatch(site):
            raise ValueError("Lever site names contain only letters, digits, '.', '-' and '_'.")
        if instance not in HOSTS:
            raise ValueError("Lever instance must be 'global' or 'eu'.")
        if not employer_name.strip():
            raise ValueError("An employer name is required for a Lever site.")
        self.key = site if instance == "global" else f"eu:{site}"
        self.employer_name = employer_name.strip()
        host = HOSTS[instance]
        self.api_url = f"https://{host}/v0/postings/{site}?mode=json"
        self._fetch = fetcher or (lambda url: fetch_json(url, allowed_hosts=frozenset({host})))

    def fetch(self) -> list[SourceListing]:
        payload = self._fetch(self.api_url)
        if not isinstance(payload, list):
            raise SourceFetchError("invalid_response")
        return [self._to_listing(item) for item in payload if isinstance(item, dict)]

    def _to_listing(self, posting: dict[str, Any]) -> SourceListing:
        categories = posting.get("categories") if isinstance(posting.get("categories"), dict) else {}
        locations = [_text(categories.get("location"))]
        all_locations = categories.get("allLocations")
        if isinstance(all_locations, list):
            locations.extend(_text(item) for item in all_locations)
        location_text = "; ".join(dict.fromkeys(item for item in locations if item)) or None
        sections = [_text(posting.get("descriptionPlain")) or html_to_text(posting.get("description")) or ""]
        for block in posting.get("lists") if isinstance(posting.get("lists"), list) else []:
            if isinstance(block, dict):
                body = html_to_text(block.get("content")) or ""
                sections.append("\n".join(part for part in (_text(block.get("text")), body) if part))
        sections.append(_text(posting.get("additionalPlain")) or html_to_text(posting.get("additional")) or "")
        description = "\n\n".join(part for part in sections if part).strip()[:MAX_DESCRIPTION_CHARACTERS] or None
        created = posting.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            if isinstance(created, (int, float)) and not isinstance(created, bool) and created > 0
            else None
        )
        salary = posting.get("salaryRange") if isinstance(posting.get("salaryRange"), dict) else {}
        currency = _text(salary.get("currency")).upper()
        country = _text(posting.get("country")).upper()
        hosted = _text(posting.get("hostedUrl"))
        return SourceListing(
            source_listing_id=_text(posting.get("id")),
            source_url=self.api_url,
            listing_url=hosted or None,
            application_url=_text(posting.get("applyUrl")) or hosted,
            employer_name=self.employer_name,
            title=_text(posting.get("text")),
            description_text=description,
            location_text=location_text,
            stated_workplace_type=WORKPLACE.get(_text(posting.get("workplaceType")).lower()),
            stated_countries=(country,) if re.fullmatch(r"[A-Z]{2}", country) else (),
            posted_at=posted_at,
            salary_min=_decimal(salary.get("min")) if currency else None,
            salary_max=_decimal(salary.get("max")) if currency else None,
            salary_currency=currency if re.fullmatch(r"[A-Z]{3}", currency) else None,
            salary_period=_text(salary.get("interval"))[:20] or None,
        )
