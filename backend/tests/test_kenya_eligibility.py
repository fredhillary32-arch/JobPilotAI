"""Strict Kenya eligibility decisions: fail closed, evidence-backed, never inferred."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models import JobListing, ListingEligibilityAssessment
from app.services.kenya_eligibility import CandidateFacts, decide, decide_cached

CHECKED = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


def listing(
    *,
    location: str | None = "Remote",
    description: str = "Join our support team.",
    title: str = "IT Support Specialist",
    source_key: str = "gitlab",
    category: str | None = "direct_employer",
    listing_url: str | None = "https://job-boards.greenhouse.io/gitlab/jobs/1",
    application_url: str = "https://job-boards.greenhouse.io/gitlab/jobs/1",
) -> JobListing:
    return JobListing(
        id=uuid4(),
        source_kind="greenhouse",
        source_key=source_key,
        source_listing_id="1",
        source_url="https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true",
        listing_url=listing_url,
        application_url=application_url,
        employer_name="GitLab",
        title=title,
        description_text=description,
        location_text=location,
        source_category=category,
        content_hash="0" * 64,
        dedupe_key="1" * 64,
        source_status="active",
        first_seen_at=CHECKED,
        last_seen_at=CHECKED,
        last_verified_at=CHECKED,
    )


def review(
    item: JobListing,
    outcome: str,
    quotation: str | None,
    *,
    field: str = "description",
    examined_description: str | None = None,
) -> ListingEligibilityAssessment:
    return ListingEligibilityAssessment(
        id=uuid4(),
        job_listing_id=item.id,
        outcome=outcome,
        explanation="Reviewed.",
        quotation=quotation,
        evidence_field=field if quotation else None,
        statement_scope="role",
        role_applicability="direct",
        examined_description=item.description_text if examined_description is None else examined_description,
        examined_location=item.location_text,
        listing_content_hash=item.content_hash,
        assessed_at=CHECKED,
    )


def test_official_listing_naming_kenya_is_eligible_with_traceable_evidence() -> None:
    decision = decide(listing(location="Nairobi, Kenya"))
    assert decision["state"] == "eligible" and decision["rule"] == "location_label_names_kenya"
    evidence = decision["evidence"][0]
    assert (
        evidence["quotation"] == "Nairobi, Kenya"
        and evidence["field"] == "location"
        and "Kenya" in evidence["countries"]
    )
    assert decision["source_url"].startswith("https://") and decision["source_type"].startswith("greenhouse board")
    assert decision["checked_at"] == CHECKED and decision["explanation"]


def test_role_scoped_description_naming_kenya_is_eligible() -> None:
    text = "About the role. This role is open to candidates based in Kenya, Nigeria or Ghana."
    decision = decide(listing(location=None, description=text))
    assert decision["state"] == "eligible" and decision["rule"] == "description_names_kenya"
    assert decision["evidence"][0]["quotation"] in text


@pytest.mark.parametrize("location", ["Remote", "Home based", None])
def test_remote_alone_or_missing_location_is_unverified(location) -> None:
    decision = decide(listing(location=location))
    assert decision["state"] == "unverified"


def test_company_marketing_that_mentions_kenya_is_not_evidence() -> None:
    decision = decide(listing(location="Remote", description="We serve 10 million customers across Kenya and Uganda."))
    assert decision["state"] == "unverified"


def test_regions_that_contain_kenya_without_naming_it_are_unverified() -> None:
    for label in ("Home based - EMEA", "Remote - Africa"):
        decision = decide(listing(location=label))
        assert (decision["state"], decision["rule"]) == ("unverified", "region_without_kenya_named")


def test_worldwide_label_is_eligible_but_not_with_a_conflicting_restriction() -> None:
    assert decide(listing(location="Home based - Worldwide"))["state"] == "eligible"
    conflicted = decide(listing(location="Home based - Worldwide", description="You must reside in the United States."))
    assert conflicted["state"] == "unverified" and conflicted["rule"] == "conflicting_evidence"
    assert any(item["rule"] == "residency_restricted_elsewhere" for item in conflicted["conflicts"])


def test_role_scoped_worldwide_wording_counts_but_hedged_or_company_wording_does_not() -> None:
    assert decide(listing(description="Location: This is a globally remote role."))["state"] == "eligible"
    assert (
        decide(listing(description="While we hire almost anywhere in the world, we prefer US residents."))["state"]
        == "unverified"
    )
    assert decide(listing(description="Work from anywhere: our company has no borders or HQ."))["state"] == "unverified"


@pytest.mark.parametrize(
    "location", ["Remote, United States", "United States", "Spain; Portugal; South Africa", "Lagos", "North America"]
)
def test_locations_that_exclude_kenya_are_ineligible(location) -> None:
    decision = decide(listing(location=location))
    assert decision["state"] == "ineligible" and decision["rule"] == "location_label_excludes_kenya"
    assert decision["evidence"][0]["quotation"] == location


def test_us_only_wording_is_ineligible_even_with_template_global_text() -> None:
    decision = decide(listing(location="Remote", description="Remote-Global\nMust be located in the United States."))
    assert decision["state"] == "ineligible" and decision["rule"] == "residency_restricted_elsewhere"


def test_explicit_kenya_exclusion_and_titles_for_other_markets_are_ineligible() -> None:
    assert (
        decide(listing(description="Applicants based in Kenya are not eligible for this role."))["state"]
        == "ineligible"
    )
    titled = decide(listing(title="Account Executive, US", location="Remote"))
    assert titled["state"] == "ineligible" and titled["rule"] == "title_names_other_country"


def test_salary_notes_for_residents_are_not_location_restrictions() -> None:
    text = "The salary range for this role is for residents of the United States only."
    assert decide(listing(location="Nairobi, Kenya", description=text))["state"] == "eligible"


def test_work_authorization_is_never_inferred_from_residence() -> None:
    text = "You must be authorized to work in the United Kingdom."
    item = listing(location="Home based - Worldwide", description=text)
    assert decide(item)["state"] == "needs_candidate_input"
    assert decide(item, facts=CandidateFacts(residence="KE"))["state"] == "needs_candidate_input"
    assert (
        decide(item, facts=CandidateFacts(residence="KE", authorizations={"GB": "authorized"}))["state"] == "eligible"
    )
    denied = decide(item, facts=CandidateFacts(residence="KE", authorizations={"GB": "not_authorized"}))
    assert denied["state"] == "ineligible" and denied["rule"] == "work_authorization_not_held"


def test_current_candidate_review_decides_and_stale_review_is_unverified() -> None:
    text = "This role is open to applicants based anywhere."
    item = listing(location="Remote", description=text)
    assert decide(item, review(item, "eligible_confirmed", text))["state"] == "eligible"
    assert decide(item, review(item, "not_eligible", text))["state"] == "ineligible"
    stale = decide(item, review(item, "eligible_confirmed", text, examined_description="Older wording of the listing."))
    assert (stale["state"], stale["rule"]) == ("unverified", "candidate_review_stale")


def test_fabricated_quotation_or_missing_source_link_cannot_approve() -> None:
    item = listing(location="Remote", description="Join our team.")
    fabricated = decide(item, review(item, "eligible_confirmed", "Applicants in Kenya are welcome."))
    assert (fabricated["state"], fabricated["rule"]) == ("unverified", "review_evidence_invalid")
    no_link = listing(location="Nairobi, Kenya", listing_url=None, application_url="http://example.com/apply")
    assert (decide(no_link)["state"], decide(no_link)["rule"]) == ("unverified", "no_source_url")


def test_aggregator_or_unregistered_sources_are_not_authoritative() -> None:
    assert decide(listing(location="Nairobi, Kenya", category="aggregator"))["rule"] == "source_not_authoritative"
    unregistered = decide(listing(location="Nairobi, Kenya", source_key="unknown-board", category=None))
    assert unregistered["state"] == "unverified" and unregistered["source_authoritative"] is False


def test_changed_wording_is_re_evaluated_not_served_from_cache() -> None:
    item = listing(location="Remote", description="Location: This is a globally remote role.")
    assert decide_cached(item, None, None)["state"] == "eligible"
    item.description_text = "Location: This role is based in Toronto. You must reside in Canada."
    assert decide_cached(item, None, None)["state"] == "ineligible"


def test_every_evidence_quotation_is_exact_source_text() -> None:
    cases = [
        listing(location="Johannesburg; Nairobi"),
        listing(description="Location: This is a globally remote role. You must reside in the United States."),
        listing(location="Remote, Canada"),
    ]
    for item in cases:
        decision = decide(item)
        for evidence in decision["evidence"] + decision["conflicts"]:
            source = {"location": item.location_text, "description": item.description_text, "title": item.title}[
                evidence["field"]
            ]
            assert evidence["quotation"] in source
