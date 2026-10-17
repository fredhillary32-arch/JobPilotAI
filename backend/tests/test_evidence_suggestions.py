"""Local evidence suggestions and evidence integrity after re-extraction."""
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    CandidateDocument,
    CandidateEvidence,
    CandidateProfile,
    CandidateWorkExperience,
    DocumentExtraction,
    User,
)
from app.schemas.cv_generation import CVSourceReference
from app.services.cv_export import InvalidDraftForExport, _assert_reference_matches
from app.services.evidence_suggestions import MAX_SUGGESTIONS_PER_DOCUMENT, suggest_evidence

API = "/api/v1/candidate-profiles"
CV_TEXT = """Amina Wanjiru
amina@example.com | +254 700 000 000 | linkedin.com/in/amina
Nairobi, Kenya

PROFILE
Passionate support specialist who loves helping people every single day.

WORK EXPERIENCE
IT Support Officer, Savanna Telecom 2019 - 2022
- Resolved 40 tickets a day across Windows and macOS laptops
- Administered Microsoft 365 accounts for new starters and leavers
- Awarded employee of the quarter for service desk quality

SKILLS
Technical: Active Directory, Microsoft 365; Jira Service Management
Customer service | Documentation

EDUCATION
Bachelor of Science in Computer Science, University of Nairobi, 2018

CERTIFICATIONS
CompTIA A+ certification (2020)

PROJECTS
- Built an onboarding checklist used by every new hire

REFERENCES
Jane Doe, Service Manager, Savanna Telecom, jane@example.com
"""


def profile(client: TestClient, name: str = "Amina Wanjiru") -> str:
    response = client.post(API, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_and_extract(client: TestClient, profile_id: str, content: bytes = CV_TEXT.encode(),
                       filename: str = "cv.txt", media_type: str = "text/plain") -> str:
    upload = client.post(f"{API}/{profile_id}/documents", files={"file": (filename, content, media_type)},
                         data={"document_kind": "source_cv"})
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]
    extracted = client.post(f"{API}/{profile_id}/documents/{document_id}/extraction")
    assert extracted.json()["status"] == "succeeded", extracted.text
    return document_id


def suggest(client: TestClient, profile_id: str, document_id: str):
    return client.post(f"{API}/{profile_id}/documents/{document_id}/evidence-suggestions")


def extracted_text(client: TestClient, profile_id: str, document_id: str) -> str:
    return client.get(f"{API}/{profile_id}/documents/{document_id}/extraction/text").json()["text"]


def evidence(client: TestClient, profile_id: str) -> list[dict]:
    return client.get(f"{API}/{profile_id}/evidence").json()


def test_suggestions_cover_every_category_with_exact_unreviewed_excerpts(api_client: TestClient) -> None:
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    response = suggest(api_client, profile_id, document_id)
    assert response.status_code == 200, response.text
    body = response.json()
    text = extracted_text(api_client, profile_id, document_id)

    assert body["created"] == len(body["evidence"]) > 0 and body["limited"] is False
    by_category: dict[str, list[str]] = {}
    for item in body["evidence"]:
        assert item["confirmation_status"] == "unreviewed"
        assert item["source_document_id"] == document_id and item["source_current"] is True
        assert text[item["source_start"]:item["source_end"]] == item["source_excerpt"]
        assert item["description"] == " ".join(item["source_excerpt"].split())
        assert item["source_section"]
        by_category.setdefault(item["category"], []).append(item["source_excerpt"])
    assert set(by_category) == {
        "employment_responsibility", "metric", "achievement", "technical_skill", "qualification", "project",
    }
    assert by_category["metric"] == ["Resolved 40 tickets a day across Windows and macOS laptops"]
    # "365" in a product name is not a figure.
    assert "Administered Microsoft 365 accounts for new starters and leavers" in by_category["employment_responsibility"]
    assert {"Active Directory", "Microsoft 365", "Jira Service Management", "Customer service", "Documentation"} <= set(by_category["technical_skill"])
    assert by_category["project"] == ["Built an onboarding checklist used by every new hire"]


def test_contact_details_summary_references_and_role_lines_are_excluded(api_client: TestClient) -> None:
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    excerpts = " ".join(item["source_excerpt"] for item in suggest(api_client, profile_id, document_id).json()["evidence"])
    for private_or_unrelated in ("amina@example.com", "+254", "linkedin", "Nairobi, Kenya", "Passionate",
                                 "Jane Doe", "IT Support Officer, Savanna Telecom 2019"):
        assert private_or_unrelated not in excerpts


