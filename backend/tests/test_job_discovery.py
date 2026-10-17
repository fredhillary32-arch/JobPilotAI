from datetime import datetime, timedelta, timezone
import json
import socket
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.models import JobDiscoveryRun, JobListing
from app.services import job_sources
from app.services.job_discovery import (
    SourceFetchError,
    SourceListing,
    content_hash,
    dedupe_key,
    run_discovery,
)
from app.services.job_sources import greenhouse
from app.services.job_sources.greenhouse import GreenhouseBoardSource, html_to_text

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
API = "/api/v1"


def greenhouse_job(job_id: int, title: str = "Technical Support Specialist", **extra) -> dict:
    # Shape follows the documented list response (content=true); synthetic values.
    job = {
        "id": job_id,
        "internal_job_id": job_id + 1000,
        "title": title,
        "updated_at": "2026-10-15T10:55:28-05:00",
        "requisition_id": "50",
        "location": {"name": "Remote - EMEA"},
        "absolute_url": f"https://boards.greenhouse.io/syntheticco/jobs/{job_id}",
        "language": "en",
        "metadata": None,
        "content": "&amp;lt;p&amp;gt;Help customers &amp;amp;amp; resolve tickets.&amp;lt;/p&amp;gt;&amp;lt;ul&amp;gt;&amp;lt;li&amp;gt;Zendesk&amp;lt;/li&amp;gt;&amp;lt;/ul&amp;gt;",
        "departments": [],
        "offices": [],
    }
    job.update(extra)
    return job


def fixture_fetcher(*jobs: dict):
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return json.dumps({"jobs": list(jobs), "meta": {"total": len(jobs)}}).encode()

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def source_for(*jobs: dict) -> GreenhouseBoardSource:
    return GreenhouseBoardSource("syntheticco", "Synthetic Co", fetcher=fixture_fetcher(*jobs))


class FailingSource:
    kind = "greenhouse"
    key = "syntheticco"

    def __init__(self, category: str) -> None:
        self.category = category

    def fetch(self) -> list[SourceListing]:
        raise SourceFetchError(self.category)


def listings(factory: sessionmaker[Session]) -> dict[str, JobListing]:
    with factory() as session:
        return {row.source_listing_id: row for row in session.scalars(select(JobListing))}


# --- Greenhouse adapter ---------------------------------------------------


def test_html_to_text_decodes_double_escaped_greenhouse_content() -> None:
    assert html_to_text(greenhouse_job(1)["content"]) == "Help customers & resolve tickets.\n- Zendesk"
    assert html_to_text("&lt;script&gt;alert(1)&lt;/script&gt;&lt;p&gt;Safe&lt;/p&gt;") == "Safe"
    assert html_to_text("") is None


def test_greenhouse_maps_documented_fields_without_inventing_values() -> None:
    source = source_for(greenhouse_job(101))
    [listing] = source.fetch()

    assert source.api_url == "https://boards-api.greenhouse.io/v1/boards/syntheticco/jobs?content=true"
    assert listing.source_listing_id == "101"
    assert listing.application_url == "https://boards.greenhouse.io/syntheticco/jobs/101"
    assert listing.employer_name == "Synthetic Co"
    assert listing.location_text == "Remote - EMEA"
    assert listing.source_updated_at == datetime(2026, 10, 15, 15, 55, 28, tzinfo=timezone.utc)
    # The list endpoint does not document a posting date, deadline, pay, workplace
    # type or countries, so none are inferred.
    assert listing.posted_at is None
    assert listing.application_deadline is None
    assert listing.salary_min is None and listing.salary_currency is None
    assert listing.stated_workplace_type is None
    assert list(listing.stated_countries) == []


