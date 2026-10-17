from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CandidateJobDescription, CandidateProfile, JobListing

API = "/api/v1/candidate-profiles"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
DESCRIPTION = (
    "Help customers resolve VoIP and network issues.\n"
    "- Troubleshoot SIP registration\n"
    "- Escalate ISP outages  with clear notes"
)


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


def _create_profile(client: TestClient) -> str:
    response = client.post(API, json={"name": "Listing Importer"})
    assert response.status_code == 201
    return response.json()["id"]


def _import(client: TestClient, profile_id: str, listing_id: UUID):
    return client.post(f"{API}/{profile_id}/job-descriptions/from-listing/{listing_id}")


def _job_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(CandidateJobDescription))


def test_import_copies_stored_listing_text_verbatim_and_links_the_source(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    profile_id = _create_profile(api_client)

    response = _import(api_client, profile_id, listing_id)

    assert response.status_code == 201, response.text
    body = response.json()
    # Interior double spaces and line structure survive: nothing is normalised.
    assert body["description"] == DESCRIPTION
    assert body["job_title"] == "Technical Support Specialist"
    assert body["company"] == "Synthetic Co"
    assert body["source_url"] == "https://job-boards.greenhouse.io/syntheticco/jobs/101"
    assert body["source_job_listing_id"] == str(listing_id)
    listed = api_client.get(f"{API}/{profile_id}/job-descriptions").json()
    assert [item["id"] for item in listed] == [body["id"]]


def test_importing_the_same_listing_again_returns_the_existing_job(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    profile_id = _create_profile(api_client)

    first = _import(api_client, profile_id, listing_id)
    second = _import(api_client, profile_id, listing_id)

    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json()["id"] == first.json()["id"]
    assert _job_count(factory) == 1


def test_each_profile_gets_its_own_copy_of_a_shared_listing(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    first_profile = _create_profile(api_client)
    second_profile = _create_profile(api_client)

    first = _import(api_client, first_profile, listing_id)
    second = _import(api_client, second_profile, listing_id)

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]


def test_unknown_listing_returns_404_and_creates_nothing(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _create_profile(api_client)

    response = _import(api_client, profile_id, uuid4())

    assert response.status_code == 404
    assert _job_count(factory) == 0


def test_listing_no_longer_at_source_cannot_be_imported(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory, source_status="missing_from_source")
    profile_id = _create_profile(api_client)

    response = _import(api_client, profile_id, listing_id)

    assert response.status_code == 409
    assert "no longer listed" in response.json()["detail"]
    assert _job_count(factory) == 0


def test_listing_without_source_description_cannot_be_imported(api_client: TestClient, database) -> None:
    _, factory = database
    empty = _store_listing(factory, description_text=None)
    blank = _store_listing(factory, description_text="   ")
    profile_id = _create_profile(api_client)

    responses = [_import(api_client, profile_id, empty), _import(api_client, profile_id, blank)]

    assert [response.status_code for response in responses] == [409, 409]
    assert _job_count(factory) == 0


def test_oversized_listing_is_rejected_rather_than_truncated(api_client: TestClient, database) -> None:
    _, factory = database
    long_title = _store_listing(factory, title="T" * 241)
    long_description = _store_listing(factory, description_text="d" * 50_001)
    at_limit = _store_listing(factory, title="T" * 240, description_text="d" * 50_000)
    profile_id = _create_profile(api_client)

    rejected = [_import(api_client, profile_id, long_title), _import(api_client, profile_id, long_description)]
    accepted = _import(api_client, profile_id, at_limit)

    assert [response.status_code for response in rejected] == [409, 409]
    assert "without shortening" in rejected[0].json()["detail"]
    assert accepted.status_code == 201
    assert len(accepted.json()["description"]) == 50_000
    assert _job_count(factory) == 1


def test_import_into_a_profile_the_user_does_not_own_is_not_found(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    with factory.begin() as session:
        legacy = CandidateProfile(name="Unowned legacy profile")
        session.add(legacy)
        session.flush()
        legacy_id = legacy.id

    response = _import(api_client, str(legacy_id), listing_id)

    assert response.status_code == 404
    assert _job_count(factory) == 0


def test_import_requires_csrf_verification(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    profile_id = _create_profile(api_client)

    response = api_client.post(
        f"{API}/{profile_id}/job-descriptions/from-listing/{listing_id}",
        headers={"X-CSRF-Token": "not-the-session-token"},
    )

    assert response.status_code == 403
    assert _job_count(factory) == 0


def test_imported_job_drives_cv_generation_and_keeps_its_source_link(api_client: TestClient, database) -> None:
    _, factory = database
    listing_id = _store_listing(factory)
    profile_id = _create_profile(api_client)
    job_id = _import(api_client, profile_id, listing_id).json()["id"]

    response = api_client.post(f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts")

    # A bare profile cannot fill a CV, so validation fails, but the attempt is
    # stored against the imported job, which still points at its listing.
    assert response.status_code in {201, 422}, response.text
    drafts = api_client.get(f"{API}/{profile_id}/cv-drafts").json()
    assert [draft["job_description_id"] for draft in drafts] == [job_id]
    job = api_client.get(f"{API}/{profile_id}/job-descriptions/{job_id}").json()
    assert job["source_job_listing_id"] == str(listing_id)
