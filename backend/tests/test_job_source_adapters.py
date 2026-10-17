"""Lever and Ashby adapters and the shared host-pinned HTTP layer (no network)."""
import json
import socket
from datetime import datetime, timezone
from decimal import Decimal
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from app.services.job_discovery import SourceFetchError
from app.services.job_sources import http
from app.services.job_sources.ashby import AshbyJobBoardSource
from app.services.job_sources.lever import LeverPostingsSource

LEVER_POSTING = {
    "id": "5ac21346-8e0c-4494-8e7a-3eb92ff77902",
    "text": "Technical Support Engineer",
    "categories": {"location": "Remote - Africa", "allLocations": ["Remote - Africa", "Nairobi"], "commitment": "Full-time"},
    "workplaceType": "remote",
    "country": "ke",
    "createdAt": 1760600000000,
    "hostedUrl": "https://jobs.lever.co/syntheticco/5ac21346-8e0c-4494-8e7a-3eb92ff77902",
    "applyUrl": "https://jobs.lever.co/syntheticco/5ac21346-8e0c-4494-8e7a-3eb92ff77902/apply",
    "descriptionPlain": "Support customers across Africa.",
    "lists": [{"text": "Requirements", "content": "<li>Linux</li><li>We cannot hire in Kenya for this role.</li>"}],
    "additionalPlain": "Applicants must have the right to work in their country.",
    "salaryRange": {"min": 30000, "max": 45000, "currency": "usd", "interval": "per-year-salary"},
}
ASHBY_JOB = {
    "title": "Customer Support Specialist",
    "location": "Remote (EMEA)",
    "secondaryLocations": [{"location": "Nairobi, Kenya"}],
    "isListed": True,
    "isRemote": True,
    "workplaceType": "Remote",
    "publishedAt": "2026-10-16T08:30:00.000+00:00",
    "descriptionPlain": "Help customers. Open to candidates in any EMEA country.",
    "jobUrl": "https://jobs.ashbyhq.com/syntheticco/2f4c1d0e-1111-4a2b-9c3d-abcdefabcdef",
    "applyUrl": "https://jobs.ashbyhq.com/syntheticco/2f4c1d0e-1111-4a2b-9c3d-abcdefabcdef/application",
}


def test_lever_maps_documented_fields_and_keeps_all_location_wording() -> None:
    source = LeverPostingsSource("SyntheticCo", "Synthetic Co", fetcher=lambda url: [LEVER_POSTING, "not-a-dict"])

    [listing] = source.fetch()

    assert source.api_url == "https://api.lever.co/v0/postings/syntheticco?mode=json"
    assert listing.source_listing_id == LEVER_POSTING["id"]
    assert listing.listing_url == LEVER_POSTING["hostedUrl"]
    assert listing.application_url == LEVER_POSTING["applyUrl"]
    assert listing.location_text == "Remote - Africa; Nairobi"
    assert listing.stated_workplace_type == "remote"
    assert tuple(listing.stated_countries) == ("KE",)
    assert listing.posted_at == datetime.fromtimestamp(1760600000, tz=timezone.utc)
    # Every section is preserved, including an exclusion buried in a list.
    assert "We cannot hire in Kenya for this role." in listing.description_text
    assert "right to work in their country" in listing.description_text
    assert (listing.salary_min, listing.salary_max, listing.salary_currency) == (Decimal("30000"), Decimal("45000"), "USD")


def test_lever_falls_back_to_hosted_url_and_leaves_unknowns_empty() -> None:
    posting = {"id": "abc", "text": "Help Desk Analyst", "hostedUrl": "https://jobs.lever.co/syntheticco/abc"}
    [listing] = LeverPostingsSource("syntheticco", "Synthetic Co", fetcher=lambda url: [posting]).fetch()

    assert listing.application_url == listing.listing_url == "https://jobs.lever.co/syntheticco/abc"
    assert listing.posted_at is None and listing.stated_workplace_type is None
    assert tuple(listing.stated_countries) == () and listing.salary_min is None


def test_lever_eu_instance_uses_its_own_host_and_key() -> None:
    source = LeverPostingsSource("syntheticco", "Synthetic Co", instance="eu", fetcher=lambda url: [])
    assert source.api_url.startswith("https://api.eu.lever.co/") and source.key == "eu:syntheticco"


@pytest.mark.parametrize("payload", [{"jobs": []}, "text", None])
def test_lever_rejects_malformed_payloads(payload) -> None:
    with pytest.raises(SourceFetchError) as caught:
        LeverPostingsSource("syntheticco", "Synthetic Co", fetcher=lambda url: payload).fetch()
    assert caught.value.category == "invalid_response"


@pytest.mark.parametrize("site", ["../x", "", "a b", "x" * 101])
def test_lever_rejects_unsafe_site_names(site: str) -> None:
    with pytest.raises(ValueError):
        LeverPostingsSource(site, "Synthetic Co")


