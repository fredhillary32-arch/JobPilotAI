from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    CandidateDocument,
    CandidateEducation,
    CandidateEvidence,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
    DocumentExtraction,
)
from app.schemas.cv_generation import CVStructuredContent
from app.services.cv_validation import EXPECTED_SECTION_ORDER, validate_cv_content

JOB_DESCRIPTION = (
    "We are hiring a platform engineer. Required skills: AWS, Terraform. "
    "Build reliable services and improve deployment workflows."
)
ACHIEVEMENTS = [
    "Built a Python service to process customer requests more reliably.",
    "Automated AWS deployment checks to prevent configuration errors.",
    "Reduced release delays by testing deployment workflows before launch.",
    "Designed monitoring dashboards that helped teams resolve service incidents.",
    "Improved database query performance by analyzing slow request patterns.",
]


def create_profile(
    client: TestClient,
    *,
    name: str = "Taylor Candidate",
    headline: str = "Platform Engineer",
    summary: str = "Builds reliable services and improves deployment workflows.",
) -> str:
    response = client.post(
        "/api/v1/candidate-profiles",
        json={
            "name": name,
            "professional_headline": headline,
            "summary": summary,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add_profile_material(
    factory: sessionmaker[Session],
    profile_id: str,
    *,
    achievements: list[str] | None = None,
    description: str | None = None,
    skills: tuple[str, ...] = ("AWS", "Python", "Communication"),
    headline: str = "Platform Engineer",
) -> UUID:
    with factory() as session:
        profile = session.get(CandidateProfile, UUID(profile_id))
        assert profile is not None
        profile.professional_headline = headline
        work = CandidateWorkExperience(
            candidate_profile_id=profile.id,
            employer="Northstar Systems",
            job_title="Platform Engineer",
            start_date=date(2022, 1, 1),
            current_role=True,
            description=description,
            achievements=achievements or ACHIEVEMENTS,
        )
        session.add(work)
        session.add_all(
            CandidateSkill(candidate_profile_id=profile.id, name=skill)
            for skill in skills
        )
        session.add(
            CandidateEducation(
                candidate_profile_id=profile.id,
                institution="Example Institute",
                qualification="Bachelor of Science",
                field_of_study="Computer Science",
                start_date=date(2017, 1, 1),
                end_date=date(2021, 1, 1),
            )
        )
        session.commit()
        return work.id


def create_job(
    client: TestClient,
    profile_id: str,
    *,
    description: str = JOB_DESCRIPTION,
    job_title: str = "Platform Engineer",
) -> dict:
    response = client.post(
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions",
        json={
            "job_title": job_title,
            "company": "Example Employer",
            "description": description,
            "source_url": "https://jobs.example.test/platform-engineer",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_source_evidence(
    factory: sessionmaker[Session],
    profile_id: str,
    *,
    description: str,
    status: str,
) -> UUID:
    with factory() as session:
        document = CandidateDocument(
            candidate_profile_id=UUID(profile_id),
            document_kind="source_cv",
            provenance="candidate_uploaded",
            original_filename="candidate.txt",
            media_type="text/plain",
            storage_key=f"{uuid4().hex}.txt",
            size_bytes=4,
            sha256=sha256(b"cv\n!").hexdigest(),
        )
        session.add(document)
        session.flush()
        # Evidence is only usable while its excerpt is in the current extraction.
        session.add(DocumentExtraction(
            source_document_id=document.id, status="succeeded", extracted_text="cv\n!",
            character_count=4, extractor_version="stdlib/stdlib",
        ))
        evidence = CandidateEvidence(
            candidate_profile_id=UUID(profile_id),
            source_document_id=document.id,
            category="achievement",
            description=description,
            source_excerpt="cv",
            source_start=0,
            source_end=2,
            source_section="Northstar Systems Platform Engineer",
            confirmation_status=status,
        )
        session.add(evidence)
        session.commit()
        return evidence.id


def test_generated_draft_has_ordered_sections_five_supported_bullets_and_traceability(
    api_client: TestClient,
    database,
) -> None:
    profile_id = create_profile(api_client)
    work_id = add_profile_material(database[1], profile_id)
    job = create_job(api_client, profile_id)
    generated = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )

    assert generated.status_code == 201, generated.text
    draft = generated.json()
    assert draft["status"] == "generated"
    structured = draft["structured_content"]
    assert [section["heading"] for section in structured["sections"]] == [
        "Professional Summary",
        "Tools and Platforms",
        "Core Skills",
        "Professional Experience",
        "Education",
    ]
    role = structured["sections"][3]["roles"][0]
    assert role["work_experience_id"] == str(work_id)
    assert len(role["bullets"]) == 5
    assert all(bullet["source_references"] for bullet in role["bullets"])
    assert all(
        reference["source_id"]
        for reference in draft["source_references"]
    )
    for section in structured["sections"]:
        assert all(claim["source_references"] for claim in section["claims"])
        for item in section["roles"]:
            assert item["source_references"]
            assert all(bullet["source_references"] for bullet in item["bullets"])
    assert "Terraform" not in draft["generated_content"]
    assert "not supported by candidate-provided or confirmed information: Terraform" in (
        draft["validation_results"]["gaps"][0]
    )
    assert draft["validation_results"]["is_valid"] is True
    assert structured["sections"][1]["claims"][0]["text"] == "AWS"
    assert all(
        reference["source_type"] != "candidate_evidence"
        for reference in draft["source_references"]
    )


def test_unreviewed_and_rejected_evidence_cannot_be_used(
    api_client: TestClient,
    database,
) -> None:
    profile_id = create_profile(api_client)
    add_profile_material(
        database[1],
        profile_id,
        achievements=ACHIEVEMENTS[:3],
        description=None,
    )
    unreviewed = "Resolved production incidents by tracing service failures."
    rejected = "Improved platform performance by rewriting all services."
    unreviewed_id = create_source_evidence(
        database[1], profile_id, description=unreviewed, status="unreviewed"
    )
    rejected_id = create_source_evidence(
        database[1], profile_id, description=rejected, status="rejected"
    )
    job = create_job(api_client, profile_id)

    response = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )
    # Three supported bullets: saved as incomplete; the unreviewed and rejected evidence is never used.
    assert response.status_code == 201
    detail = response.json()
    assert detail["status"] == "needs_review"
    assert any("3 supported bullets" in issue["message"] for issue in detail["validation_results"]["issues"])
    assert str(unreviewed_id) not in str(detail)
    assert str(rejected_id) not in str(detail)
    assert unreviewed not in detail["generated_content"] and rejected not in detail["generated_content"]
    with database[1]() as session:
        assert session.get(CandidateEvidence, unreviewed_id).confirmation_status == "unreviewed"
        assert session.get(CandidateEvidence, rejected_id).confirmation_status == "rejected"


def test_confirmed_evidence_can_fill_role_and_is_referenced(
    api_client: TestClient,
    database,
) -> None:
    profile_id = create_profile(api_client)
    add_profile_material(
        database[1],
        profile_id,
        achievements=ACHIEVEMENTS[:4],
        description=None,
    )
    evidence_id = create_source_evidence(
        database[1],
        profile_id,
        description="Resolved production incidents by tracing service failures.",
        status="candidate_confirmed",
    )
    job = create_job(api_client, profile_id)
    response = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )

    assert response.status_code == 201
    draft = response.json()
    role = draft["structured_content"]["sections"][3]["roles"][0]
    assert len(role["bullets"]) == 5
    final_bullet = role["bullets"][-1]
    assert "Resolved production incidents" in final_bullet["text"]
    assert final_bullet["source_references"][0]["source_type"] == "candidate_evidence"
    assert final_bullet["source_references"][0]["source_id"] == str(evidence_id)
    assert final_bullet["source_references"][0]["source_document_id"]
    assert final_bullet["source_references"][0]["source_excerpt"] == "cv"
    assert final_bullet["source_references"][0]["evidence_confirmation_status"] == (
        "candidate_confirmed"
    )


@pytest.mark.parametrize(
    ("headline", "achievement", "expected_error"),
    [
        ("Platform Engineer", "Built services & improved operational uptime for teams.", "ampersand"),
        ("Engineer — Platform", "Built services and improved operational uptime for teams.", "em dash"),
    ],
)
def test_prohibited_punctuation_fails_and_persists_validation(
    api_client: TestClient,
    database,
    headline: str,
    achievement: str,
    expected_error: str,
) -> None:
    profile_id = create_profile(api_client, headline=headline)
    add_profile_material(
        database[1],
        profile_id,
        headline=headline,
        achievements=[achievement, *ACHIEVEMENTS[1:]],
    )
    job = create_job(api_client, profile_id)

    response = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )
    assert response.status_code == 422
    assert expected_error in str(response.json()["detail"]["validation_results"])
    drafts = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/cv-drafts"
    ).json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "failed"
    assert drafts[0]["validation_results"]["is_valid"] is False


