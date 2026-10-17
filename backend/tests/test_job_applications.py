from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CandidateProfile, JobApplication, TailoredCvDraft
from app.models.job_application import ALLOWED_TRANSITIONS, APPLICATION_STATUSES

API = "/api/v1/candidate-profiles"
TODAY = date.today()


def _profile(client: TestClient, name: str = "Application Owner") -> str:
    response = client.post(API, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def _job(client: TestClient, profile_id: str, title: str = "IT Support Specialist") -> str:
    response = client.post(
        f"{API}/{profile_id}/job-descriptions",
        json={"job_title": title, "company": "Synthetic Co", "description": "Support users."},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _track(client: TestClient, profile_id: str, job_id: str, **extra):
    return client.post(
        f"{API}/{profile_id}/applications",
        json={"job_description_id": job_id, **extra},
    )


def _move(client: TestClient, profile_id: str, application_id: str, status: str, **extra):
    return client.post(
        f"{API}/{profile_id}/applications/{application_id}/status",
        json={"status": status, **extra},
    )


def _draft(factory: sessionmaker[Session], profile_id: str, job_id: str, *, generated: bool) -> UUID:
    with factory.begin() as session:
        draft = TailoredCvDraft(
            candidate_profile_id=UUID(profile_id),
            job_description_id=UUID(job_id),
            status="generated" if generated else "failed",
            generated_content="Synthetic CV" if generated else None,
            structured_content={} if generated else None,
            validation_results={"is_valid": generated, "errors": [], "gaps": [], "warnings": []},
            source_references=[],
        )
        session.add(draft)
        session.flush()
        return draft.id


def _count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(JobApplication))


def test_transition_map_covers_every_status_and_closed_is_final() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(APPLICATION_STATUSES)
    for targets in ALLOWED_TRANSITIONS.values():
        assert targets <= set(APPLICATION_STATUSES)
    assert ALLOWED_TRANSITIONS["closed"] == frozenset()


def test_tracking_a_saved_job_records_the_first_status_event(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    job_id = _job(api_client, profile_id)

    response = _track(
        api_client, profile_id, job_id, deadline_on=str(TODAY + timedelta(days=5)), notes="Referral from a friend."
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "saved"
    assert body["applied_on"] is None
    assert body["deadline_on"] == str(TODAY + timedelta(days=5))
    assert [(event["from_status"], event["to_status"]) for event in body["events"]] == [(None, "saved")]
    assert body["allowed_next_statuses"] == ["eligibility_review", "preparing", "withdrawn", "closed"]
    listed = api_client.get(f"{API}/{profile_id}/applications").json()
    assert [item["id"] for item in listed] == [body["id"]]


def test_full_lifecycle_through_offer_keeps_ordered_history(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    application_id = _track(api_client, profile_id, _job(api_client, profile_id)).json()["id"]

    for step in ["eligibility_review", "preparing", "ready_for_review"]:
        assert _move(api_client, profile_id, application_id, step).status_code == 200
    applied = _move(
        api_client, profile_id, application_id, "applied", applied_on=str(TODAY), note="Submitted on the employer site."
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied_on"] == str(TODAY)
    for step in ["interviewing", "offer", "closed"]:
        assert _move(api_client, profile_id, application_id, step).status_code == 200

    final = api_client.get(f"{API}/{profile_id}/applications/{application_id}").json()
    assert final["status"] == "closed"
    assert final["allowed_next_statuses"] == []
    assert [event["to_status"] for event in final["events"]] == [
        "saved",
        "eligibility_review",
        "preparing",
        "ready_for_review",
        "applied",
        "interviewing",
        "offer",
        "closed",
    ]
    assert final["events"][4]["note"] == "Submitted on the employer site."


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ([], "offer"),
        ([], "applied"),
        ([], "saved"),
        (["closed"], "saved"),
        (["withdrawn"], "applied"),
    ],
)
def test_disallowed_transitions_are_refused_without_changing_state(
    api_client: TestClient, path: list[str], target: str
) -> None:
    profile_id = _profile(api_client)
    application_id = _track(api_client, profile_id, _job(api_client, profile_id)).json()["id"]
    for step in path:
        assert _move(api_client, profile_id, application_id, step).status_code == 200
    before = api_client.get(f"{API}/{profile_id}/applications/{application_id}").json()

    response = _move(api_client, profile_id, application_id, target, applied_on=str(TODAY))

    assert response.status_code == 409
    after = api_client.get(f"{API}/{profile_id}/applications/{application_id}").json()
    assert after["status"] == before["status"]
    assert len(after["events"]) == len(before["events"])


def test_marking_applied_requires_a_recorded_non_future_date(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    application_id = _track(api_client, profile_id, _job(api_client, profile_id), status="ready_for_review").json()[
        "id"
    ]

    missing = _move(api_client, profile_id, application_id, "applied")
    future = _move(api_client, profile_id, application_id, "applied", applied_on=str(TODAY + timedelta(days=3)))

    assert (missing.status_code, future.status_code) == (422, 422)
    assert api_client.get(f"{API}/{profile_id}/applications/{application_id}").json()["status"] == "ready_for_review"


def test_application_date_is_only_accepted_when_marking_applied(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    job_id = _job(api_client, profile_id)

    early = _track(api_client, profile_id, job_id, applied_on=str(TODAY))
    application_id = _track(api_client, profile_id, job_id).json()["id"]
    misplaced = _move(api_client, profile_id, application_id, "preparing", applied_on=str(TODAY))

    assert (early.status_code, misplaced.status_code) == (422, 422)


def test_an_already_submitted_application_can_be_recorded_with_its_date(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    job_id = _job(api_client, profile_id)

    without_date = _track(api_client, profile_id, job_id, status="applied")
    with_date = _track(api_client, profile_id, job_id, status="applied", applied_on=str(TODAY - timedelta(days=2)))

    assert without_date.status_code == 422
    assert with_date.status_code == 201
    assert with_date.json()["allowed_next_statuses"] == ["interviewing", "offer", "rejected", "withdrawn", "closed"]


def test_later_stages_cannot_be_used_as_the_starting_status(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    response = _track(api_client, profile_id, _job(api_client, profile_id), status="offer", applied_on=str(TODAY))

    assert response.status_code == 422


def test_a_job_can_only_be_tracked_once_per_profile(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    job_id = _job(api_client, profile_id)

    first = _track(api_client, profile_id, job_id)
    second = _track(api_client, profile_id, job_id)

    assert (first.status_code, second.status_code) == (201, 409)
    assert _count(factory) == 1


def test_jobs_and_applications_from_another_profile_are_not_reachable(api_client: TestClient, database) -> None:
    _, factory = database
    first = _profile(api_client, "First profile")
    second = _profile(api_client, "Second profile")
    foreign_job = _job(api_client, first)
    application_id = _track(api_client, first, foreign_job).json()["id"]

    cross_job = _track(api_client, second, foreign_job)
    cross_read = api_client.get(f"{API}/{second}/applications/{application_id}")
    cross_move = _move(api_client, second, application_id, "preparing")

    assert (cross_job.status_code, cross_read.status_code, cross_move.status_code) == (404, 404, 404)
    assert api_client.get(f"{API}/{second}/applications").json() == []
    assert _count(factory) == 1


def test_profiles_the_user_does_not_own_are_not_found(api_client: TestClient, database) -> None:
    _, factory = database
    with factory.begin() as session:
        legacy = CandidateProfile(name="Unowned legacy profile")
        session.add(legacy)
        session.flush()
        legacy_id = legacy.id

    assert api_client.get(f"{API}/{legacy_id}/applications").status_code == 404
    assert _track(api_client, str(legacy_id), str(uuid4())).status_code == 404


def test_only_a_generated_draft_for_the_same_job_can_be_linked(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    job_id = _job(api_client, profile_id)
    other_job = _job(api_client, profile_id, "Help Desk Analyst")
    failed = _draft(factory, profile_id, job_id, generated=False)
    wrong_job = _draft(factory, profile_id, other_job, generated=True)
    usable = _draft(factory, profile_id, job_id, generated=True)

    assert _track(api_client, profile_id, job_id, cv_draft_id=str(failed)).status_code == 422
    assert _track(api_client, profile_id, job_id, cv_draft_id=str(wrong_job)).status_code == 422
    assert _track(api_client, profile_id, job_id, cv_draft_id=str(uuid4())).status_code == 422
    linked = _track(api_client, profile_id, job_id, cv_draft_id=str(usable))
    assert linked.status_code == 201
    assert linked.json()["cv_draft_id"] == str(usable)


def test_details_can_be_updated_and_cleared(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    job_id = _job(api_client, profile_id)
    application_id = _track(api_client, profile_id, job_id, notes="First note.").json()["id"]
    draft_id = _draft(factory, profile_id, job_id, generated=True)
    path = f"{API}/{profile_id}/applications/{application_id}"

    updated = api_client.patch(
        path,
        json={
            "contact_name": "Recruiter Name",
            "contact_email": "recruiter@example.com",
            "follow_up_on": str(TODAY + timedelta(days=7)),
            "cv_draft_id": str(draft_id),
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["notes"] == "First note."  # untouched fields are kept

    cleared = api_client.patch(path, json={"notes": None, "contact_email": None})
    assert cleared.status_code == 200
    assert (cleared.json()["notes"], cleared.json()["contact_email"]) == (None, None)
    assert cleared.json()["contact_name"] == "Recruiter Name"

    assert api_client.patch(path, json={"contact_email": "not-an-email"}).status_code == 422
    assert api_client.patch(path, json={"notes": "x" * 10_001}).status_code == 422


def test_status_filter_returns_matching_applications(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    saved_id = _track(api_client, profile_id, _job(api_client, profile_id, "Role A")).json()["id"]
    preparing_id = _track(api_client, profile_id, _job(api_client, profile_id, "Role B"), status="preparing").json()[
        "id"
    ]

    saved = api_client.get(f"{API}/{profile_id}/applications?status=saved").json()
    preparing = api_client.get(f"{API}/{profile_id}/applications?status=preparing").json()

    assert [item["id"] for item in saved] == [saved_id]
    assert [item["id"] for item in preparing] == [preparing_id]
    assert api_client.get(f"{API}/{profile_id}/applications?status=unknown").status_code == 422


def test_status_changes_require_csrf_verification(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    application_id = _track(api_client, profile_id, _job(api_client, profile_id)).json()["id"]

    response = api_client.post(
        f"{API}/{profile_id}/applications/{application_id}/status",
        json={"status": "preparing"},
        headers={"X-CSRF-Token": "not-the-session-token"},
    )

    assert response.status_code == 403
    assert api_client.get(f"{API}/{profile_id}/applications/{application_id}").json()["status"] == "saved"