def test_ashby_maps_published_listings_and_derives_id_from_its_own_url() -> None:
    unlisted = {**ASHBY_JOB, "isListed": False, "title": "Hidden role"}
    source = AshbyJobBoardSource("SyntheticCo", "Synthetic Co", fetcher=lambda url: {"jobs": [ASHBY_JOB, unlisted, 7]})

    [listing] = source.fetch()

    assert source.key == "syntheticco"
    assert source.api_url == "https://api.ashbyhq.com/posting-api/job-board/SyntheticCo?includeCompensation=true"
    assert listing.source_listing_id == "2f4c1d0e-1111-4a2b-9c3d-abcdefabcdef"
    assert listing.listing_url == ASHBY_JOB["jobUrl"] and listing.application_url == ASHBY_JOB["applyUrl"]
    assert listing.location_text == "Remote (EMEA); Nairobi, Kenya"
    assert listing.stated_workplace_type == "remote"
    assert listing.posted_at == datetime(2026, 10, 16, 8, 30, tzinfo=timezone.utc)


def test_ashby_entry_without_any_url_cannot_get_an_invented_link() -> None:
    job = {key: value for key, value in ASHBY_JOB.items() if key not in ("jobUrl", "applyUrl")}
    [listing] = AshbyJobBoardSource("syntheticco", "Synthetic Co", fetcher=lambda url: {"jobs": [job]}).fetch()
    assert listing.application_url == "" and listing.listing_url is None and listing.source_listing_id == ""


@pytest.mark.parametrize("payload", [{"jobs": "nope"}, [], {"apiVersion": "1"}])
def test_ashby_rejects_malformed_payloads(payload) -> None:
    with pytest.raises(SourceFetchError) as caught:
        AshbyJobBoardSource("syntheticco", "Synthetic Co", fetcher=lambda url: payload).fetch()
    assert caught.value.category == "invalid_response"


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int) -> bytes:
        return self.body[:size]


def _scripted(monkeypatch, *events):
    calls: list[str] = []
    queue = list(events)

    def fake_open(request: Request, *, timeout, allowed_hosts):
        calls.append(request.full_url)
        event = queue.pop(0)
        if isinstance(event, BaseException):
            raise event
        return _Response(event)

    monkeypatch.setattr(http, "open_url", fake_open)
    return calls


HOSTS = frozenset({"api.example-ats.test"})
URL = "https://api.example-ats.test/board"


def _http_error(code: int, headers: dict | None = None) -> HTTPError:
    return HTTPError(URL, code, "error", headers or {}, None)


def test_transient_failures_are_retried_with_backoff_then_succeed(monkeypatch) -> None:
    calls = _scripted(monkeypatch, _http_error(503), _http_error(429, {"Retry-After": "7"}), json.dumps([1]).encode())
    slept: list[float] = []

    assert http.fetch_json(URL, allowed_hosts=HOSTS, sleep=slept.append) == [1]
    assert len(calls) == 3 and slept == [2.0, 7.0]


def test_retries_are_bounded_and_report_the_last_failure(monkeypatch) -> None:
    calls = _scripted(monkeypatch, socket.timeout(), socket.timeout(), socket.timeout())
    with pytest.raises(SourceFetchError) as caught:
        http.fetch_bytes(URL, allowed_hosts=HOSTS, sleep=lambda _: None)
    assert caught.value.category == "timeout" and len(calls) == 3


def test_not_found_and_client_errors_are_not_retried(monkeypatch) -> None:
    calls = _scripted(monkeypatch, _http_error(404))
    with pytest.raises(SourceFetchError) as caught:
        http.fetch_bytes(URL, allowed_hosts=HOSTS, sleep=lambda _: None)
    assert caught.value.category == "not_found" and len(calls) == 1


def test_retry_after_is_capped(monkeypatch) -> None:
    _scripted(monkeypatch, _http_error(429, {"Retry-After": "3600"}), b"{}")
    slept: list[float] = []
    http.fetch_json(URL, allowed_hosts=HOSTS, sleep=slept.append)
    assert slept == [http.MAX_RETRY_AFTER_SECONDS]


def test_oversized_and_malformed_bodies_are_rejected(monkeypatch) -> None:
    _scripted(monkeypatch, b"x" * (http.MAX_RESPONSE_BYTES + 1))
    with pytest.raises(SourceFetchError) as too_large:
        http.fetch_bytes(URL, allowed_hosts=HOSTS, sleep=lambda _: None)
    _scripted(monkeypatch, b"{not json")
    with pytest.raises(SourceFetchError) as malformed:
        http.fetch_json(URL, allowed_hosts=HOSTS, sleep=lambda _: None)
    assert (too_large.value.category, malformed.value.category) == ("too_large", "invalid_response")


@pytest.mark.parametrize("url", ["http://api.example-ats.test/board", "https://evil.test/board"])
def test_requests_off_the_pinned_host_are_refused_before_sending(monkeypatch, url: str) -> None:
    calls = _scripted(monkeypatch, b"{}")
    with pytest.raises(SourceFetchError):
        http.fetch_bytes(url, allowed_hosts=HOSTS, sleep=lambda _: None)
    assert calls == []


@pytest.mark.parametrize("target", ["https://evil.test/x", "http://api.example-ats.test/x"])
def test_redirects_off_the_pinned_host_are_refused(target: str) -> None:
    handler = http.PinnedHostRedirectHandler(HOSTS)
    with pytest.raises(SourceFetchError):
        handler.redirect_request(Request(URL), None, 302, "Found", {}, target)
    followed = handler.redirect_request(Request(URL), None, 301, "Moved", {}, "https://api.example-ats.test/new")
    assert followed.full_url == "https://api.example-ats.test/new"