def test_insufficient_evidence_returns_actionable_role_error_and_no_content(
    api_client: TestClient,
    database,
) -> None:
    profile_id = create_profile(api_client)
    add_profile_material(
        database[1],
        profile_id,
        achievements=ACHIEVEMENTS[:2],
        description=None,
    )
    job = create_job(api_client, profile_id)
    response = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )

    # Missing evidence is an actionable issue on a saved, incomplete draft, not a dead end.
    assert response.status_code == 201
    draft = response.json()
    assert draft["status"] == "needs_review" and draft["validation_results"]["is_valid"] is True
    (issue,) = draft["validation_results"]["issues"]
    assert issue["group"] == "experience_evidence" and issue["role"] == "Platform Engineer at Northstar Systems"
    assert "2 supported bullets" in issue["message"] and "will not invent" in issue["action"]
    role = next(section for section in draft["structured_content"]["sections"] if section["heading"] == "Professional Experience")["roles"][0]
    # Only the two supported bullets: nothing was added to reach five.
    assert len(role["bullets"]) == 2


def test_multiple_drafts_preserve_profile_and_original_uploaded_document(
    api_client: TestClient,
    database,
) -> None:
    profile_id = create_profile(api_client)
    add_profile_material(database[1], profile_id)
    original = b"Original CV bytes remain unchanged."
    uploaded = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/documents",
        files={"file": ("source.txt", original, "text/plain")},
        data={"document_kind": "source_cv"},
    )
    assert uploaded.status_code == 201
    job = create_job(api_client, profile_id)
    url = (
        f"/api/v1/candidate-profiles/{profile_id}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )
    first = api_client.post(url)
    second = api_client.post(url)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents/"
        f"{uploaded.json()['id']}/download"
    ).content == original
    profile = api_client.get(f"/api/v1/candidate-profiles/{profile_id}").json()
    assert profile["name"] == "Taylor Candidate"
    assert len(api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/cv-drafts"
    ).json()) == 2


