from datetime import date, datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    CandidateDocument,
    CandidateEvidence,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
    DocumentExtraction,
    JobListing,
)

API = "/api/v1/candidate-profiles"
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
SKILLS_JOB = "Support engineer.\nRequired skills: Python, SQL, Zendesk, Linux, Salesforce."


def _profile(client: TestClient) -> str:
    response = client.post(API, json={"name": "Fit Candidate"})
    assert response.status_code == 201
    return response.json()["id"]


def _job(client: TestClient, profile_id: str, description: str) -> str:
    response = client.post(f"{API}/{profile_id}/job-descriptions", json={"job_title": "Support Engineer", "description": description})
    assert response.status_code == 201
    return response.json()["id"]


def _fit(client: TestClient, profile_id: str, job_id: str) -> dict:
    response = client.get(f"{API}/{profile_id}/job-descriptions/{job_id}/fit")
    assert response.status_code == 200, response.text
    return response.json()


def _confirm(client: TestClient, profile_id: str, **details) -> None:
    response = client.put(f"{API}/{profile_id}/eligibility-details", json={"confirmed": True, **details})
    assert response.status_code == 200, response.text


def _evidence(factory: sessionmaker[Session], profile_id: str, description: str, status: str) -> UUID:
    with factory.begin() as session:
        document = CandidateDocument(
            candidate_profile_id=UUID(profile_id), document_kind="source_cv", provenance="candidate_uploaded",
            original_filename="cv.txt", media_type="text/plain", storage_key=f"{uuid4().hex}.txt",
            size_bytes=4, sha256=sha256(b"cv").hexdigest(),
        )
        session.add(document)
        session.flush()
        session.add(DocumentExtraction(
            source_document_id=document.id, status="succeeded", extracted_text="cv",
            character_count=2, extractor_version="stdlib/stdlib",
        ))
        evidence = CandidateEvidence(
            candidate_profile_id=UUID(profile_id), source_document_id=document.id, category="technical_skill",
            description=description, source_excerpt="cv", source_start=0, source_end=2, confirmation_status=status,
        )
        session.add(evidence)
        session.flush()
        return evidence.id


def _material(factory: sessionmaker[Session], profile_id: str) -> tuple[UUID, UUID]:
    with factory.begin() as session:
        skill = CandidateSkill(candidate_profile_id=UUID(profile_id), name="Python")
        experience = CandidateWorkExperience(
            candidate_profile_id=UUID(profile_id), employer="Northstar", job_title="Support Analyst",
            start_date=date(2022, 1, 1), current_role=True, achievements=["Wrote SQL reports for the help desk."],
        )
        session.add_all([skill, experience])
        session.flush()
        return skill.id, experience.id


def _listing(factory: sessionmaker[Session], description: str) -> UUID:
    with factory.begin() as session:
        listing = JobListing(
            source_kind="greenhouse", source_key="syntheticco", source_listing_id=str(uuid4()),
            source_url="https://boards-api.greenhouse.io/v1/boards/syntheticco/jobs?content=true",
            application_url="https://job-boards.greenhouse.io/syntheticco/jobs/1", employer_name="Synthetic Co",
            title="Support Engineer", description_text=description, location_text="Remote",
            content_hash="0" * 64, dedupe_key="1" * 64, source_status="active",
            first_seen_at=NOW, last_seen_at=NOW, last_verified_at=NOW,
        )
        session.add(listing)
        session.flush()
        return listing.id


def _items(fit: dict, bucket: str) -> dict[str, dict]:
    return {item["requirement"]: item for item in fit[bucket]}