def test_repeated_generation_never_duplicates_or_resets_review_decisions(api_client: TestClient) -> None:
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    first = suggest(api_client, profile_id, document_id).json()
    records = first["evidence"]
    confirmed, rejected = records[0]["id"], records[1]["id"]
    assert api_client.patch(f"{API}/{profile_id}/evidence/{confirmed}", json={"confirmation_status": "candidate_confirmed"}).status_code == 200
    assert api_client.patch(f"{API}/{profile_id}/evidence/{rejected}", json={"confirmation_status": "rejected"}).status_code == 200

    # Re-extracting the unchanged document and suggesting again adds nothing.
    assert api_client.post(f"{API}/{profile_id}/documents/{document_id}/extraction").json()["status"] == "succeeded"
    second = suggest(api_client, profile_id, document_id).json()
    assert second["created"] == 0 and second["skipped_existing"] == first["created"]

    stored = {item["id"]: item for item in evidence(api_client, profile_id)}
    assert len(stored) == first["created"]
    assert stored[confirmed]["confirmation_status"] == "candidate_confirmed"
    assert stored[rejected]["confirmation_status"] == "rejected"
    excerpts = [item["source_excerpt"] for item in stored.values()]
    assert len(excerpts) == len(set(excerpts))


def test_manual_evidence_for_the_same_excerpt_is_not_duplicated(api_client: TestClient) -> None:
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    manual = api_client.post(f"{API}/{profile_id}/evidence", json={
        "source_document_id": document_id, "category": "project", "description": "Onboarding checklist",
        "source_excerpt": "Built an onboarding checklist used by every new hire",
    })
    assert manual.status_code == 201
    body = suggest(api_client, profile_id, document_id).json()
    assert body["skipped_existing"] == 1
    assert all(item["source_excerpt"] != "Built an onboarding checklist used by every new hire" for item in body["evidence"])


def test_per_document_limit_is_reported(api_client: TestClient) -> None:
    lines = "\n".join(f"- Resolved escalated laptop ticket number {index} for the finance team" for index in range(70))
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id, f"WORK EXPERIENCE\n{lines}\n".encode())
    body = suggest(api_client, profile_id, document_id).json()
    assert body["created"] == MAX_SUGGESTIONS_PER_DOCUMENT and body["limited"] is True


def test_pdf_cv_suggestions_join_wrapped_bullets_with_exact_offsets(api_client: TestClient) -> None:
    pdf = pymupdf.open()
    page = pdf.new_page()
    y = 72
    for line in ["WORK EXPERIENCE", "- Migrated 300 mailboxes to Microsoft 365 for the head", "office team over one weekend",
                 "- Maintained laptop asset records for the service desk", "SKILLS", "Windows, Active Directory"]:
        page.insert_text((72, y), line)
        y += 16
    content = pdf.tobytes()
    pdf.close()
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id, content, "cv.pdf", "application/pdf")
    body = suggest(api_client, profile_id, document_id).json()
    text = extracted_text(api_client, profile_id, document_id)
    descriptions = {item["description"]: item for item in body["evidence"]}
    assert "Migrated 300 mailboxes to Microsoft 365 for the head office team over one weekend" in descriptions
    for item in body["evidence"]:
        assert text[item["source_start"]:item["source_end"]] == item["source_excerpt"]
    assert {"Windows", "Active Directory"} <= {item["source_excerpt"] for item in body["evidence"]}