def test_greenhouse_uses_first_published_and_company_name_only_when_present() -> None:
    [listing] = source_for(
        greenhouse_job(
            102,
            first_published="2026-10-16T06:00:00Z",
            company_name="Synthetic Co Ltd",
            application_deadline="2026-11-01T20:00:00Z",
        )
    ).fetch()
    assert listing.posted_at == datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)
    assert listing.employer_name == "Synthetic Co Ltd"
    assert listing.application_deadline.isoformat() == "2026-11-01"


@pytest.mark.parametrize("token", ["", "../admin", "evil.example.com/x", "a b", "x" * 101, "board?x=1"])
def test_greenhouse_rejects_unsafe_board_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        GreenhouseBoardSource(token, "Synthetic Co")


def test_greenhouse_requires_an_employer_name() -> None:
    with pytest.raises(ValueError):
        GreenhouseBoardSource("syntheticco", "   ")


@pytest.mark.parametrize("body", [b"not json", b"{\"jobs\": {}}", b"[]", b"\xff\xfe"])
def test_greenhouse_reports_malformed_responses(body: bytes) -> None:
    source = GreenhouseBoardSource("syntheticco", "Synthetic Co", fetcher=lambda url: body)
    with pytest.raises(SourceFetchError) as caught:
        source.fetch()
    assert caught.value.category == "invalid_response"


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (HTTPError("u", 404, "Not Found", {}, None), "not_found"),
        (HTTPError("u", 429, "Too Many", {}, None), "rate_limited"),
        (HTTPError("u", 503, "Unavailable", {}, None), "unavailable"),
        (URLError("connection refused"), "unavailable"),
        (URLError(socket.timeout()), "timeout"),
        (TimeoutError(), "timeout"),
    ],
)
def test_default_fetch_classifies_source_failures(monkeypatch, error, category) -> None:
    def fake_urlopen(*args, **kwargs):
        raise error

    monkeypatch.setattr(greenhouse, "urlopen", fake_urlopen)
    with pytest.raises(SourceFetchError) as caught:
        greenhouse.default_fetch("https://boards-api.greenhouse.io/v1/boards/x/jobs")
    assert caught.value.category == category


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/v1/boards/x/jobs",
        "http://boards-api.greenhouse.io/v1/boards/x/jobs",
        "https://boards-api.greenhouse.io.evil.example/jobs",
    ],
)
def test_redirects_away_from_the_greenhouse_api_host_are_refused(target: str) -> None:
    from urllib.request import Request

    handler = greenhouse.GreenhouseOnlyRedirectHandler()
    original = Request("https://boards-api.greenhouse.io/v1/boards/x/jobs")
    with pytest.raises(SourceFetchError) as caught:
        handler.redirect_request(original, None, 302, "Found", {}, target)
    assert caught.value.category == "invalid_response"


def test_redirects_within_the_greenhouse_api_host_are_followed() -> None:
    from urllib.request import Request

    handler = greenhouse.GreenhouseOnlyRedirectHandler()
    original = Request("https://boards-api.greenhouse.io/v1/boards/x/jobs")
    followed = handler.redirect_request(
        original, None, 301, "Moved", {}, "https://boards-api.greenhouse.io/v1/boards/y/jobs"
    )
    assert followed.full_url == "https://boards-api.greenhouse.io/v1/boards/y/jobs"


