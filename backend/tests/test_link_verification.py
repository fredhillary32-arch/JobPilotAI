"""Direct-link verification, vacancy status, duplicates, filters and source health."""

from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import cli
from app.models import JobDiscoveryRun, JobListing, JobListingLinkCheck
from app.services.link_verification import check_link, verify_listing_links

API = "/api/v1/job-listings"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
GH = "https://job-boards.greenhouse.io/gitlab/jobs/1"


class _Page:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int) -> bytes:
        return b"<html>job</html>"


def _opener(routes: dict, calls: list[str] | None = None):
    def open_once(url: str):
        if calls is not None:
            calls.append(url)
        event = routes[url]
        if isinstance(event, BaseException):
            raise event
        if isinstance(event, tuple):  # (status, location) redirect
            raise HTTPError(url, event[0], "redirect", {"Location": event[1]}, None)
        return _Page(event)

    return open_once


def _gh_owner(host):
    return host in ("job-boards.greenhouse.io", "about.gitlab.com")


@pytest.mark.parametrize(
    "routes, outcome",
    [
        ({GH: 200}, "reachable"),
        ({GH: HTTPError(GH, 404, "nf", {}, None)}, "expired"),
        ({GH: HTTPError(GH, 410, "gone", {}, None)}, "expired"),
        ({GH: HTTPError(GH, 403, "no", {}, None)}, "auth_required"),
        ({GH: HTTPError(GH, 429, "slow", {}, None)}, "rate_limited"),
        ({GH: HTTPError(GH, 500, "err", {}, None)}, "broken"),
        ({GH: URLError("down")}, "unreachable"),
        ({GH: (302, "/gitlab?error=true"), "https://job-boards.greenhouse.io/gitlab?error=true": 200}, "expired"),
        ({GH: (302, "https://about.gitlab.com/jobs/1"), "https://about.gitlab.com/jobs/1": 200}, "reachable"),
        (
            {GH: (302, "https://about.gitlab.com/users/sign_in"), "https://about.gitlab.com/users/sign_in": 200},
            "auth_required",
        ),
    ],
)
def test_link_outcomes(routes: dict, outcome: str) -> None:
    assert check_link(GH, _gh_owner, opener=_opener(routes)).outcome == outcome


def test_redirect_off_the_source_is_not_followed() -> None:
    calls: list[str] = []
    result = check_link(GH, _gh_owner, opener=_opener({GH: (301, "https://aggregator.test/job/1")}, calls))
    assert (result.outcome, result.final_url) == ("redirected_off_domain", "https://aggregator.test/job/1")
    assert calls == [GH]


@pytest.mark.parametrize(
    "url, outcome",
    [("http://job-boards.greenhouse.io/x", "insecure"), ("https://lookalike-gitlab.test/x", "unverified_domain")],
)
def test_insecure_or_unowned_links_are_never_requested(url: str, outcome: str) -> None:
    calls: list[str] = []
    assert check_link(url, _gh_owner, opener=_opener({}, calls)).outcome == outcome
    assert calls == []


def _store(factory: sessionmaker[Session], **overrides) -> UUID:
    values = dict(
        source_kind="greenhouse",
        source_key="gitlab",
        source_listing_id=str(uuid4()),
        source_url="https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true",
        listing_url=GH,
        application_url=GH,
        employer_name="GitLab",
        title="Support Engineer",
        description_text="Support customers.",
        location_text="Remote",
        content_hash="0" * 64,
        dedupe_key="1" * 64,
        source_status="active",
        source_category="direct_employer",
        posted_at=NOW,
        first_seen_at=NOW,
        last_seen_at=NOW,
        last_verified_at=NOW,
    )
    values.update(overrides)
    with factory.begin() as session:
        row = JobListing(**values)
        session.add(row)
        session.flush()
        return row.id


def test_shared_page_is_checked_once_and_form_is_not_claimed_tested(database) -> None:
    _, factory = database
    listing_id = _store(factory)
    calls: list[str] = []
    with factory() as session:
        rows = verify_listing_links(
            session, session.get(JobListing, listing_id), opener=_opener({GH: 200}, calls), now=NOW
        )
        session.commit()
    assert calls == [GH]
    assert [(r.url_kind, r.outcome) for r in rows] == [("listing", "reachable"), ("application", "reachable")]
    assert "the form itself was not tested" in rows[1].detail


def test_separate_page_and_form_are_checked_separately_with_a_delay(database) -> None:
    _, factory = database
    apply = "https://job-boards.greenhouse.io/gitlab/jobs/1/apply"
    listing_id = _store(factory, application_url=apply)
    slept: list[float] = []
    with factory() as session:
        rows = verify_listing_links(
            session,
            session.get(JobListing, listing_id),
            opener=_opener({GH: 200, apply: HTTPError(apply, 404, "nf", {}, None)}),
            now=NOW,
            sleep=slept.append,
            delay_seconds=2.0,
        )
    assert [(r.url_kind, r.outcome) for r in rows] == [("listing", "reachable"), ("application", "expired")]
    assert slept == [2.0]


