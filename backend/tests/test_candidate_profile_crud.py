from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateSkill,
    CandidateWorkExperience,
)


def create_profile(client: TestClient, name: str) -> str:
    response = client.post("/api/v1/candidate-profiles", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    ("path", "payload", "updated", "model", "updated_field"),
    [
        (
            "experiences",
            {
                "employer": "Northstar Systems",
                "job_title": "Platform Engineer",
                "start_date": "2022-01-01",
                "current_role": True,
                "description": "Maintained deployment systems.",
                "achievements": ["Candidate-entered achievement."],
            },
            {"job_title": "Senior Platform Engineer"},
            CandidateWorkExperience,
            "job_title",
        ),
        (
            "education",
            {
                "institution": "Example Institute",
                "qualification": "Bachelor of Science",
                "field_of_study": "Computer Science",
                "start_date": "2017-01-01",
                "end_date": "2021-01-01",
            },
            {"qualification": "BSc Computer Science"},
            CandidateEducation,
            "qualification",
        ),
        (
            "skills",
            {"name": "Python", "proficiency_level": "advanced"},
            {"proficiency_level": "expert"},
            CandidateSkill,
            "proficiency_level",
        ),
        (
            "certifications",
            {
                "name": "Cloud Practitioner",
                "issuer": "Example Board",
                "issue_date": "2023-01-01",
                "expires_on": "2026-01-01",
            },
            {"issuer": "Candidate-confirmed Board"},
            CandidateCertification,
            "issuer",
        ),
    ],
)
def test_profile_record_crud_and_database_persistence(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
    path: str,
    payload: dict,
    updated: dict,
    model: type,
    updated_field: str,
) -> None:
    profile_id = create_profile(api_client, f"Candidate for {path}")
    collection_url = f"/api/v1/candidate-profiles/{profile_id}/{path}"

    created_response = api_client.post(collection_url, json=payload)
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    record_id = created["id"]
    assert created["candidate_profile_id"] == profile_id
    retrieved = api_client.get(f"{collection_url}/{record_id}")
    assert retrieved.status_code == 200
    assert retrieved.json() == created

    listed = api_client.get(collection_url)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [record_id]

    updated_response = api_client.patch(f"{collection_url}/{record_id}", json=updated)
    assert updated_response.status_code == 200, updated_response.text
    assert updated_response.json()[updated_field] == updated[updated_field]

    _, factory = database
    with factory() as session:
        persisted = session.get(model, UUID(record_id))
        assert persisted is not None
        assert getattr(persisted, updated_field) == updated[updated_field]
        assert persisted.candidate_profile_id == UUID(profile_id)

    deleted_response = api_client.delete(f"{collection_url}/{record_id}")
    assert deleted_response.status_code == 204
    assert api_client.get(collection_url).json() == []
    assert api_client.delete(f"{collection_url}/{record_id}").status_code == 404


@pytest.mark.parametrize(
    ("path", "payload", "invalid_patch"),
    [
        (
            "experiences",
            {"employer": "Example", "job_title": "Engineer", "start_date": "2023-01-01"},
            {"end_date": "2022-01-01"},
        ),
        (
            "education",
            {"institution": "Example", "qualification": "Degree", "start_date": "2023-01-01"},
            {"end_date": "2022-01-01"},
        ),
        (
            "skills",
            {"name": "Python"},
            {"name": "   "},
        ),
        (
            "certifications",
            {"name": "Certificate", "issuer": "Issuer", "issue_date": "2023-01-01"},
            {"expires_on": "2022-01-01"},
        ),
    ],
)
def test_profile_record_validation_rejects_invalid_create_and_update(
    api_client: TestClient,
    path: str,
    payload: dict,
    invalid_patch: dict,
) -> None:
    profile_id = create_profile(api_client, f"Invalid {path}")
    collection_url = f"/api/v1/candidate-profiles/{profile_id}/{path}"

    invalid_create = {**payload}
    if path in {"experiences", "education"}:
        invalid_create["end_date"] = "2022-01-01"
    elif path == "certifications":
        invalid_create["expires_on"] = "2022-01-01"
    else:
        invalid_create["proficiency_level"] = "master"
    assert api_client.post(collection_url, json=invalid_create).status_code == 422

    created = api_client.post(collection_url, json=payload)
    assert created.status_code == 201, created.text
    invalid_update = api_client.patch(
        f"{collection_url}/{created.json()['id']}",
        json=invalid_patch,
    )
    assert invalid_update.status_code == 422