def test_default_fetch_rejects_oversized_responses(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b"x" * size

    seen: dict = {}

    def fake_urlopen(request, timeout):
        seen["timeout"] = timeout
        seen["agent"] = request.get_header("User-agent")
        return Response()

    monkeypatch.setattr(greenhouse, "urlopen", fake_urlopen)
    with pytest.raises(SourceFetchError) as caught:
        greenhouse.default_fetch("https://boards-api.greenhouse.io/v1/boards/x/jobs")
    assert caught.value.category == "too_large"
    assert seen["timeout"] == greenhouse.REQUEST_TIMEOUT_SECONDS
    assert seen["agent"].startswith("JobPilotAI/")


# --- Discovery service ----------------------------------------------------


def test_first_run_stores_listings_with_discovery_timestamps(database) -> None:
    _, factory = database
    with factory() as session:
        run = run_discovery(session, source_for(greenhouse_job(1), greenhouse_job(2, "IT Support L2")), now=NOW)

    assert (run.status, run.fetched_count, run.created_count, run.error_category) == ("succeeded", 2, 2, None)
    stored = listings(factory)
    assert set(stored) == {"1", "2"}
    row = stored["1"]
    assert row.source_status == "active"
    assert row.first_seen_at.replace(tzinfo=timezone.utc) == NOW
    assert row.posted_at is None
    assert row.description_text == "Help customers & resolve tickets.\n- Zendesk"


def test_rerun_is_idempotent_and_updates_only_changed_facts(database) -> None:
    _, factory = database
    later = NOW + timedelta(hours=6)
    with factory() as session:
        run_discovery(session, source_for(greenhouse_job(1), greenhouse_job(2)), now=NOW)
    with factory() as session:
        run = run_discovery(
            session,
            source_for(greenhouse_job(1), greenhouse_job(2, title="Senior Technical Support")),
            now=later,
        )

    assert (run.created_count, run.updated_count, run.unchanged_count) == (0, 1, 1)
    stored = listings(factory)
    assert len(stored) == 2
    assert stored["2"].title == "Senior Technical Support"
    for row in stored.values():
        assert row.first_seen_at.replace(tzinfo=timezone.utc) == NOW
        assert row.last_verified_at.replace(tzinfo=timezone.utc) == later


def test_duplicate_and_invalid_entries_in_one_response_are_skipped(database) -> None:
    _, factory = database
    with factory() as session:
        run = run_discovery(
            session,
            source_for(
                greenhouse_job(1),
                greenhouse_job(1, title="Duplicate id"),
                greenhouse_job(3, title="   "),
                greenhouse_job(4, absolute_url="http://insecure.example/jobs/4"),
                greenhouse_job(5, absolute_url=None),
            ),
            now=NOW,
        )
    assert (run.created_count, run.skipped_count) == (1, 4)
    assert listings(factory)["1"].title == "Technical Support Specialist"


def test_listing_absent_from_successful_run_is_marked_missing_then_restored(database) -> None:
    _, factory = database
    with factory() as session:
        run_discovery(session, source_for(greenhouse_job(1), greenhouse_job(2)), now=NOW)
    with factory() as session:
        run = run_discovery(session, source_for(greenhouse_job(1)), now=NOW + timedelta(hours=1))
    assert run.missing_count == 1
    assert listings(factory)["2"].source_status == "missing_from_source"

    with factory() as session:
        run_discovery(session, source_for(greenhouse_job(1), greenhouse_job(2)), now=NOW + timedelta(hours=2))
    assert listings(factory)["2"].source_status == "active"


@pytest.mark.parametrize("category", ["unavailable", "not_found", "rate_limited", "timeout", "invalid_response"])
def test_failed_run_is_recorded_and_leaves_listings_untouched(database, category: str) -> None:
    _, factory = database
    with factory() as session:
        run_discovery(session, source_for(greenhouse_job(1)), now=NOW)
    before = {key: (row.source_status, row.last_verified_at) for key, row in listings(factory).items()}

    with factory() as session:
        run = run_discovery(session, FailingSource(category), now=NOW + timedelta(hours=1))

    assert (run.status, run.error_category, run.fetched_count) == ("failed", category, 0)
    after = {key: (row.source_status, row.last_verified_at) for key, row in listings(factory).items()}
    assert after == before
    with factory() as session:
        assert [r.status for r in session.scalars(select(JobDiscoveryRun).order_by(JobDiscoveryRun.started_at))] == ["succeeded", "failed"]


def test_unexpected_storage_error_marks_run_failed_and_rolls_back(database, monkeypatch) -> None:
    _, factory = database
    from app.services import job_discovery

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(job_discovery, "_apply_facts", explode)
    with factory() as session, pytest.raises(RuntimeError):
        run_discovery(session, source_for(greenhouse_job(1)), now=NOW)

    assert listings(factory) == {}
    with factory() as session:
        [run] = session.scalars(select(JobDiscoveryRun)).all()
        assert (run.status, run.error_category) == ("failed", "internal_error")


def test_storage_conflict_from_a_parallel_run_is_recorded_as_conflict(database, monkeypatch) -> None:
    _, factory = database
    from app.services import job_discovery

    def conflict(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(job_discovery, "_apply_facts", conflict)
    with factory() as session, pytest.raises(IntegrityError):
        run_discovery(session, source_for(greenhouse_job(1)), now=NOW)

    with factory() as session:
        [run] = session.scalars(select(JobDiscoveryRun)).all()
        assert (run.status, run.error_category) == ("failed", "conflict")


def test_unknown_error_category_is_rejected() -> None:
    with pytest.raises(ValueError):
        SourceFetchError("made_up")


def test_database_enforces_source_identity_uniqueness(database) -> None:
    _, factory = database
    with factory() as session:
        run_discovery(session, source_for(greenhouse_job(1)), now=NOW)
    original = listings(factory)["1"]
    with factory() as session, pytest.raises(IntegrityError):
        session.add(
            JobListing(
                source_kind="greenhouse", source_key="syntheticco", source_listing_id="1",
                source_url=original.source_url, application_url=original.application_url,
                employer_name="Synthetic Co", title="Copy", content_hash="0" * 64, dedupe_key="0" * 64,
                first_seen_at=NOW, last_seen_at=NOW, last_verified_at=NOW,
            )
        )
        session.commit()


def test_dedupe_key_groups_same_job_across_sources_but_not_different_jobs() -> None:
    assert dedupe_key("Synthetic Co", "IT  Support", "Remote") == dedupe_key(" synthetic co", "it support", "remote ")
    assert dedupe_key("Synthetic Co", "IT Support", "Remote") != dedupe_key("Synthetic Co", "IT Support", "Nairobi")


def test_content_hash_changes_when_facts_change() -> None:
    base = SourceListing("1", "https://a", "https://b", "Synthetic Co", "Support")
    changed = SourceListing("1", "https://a", "https://b", "Synthetic Co", "Support Lead")
    assert content_hash(base) == content_hash(SourceListing("1", "https://a", "https://b", "Synthetic Co", "Support"))
    assert content_hash(base) != content_hash(changed)


# --- API --------------------------------------------------------------------


def _seed(factory, jobs: list[tuple[int, int | None]], missing: tuple[int, ...] = ()):
    """Store jobs from one discovery run; (job_id, posted_hours_ago or None)."""
    payload = []
    for job_id, hours in jobs:
        extra = {}
        if hours is not None:
            extra["first_published"] = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        payload.append(greenhouse_job(job_id, **extra))
    with factory() as session:
        run_discovery(session, source_for(*payload))
    with factory() as session:
        for row in session.scalars(select(JobListing)):
            if int(row.source_listing_id) in missing:
                row.source_status = "missing_from_source"
        session.commit()


def test_api_lists_active_listings_with_unknown_eligibility(api_client: TestClient, database) -> None:
    _, factory = database
    _seed(factory, [(1, 2), (2, None)])

    response = api_client.get(f"{API}/job-listings")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2 and body["limit"] == 50 and body["offset"] == 0
    first = body["items"][0]
    assert first["source_listing_id"] == "1"  # dated listings sort first
    assert first["eligibility"]["status"] == "eligibility_unknown"
    assert first["eligibility"]["currency"] == "not_assessed"
    assert "description_text" not in first
    assert body["items"][1]["posted_at"] is None


def test_api_posted_within_filter_excludes_undated_old_and_future_listings(api_client: TestClient, database) -> None:
    _, factory = database
    _seed(factory, [(1, 2), (2, 48), (3, None), (4, -3)])

    ids = [i["source_listing_id"] for i in api_client.get(f"{API}/job-listings?posted_within_hours=24").json()["items"]]
    assert ids == ["1"]


def test_api_filters_by_source_status_and_paginates(api_client: TestClient, database) -> None:
    _, factory = database
    _seed(factory, [(1, None), (2, None)], missing=(2,))

    def ids(query: str) -> list[str]:
        return [i["source_listing_id"] for i in api_client.get(f"{API}/job-listings{query}").json()["items"]]

    assert ids("") == ["1"]
    assert ids("?source_status=missing_from_source") == ["2"]
    assert sorted(ids("?source_status=all")) == ["1", "2"]
    page = api_client.get(f"{API}/job-listings?source_status=all&limit=1&offset=1").json()
    assert (page["total"], len(page["items"])) == (2, 1)


@pytest.mark.parametrize(
    "query",
    ["?limit=0", "?limit=201", "?offset=-1", "?posted_within_hours=0", "?source_status=closed"],
)
def test_api_rejects_invalid_listing_queries(api_client: TestClient, query: str) -> None:
    assert api_client.get(f"{API}/job-listings{query}").status_code == 422


def test_api_listing_detail_includes_description_and_404s_unknown(api_client: TestClient, database) -> None:
    _, factory = database
    _seed(factory, [(1, None)])
    listing_id = api_client.get(f"{API}/job-listings").json()["items"][0]["id"]

    detail = api_client.get(f"{API}/job-listings/{listing_id}")
    assert detail.status_code == 200
    assert detail.json()["description_text"] == "Help customers & resolve tickets.\n- Zendesk"
    assert api_client.get(f"{API}/job-listings/{uuid4()}").status_code == 404
    assert api_client.get(f"{API}/job-listings/not-a-uuid").status_code == 422


def test_api_reports_failed_discovery_runs(api_client: TestClient, database) -> None:
    _, factory = database
    with factory() as session:
        run_discovery(session, FailingSource("rate_limited"))

    [run] = api_client.get(f"{API}/job-discovery/runs").json()
    assert (run["status"], run["error_category"], run["source_key"]) == ("failed", "rate_limited", "syntheticco")


def test_job_routes_require_a_session(unauthenticated_client: TestClient) -> None:
    for path in ("/job-listings", f"/job-listings/{uuid4()}", "/job-discovery/runs"):
        assert unauthenticated_client.get(f"{API}{path}").status_code == 401


def test_api_exposes_no_route_that_triggers_external_discovery() -> None:
    from app.api.v1.job_listings import router

    assert {method for route in router.routes for method in route.methods} == {"GET"}


# --- CLI --------------------------------------------------------------------


def test_cli_reports_success_and_failure_with_exit_codes(database) -> None:
    _, factory = database
    messages: list[str] = []

    ok = cli.main(
        ["discover-greenhouse", "--board", "syntheticco", "--employer", "Synthetic Co"],
        output=messages.append,
        session_factory=factory,
        source_factory=lambda board, employer: source_for(greenhouse_job(1)),
    )
    failed = cli.main(
        ["discover-greenhouse", "--board", "syntheticco", "--employer", "Synthetic Co"],
        output=messages.append,
        session_factory=factory,
        source_factory=lambda board, employer: FailingSource("unavailable"),
    )
    invalid = cli.main(
        ["discover-greenhouse", "--board", "../x", "--employer", "Synthetic Co"],
        output=messages.append,
        session_factory=factory,
    )

    assert (ok, failed, invalid) == (0, 1, 2)
    assert "fetched 1, new 1" in messages[0]
    assert "(unavailable); stored listings were not changed" in messages[1]
    assert len(listings(factory)) == 1


def test_job_sources_package_is_importable() -> None:
    assert job_sources.__doc__