def test_suggestions_require_owned_source_document_and_successful_extraction(
    api_client: TestClient, database, tmp_path: Path,
) -> None:
    factory = database[1]
    profile_id = profile(api_client)
    other_profile = profile(api_client, "Second Profile")
    document_id = upload_and_extract(api_client, profile_id)

    assert suggest(api_client, other_profile, document_id).status_code == 404
    assert suggest(api_client, profile_id, str(uuid4())).status_code == 404

    not_extracted = api_client.post(f"{API}/{profile_id}/documents", files={"file": ("b.txt", b"WORK EXPERIENCE\n- Resolved forty laptop tickets every single day", "text/plain")}).json()
    assert suggest(api_client, profile_id, not_extracted["id"]).status_code == 409

    with factory() as session:
        generated = CandidateDocument(
            candidate_profile_id=UUID(profile_id), document_kind="tailored_cv", provenance="system_generated",
            original_filename=f"jobpilot-cv-{uuid4().hex}.pdf", media_type="application/pdf",
            storage_key=f"{uuid4().hex}.pdf", size_bytes=4, sha256=sha256(b"x").hexdigest())
        session.add(generated)
        other = User(email="someone-else@example.com", password_hash="$argon2id$test-fixture")
        session.add(other)
        session.flush()
        foreign = CandidateProfile(name="Foreign", user_id=other.id)
        session.add(foreign)
        session.commit()
        generated_id, foreign_id = generated.id, foreign.id
    assert suggest(api_client, profile_id, str(generated_id)).status_code == 409
    assert suggest(api_client, str(foreign_id), document_id).status_code == 404

    token = api_client.headers.pop("X-CSRF-Token")
    try:
        assert suggest(api_client, profile_id, document_id).status_code == 403
    finally:
        api_client.headers["X-CSRF-Token"] = token
    assert evidence(api_client, profile_id) == []


def test_failed_re_extraction_makes_existing_evidence_stale_and_unusable(
    api_client: TestClient, tmp_path: Path,
) -> None:
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    item = suggest(api_client, profile_id, document_id).json()["evidence"][0]
    assert api_client.patch(f"{API}/{profile_id}/evidence/{item['id']}", json={"confirmation_status": "candidate_confirmed"}).status_code == 200

    stored = next((tmp_path / "private-documents").iterdir())
    stored.write_bytes(b"tampered source")
    assert api_client.post(f"{API}/{profile_id}/documents/{document_id}/extraction").json()["status"] == "failed"

    current = {entry["id"]: entry for entry in evidence(api_client, profile_id)}[item["id"]]
    assert current["source_current"] is False
    assert current["confirmation_status"] == "candidate_confirmed"  # the decision is kept, but not used
    assert suggest(api_client, profile_id, document_id).status_code == 409


