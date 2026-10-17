from datetime import date
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)


def test_create_get_update_and_list_associated_records(
    api_client: TestClient,
    database: tuple[Engine, sessionmaker[Session]],
) -> None:
    response = api_client.post(
        "/api/v1/candidate-profiles",
        json={
            "name": "Ada Candidate",
            "contact_email": "ada@example.com",
            "contact_phone": "+254700000000",
            "professional_headline": "Backend Engineer",
            "summary": "Builds reliable APIs.",
            "location": "Nairobi, Kenya",
            "remote_work_preference": "hybrid",
            "target_job_categories": ["Engineering", "Platform"],
        },
    )

    assert response.status_code == 201
    created = response.json()
    profile_id = created["id"]
    assert created["name"] == "Ada Candidate"
    assert created["contact_email"] == "ada@example.com"
    assert "password" not in created

    profile_response = api_client.get(f"/api/v1/candidate-profiles/{profile_id}")
    assert profile_response.status_code == 200
    assert profile_response.json()["location"] == "Nairobi, Kenya"

    update_response = api_client.patch(
        f"/api/v1/candidate-profiles/{profile_id}",
        json={"professional_headline": "Senior Backend Engineer", "location": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["professional_headline"] == "Senior Backend Engineer"
    assert update_response.json()["location"] is None

    _, factory = database
    with factory.begin() as session:
        profile = session.get(CandidateProfile, UUID(profile_id))
        assert profile is not None
        profile.work_experiences.append(
            CandidateWorkExperience(
                employer="Example Ltd",
                job_title="Engineer",
                start_date=date(2022, 1, 1),
                current_role=True,
                achievements=["Improved API reliability"],
            )
        )
        profile.education_records.append(
            CandidateEducation(
                institution="Example University",
                qualification="BSc",
                field_of_study="Computer Science",
                start_date=date(2017, 1, 1),
                end_date=date(2021, 1, 1),
            )
        )
        profile.skills.append(CandidateSkill(name="Python", proficiency_level="advanced"))
        profile.certifications.append(
            CandidateCertification(
                name="Cloud Practitioner",
                issuer="Example Board",
                issue_date=date(2023, 1, 1),
            )
        )

    endpoint_expectations = (
        ("experiences", "employer", "Example Ltd"),
        ("education", "institution", "Example University"),
        ("skills", "name", "Python"),
        ("certifications", "name", "Cloud Practitioner"),
    )
    for path, field, value in endpoint_expectations:
        listed = api_client.get(f"/api/v1/candidate-profiles/{profile_id}/{path}")
        assert listed.status_code == 200
        assert listed.json()[0][field] == value


def test_create_rejects_invalid_profile_input(api_client: TestClient) -> None:
    empty_name = api_client.post(
        "/api/v1/candidate-profiles",
        json={"name": "  "},
    )
    invalid_email = api_client.post(
        "/api/v1/candidate-profiles",
        json={"name": "Candidate", "contact_email": "not-an-email"},
    )
    invalid_preference = api_client.post(
        "/api/v1/candidate-profiles",
        json={"name": "Candidate", "remote_work_preference": "anywhere"},
    )

    assert empty_name.status_code == 422
    assert invalid_email.status_code == 422
    assert invalid_preference.status_code == 422


def test_update_rejects_empty_patch_and_null_required_fields(
    api_client: TestClient,
) -> None:
    created = api_client.post(
        "/api/v1/candidate-profiles",
        json={"name": "Candidate"},
    )
    profile_id = created.json()["id"]

    empty_patch = api_client.patch(f"/api/v1/candidate-profiles/{profile_id}", json={})
    null_name = api_client.patch(
        f"/api/v1/candidate-profiles/{profile_id}",
        json={"name": None},
    )
    null_categories = api_client.patch(
        f"/api/v1/candidate-profiles/{profile_id}",
        json={"target_job_categories": None},
    )

    assert empty_patch.status_code == 422
    assert null_name.status_code == 422
    assert null_categories.status_code == 422


def test_profile_and_associated_lists_return_not_found_for_missing_profile(
    api_client: TestClient,
) -> None:
    profile_id = uuid4()

    assert api_client.get(f"/api/v1/candidate-profiles/{profile_id}").status_code == 404
    assert (
        api_client.patch(
            f"/api/v1/candidate-profiles/{profile_id}",
            json={"name": "Updated"},
        ).status_code
        == 404
    )
    for section in ("experiences", "education", "skills", "certifications"):
        response = api_client.get(f"/api/v1/candidate-profiles/{profile_id}/{section}")
        assert response.status_code == 404
