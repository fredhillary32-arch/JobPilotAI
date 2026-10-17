"""Source registry validation, registry-driven discovery and run provenance."""
import copy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import cli
from app.models import JobDiscoveryRun, JobListing
from app.services.job_discovery import SourceFetchError, SourceListing, run_discovery
from app.services.source_registry import AGGREGATOR_METHODS, RegistryError, load_registry, parse_registry

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
VALID = {
    "id": "syntheticco", "name": "Synthetic Co", "category": "direct_employer",
    "official_domain": "synthetic.example", "additional_domains": [],
    "careers_url": "https://synthetic.example/careers",
    "discovery": {"method": "ashby", "board": "syntheticco", "instance": None}, "enabled": True,
    "verification": {"checked_at": "2026-10-16T23:00:00Z", "outcome": "board_found_on_official_page", "evidence": "x"},
}


def _registry(*entries) -> dict:
    return {"entries": [copy.deepcopy(entry) for entry in entries]}


def test_shipped_registry_is_valid_and_only_enables_verified_boards() -> None:
    registry = load_registry()
    assert len({entry.id for entry in registry}) == len(registry)
    for entry in registry:
        assert entry.careers_url.startswith("https://")
        if entry.enabled and entry.method in AGGREGATOR_METHODS:
            # Public aggregator APIs: enabled on documented terms, never as employer evidence.
            assert entry.category == "aggregator" and entry.board == "public" and entry.terms
            assert entry.verification["outcome"] == "public_api_documented"
        elif entry.enabled:
            assert entry.board and entry.verification["outcome"] == "board_found_on_official_page"
        elif entry.method == "manual":
            assert entry.board is None
        else:
            # A disabled platform source must record why it is not enabled.
            assert entry.verification["outcome"] != "board_found_on_official_page"
    categories = {entry.category for entry in registry}
    assert {"direct_employer", "staffing_agency", "recruitment_outsourcing"} <= categories


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda e: e.update(category="mystery"), "unknown category"),
        (lambda e: e.update(careers_url="https://lookalike-synthetic.test/careers"), "official domain"),
        (lambda e: e.update(careers_url="http://synthetic.example/careers"), "official domain"),
        (lambda e: e["discovery"].update(method="manual"), "manual sources"),
        (lambda e: e["discovery"].update(board=None), "verified board"),
        (lambda e: e["verification"].update(outcome="careers_page_reachable_no_feed"), "only sources whose board"),
        (lambda e: e["discovery"].update(board="../escape"), "Ashby job board names"),
    ],
)
def test_unsafe_registry_entries_are_rejected(change, message: str) -> None:
    entry = copy.deepcopy(VALID)
    change(entry)
    with pytest.raises((RegistryError, ValueError), match=message):
        parse_registry(_registry(entry))


def test_duplicate_ids_and_boards_are_rejected() -> None:
    with pytest.raises(RegistryError, match="duplicate"):
        parse_registry(_registry(VALID, VALID))
    other = {**copy.deepcopy(VALID), "id": "another"}
    with pytest.raises(RegistryError, match="already registered"):
        parse_registry(_registry(VALID, other))


def test_link_hosts_belong_to_the_platform_or_official_domain() -> None:
    [entry] = parse_registry(_registry(VALID))
    assert entry.owns_host("jobs.ashbyhq.com") and entry.owns_host("careers.synthetic.example")
    assert not entry.owns_host("synthetic.example.evil.test") and not entry.owns_host("jobs.lever.co")


class _FakeSource:
    def __init__(self, key: str, listings=None, error: Exception | None = None) -> None:
        self.kind, self.key, self._listings, self._error = "ashby", key, listings or [], error

    def fetch(self):
        if self._error:
            raise self._error
        return self._listings


def _listing(identifier: str, **extra) -> SourceListing:
    values = dict(
        source_listing_id=identifier, source_url="https://api.ashbyhq.com/posting-api/job-board/x",
        listing_url=f"https://jobs.ashbyhq.com/x/{identifier}", application_url=f"https://jobs.ashbyhq.com/x/{identifier}/application",
        employer_name="Synthetic Co", title="Support Specialist",
    )
    values.update(extra)
    return SourceListing(**values)