def test_verify_links_cli_is_rate_limited_and_bounded(database) -> None:
    _, factory = database
    for _ in range(3):
        _store(factory)
    slept: list[float] = []
    output: list[str] = []

    code = cli.main(
        ["verify-links", "--limit", "2", "--delay", "1.5"],
        output=output.append,
        session_factory=factory,
        link_opener=_opener({GH: 200}),
        sleep=slept.append,
    )

    assert code == 0 and slept == [1.5]
    assert output == ["Checked 2 listing(s): application:reachable=2, listing:reachable=2."]
    assert cli.main(["verify-links", "--delay", "0.1"], output=output.append, session_factory=factory) == 2


def _check(factory, listing_id: UUID, kind: str, outcome: str, at: datetime = NOW) -> None:
    with factory.begin() as session:
        session.add(
            JobListingLinkCheck(
                job_listing_id=listing_id, url_kind=kind, url=GH, final_url=GH, outcome=outcome, checked_at=at
            )
        )


def test_listing_api_reports_source_links_and_vacancy_status(api_client: TestClient, database) -> None:
    _, factory = database
    open_id = _store(factory, title="Open role", dedupe_key="a" * 64)
    expired_id = _store(factory, title="Expired role", dedupe_key="b" * 64)
    _check(factory, open_id, "application", "reachable")
    _check(factory, expired_id, "application", "reachable", NOW - timedelta(days=2))
    _check(factory, expired_id, "listing", "expired")

    body = api_client.get(API).json()
    assert [item["title"] for item in body["items"]] == ["Open role"]
    item = body["items"][0]
    assert item["source"]["registered"] is True and item["source"]["registry_id"] == "gitlab"
    assert item["source"]["category"] == "direct_employer"
    assert item["links"]["application"]["outcome"] == "reachable" and item["links"]["listing"] is None
    assert item["vacancy_status"] == "listed_by_source"

    everything = {i["title"]: i for i in api_client.get(f"{API}?include_expired_links=true").json()["items"]}
    assert everything["Expired role"]["vacancy_status"] == "link_expired"


def test_verified_link_filter_needs_a_reachable_latest_application_check(api_client: TestClient, database) -> None:
    _, factory = database
    verified = _store(factory, title="Verified", dedupe_key="a" * 64)
    regressed = _store(factory, title="Was verified", dedupe_key="b" * 64)
    _store(factory, title="Never checked", dedupe_key="c" * 64)
    _check(factory, verified, "application", "reachable")
    _check(factory, regressed, "application", "reachable", NOW - timedelta(days=1))
    _check(factory, regressed, "application", "auth_required")

    titles = [i["title"] for i in api_client.get(f"{API}?verified_application_link=true").json()["items"]]
    assert titles == ["Verified"]


def test_cross_source_duplicates_collapse_to_the_employer_posting(api_client: TestClient, database) -> None:
    _, factory = database
    employer = _store(factory, title="Support Engineer", dedupe_key="d" * 64)
    agency = _store(
        factory,
        title="Support Engineer",
        dedupe_key="d" * 64,
        source_kind="ashby",
        source_key="agency",
        source_category="staffing_agency",
        first_seen_at=NOW - timedelta(days=1),
        listing_url="https://jobs.ashbyhq.com/agency/1",
        application_url="https://jobs.ashbyhq.com/agency/1/apply",
    )
    _store(factory, title="Support Engineer", dedupe_key="d" * 64)  # second opening at the same employer

    items = api_client.get(API).json()["items"]
    assert {i["source_key"] for i in items} == {"gitlab"} and len(items) == 2
    assert {i["duplicate_group_size"] for i in items} == {2}
    detail = api_client.get(f"{API}/{employer}").json()
    assert [a["id"] for a in detail["alternates"]] == [str(agency)]
    assert len(api_client.get(f"{API}?collapse_duplicates=false").json()["items"]) == 3


