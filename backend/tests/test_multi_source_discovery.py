"""Multi-source discovery: aggregator adapters, windowed reconciliation, pacing,
locking, the background refresh endpoint and the richer listing filters.

Every response here is a synthetic fixture shaped like the documented APIs; no
test contacts a real source.
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import cli
from app.models import JobDiscoveryRun, JobListing
from app.services import discovery_runner
from app.services.discovery_runner import DiscoveryBusy, discovery_lock, effective_run_status, run_sources
from app.services.job_discovery import SourceFetchError, run_discovery
from app.services.job_sources.aggregators import (
    ARBEITNOW_MAX_PAGES,
    JOBICY_MAX_PAGES,
    ArbeitnowSource,
    JobicySource,
    RemoteOkSource,
)
from app.services.source_registry import load_registry

NOW = datetime.now(UTC).replace(microsecond=0)
API = "/api/v1/job-listings"


def jobicy_job(number: int, **extra) -> dict:
    return {
        "id": number, "url": f"https://jobicy.com/jobs/{number}-support", "jobTitle": f"Customer Support Agent {number}",
        "companyName": "Synthetic Remote Co", "jobGeo": "Anywhere", "jobDescription": "<p>Help customers.</p>",
        "pubDate": (NOW - timedelta(hours=number)).isoformat(), "salaryMin": 30000, "salaryMax": 40000,
        "salaryCurrency": "USD", "salaryPeriod": "yearly", **extra,
    }


def arbeitnow_job(number: int, *, age_hours: int = 1, **extra) -> dict:
    return {
        "slug": f"it-support-{number}", "company_name": "Synthetic GmbH", "title": f"IT Support Specialist {number}",
        "description": "<p>Support users.</p>", "remote": False, "url": f"https://www.arbeitnow.com/jobs/companies/x/it-support-{number}",
        "tags": [], "job_types": [], "location": "Berlin", "created_at": int((NOW - timedelta(hours=age_hours)).timestamp()), **extra,
    }


def recorder(pages):
    """A fetcher that serves pages in order and records each URL requested."""
    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        page = pages[len(calls) - 1] if callable(pages) is False else pages(url)
        if isinstance(page, Exception):
            raise page
        return page

    return fetch, calls


# --- adapters -------------------------------------------------------------------


def test_jobicy_follows_the_cursor_and_maps_the_documented_fields() -> None:
    fetch, calls = recorder([
        {"jobs": [jobicy_job(1)], "nextCursor": "abc", "hasMore": True},
        {"jobs": [jobicy_job(2)], "nextCursor": None, "hasMore": False},
    ])
    listings = JobicySource(fetcher=fetch).fetch()
    assert [item.source_listing_id for item in listings] == ["1", "2"]
    assert calls[0].startswith("https://jobicy.com/api/v2/remote-jobs?count=200") and "cursor=abc" in calls[1]
    first = listings[0]
    assert first.listing_url == first.application_url == "https://jobicy.com/jobs/1-support"  # canonical Jobicy URL
    assert first.posted_at == NOW - timedelta(hours=1) and first.stated_workplace_type == "remote"
    assert (first.salary_min, first.salary_currency) == (30000, "USD") and first.description_text == "Help customers."


def test_jobicy_pagination_is_capped() -> None:
    fetch, calls = recorder(lambda url: {"jobs": [], "nextCursor": "again", "hasMore": True})
    assert JobicySource(fetcher=fetch).fetch() == []
    assert len(calls) == JOBICY_MAX_PAGES


def test_an_empty_feed_is_a_success_and_a_malformed_one_is_a_failure() -> None:
    assert JobicySource(fetcher=recorder([{"jobs": [], "nextCursor": None}])[0]).fetch() == []
    assert JobicySource(fetcher=recorder([{"jobCount": 0}])[0]).fetch() == []
    for bad in ({"error": "nope"}, ["not", "a", "dict"], {"jobs": "x"}):
        with pytest.raises(SourceFetchError) as caught:
            JobicySource(fetcher=recorder([bad])[0]).fetch()
        assert caught.value.category == "invalid_response"


def test_off_host_or_insecure_links_are_not_trusted() -> None:
    fetch, _ = recorder([{"jobs": [jobicy_job(1, url="https://evil.example/jobs/1"), jobicy_job(2, url="http://jobicy.com/jobs/2")]}])
    listings = JobicySource(fetcher=fetch).fetch()
    assert all(item.application_url == "" and item.listing_url is None for item in listings)


def test_salary_without_a_currency_or_in_the_wrong_order_is_dropped() -> None:
    fetch, _ = recorder([{"jobs": [jobicy_job(1, salaryCurrency=""), jobicy_job(2, salaryMin=50, salaryMax=10)]}])
    assert all(item.salary_min is None and item.salary_currency is None for item in JobicySource(fetcher=fetch).fetch())


def test_arbeitnow_reads_pages_until_next_is_missing_and_never_assumes_onsite() -> None:
    fetch, calls = recorder([
        {"data": [arbeitnow_job(1)], "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"}},
        {"data": [arbeitnow_job(2, remote=True)], "links": {"next": None}},
    ])
    listings = ArbeitnowSource(fetcher=fetch).fetch()
    assert [call.rsplit("=", 1)[1] for call in calls] == ["1", "2"]
    assert [item.stated_workplace_type for item in listings] == [None, "remote"]
    assert listings[0].posted_at == datetime.fromtimestamp(arbeitnow_job(1)["created_at"], UTC)


def test_arbeitnow_incremental_refresh_stops_at_older_jobs_and_pages_are_capped() -> None:
    next_link = {"next": "https://www.arbeitnow.com/api/job-board-api?page=n"}
    fetch, calls = recorder(lambda url: {"data": [arbeitnow_job(1, age_hours=200)], "links": next_link})
    ArbeitnowSource(fetcher=fetch, since=NOW - timedelta(hours=2)).fetch()
    assert len(calls) == 1  # the first page already reached jobs older than the last run
    fetch, calls = recorder(lambda url: {"data": [arbeitnow_job(1)], "links": next_link})
    ArbeitnowSource(fetcher=fetch).fetch()
    assert len(calls) == ARBEITNOW_MAX_PAGES


def test_remoteok_skips_the_legal_notice_and_reads_dates() -> None:
    fetch, _ = recorder([[
        {"last_updated": 1, "legal": "Please link back to Remote OK."},
        {"id": "991", "position": "Technical Support Engineer", "company": "Synthetic Inc", "location": "",
         "date": "2026-10-16T17:55:35+00:00", "url": "https://remoteok.com/remote-jobs/991",
         "apply_url": "https://remoteok.com/l/991", "description": "<b>Support</b>"},
    ]])
    (listing,) = RemoteOkSource(fetcher=fetch).fetch()
    assert listing.source_listing_id == "991" and listing.application_url == "https://remoteok.com/l/991"
    assert listing.posted_at == datetime(2026, 10, 16, 17, 55, 35, tzinfo=UTC) and listing.location_text is None
    with pytest.raises(SourceFetchError):
        RemoteOkSource(fetcher=recorder([{"jobs": []}])[0]).fetch()


# --- reconciliation of windowed feeds -----------------------------------------------


def test_windowed_feeds_are_idempotent_and_never_mark_absent_jobs_removed(database) -> None:
    _, factory = database
    first = JobicySource(fetcher=recorder([{"jobs": [jobicy_job(1), jobicy_job(2)]}])[0])
    first.category = "aggregator"
    with factory() as session:
        run = run_discovery(session, first)
    assert (run.created_count, run.skipped_count) == (2, 0)
    again = JobicySource(fetcher=recorder([{"jobs": [jobicy_job(1), jobicy_job(2)]}])[0])
    with factory() as session:
        run = run_discovery(session, again)
    assert (run.created_count, run.unchanged_count) == (0, 2)
    later = JobicySource(fetcher=recorder([{"jobs": [jobicy_job(2)]}])[0])
    with factory() as session:
        run = run_discovery(session, later)
        statuses = set(session.scalars(select(JobListing.source_status)))
        assert run.missing_count == 0 and statuses == {"active"}
        assert session.scalar(select(JobListing.source_category).limit(1)) == "aggregator"


def test_entries_without_a_usable_link_are_skipped_with_a_reason(database) -> None:
    _, factory = database
    source = JobicySource(fetcher=recorder([{"jobs": [jobicy_job(1, url="https://evil.example/1"), jobicy_job(2)]}])[0])
    with factory() as session:
        run = run_discovery(session, source)
    assert (run.created_count, run.skipped_count) == (1, 1)
    assert run.skip_reasons == {"no usable https application URL": 1}


# --- runner: pacing, isolation, locking ---------------------------------------------------


def _entries(*ids):
    registry = {entry.id: entry for entry in load_registry()}
    return [registry[item] for item in ids]


def test_runner_paces_sources_isolates_failures_and_uses_incremental_windows(database) -> None:
    _, factory = database
    built: dict[str, object] = {}

    def builder(entry):
        if entry.id == "remoteok":
            raise RuntimeError("adapter bug")
        if entry.id == "arbeitnow":
            source = ArbeitnowSource(fetcher=recorder(lambda url: {"data": [arbeitnow_job(1)], "links": {}})[0])
        else:
            source = JobicySource(fetcher=recorder(lambda url: {"jobs": [jobicy_job(1)]})[0])
        built[entry.id] = source
        return source

    entries = _entries("jobicy", "remoteok", "arbeitnow")
    first = {o.source_id: o for o in run_sources(factory, entries, builder=builder)}
    assert first["jobicy"].status == "succeeded" and first["jobicy"].created == 1
    assert first["remoteok"].status == "error" and "other sources continue" in first["remoteok"].message
    assert first["arbeitnow"].status == "succeeded" and built["arbeitnow"].since is None
    second = {o.source_id: o for o in run_sources(factory, entries, builder=builder)}
    assert second["jobicy"].status == "skipped" and "60 minutes" in second["jobicy"].message  # Jobicy: once per hour
    assert built["arbeitnow"].since is not None  # incremental since the last success
    forced = {o.source_id: o for o in run_sources(factory, entries, builder=builder, force=True, full=True)}
    assert forced["jobicy"].status == "succeeded" and built["arbeitnow"].since is None


def test_only_one_discovery_pass_runs_at_a_time(database) -> None:
    _, factory = database
    messages: list[str] = []
    with discovery_lock(factory):
        with pytest.raises(DiscoveryBusy):
            with discovery_lock(factory):
                pass
        code = cli.main(["discover-registry", "--source", "jobicy"], output=messages.append, session_factory=factory,
                        registry_source_factory=lambda entry: pytest.fail("must not fetch while locked"))
    assert code == 3 and "Another discovery pass is running" in messages[-1]


def test_cli_validates_the_registry_and_summarises_runs(database) -> None:
    _, factory = database
    messages: list[str] = []
    assert cli.main(["validate-sources"], output=messages.append) == 0
    assert messages[-1].startswith("Registry valid:") and "jobicy 1" in messages[-1]
    with factory.begin() as session:
        session.add(JobDiscoveryRun(source_kind="jobicy", source_key="public", status="running", started_at=NOW - timedelta(hours=3)))
    messages.clear()
    assert cli.main(["discovery-status"], output=messages.append, session_factory=factory) == 1
    assert any(line.startswith("- jobicy: interrupted") for line in messages)
    assert any(line == "- remoteok: never run" for line in messages)


def test_a_recent_running_run_is_not_called_interrupted() -> None:
    run = JobDiscoveryRun(source_kind="jobicy", source_key="public", status="running", started_at=NOW - timedelta(minutes=5))
    assert effective_run_status(run, NOW) == "running"
    assert effective_run_status(run, NOW + timedelta(hours=2)) == "interrupted"


# --- refresh endpoint ---------------------------------------------------------------------


@pytest.fixture
def synchronous_refresh(monkeypatch):
    """Run refreshes inline with synthetic sources: no thread, no network."""
    monkeypatch.setattr(discovery_runner, "refresh_state", discovery_runner.RefreshState())
    original = discovery_runner.run_refresh_in_background

    def inline(factory, entries, *, full=False, launch=None):
        return original(factory, entries, full=full, launch=lambda work: work())

    monkeypatch.setattr("app.api.v1.job_discovery.run_refresh_in_background", inline)
    monkeypatch.setattr(discovery_runner, "_default_builder",
                        lambda entry: JobicySource(fetcher=recorder(lambda url: {"jobs": [jobicy_job(1)]})[0]))


def test_refresh_endpoint_starts_a_pass_and_reports_progress(api_client: TestClient, synchronous_refresh) -> None:
    response = api_client.post("/api/v1/job-discovery/refresh", json={"sources": ["jobicy"]})
    assert response.status_code == 202 and response.json()["requested"] == ["jobicy"]
    state = api_client.get("/api/v1/job-discovery/refresh").json()
    assert state["state"] == "finished" and state["outcomes"][0]["status"] == "succeeded"
    runs = api_client.get("/api/v1/job-discovery/runs").json()
    assert runs[0]["source_id"] == "jobicy" and runs[0]["display_status"] == "succeeded"


def test_refresh_endpoint_rejects_unknown_manual_and_concurrent_requests(api_client: TestClient, synchronous_refresh, monkeypatch) -> None:
    assert api_client.post("/api/v1/job-discovery/refresh", json={"sources": ["nope"]}).status_code == 422
    manual = next(entry.id for entry in load_registry() if entry.method == "manual")
    assert api_client.post("/api/v1/job-discovery/refresh", json={"sources": [manual]}).status_code == 422
    monkeypatch.setattr(discovery_runner, "refresh_state", discovery_runner.RefreshState(state="running"))
    assert api_client.post("/api/v1/job-discovery/refresh", json={}).status_code == 409


def test_refresh_endpoint_requires_a_session_and_csrf(unauthenticated_client: TestClient, synchronous_refresh) -> None:
    assert unauthenticated_client.post("/api/v1/job-discovery/refresh", json={}).status_code == 401


def test_refresh_router_has_only_the_start_and_progress_routes() -> None:
    from app.api.v1.job_discovery import router

    assert sorted((route.path, *sorted(route.methods)) for route in router.routes) == [
        ("/job-discovery/refresh", "GET"), ("/job-discovery/refresh", "POST")]


# --- listing filters, sorting, provenance and eligibility of aggregator jobs ----------------


def _store(factory, title: str, *, kind="jobicy", key="public", category="aggregator", workplace=None,
           posted=None, first_seen=NOW, description="Join us.", location="Anywhere") -> str:
    with factory.begin() as session:
        row = JobListing(
            source_kind=kind, source_key=key, source_listing_id=str(uuid4()), source_url="https://jobicy.com/api/v2/remote-jobs",
            listing_url="https://jobicy.com/jobs/1", application_url="https://jobicy.com/jobs/1", employer_name="Synthetic Co",
            title=title, description_text=description, location_text=location, source_category=category,
            stated_workplace_type=workplace, content_hash=uuid4().hex * 2, dedupe_key=uuid4().hex * 2, source_status="active",
            posted_at=posted, first_seen_at=first_seen, last_seen_at=first_seen, last_verified_at=first_seen,
        )
        session.add(row)
        session.flush()
        return str(row.id)


def test_source_workplace_sort_and_posting_date_provenance(api_client: TestClient, database) -> None:
    _, factory = database
    _store(factory, "Seller Support Associate", workplace="remote", posted=NOW - timedelta(days=2), first_seen=NOW - timedelta(days=1))
    _store(factory, "Backend Engineer", workplace="remote", posted=NOW - timedelta(hours=1), first_seen=NOW - timedelta(days=3))
    _store(factory, "Help Desk Analyst", kind="greenhouse", key="gitlab", category="direct_employer", workplace="onsite",
           posted=None, first_seen=NOW - timedelta(hours=2))

    def titles(query: str) -> list[str]:
        return [item["title"] for item in api_client.get(f"{API}?{query}").json()["items"]]

    assert titles("source=jobicy") == ["Backend Engineer", "Seller Support Associate"]
    assert titles("workplace=onsite") == ["Help Desk Analyst"]
    assert titles("sort=posted") == ["Backend Engineer", "Seller Support Associate", "Help Desk Analyst"]  # undated last
    assert titles("sort=discovered") == ["Help Desk Analyst", "Seller Support Associate", "Backend Engineer"]
    assert titles("sort=relevance") == ["Seller Support Associate", "Help Desk Analyst", "Backend Engineer"]
    assert titles("role_family=ecommerce_support") == ["Seller Support Associate"]
    assert api_client.get(f"{API}?source=nope").status_code == 422
    items = {item["title"]: item for item in api_client.get(API).json()["items"]}
    assert items["Seller Support Associate"]["posted_at_source"] == "job_board"
    assert items["Help Desk Analyst"]["posted_at_source"] is None
    assert items["Seller Support Associate"]["role_match"]["group"] == "ecommerce_support"
    # Date windows never count undated listings as fresh.
    assert titles("posted_within_hours=72") == ["Backend Engineer", "Seller Support Associate"]


def test_aggregator_kenya_wording_is_never_treated_as_authoritative(api_client: TestClient, database) -> None:
    _, factory = database
    _store(factory, "Customer Support Agent", location="Remote - Kenya",
           description="This role is open to candidates based in Kenya.", posted=NOW - timedelta(hours=1))
    (item,) = api_client.get(API).json()["items"]
    assert item["kenya_eligibility"]["state"] == "unverified"
    assert api_client.get(f"{API}?kenya=eligible").json()["total"] == 0
    assert api_client.get(f"{API}?kenya=unverified&role_family=customer_support").json()["total"] == 1


def test_pipeline_accepts_several_role_groups_and_exclusions(api_client: TestClient, database) -> None:
    _, factory = database
    for title in ("Help Desk Analyst", "Customer Care Agent", "Seller Support Associate", "Backend Engineer"):
        _store(factory, title, posted=NOW - timedelta(hours=1))
    profile_id = api_client.post("/api/v1/candidate-profiles", json={"name": "Amina Wanjiru"}).json()["id"]

    def titles(query: str) -> set[str]:
        result = api_client.get(f"/api/v1/candidate-profiles/{profile_id}/job-pipeline?include_fit=false&{query}").json()
        return {card["title"] for cards in result["queues"].values() for card in cards}

    assert titles("role_family=support_it") == {"Help Desk Analyst"}
    assert titles("role_family=support_it&role_family=customer_support") == {"Help Desk Analyst", "Customer Care Agent"}
    assert titles("exclude_role_family=ecommerce_support") == {"Help Desk Analyst", "Customer Care Agent", "Backend Engineer"}