def test_one_failing_source_does_not_stop_the_others(database, monkeypatch) -> None:
    _, factory = database
    registry = parse_registry(_registry(
        {**copy.deepcopy(VALID), "id": "ok-source", "discovery": {"method": "ashby", "board": "ok", "instance": None}},
        {**copy.deepcopy(VALID), "id": "flaky", "discovery": {"method": "ashby", "board": "flaky", "instance": None}},
        {**copy.deepcopy(VALID), "id": "crashing", "discovery": {"method": "ashby", "board": "crashing", "instance": None}},
    ))
    monkeypatch.setattr(cli, "load_registry", lambda: registry)
    sources = {
        "ok-source": _FakeSource("ok", [_listing("1"), _listing("2", application_url="http://insecure.test/apply"), _listing("1")]),
        "flaky": _FakeSource("flaky", error=SourceFetchError("rate_limited")),
        "crashing": _FakeSource("crashing", error=RuntimeError("boom")),
    }
    output: list[str] = []

    code = cli.main(["discover-registry"], output=output.append, session_factory=factory,
                    registry_source_factory=lambda entry: sources[entry.id])

    assert code == 1
    assert any(line.startswith("ok-source: fetched 3, new 1") for line in output)
    assert "duplicate in response: 1" in output[0] and "no usable https application URL: 1" in output[0]
    assert "flaky: failed (rate_limited); stored listings were not changed." in output
    assert any(line.startswith("crashing: failed with an internal error") for line in output)
    assert output[-1] == "1 of 3 sources succeeded."
    with factory() as session:
        stored = session.scalars(select(JobListing)).all()
        assert [(row.source_key, row.source_category) for row in stored] == [("ok", "direct_employer")]
        run = session.scalars(select(JobDiscoveryRun).where(JobDiscoveryRun.source_key == "ok")).one()
        assert run.skip_reasons == {"duplicate in response": 1, "no usable https application URL": 1}


def test_manual_and_unknown_sources_are_refused(database) -> None:
    _, factory = database
    output: list[str] = []
    assert cli.main(["discover-registry", "--source", "randstad"], output=output.append, session_factory=factory) == 2
    assert "Manual-only sources are never fetched: randstad" in output
    assert cli.main(["discover-registry", "--source", "not-a-source"], output=output.append, session_factory=factory) == 2


def test_list_sources_reports_registry_counts() -> None:
    output: list[str] = []
    assert cli.main(["list-sources"], output=output.append) == 0
    registry = load_registry()
    assert output[0] == f"{len(registry)} registered sources, {sum(e.enabled for e in registry)} enabled for automatic discovery."


def test_relisted_vacancy_keeps_its_stated_posting_date(database) -> None:
    _, factory = database
    posted = NOW - timedelta(days=3)
    with factory() as session:
        run_discovery(session, _FakeSource("x", [_listing("1", posted_at=posted)]), now=NOW)
        run_discovery(session, _FakeSource("x", []), now=NOW + timedelta(hours=1))
        run_discovery(session, _FakeSource("x", [_listing("1", posted_at=posted)]), now=NOW + timedelta(hours=2))
        row = session.scalars(select(JobListing)).one()
        assert row.source_status == "active"
        assert row.relisted_at.replace(tzinfo=timezone.utc) == NOW + timedelta(hours=2)
        assert row.posted_at.replace(tzinfo=timezone.utc) == posted
        assert row.listing_url == "https://jobs.ashbyhq.com/x/1"


AGGREGATOR = {
    "id": "jobicy-test", "name": "Jobicy", "category": "aggregator", "official_domain": "jobicy.com",
    "careers_url": "https://jobicy.com/jobs-rss-feed", "discovery": {"method": "jobicy", "board": "public"},
    "enabled": True, "verification": {"outcome": "public_api_documented", "checked_at": "2026-10-17T00:00:00Z"},
    "terms": "Credit Jobicy and keep its canonical URL.",
}


def test_aggregator_api_entry_is_accepted_and_builds_a_partial_window_source() -> None:
    (entry,) = parse_registry(_registry(AGGREGATOR))
    source = entry.build_source()
    assert (source.kind, source.key, source.category) == ("jobicy", "public", "aggregator")
    assert source.complete_snapshot is False
    assert entry.owns_host("jobicy.com") and not entry.owns_host("jobicy.com.evil.test")


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda e: e.update(category="direct_employer"), "aggregator API"),
        (lambda e: e["discovery"].update(board="other"), "aggregator API"),
        (lambda e: e["verification"].update(outcome="board_found_on_official_page"), "documented public API terms"),
        (lambda e: e.update(terms=""), "record the API terms"),
    ],
)
def test_aggregator_entries_need_aggregator_category_and_documented_terms(change, message: str) -> None:
    entry = copy.deepcopy(AGGREGATOR)
    change(entry)
    with pytest.raises(RegistryError, match=message):
        parse_registry(_registry(entry))