@pytest.mark.parametrize(
    ("path", "payload", "patch", "date_field"),
    [
        (
            "experiences",
            {
                "employer": "Example",
                "job_title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": "2021-01-01",
            },
            {"start_date": "2022-01-01"},
            "start_date",
        ),
        (
            "education",
            {
                "institution": "Example",
                "qualification": "Degree",
                "start_date": "2020-01-01",
                "end_date": "2021-01-01",
            },
            {"start_date": "2022-01-01"},
            "start_date",
        ),
        (
            "certifications",
            {
                "name": "Certificate",
                "issuer": "Issuer",
                "issue_date": "2020-01-01",
                "expires_on": "2021-01-01",
            },
            {"issue_date": "2022-01-01"},
            "issue_date",
        ),
    ],
)
def test_record_patch_validates_dates_against_existing_values(
    api_client: TestClient,
    path: str,
    payload: dict,
    patch: dict,
    date_field: str,
) -> None:
    profile_id = create_profile(api_client, f"Merged dates for {path}")
    collection_url = f"/api/v1/candidate-profiles/{profile_id}/{path}"
    created = api_client.post(collection_url, json=payload)
    assert created.status_code == 201, created.text
    record_url = f"{collection_url}/{created.json()['id']}"

    invalid_update = api_client.patch(record_url, json=patch)

    assert invalid_update.status_code == 422
    assert api_client.get(record_url).json()[date_field] == payload[date_field]


def test_work_experience_patch_rejects_current_role_with_existing_end_date(
    api_client: TestClient,
) -> None:
    profile_id = create_profile(api_client, "Current role date validation")
    collection_url = f"/api/v1/candidate-profiles/{profile_id}/experiences"
    created = api_client.post(
        collection_url,
        json={
            "employer": "Example",
            "job_title": "Engineer",
            "start_date": "2020-01-01",
            "end_date": "2021-01-01",
        },
    )
    assert created.status_code == 201, created.text
    record_url = f"{collection_url}/{created.json()['id']}"

    invalid_update = api_client.patch(record_url, json={"current_role": True})

    assert invalid_update.status_code == 422
    assert api_client.get(record_url).json()["current_role"] is False
    assert api_client.get(record_url).json()["end_date"] == "2021-01-01"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("experiences", {"employer": "Example", "job_title": "Engineer", "start_date": "2022-01-01"}),
        ("education", {"institution": "Example", "qualification": "Degree", "start_date": "2022-01-01"}),
        ("skills", {"name": "Python"}),
        ("certifications", {"name": "Certificate", "issuer": "Issuer", "issue_date": "2022-01-01"}),
    ],
)
def test_record_ids_are_scoped_to_profile_and_missing_profiles_are_rejected(
    api_client: TestClient,
    path: str,
    payload: dict,
) -> None:
    owner_id = create_profile(api_client, f"Owner of {path}")
    other_id = create_profile(api_client, f"Other profile for {path}")
    owner_url = f"/api/v1/candidate-profiles/{owner_id}/{path}"
    other_url = f"/api/v1/candidate-profiles/{other_id}/{path}"
    created = api_client.post(owner_url, json=payload)
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]

    assert api_client.patch(f"{other_url}/{record_id}", json={next(iter(payload)): "Changed"}).status_code == 404
    assert api_client.get(f"{other_url}/{record_id}").status_code == 404
    assert api_client.delete(f"{other_url}/{record_id}").status_code == 404
    assert api_client.get(owner_url).json()[0]["id"] == record_id

    missing_profile_url = f"/api/v1/candidate-profiles/{uuid4()}/{path}"
    assert api_client.get(missing_profile_url).status_code == 404
    assert api_client.post(missing_profile_url, json=payload).status_code == 404


def test_skill_duplicate_conflict_is_recoverable(api_client: TestClient) -> None:
    profile_id = create_profile(api_client, "Skill conflict candidate")
    url = f"/api/v1/candidate-profiles/{profile_id}/skills"
    original = api_client.post(url, json={"name": "Python"})
    second = api_client.post(url, json={"name": "Go"})
    assert original.status_code == second.status_code == 201
    duplicate_create = api_client.post(url, json={"name": " python "})
    duplicate_update = api_client.patch(
        f"{url}/{second.json()['id']}",
        json={"name": "PYTHON"},
    )
    for response in (duplicate_create, duplicate_update):
        assert response.status_code == 409
        assert response.json()["detail"] == "This skill already exists for the candidate profile"
    assert {item["name"] for item in api_client.get(url).json()} == {"Python", "Go"}


def test_patch_rejects_empty_body(api_client: TestClient) -> None:
    profile_id = create_profile(api_client, "Empty patch candidate")
    response = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/skills",
        json={"name": "Python"},
    )
    assert response.status_code == 201
    patched = api_client.patch(
        f"/api/v1/candidate-profiles/{profile_id}/skills/{response.json()['id']}",
        json={},
    )
    assert patched.status_code == 422