def test_job_description_and_draft_resources_are_profile_scoped(
    api_client: TestClient,
) -> None:
    first_profile = create_profile(api_client)
    second_profile = create_profile(api_client, name="Another Candidate")
    job = create_job(api_client, first_profile)
    other_profile_job = api_client.post(
        f"/api/v1/candidate-profiles/{second_profile}/job-descriptions/"
        f"{job['id']}/cv-drafts"
    )
    missing_job = api_client.get(
        f"/api/v1/candidate-profiles/{second_profile}/job-descriptions/{job['id']}"
    )
    missing_draft = api_client.get(
        f"/api/v1/candidate-profiles/{second_profile}/cv-drafts/{uuid4()}"
    )
    missing_profile = api_client.post(
        f"/api/v1/candidate-profiles/{uuid4()}/job-descriptions",
        json={"job_title": "Engineer", "description": "Build reliable systems."},
    )
    invalid_payload = api_client.post(
        f"/api/v1/candidate-profiles/{first_profile}/job-descriptions",
        json={"job_title": "", "description": ""},
    )
    invalid_url = api_client.post(
        f"/api/v1/candidate-profiles/{first_profile}/job-descriptions",
        json={
            "job_title": "Engineer",
            "description": "Build reliable systems.",
            "source_url": "not a URL",
        },
    )

    assert other_profile_job.status_code == 404
    assert missing_job.status_code == 404
    assert missing_draft.status_code == 404
    assert missing_profile.status_code == 404
    assert invalid_payload.status_code == 422
    assert invalid_url.status_code == 422


def test_validator_enforces_section_order_and_claim_sources() -> None:
    content = CVStructuredContent(
        candidate_name="Candidate",
        professional_heading="Engineer",
        header_source_references=[
            {
                "source_type": "profile_field",
                "source_id": "profile",
                "source_field": "name",
                "claim_text": "Candidate",
            }
        ],
        sections=[
            {"heading": heading, "claims": [], "roles": []}
            for heading in reversed(EXPECTED_SECTION_ORDER)
        ],
    )
    errors = validate_cv_content(content, "Candidate\nEngineer")
    assert any("section order" in error for error in errors)