def test_changed_extraction_text_marks_evidence_stale_until_re_linked(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    items = suggest(api_client, profile_id, document_id).json()["evidence"]
    target = next(item for item in items if item["category"] == "project")

    # A different extractor version produces shifted text for the same document.
    with factory() as session:
        extraction = session.scalar(select(DocumentExtraction).where(DocumentExtraction.source_document_id == UUID(document_id)))
        extraction.extracted_text = "Curriculum vitae\n\n" + extraction.extracted_text
        session.commit()

    stale = {entry["id"]: entry for entry in evidence(api_client, profile_id)}[target["id"]]
    assert stale["source_current"] is False
    refused = api_client.patch(f"{API}/{profile_id}/evidence/{target['id']}", json={"confirmation_status": "candidate_confirmed"})
    assert refused.status_code == 409 and "Re-link" in refused.json()["detail"]
    assert api_client.patch(f"{API}/{profile_id}/evidence/{target['id']}", json={"confirmation_status": "rejected"}).status_code == 200

    # Re-linking clears the old offsets so the server locates the excerpt in the current text.
    relinked = api_client.patch(f"{API}/{profile_id}/evidence/{target['id']}", json={
        "source_excerpt": target["source_excerpt"], "source_start": None, "source_end": None})
    assert relinked.status_code == 200
    body = relinked.json()
    assert body["source_current"] is True and body["confirmation_status"] == "rejected"
    assert body["source_start"] == target["source_start"] + len("Curriculum vitae\n\n")

    # Suggesting again against the new text does not duplicate re-linked or stale claims.
    again = suggest(api_client, profile_id, document_id).json()
    assert again["created"] == 0


def test_stale_confirmed_evidence_is_not_used_for_matching_or_export(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    item = next(entry for entry in suggest(api_client, profile_id, document_id).json()["evidence"] if entry["source_excerpt"] == "Active Directory")
    api_client.patch(f"{API}/{profile_id}/evidence/{item['id']}", json={"confirmation_status": "candidate_confirmed"})
    job = api_client.post(f"{API}/{profile_id}/job-descriptions", json={
        "job_title": "Support", "description": "Requirements:\n- Active Directory administration"}).json()

    def status_of_requirement() -> str:
        report = api_client.get(f"{API}/{profile_id}/job-descriptions/{job['id']}/ats-analysis").json()
        return report["requirements"]["essential"][0]["status"]

    assert status_of_requirement() == "matched"
    reference = CVSourceReference(
        source_type="candidate_evidence", source_id=item["id"], source_field="description",
        claim_text=item["description"], source_document_id=document_id, source_excerpt=item["source_excerpt"],
        source_start=item["source_start"], source_end=item["source_end"], evidence_confirmation_status="candidate_confirmed")
    with factory() as session:
        owner = session.get(CandidateProfile, UUID(profile_id))
        _assert_reference_matches(reference, owner, session)  # valid while the source matches
        extraction = session.scalar(select(DocumentExtraction).where(DocumentExtraction.source_document_id == UUID(document_id)))
        extraction.extracted_text = extraction.extracted_text.replace("Active Directory", "Directory services")
        session.commit()
        with pytest.raises(InvalidDraftForExport):
            _assert_reference_matches(reference, owner, session)
    assert status_of_requirement() == "missing"


def test_a_long_skills_list_does_not_crowd_out_experience_claims() -> None:
    skills = ", ".join(f"Tool{index}" for index in range(40))
    bullets = "\n".join(f"- Resolved priority incident type {name} for retail branches" for name in "ABCDE")
    found, limited = suggest_evidence(f"SKILLS\n{skills}\n\nWORK EXPERIENCE\n{bullets}\n")
    categories = [item.category for item in found]
    assert categories.count("technical_skill") == 25 and categories.count("employment_responsibility") == 5
    assert limited is True
    assert [item.start for item in found] == sorted(item.start for item in found)


def test_wrapped_line_starting_with_a_product_name_is_joined() -> None:
    text = "WORK EXPERIENCE\n- Automated new starter account creation using\nMicrosoft Graph scripts and a shared approval form\n- Trained six analysts on the incident process"
    excerpts = [item.excerpt for item in suggest_evidence(text)[0]]
    assert excerpts[0] == "Automated new starter account creation using\nMicrosoft Graph scripts and a shared approval form"
    assert excerpts[1] == "Trained six analysts on the incident process"


def test_evidence_list_order_is_deterministic_for_equal_timestamps(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = profile(api_client)
    document_id = upload_and_extract(api_client, profile_id)
    text = extracted_text(api_client, profile_id, document_id)
    created = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    phrases = ["Resolved 40 tickets", "Administered Microsoft 365", "Awarded employee", "Built an onboarding"]
    with factory() as session:
        # Inserted out of document order (neither forward nor reverse), with one timestamp as a batch has.
        for phrase in (phrases[2], phrases[0], phrases[3], phrases[1]):
            start = text.index(phrase)
            session.add(CandidateEvidence(
                candidate_profile_id=UUID(profile_id), source_document_id=UUID(document_id), category="achievement",
                description=phrase, source_excerpt=phrase, source_start=start, source_end=start + len(phrase),
                confirmation_status="unreviewed", created_at=created, updated_at=created))
        session.commit()

    def order() -> list[str]:
        return [item["description"] for item in evidence(api_client, profile_id)]

    assert order() == phrases  # document position breaks the tie
    middle = next(item for item in evidence(api_client, profile_id) if item["description"] == "Awarded employee")
    assert api_client.patch(f"{API}/{profile_id}/evidence/{middle['id']}", json={"confirmation_status": "candidate_confirmed"}).status_code == 200
    assert order() == phrases


def test_rules_outside_known_sections_only_take_clear_action_bullets() -> None:
    text = "Amina Wanjiru\nI enjoy hiking and reading on weekends with friends.\n- Configured backup jobs for the finance file server\nSUPERPOWERS\nNot a heading anyone parses reliably at all"
    excerpts = [item.excerpt for item in suggest_evidence(text)[0]]
    assert excerpts == ["Configured backup jobs for the finance file server"]


def test_role_dates_in_experience_are_left_to_the_profile(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id = profile(api_client)
    with factory() as session:
        session.add(CandidateWorkExperience(candidate_profile_id=UUID(profile_id), employer="Savanna Telecom",
                                            job_title="IT Support Officer", start_date=date(2019, 1, 1), current_role=True, achievements=[]))
        session.commit()
    document_id = upload_and_extract(api_client, profile_id)
    excerpts = [item["source_excerpt"] for item in suggest(api_client, profile_id, document_id).json()["evidence"]]
    assert not any("2019 - 2022" in excerpt for excerpt in excerpts)
    with factory() as session:
        assert session.scalar(select(CandidateEvidence).where(CandidateEvidence.confirmation_status != "unreviewed")) is None
