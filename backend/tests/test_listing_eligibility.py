"""Reviewed Kenya eligibility (docs/JOB_ELIGIBILITY_SPEC.md; case IDs in comments)."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import JobListing

API = "/api/v1/job-listings"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
DESCRIPTION = (
    "We are a global, all-remote company.\n"
    "This role is fully remote and open to candidates in any country.\n"
    "You will support customers by phone and chat."
)
WORLDWIDE = "This role is fully remote and open to candidates in any country."


def _store_listing(factory: sessionmaker[Session], **overrides) -> UUID:
    values = {
        "source_kind": "greenhouse",
        "source_key": "syntheticco",
        "source_listing_id": str(uuid4()),
        "source_url": "https://boards-api.greenhouse.io/v1/boards/syntheticco/jobs?content=true",
        "application_url": "https://job-boards.greenhouse.io/syntheticco/jobs/101",
        "employer_name": "Synthetic Co",
        "title": "Technical Support Specialist",
        "description_text": DESCRIPTION,
        "location_text": "Remote",
        "content_hash": "0" * 64,
        "dedupe_key": "1" * 64,
        "source_status": "active",
        "posted_at": NOW,
        "source_updated_at": NOW,
        "first_seen_at": NOW,
        "last_seen_at": NOW,
        "last_verified_at": NOW,
    }
    values.update(overrides)
    with factory.begin() as session:
        listing = JobListing(**values)
        session.add(listing)
        session.flush()
        return listing.id


def _update_listing(factory: sessionmaker[Session], listing_id: UUID, **changes) -> None:
    with factory.begin() as session:
        listing = session.get(JobListing, listing_id)
        for field, value in changes.items():
            setattr(listing, field, value)


def _confirm(client: TestClient, listing_id: UUID, **overrides):
    payload = {
        "outcome": "eligible_confirmed",
        "explanation": "The description opens the role to candidates in any country.",
        "quotation": WORLDWIDE,
        "evidence_field": "description",
        "statement_scope": "role",
        "role_applicability": "direct",
    }
    payload.update(overrides)
    return client.post(f"{API}/{listing_id}/eligibility-assessments", json=payload)


def _eligibility(client: TestClient, listing_id: UUID) -> dict:
    return client.get(f"{API}/{listing_id}").json()["eligibility"]


def test_unassessed_listing_is_unknown_and_marked_not_assessed(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)

    eligibility = _eligibility(api_client, listing_id)

    assert eligibility["status"] == "eligibility_unknown"
    assert eligibility["currency"] == "not_assessed"
    assert eligibility["quotation"] is None


def test_confirmation_with_exact_role_quotation_is_current(api_client: TestClient, database) -> None:  # EL-01
    _, factory = database
    listing_id = _store_listing(factory)

    response = _confirm(api_client, listing_id)

    assert response.status_code == 201, response.text
    eligibility = _eligibility(api_client, listing_id)
    assert eligibility["status"] == "eligible_confirmed"
    assert eligibility["currency"] == "current"
    assert eligibility["quotation"] == WORLDWIDE
    history = api_client.get(f"{API}/{listing_id}/eligibility-assessments").json()
    assert history[0]["quote_start"] == DESCRIPTION.index(WORLDWIDE)
    assert history[0]["listing_content_hash"] == "0" * 64


def test_quotation_must_match_the_source_text_exactly(api_client: TestClient, database) -> None:  # EL-28
    _, factory = database
    listing_id = _store_listing(factory)

    altered = _confirm(api_client, listing_id, quotation=WORLDWIDE.replace("any", "every"))
    respaced = _confirm(api_client, listing_id, quotation=WORLDWIDE.replace(" ", "  ", 1))
    wrong_field = _confirm(api_client, listing_id, evidence_field="location")

    assert [r.status_code for r in (altered, respaced, wrong_field)] == [422, 422, 422]
    assert _eligibility(api_client, listing_id)["currency"] == "not_assessed"


def test_definite_outcomes_need_quoted_role_applicable_evidence(api_client: TestClient, database) -> None:  # EL-29
    _, factory = database
    listing_id = _store_listing(factory)

    no_quote = _confirm(api_client, listing_id, quotation=None, evidence_field=None)
    unclear = _confirm(api_client, listing_id, role_applicability="unclear")
    marketing = _confirm(  # EL-15/EL-37: company reach is not a hiring policy
        api_client,
        listing_id,
        outcome="eligible_confirmed",
        quotation="We are a global, all-remote company.",
        statement_scope="company",
        role_applicability="not_applicable",
    )
    no_scope = _confirm(api_client, listing_id, statement_scope=None)

    assert [r.status_code for r in (no_quote, unclear, marketing, no_scope)] == [422, 422, 422, 422]


def test_company_policy_counts_only_when_its_wording_covers_the_role(api_client: TestClient, database) -> None:  # EL-17
    _, factory = database
    policy = "This applies to all of our open positions: we are unable to hire anyone based in Kenya."
    listing_id = _store_listing(factory, description_text=f"Support role.\n{policy}")

    response = _confirm(
        api_client,
        listing_id,
        outcome="not_eligible",
        explanation="A company-wide policy covering all positions excludes Kenya.",
        quotation=policy,
        statement_scope="company",
        role_applicability="established_by_wording",
    )

    assert response.status_code == 201, response.text
    eligibility = _eligibility(api_client, listing_id)
    assert (eligibility["status"], eligibility["statement_scope"]) == ("not_eligible", "company")


def test_reviewed_unknown_needs_no_quotation(api_client: TestClient, database) -> None:  # EL-07
    _, factory = database
    listing_id = _store_listing(factory, description_text="Remote support role.", location_text="Remote")

    response = api_client.post(
        f"{API}/{listing_id}/eligibility-assessments",
        json={"outcome": "eligibility_unknown", "explanation": "\"Remote\" without geography does not establish eligibility."},
    )

    assert response.status_code == 201
    eligibility = _eligibility(api_client, listing_id)
    assert (eligibility["status"], eligibility["currency"]) == ("eligibility_unknown", "current")
    assert eligibility["reason"] == "Kenya eligibility was reviewed but not established."


def test_changed_wording_makes_the_assessment_stale(api_client: TestClient, database) -> None:  # EV-01, EV-07
    _, factory = database
    description_changed = _store_listing(factory)
    location_changed = _store_listing(factory)
    for listing_id in (description_changed, location_changed):
        assert _confirm(api_client, listing_id).status_code == 201

    _update_listing(factory, description_changed, description_text=DESCRIPTION.replace("phone", "email"))
    _update_listing(factory, location_changed, location_text="Remote, United States")

    for listing_id in (description_changed, location_changed):
        eligibility = _eligibility(api_client, listing_id)
        assert eligibility["status"] == "eligibility_unknown"
        assert eligibility["currency"] == "stale"
        assert eligibility["previous_status"] == "eligible_confirmed"
        assert eligibility["reason"] == "Eligibility evidence changed; reassessment needed."


def test_whitespace_only_or_removed_text_is_a_change(api_client: TestClient, database) -> None:  # EV-13, EV-11
    _, factory = database
    whitespace = _store_listing(factory)
    removed = _store_listing(factory)
    for listing_id in (whitespace, removed):
        assert _confirm(api_client, listing_id).status_code == 201

    _update_listing(factory, whitespace, description_text=DESCRIPTION + "\n")
    _update_listing(factory, removed, description_text=None)

    assert _eligibility(api_client, whitespace)["currency"] == "stale"
    assert _eligibility(api_client, removed)["currency"] == "stale"


def test_timestamp_only_changes_keep_the_assessment_current(api_client: TestClient, database) -> None:  # EV-02, EV-03, EV-09
    _, factory = database
    listing_id = _store_listing(factory)
    assert _confirm(api_client, listing_id).status_code == 201

    _update_listing(
        factory,
        listing_id,
        source_updated_at=NOW + timedelta(days=1),
        posted_at=NOW + timedelta(hours=5),
        last_verified_at=NOW + timedelta(days=2),
        last_seen_at=NOW + timedelta(days=2),
        content_hash="f" * 64,
    )

    eligibility = _eligibility(api_client, listing_id)
    assert (eligibility["status"], eligibility["currency"]) == ("eligible_confirmed", "current")


def test_newest_assessment_wins_and_history_is_kept(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    assert _confirm(api_client, listing_id).status_code == 201
    second = api_client.post(
        f"{API}/{listing_id}/eligibility-assessments",
        json={"outcome": "eligibility_unknown", "explanation": "On reflection the wording is ambiguous."},
    )
    assert second.status_code == 201

    assert _eligibility(api_client, listing_id)["status"] == "eligibility_unknown"
    history = api_client.get(f"{API}/{listing_id}/eligibility-assessments").json()
    assert [item["outcome"] for item in history] == ["eligibility_unknown", "eligible_confirmed"]


def test_listings_can_be_filtered_by_effective_eligibility(api_client: TestClient, database) -> None:
    _, factory = database
    confirmed = _store_listing(factory, title="Confirmed role")
    stale = _store_listing(factory, title="Stale role")
    excluded = _store_listing(factory, title="Excluded role", description_text="Applicants must reside in the United Kingdom.")
    unassessed = _store_listing(factory, title="Unassessed role")
    assert _confirm(api_client, confirmed).status_code == 201
    assert _confirm(api_client, stale).status_code == 201
    assert _confirm(
        api_client,
        excluded,
        outcome="not_eligible",
        explanation="Applicants must live in the UK.",
        quotation="Applicants must reside in the United Kingdom.",
    ).status_code == 201
    _update_listing(factory, stale, description_text=DESCRIPTION + " Updated.")

    def titles(state: str) -> set[str]:
        body = api_client.get(f"{API}?eligibility={state}").json()
        assert body["total"] == len(body["items"])
        return {item["title"] for item in body["items"]}

    assert titles("eligible_confirmed") == {"Confirmed role"}
    assert titles("not_eligible") == {"Excluded role"}
    assert titles("eligibility_unknown") == {"Stale role", "Unassessed role"}
    assert unassessed  # stored, unassessed listing is part of the unknown set
    listed = {item["title"]: item["eligibility"]["status"] for item in api_client.get(API).json()["items"]}
    assert listed["Confirmed role"] == "eligible_confirmed"
    assert listed["Stale role"] == "eligibility_unknown"


def test_listing_no_longer_at_source_is_not_reassessed(api_client: TestClient, database) -> None:  # EV-06
    _, factory = database
    listing_id = _store_listing(factory, source_status="missing_from_source")

    assert _confirm(api_client, listing_id).status_code == 409


def test_unknown_listing_returns_404(api_client: TestClient) -> None:
    assert _confirm(api_client, uuid4()).status_code == 404
    assert api_client.get(f"{API}/{uuid4()}/eligibility-assessments").status_code == 404


def test_recording_an_assessment_requires_csrf(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)

    response = api_client.post(
        f"{API}/{listing_id}/eligibility-assessments",
        json={"outcome": "eligibility_unknown", "explanation": "Not stated."},
        headers={"X-CSRF-Token": "not-the-session-token"},
    )

    assert response.status_code == 403
    assert _eligibility(api_client, listing_id)["currency"] == "not_assessed"
