"""Job pipeline queues, strict Kenya filtering and application preparation (never submission)."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import (
    CandidateEvidence,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
    JobApplication,
    JobApplicationEvent,
    JobListing,
    TailoredCvDraft,
    User,
)
from app.services.application_methods import automatic_submission_available

API = "/api/v1/candidate-profiles"
NOW = datetime.now(UTC)
SUPPORT_TEXT = (
    "About the role. Resolve Windows laptop tickets for staff.\n\nRequirements:\n"
    "- Troubleshooting Windows laptops\n- Experience with Active Directory\n"
)


def add_listing(
    factory,
    *,
    title="IT Support Specialist",
    location="Nairobi, Kenya",
    description=SUPPORT_TEXT,
    source_key="gitlab",
    category="direct_employer",
    status="active",
    posted=NOW - timedelta(hours=3),
    first_seen=NOW,
    verified=NOW,
    dedupe=None,
    application_url="https://job-boards.greenhouse.io/gitlab/jobs/1",
    workplace=None,
    deadline=None,
) -> str:
    with factory.begin() as session:
        item = JobListing(
            source_kind="greenhouse",
            source_key=source_key,
            source_listing_id=str(uuid4()),
            source_url="https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true",
            listing_url=application_url,
            application_url=application_url,
            employer_name="GitLab",
            title=title,
            description_text=description,
            location_text=location,
            source_category=category,
            content_hash=uuid4().hex * 2,
            dedupe_key=dedupe or uuid4().hex * 2,
            source_status=status,
            posted_at=posted,
            first_seen_at=min(first_seen, verified),
            last_seen_at=verified,
            last_verified_at=verified,
            stated_workplace_type=workplace,
            application_deadline=deadline,
        )
        session.add(item)
        session.flush()
        return str(item.id)


def candidate(client: TestClient, factory) -> str:
    profile_id = client.post(
        API,
        json={
            "name": "Amina Wanjiru",
            "professional_headline": "IT Support Specialist",
            "contact_email": "amina@example.com",
            "summary": "Service desk analyst who keeps staff productive with fast, well documented fixes.",
        },
    ).json()["id"]
    with factory() as session:
        session.add(
            CandidateWorkExperience(
                candidate_profile_id=UUID(profile_id),
                employer="Savanna Telecom",
                job_title="IT Support Officer",
                start_date=date(2019, 1, 1),
                current_role=True,
                achievements=[
                    "Troubleshot Windows laptops for 300 staff across two offices",
                    "Managed Active Directory accounts for new starters and leavers",
                    "Documented common fixes so repeat tickets dropped across the service desk",
                    "Configured standard software on Windows laptops before issue to staff",
                    "Monitored Microsoft 365 licence usage and reported monthly costs to finance",
                ],
            )
        )
        session.add(CandidateSkill(candidate_profile_id=UUID(profile_id), name="Active Directory"))
        session.commit()
    return profile_id


def pipeline(client: TestClient, profile_id: str, **params) -> dict:
    response = client.get(f"{API}/{profile_id}/job-pipeline", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def card(result: dict, listing_id: str) -> dict:
    return next(item for items in result["queues"].values() for item in items if item["listing_id"] == listing_id)


def test_listings_are_sorted_into_separate_queues_with_reasons(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    eligible = add_listing(factory)
    remote = add_listing(factory, location="Remote")
    us_only = add_listing(factory, location="Remote, United States")
    unregistered = add_listing(factory, source_key="unknown-board", category=None)
    result = pipeline(api_client, profile_id)

    assert result["counts"] == {"auto_apply": 0, "needs_action": 1, "review_needed": 2, "not_eligible": 1}
    ready = card(result, eligible)
    assert ready["queue"] == "needs_action" and ready["eligibility"]["state"] == "eligible"
    assert (
        ready["reasons"][0]["code"] == "manual_submission"
        and "employer's private API key" in ready["reasons"][0]["message"]
    )
    assert "submit it yourself" in ready["next_step"]
    assert (
        ready["application_method"]["submission"] == "manual_submission"
        and ready["application_method"]["candidate_steps"]
    )
    assert ready["fit"]["essential_total"] >= 1 and ready["fit"]["score"] is not None
    assert card(result, remote)["queue"] == "review_needed"
    assert card(result, unregistered)["reasons"][0]["code"] == "unregistered_source"
    excluded = card(result, us_only)
    assert excluded["queue"] == "not_eligible" and excluded["reasons"][0]["code"] == "location_label_excludes_kenya"
    assert result["automation"]["automatic_submission_available"] is False


def test_no_platform_offers_automatic_submission_so_auto_apply_stays_empty(api_client: TestClient, database) -> None:
    assert not any(automatic_submission_available(kind) for kind in ("greenhouse", "lever", "ashby", "workday"))
    profile_id = candidate(api_client, database[1])
    add_listing(database[1], location="Home based - Worldwide")
    assert pipeline(api_client, profile_id)["queues"]["auto_apply"] == []


def test_expired_stale_duplicate_unsafe_and_tracked_listings_are_excluded(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    gone = add_listing(factory, status="missing_from_source")
    past_deadline = add_listing(factory, deadline=date.today() - timedelta(days=1))
    stale = add_listing(factory, verified=NOW - timedelta(days=30))
    unsafe = add_listing(factory, application_url="http://example.com/apply")
    shared = uuid4().hex * 2
    preferred = add_listing(factory, dedupe=shared, first_seen=NOW - timedelta(days=2))
    copy = add_listing(factory, dedupe=shared, category="aggregator", source_key="canonical")
    result = pipeline(api_client, profile_id)

    codes = {
        listing_id: [r["code"] for r in card(result, listing_id)["reasons"]]
        for listing_id in (gone, past_deadline, stale, unsafe, copy)
    }
    assert codes[gone] == ["no_longer_listed"] and codes[past_deadline] == ["deadline_passed"]
    assert (
        codes[stale] == ["stale_listing"]
        and codes[unsafe] == ["unsafe_application_link"]
        and codes[copy] == ["duplicate"]
    )
    assert card(result, preferred)["queue"] == "needs_action"

    prepared = api_client.post(f"{API}/{profile_id}/job-listings/{preferred}/prepare-application")
    assert prepared.status_code == 200, prepared.text
    tracked = card(pipeline(api_client, profile_id), preferred)
    assert tracked["queue"] == "not_eligible" and tracked["reasons"][0]["code"] == "already_tracked"
    assert tracked["application"]["status"] == "preparing"


def test_work_arrangement_and_authorization_use_only_confirmed_facts(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    onsite = add_listing(factory, workplace="onsite")
    needs_auth = add_listing(
        factory,
        location="Home based - Worldwide",
        description=SUPPORT_TEXT + "You must be authorized to work in the United Kingdom.",
    )
    before = pipeline(api_client, profile_id)
    assert card(before, onsite)["queue"] == "needs_action"  # no confirmed preference yet: nothing is assumed
    assert card(before, needs_auth)["eligibility"]["state"] == "needs_candidate_input"
    assert "United Kingdom" in card(before, needs_auth)["next_step"]

    confirmed = api_client.put(
        f"{API}/{profile_id}/eligibility-details",
        json={
            "confirmed": True,
            "country_of_residence": "KE",
            "accepted_work_arrangements": ["remote"],
            "work_authorizations": [{"country_code": "GB", "status": "not_authorized"}],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    after = pipeline(api_client, profile_id)
    assert card(after, onsite)["reasons"][0]["code"] == "arrangement_not_accepted"
    assert card(after, needs_auth)["queue"] == "not_eligible"
    assert card(after, needs_auth)["eligibility"]["rule"] == "work_authorization_not_held"


def test_freshness_uses_the_source_posting_date_not_discovery_date(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    old_but_new_to_us = add_listing(factory, posted=NOW - timedelta(days=10), first_seen=NOW)
    undated = add_listing(factory, posted=None, first_seen=NOW)
    fresh = add_listing(factory, posted=NOW - timedelta(hours=2))
    ids = {
        item["listing_id"]
        for items in pipeline(api_client, profile_id, posted_within_hours=24)["queues"].values()
        for item in items
    }
    assert fresh in ids and old_but_new_to_us not in ids and undated not in ids


def test_strict_kenya_listing_filter_never_returns_unverified_or_ineligible(api_client: TestClient, database) -> None:
    factory = database[1]
    eligible = add_listing(factory, location="Nairobi, Kenya")
    add_listing(factory, location="Remote")
    add_listing(factory, location="Home based - EMEA")
    add_listing(factory, location="Remote, United States")
    qualified = api_client.get("/api/v1/job-listings", params={"kenya": "eligible"}).json()
    assert [item["id"] for item in qualified["items"]] == [eligible] and qualified["total"] == 1
    assert qualified["items"][0]["kenya_eligibility"]["evidence"][0]["quotation"] == "Nairobi, Kenya"
    review = api_client.get("/api/v1/job-listings", params={"kenya": "unverified"}).json()
    assert review["total"] == 2 and all(item["kenya_eligibility"]["state"] == "unverified" for item in review["items"])
    everything = api_client.get("/api/v1/job-listings").json()
    assert everything["total"] == 4
    assert {item["kenya_eligibility"]["state"] for item in everything["items"]} == {
        "eligible",
        "unverified",
        "ineligible",
    }


def test_prepare_application_builds_the_pack_and_never_submits(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    listing_id = add_listing(factory, deadline=date.today() + timedelta(days=10))
    response = api_client.post(f"{API}/{profile_id}/job-listings/{listing_id}/prepare-application")
    assert response.status_code == 200, response.text
    pack = response.json()
    assert pack["submitted"] is False and pack["application_status"] == "preparing"
    assert pack["cv_draft_status"] == "generated" and pack["eligibility"]["state"] == "eligible"
    assert [s["status"] for s in pack["steps"]][-1] == "handed_to_you"
    assert pack["handoff"]["application_url"].startswith("https://") and pack["handoff"]["candidate_steps"]
    letter = pack["cover_letter"]
    assert "IT Support Specialist" in letter["text"] and "Troubleshot Windows laptops for 300 staff" in letter["text"]
    assert {source["source_type"] for source in letter["sources"]} <= {"profile_field", "work_experience"}

    with factory() as session:
        application = session.get(JobApplication, UUID(pack["application_id"]))
        assert application.status == "preparing" and application.applied_on is None
        assert application.deadline_on == date.today() + timedelta(days=10)
        event = session.scalar(select(JobApplicationEvent).where(JobApplicationEvent.application_id == application.id))
        assert "Prepared by JobPilot" in event.note and "Submission is manual" in event.note

    again = api_client.post(f"{API}/{profile_id}/job-listings/{listing_id}/prepare-application").json()
    assert again["application_id"] == pack["application_id"] and again["cv_draft_id"] == pack["cv_draft_id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JobApplication)) == 1
        assert session.scalar(select(func.count()).select_from(TailoredCvDraft)) == 1


def test_prepare_refuses_listings_that_are_not_established_as_eligible(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    for location, expected in (("Remote", "unverified"), ("Remote, United States", "ineligible")):
        listing_id = add_listing(factory, location=location)
        refused = api_client.post(f"{API}/{profile_id}/job-listings/{listing_id}/prepare-application")
        assert refused.status_code == 409 and expected in refused.json()["detail"]["message"]
    expired = add_listing(factory, status="missing_from_source")
    assert api_client.post(f"{API}/{profile_id}/job-listings/{expired}/prepare-application").status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(JobApplication)) == 0


def test_unconfirmed_evidence_never_reaches_the_cv_or_cover_letter(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    document = api_client.post(
        f"{API}/{profile_id}/documents", files={"file": ("cv.txt", b"Savanna Telecom notes", "text/plain")}
    ).json()
    with factory() as session:
        session.add(
            CandidateEvidence(
                candidate_profile_id=UUID(profile_id),
                source_document_id=UUID(document["id"]),
                category="achievement",
                description="Rebuilt the Savanna Telecom Active Directory forest for 9000 users",
                source_excerpt="Savanna Telecom notes",
                source_section="Savanna Telecom",
                confirmation_status="unreviewed",
            )
        )
        session.commit()
    listing_id = add_listing(factory)
    pack = api_client.post(f"{API}/{profile_id}/job-listings/{listing_id}/prepare-application").json()
    assert "9000" not in pack["cover_letter"]["text"]
    draft = api_client.get(f"{API}/{profile_id}/cv-drafts/{pack['cv_draft_id']}").json()
    assert "9000" not in (draft["generated_content"] or "")


def test_pipeline_and_preparation_are_owner_scoped_and_csrf_protected(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    listing_id = add_listing(factory)
    with factory() as session:
        other = User(email="someone-else@example.com", password_hash="$argon2id$test-fixture")
        session.add(other)
        session.flush()
        foreign = CandidateProfile(name="Other", user_id=other.id)
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id
    assert api_client.get(f"{API}/{foreign_id}/job-pipeline").status_code == 404
    assert api_client.post(f"{API}/{foreign_id}/job-listings/{listing_id}/prepare-application").status_code == 404
    token = api_client.headers.pop("X-CSRF-Token")
    try:
        assert api_client.post(f"{API}/{profile_id}/job-listings/{listing_id}/prepare-application").status_code == 403
    finally:
        api_client.headers["X-CSRF-Token"] = token
    assert api_client.post(f"{API}/{profile_id}/job-listings/{uuid4()}/prepare-application").status_code == 404


def test_fit_never_overrides_an_eligibility_failure(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = candidate(api_client, factory)
    us_only = add_listing(factory, location="Remote, United States")
    result = pipeline(api_client, profile_id)
    excluded = card(result, us_only)
    assert excluded["queue"] == "not_eligible" and excluded["fit"] is None
    job = api_client.post(f"{API}/{profile_id}/job-descriptions/from-listing/{us_only}").json()
    report = api_client.get(f"{API}/{profile_id}/job-descriptions/{job['id']}/ats-analysis").json()
    assert report["eligibility_overrides_score"] is True and report["verdict"] == "excluded_by_employer"