def test_requirements_are_split_into_matched_unverified_and_missing_with_provenance(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    skill_id, experience_id = _material(factory, profile_id)
    confirmed = _evidence(factory, profile_id, "Administered Linux servers.", "candidate_confirmed")
    _evidence(factory, profile_id, "Handled Zendesk tickets.", "unreviewed")
    _evidence(factory, profile_id, "Used Salesforce daily.", "rejected")
    job_id = _job(api_client, profile_id, SKILLS_JOB)

    fit = _fit(api_client, profile_id, job_id)

    matched = _items(fit, "matched")
    assert set(matched) == {"Python", "SQL", "Linux"}
    assert matched["Python"]["sources"][0] == {"source_type": "skill", "source_id": str(skill_id), "label": "Skill: Python"}
    assert matched["SQL"]["sources"][0]["source_id"] == str(experience_id)
    assert matched["Linux"]["sources"][0]["source_id"] == str(confirmed)
    assert _items(fit, "uncertain")["Zendesk"]["sources"][0]["label"].startswith("Unreviewed evidence")
    # Rejected evidence never supports a requirement.
    assert set(_items(fit, "missing")) == {"Salesforce"}
    assert fit["coverage"]["met"] == 3 and fit["coverage"]["total"] == 5
    assert "not eligibility" in fit["coverage"]["summary"]


def test_pasted_job_has_unknown_geographic_eligibility(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    _material(factory, profile_id)

    fit = _fit(api_client, profile_id, _job(api_client, profile_id, "Required skills: Python."))

    assert fit["coverage"]["met"] == fit["coverage"]["total"] == 1
    assert fit["verdict"] == "eligibility_unknown"
    assert fit["geographic_eligibility"]["currency"] == "not_assessed"
    assert "pasted" in fit["geographic_eligibility"]["reason"]


def _import_reviewed(client: TestClient, factory, profile_id: str, description: str, review: dict) -> tuple[str, str]:
    listing_id = _listing(factory, description)
    recorded = client.post(f"/api/v1/job-listings/{listing_id}/eligibility-assessments", json=review)
    assert recorded.status_code == 201, recorded.text
    job = client.post(f"{API}/{profile_id}/job-descriptions/from-listing/{listing_id}")
    assert job.status_code == 201
    return job.json()["id"], recorded.json()["assessment_id"]


def test_geographic_exclusion_is_not_outweighed_by_full_skills_coverage(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    _material(factory, profile_id)
    restriction = "Applicants must reside in the United Kingdom."
    job_id, assessment_id = _import_reviewed(api_client, factory, profile_id, f"Required skills: Python.\n{restriction}", {
        "outcome": "not_eligible", "explanation": "UK residents only.", "quotation": restriction,
        "evidence_field": "description", "statement_scope": "role", "role_applicability": "direct",
    })

    fit = _fit(api_client, profile_id, job_id)

    assert fit["coverage"]["met"] == fit["coverage"]["total"] == 1
    assert fit["verdict"] == "excluded_by_employer"
    assert "Skills coverage does not change this" in fit["headline"]
    geographic = fit["geographic_eligibility"]
    assert (geographic["status"], geographic["currency"]) == ("not_eligible", "current")
    assert geographic["assessment_id"] == assessment_id and geographic["quotation"] == restriction


def test_confirmed_eligibility_without_blockers(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    statement = "This role is open to candidates in any country."
    job_id, _ = _import_reviewed(api_client, factory, profile_id, f"Required skills: Python.\n{statement}", {
        "outcome": "eligible_confirmed", "explanation": "Any country.", "quotation": statement,
        "evidence_field": "description", "statement_scope": "role", "role_applicability": "direct",
    })

    fit = _fit(api_client, profile_id, job_id)

    assert fit["verdict"] == "no_blockers_found"
    assert fit["geographic_eligibility"]["status"] == "eligible_confirmed"
    assert fit["disqualifiers"] == []


def test_stale_geographic_evidence_is_reported_as_unknown(api_client: TestClient, database) -> None:
    _, factory = database
    profile_id = _profile(api_client)
    statement = "This role is open to candidates in any country."
    job_id, _ = _import_reviewed(api_client, factory, profile_id, statement, {
        "outcome": "eligible_confirmed", "explanation": "Any country.", "quotation": statement,
        "evidence_field": "description", "statement_scope": "role", "role_applicability": "direct",
    })
    with factory.begin() as session:
        listing = session.query(JobListing).one()
        listing.description_text = statement + " Updated."

    geographic = _fit(api_client, profile_id, job_id)["geographic_eligibility"]

    assert (geographic["status"], geographic["currency"]) == ("eligibility_unknown", "stale")


def test_work_authorization_disqualifier_only_with_confirmed_denial_and_no_sponsorship(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    requirement = "You must be authorized to work in the United States."
    strict_job = _job(api_client, profile_id, requirement)
    sponsored_job = _job(api_client, profile_id, f"{requirement}\nVisa sponsorship is available for this role.")

    unknown = _fit(api_client, profile_id, strict_job)
    assert unknown["disqualifiers"] == []
    assert _items(unknown, "uncertain")["Work authorization"]["quotation"] == requirement

    _confirm(api_client, profile_id, work_authorizations=[{"country_code": "US", "status": "not_authorized"}])
    denied = _fit(api_client, profile_id, strict_job)
    assert denied["verdict"] == "potential_disqualifiers"
    disqualifier = denied["disqualifiers"][0]
    assert disqualifier["kind"] == "work_authorization"
    assert "not authorized to work in United States" in disqualifier["explanation"]
    assert {s["source_type"] for s in disqualifier["sources"]} == {"eligibility_details", "work_authorization"}
    assert _fit(api_client, profile_id, sponsored_job)["disqualifiers"] == []

    _confirm(api_client, profile_id, work_authorizations=[{"country_code": "US", "status": "authorized"}])
    granted = _fit(api_client, profile_id, strict_job)
    assert [item["kind"] for item in granted["location_requirements_met"]] == ["work_authorization"]


def test_residence_alone_never_implies_work_authorization(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    _confirm(api_client, profile_id, country_of_residence="KE")

    fit = _fit(api_client, profile_id, _job(api_client, profile_id, "You must be authorized to work in Kenya."))

    assert fit["location_requirements_met"] == [] and fit["disqualifiers"] == []
    assert _items(fit, "uncertain")["Work authorization"]["status"] == "uncertain"


def test_residency_restrictions_against_confirmed_residence_and_relocation(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    strict = _job(api_client, profile_id, "Candidates must reside in Germany.")
    descriptive = _job(api_client, profile_id, "Our team is based in Germany.")

    assert _fit(api_client, profile_id, strict)["disqualifiers"] == []  # residence unknown

    _confirm(api_client, profile_id, country_of_residence="KE", relocation_willingness="not_willing")
    excluded = _fit(api_client, profile_id, strict)
    assert [d["kind"] for d in excluded["disqualifiers"]] == ["location"]
    assert "not willing to relocate" in excluded["disqualifiers"][0]["explanation"]
    assert _fit(api_client, profile_id, descriptive)["disqualifiers"] == []

    _confirm(api_client, profile_id, country_of_residence="KE", relocation_willingness="willing", relocation_countries=["DE"])
    movable = _fit(api_client, profile_id, strict)
    assert movable["disqualifiers"] == []
    assert "willing to relocate" in _items(movable, "uncertain")["Location"]["explanation"]

    _confirm(api_client, profile_id, country_of_residence="DE")
    assert [m["kind"] for m in _fit(api_client, profile_id, strict)["location_requirements_met"]] == ["location"]


def test_contradictory_location_wording_is_flagged_as_uncertain(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    fit = _fit(api_client, profile_id, _job(api_client, profile_id, "This role is open to candidates in any country.\nYou must reside in Canada."))

    contradiction = _items(fit, "uncertain")["Contradictory location wording"]
    assert "open to candidates in any country" in contradiction["quotation"]
    assert "You must reside in Canada." in contradiction["quotation"]


def test_work_arrangement_is_a_preference_not_a_disqualifier(api_client: TestClient) -> None:
    profile_id = _profile(api_client)
    _confirm(api_client, profile_id, accepted_work_arrangements=["remote"])

    fit = _fit(api_client, profile_id, _job(api_client, profile_id, "This is a hybrid role with 3 days per week in our office."))

    assert {item["status"] for item in fit["preferences"]} == {"mismatch"}
    assert fit["disqualifiers"] == []


def test_no_stated_requirements_and_pronoun_us_are_handled_honestly(api_client: TestClient) -> None:
    profile_id = _profile(api_client)

    fit = _fit(api_client, profile_id, _job(api_client, profile_id, "Tell us about yourself. Applicants must be authorized to work."))

    assert fit["coverage"]["total"] == 0
    assert "not measured" in fit["coverage"]["summary"]
    assert "names no country" in _items(fit, "uncertain")["Work authorization"]["explanation"]


def test_fit_is_owner_scoped(api_client: TestClient, database) -> None:
    _, factory = database
    first = _profile(api_client)
    second = _profile(api_client)
    job_id = _job(api_client, first, SKILLS_JOB)
    with factory.begin() as session:
        legacy = CandidateProfile(name="Unowned legacy profile")
        session.add(legacy)
        session.flush()
        legacy_id = legacy.id

    assert api_client.get(f"{API}/{second}/job-descriptions/{job_id}/fit").status_code == 404
    assert api_client.get(f"{API}/{legacy_id}/job-descriptions/{job_id}/fit").status_code == 404
    assert api_client.get(f"{API}/{first}/job-descriptions/{uuid4()}/fit").status_code == 404