def test_search_role_family_and_category_filters(api_client: TestClient, database) -> None:
    _, factory = database
    _store(factory, title="Customer Support Specialist", dedupe_key="e" * 64)
    _store(factory, title="Staff Backend Engineer", dedupe_key="f" * 64)
    _store(factory, title="VoIP Network Technician", dedupe_key="g" * 64, source_category="staffing_agency")

    def titles(query: str) -> set[str]:
        return {i["title"] for i in api_client.get(f"{API}?{query}").json()["items"]}

    # Customer support is its own role group since the multi-source taxonomy.
    assert titles("role_family=support_it") == {"VoIP Network Technician"}
    assert titles("role_family=customer_support") == {"Customer Support Specialist"}
    assert titles("role_family=support_it&role_family=customer_support") == {
        "Customer Support Specialist",
        "VoIP Network Technician",
    }
    assert titles("exclude_role_family=support_it") == {"Customer Support Specialist", "Staff Backend Engineer"}
    assert titles("q=backend,voip") == {"Staff Backend Engineer", "VoIP Network Technician"}
    assert titles("q=backend") == {"Staff Backend Engineer"}
    assert titles("q=100%25") == set()
    assert titles("source_category=staffing_agency") == {"VoIP Network Technician"}


def test_eligible_scope_filter(api_client: TestClient, database) -> None:
    _, factory = database
    worldwide_text = "This role is open to candidates in any country."
    africa_text = "Open to candidates in any African country."
    worldwide = _store(factory, title="Worldwide", dedupe_key="h" * 64, description_text=worldwide_text)
    africa = _store(factory, title="Africa", dedupe_key="i" * 64, description_text=africa_text)
    for listing_id, quote, scope in ((worldwide, worldwide_text, "worldwide"), (africa, africa_text, "africa")):
        response = api_client.post(
            f"{API}/{listing_id}/eligibility-assessments",
            json={
                "outcome": "eligible_confirmed",
                "explanation": "Quoted.",
                "quotation": quote,
                "evidence_field": "description",
                "statement_scope": "role",
                "role_applicability": "direct",
                "geographic_scope": scope,
            },
        )
        assert response.status_code == 201, response.text

    assert [i["title"] for i in api_client.get(f"{API}?eligible_scope=africa").json()["items"]] == ["Africa"]
    assert [i["title"] for i in api_client.get(f"{API}?eligible_scope=worldwide").json()["items"]] == ["Worldwide"]


def test_worldwide_claim_with_a_kenya_exclusion_cannot_be_confirmed(api_client: TestClient, database) -> None:
    _, factory = database
    text = "This role is open to candidates in any country.\nWe are unable to hire in Kenya or Nigeria."
    listing_id = _store(factory, description_text=text)

    evidence = api_client.get(f"{API}/{listing_id}/eligibility-evidence").json()
    assert {p["kind"] for p in evidence["passages"]} >= {"worldwide_claim", "kenya_exclusion", "location_label"}
    assert "The listing contains a statement excluding Kenya." in evidence["conflicts"]

    confirm = api_client.post(
        f"{API}/{listing_id}/eligibility-assessments",
        json={
            "outcome": "eligible_confirmed",
            "explanation": "Worldwide.",
            "quotation": "This role is open to candidates in any country.",
            "evidence_field": "description",
            "statement_scope": "role",
            "role_applicability": "direct",
            "geographic_scope": "worldwide",
        },
    )
    assert confirm.status_code == 409
    assert "We are unable to hire in Kenya or Nigeria." in confirm.json()["detail"]
    conflicting = api_client.post(
        f"{API}/{listing_id}/eligibility-assessments",
        json={
            "outcome": "eligibility_unknown",
            "explanation": "Worldwide claim but Kenya excluded.",
            "geographic_scope": "conflicting",
        },
    )
    assert conflicting.status_code == 201
    assert api_client.get(f"{API}/{listing_id}").json()["eligibility"]["geographic_scope"] == "conflicting"


def test_geographic_scope_must_fit_the_outcome(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store(factory)
    response = api_client.post(
        f"{API}/{listing_id}/eligibility-assessments",
        json={
            "outcome": "eligibility_unknown",
            "explanation": "x",
            "geographic_scope": "worldwide",
        },
    )
    assert response.status_code == 422


def test_source_health_reports_manual_never_run_and_failing_sources(api_client: TestClient, database) -> None:
    _, factory = database
    with factory.begin() as session:
        for minutes in (1, 2, 3):
            session.add(
                JobDiscoveryRun(
                    source_kind="greenhouse",
                    source_key="canonical",
                    status="failed",
                    error_category="unavailable",
                    started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes),
                )
            )
        session.add(
            JobDiscoveryRun(
                source_kind="greenhouse",
                source_key="gitlab",
                status="succeeded",
                started_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
    _store(factory)

    sources = {s["id"]: s for s in api_client.get("/api/v1/job-sources").json()}
    assert (sources["gitlab"]["health"], sources["gitlab"]["active_listings"]) == ("healthy", 1)
    assert (sources["canonical"]["health"], sources["canonical"]["consecutive_failures"]) == ("failing", 3)
    assert sources["toggl"]["health"] == "disabled"  # board link found, but the API returned 404
    assert sources["kraken"]["health"] == "never_run"
    assert sources["randstad"]["health"] == "manual_only" and sources["randstad"]["category"] == "staffing_agency"
