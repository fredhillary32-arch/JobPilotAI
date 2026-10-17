"""Reviewed CV writer: tailoring without invention, change log, edits, approval and export checks."""
import re
from datetime import date
from io import BytesIO
from uuid import UUID, uuid4

from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    CandidateCertification,
    CandidateEvidence,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
    TailoredCvDraft,
    User,
)
from app.schemas.cv_generation import CVStructuredContent
from app.services.cv_document_analysis import pdf_layout_risks
from app.services.cv_export import render_docx, render_pdf
from app.services.cv_export_checks import extract_export_text, verify_export
from app.services.cv_writer import introduced_words, language_quality, restate

API = "/api/v1/candidate-profiles"
JOB = """Service Desk Analyst

Requirements:
- Experience with Microsoft 365 and Active Directory
- Troubleshooting Windows laptops
- 2+ years of experience in IT support

Nice to have:
- ITIL certification
"""
# Deliberately weak source wording; the writer may restate but never add facts.
PAST_ROLE = [
    "responsible for managing Active Directory accounts & onboarding new staff",
    "Worked on the migration of 300 mailboxes to Microsoft 365",
    "I resolved Windows laptop tickets raised through the service desk",
    "Successfully reduced repeat tickets by documenting common fixes",
    "Maintain asset records for laptops and replacement hardware",
    "Trained staff on password resets and multi-factor sign-in",
]
CURRENT_ROLE = [
    "Manage the help desk queue for 120 staff across two offices",
    "Configure Windows laptops with standard software before issue",
    "Monitor Microsoft 365 licence usage and report monthly costs",
    "Coordinate hardware repairs with the vendor support team",
    "Document troubleshooting steps for new service desk analysts",
]


def setup_candidate(client: TestClient, factory, *, summary: str = "Service desk analyst who keeps staff productive with fast, well documented fixes.") -> tuple[str, str]:
    profile = client.post(API, json={
        "name": "Amina Wanjiru", "professional_headline": "Service Desk Analyst", "summary": summary,
        "contact_email": "amina@example.com", "contact_phone": "+254 700 000 000", "location": "Nairobi, Kenya",
    })
    assert profile.status_code == 201, profile.text
    profile_id = profile.json()["id"]
    with factory() as session:
        pid = UUID(profile_id)
        session.add_all([
            CandidateWorkExperience(candidate_profile_id=pid, employer="Savanna Telecom", job_title="IT Support Officer",
                                    start_date=date(2019, 2, 1), end_date=date(2022, 6, 30), current_role=False, achievements=PAST_ROLE),
            CandidateWorkExperience(candidate_profile_id=pid, employer="Kilimo Finance", job_title="Service Desk Analyst",
                                    start_date=date(2022, 7, 1), current_role=True, achievements=CURRENT_ROLE),
            CandidateSkill(candidate_profile_id=pid, name="Active Directory"),
            CandidateSkill(candidate_profile_id=pid, name="Customer service"),
            CandidateCertification(candidate_profile_id=pid, name="ITIL 4 Foundation", issuer="PeopleCert", issue_date=date(2021, 5, 1)),
        ])
        session.commit()
    job = client.post(f"{API}/{profile_id}/job-descriptions", json={"job_title": "Service Desk Analyst", "company": "Acme", "description": JOB})
    assert job.status_code == 201, job.text
    return profile_id, job.json()["id"]


def generate(client: TestClient, profile_id: str, job_id: str, **body) -> dict:
    response = client.post(f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts", json={"writer": "reviewed", **body})
    assert response.status_code == 201, response.text
    return response.json()


def review(client: TestClient, profile_id: str, draft_id: str) -> dict:
    response = client.get(f"{API}/{profile_id}/cv-drafts/{draft_id}/review")
    assert response.status_code == 200, response.text
    return response.json()


def bullets(draft: dict) -> list[dict]:
    return [b for s in draft["structured_content"]["sections"] for r in s["roles"] for b in r["bullets"]]


def test_reviewed_draft_restates_without_adding_words_or_numbers(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    content = draft["structured_content"]
    assert content["review"]["approval_status"] == "pending_review"
    assert content["contact_details"] == "amina@example.com | +254 700 000 000 | Nairobi, Kenya"
    assert [s["heading"] for s in content["sections"]][-1] == "Certifications"

    log = review(api_client, profile_id, draft["id"])["change_log"]
    rewritten = [entry for entry in log if entry["origin"] == "rewritten"]
    assert rewritten, "weak source wording should have been restated"
    for entry in log:
        if entry["origin"] in {"source", "rewritten"}:
            assert introduced_words(entry["proposed"], entry["original"]) == [], entry
        assert entry["evidence"], entry
        if entry["changed"]:
            assert entry["reasons"], entry
        if entry["significance"] == "minor":
            assert entry["original"].rstrip(".").casefold() == entry["proposed"].rstrip(".").casefold()
    assert any(entry["significance"] == "wording" for entry in log)
    text = draft["generated_content"]
    # Every number on the CV comes from the candidate's own records.
    records = " ".join(PAST_ROLE + CURRENT_ROLE) + " amina@example.com +254 700 000 000 ITIL 4 2019 2021 2022"
    for number in re.findall(r"\d+", text):
        assert number in records, number
    assert "&" not in text and "—" not in text


def test_past_roles_use_past_tense_and_weak_openers_are_removed(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    past = next(r for s in draft["structured_content"]["sections"] for r in s["roles"] if r["employer"] == "Savanna Telecom")
    statements = [b["text"] for b in past["bullets"]]
    quality = language_quality(statements)
    assert quality["weak_openers"] == 0 and quality["first_person"] == 0
    assert quality["opener_diversity"] >= 0.8
    assert all(not s.split()[0].endswith(("ing",)) for s in statements)
    assert not any(s.startswith(("Maintain ", "Manage ")) for s in statements)
    # Restated wording is clearer by measurable signals than the source wording.
    assert language_quality(PAST_ROLE)["weak_openers"] > quality["weak_openers"]


def test_experience_is_reverse_chronological_and_dates_are_preserved(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    roles = [r for s in generate(api_client, profile_id, job_id)["structured_content"]["sections"] for r in s["roles"]]
    assert [r["employer"] for r in roles] == ["Kilimo Finance", "Savanna Telecom"]
    assert [r["dates"] for r in roles] == ["Jul 2022 to Present", "Feb 2019 to Jun 2022"]


def test_composed_summary_names_only_demonstrated_requirements(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    summary = draft["structured_content"]["sections"][0]["claims"]
    composed = [c for c in summary if c["origin"] == "composed"]
    assert len(composed) == 1
    assert "Active Directory" in composed[0]["text"] and "Microsoft 365" in composed[0]["text"]
    assert all(ref["source_type"] in {"work_experience", "candidate_evidence"} for ref in composed[0]["source_references"])
    # Every term named appears in the referenced source wording.
    sources = " ".join(ref["claim_text"] for ref in composed[0]["source_references"])
    assert "Active Directory" in sources and "Microsoft 365" in sources


def test_unreviewed_evidence_is_never_used_by_the_writer(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id, job_id = setup_candidate(api_client, factory)
    document = api_client.post(f"{API}/{profile_id}/documents", files={"file": ("cv.txt", b"Savanna Telecom notes", "text/plain")}).json()
    with factory() as session:
        session.add(CandidateEvidence(
            candidate_profile_id=UUID(profile_id), source_document_id=UUID(document["id"]), category="achievement",
            description="Led a Savanna Telecom data centre move for 900 servers", source_excerpt="Savanna Telecom notes",
            source_section="Savanna Telecom", confirmation_status="unreviewed"))
        session.commit()
    draft = generate(api_client, profile_id, job_id)
    assert "900" not in draft["generated_content"]
    assert all(ref["source_type"] != "candidate_evidence" for ref in draft["source_references"])


def test_export_requires_approval_then_pdf_and_docx_read_back_exactly(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    exports = f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft['id']}/exports"
    blocked = api_client.post(exports, json={"export_format": "pdf"})
    assert blocked.status_code == 409 and "approve" in blocked.json()["detail"]
    assert review(api_client, profile_id, draft["id"])["export_ready"] is False

    approved = api_client.post(f"{API}/{profile_id}/cv-drafts/{draft['id']}/approval", json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["structured_content"]["review"]["approval_status"] == "approved"
    assert approved.json()["generated_content"] == draft["generated_content"]
    for export_format in ("pdf", "docx"):
        created = api_client.post(exports, json={"export_format": export_format})
        assert created.status_code == 201, created.text
        verification = created.json()["verification"]
        assert verification["ok"] is True and verification["missing_lines"] == []
        download = api_client.get(f"{exports}/{created.json()['id']}/download")
        text = " ".join(extract_export_text(download.content, export_format).split())
        for bullet in bullets(draft):
            assert " ".join(bullet["text"].split()) in text
    assert api_client.get(exports).json()[0]["verification"] is None


def test_candidate_edits_create_a_new_version_and_flag_unsupported_wording(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    target = bullets(draft)[0]
    # Going back to the candidate's own source wording adds nothing new.
    supported = target["source_references"][0]["claim_text"]
    invented = "Cut ticket volume by 87% using Microsoft 365 automation."

    revision = api_client.post(f"{API}/{profile_id}/cv-drafts/{draft['id']}/revisions", json={"edits": [
        {"key": target["key"], "text": invented}]})
    assert revision.status_code == 201, revision.text
    revised = revision.json()
    assert revised["id"] != draft["id"]
    assert api_client.get(f"{API}/{profile_id}/cv-drafts/{draft['id']}").json()["generated_content"] == draft["generated_content"]
    edited = next(b for b in bullets(revised) if b["key"] == target["key"])
    assert edited["origin"] == "candidate_edited" and edited["needs_confirmation"] is True
    assert "87" in edited["confirmation_note"]
    details = review(api_client, profile_id, revised["id"])
    assert details["needs_confirmation"] == 1
    assert details["trace"]["parent_draft_id"] == draft["id"]

    refused = api_client.post(f"{API}/{profile_id}/cv-drafts/{revised['id']}/approval", json={})
    assert refused.status_code == 409 and "not in your records" in refused.json()["detail"]
    attested = api_client.post(f"{API}/{profile_id}/cv-drafts/{revised['id']}/approval", json={"attest_unconfirmed_statements": True})
    assert attested.status_code == 200
    assert attested.json()["structured_content"]["review"]["attested_unconfirmed_statements"] is True
    export = api_client.post(f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/{revised['id']}/exports", json={"export_format": "docx"})
    assert export.status_code == 201, export.text

    plain = api_client.post(f"{API}/{profile_id}/cv-drafts/{draft['id']}/revisions", json={"edits": [
        {"key": target["key"], "text": supported}]})
    assert plain.status_code == 201
    assert next(b for b in bullets(plain.json()) if b["key"] == target["key"])["needs_confirmation"] is False


def test_invalid_edits_and_standard_drafts_are_refused(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    unknown = api_client.post(f"{API}/{profile_id}/cv-drafts/{draft['id']}/revisions", json={"edits": [{"key": "skill:anything", "text": "Python"}]})
    assert unknown.status_code == 422
    standard = api_client.post(f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts")
    if standard.status_code == 201:
        response = api_client.post(f"{API}/{profile_id}/cv-drafts/{standard.json()['id']}/revisions", json={"edits": [{"key": "summary:0", "text": "New"}]})
        assert response.status_code == 409


def test_review_and_approval_are_owner_scoped_and_csrf_protected(api_client: TestClient, database) -> None:
    factory = database[1]
    profile_id, job_id = setup_candidate(api_client, factory)
    draft = generate(api_client, profile_id, job_id)
    with factory() as session:
        other = User(email="another-owner@example.com", password_hash="$argon2id$test-fixture")
        session.add(other)
        session.flush()
        foreign = CandidateProfile(name="Another Person", user_id=other.id)
        session.add(foreign)
        session.flush()
        stored = session.get(TailoredCvDraft, UUID(draft["id"]))
        foreign_id = foreign.id
        session.commit()
        assert stored is not None
    assert api_client.get(f"{API}/{foreign_id}/cv-drafts/{draft['id']}/review").status_code == 404
    assert api_client.post(f"{API}/{foreign_id}/cv-drafts/{draft['id']}/approval", json={}).status_code == 404
    assert api_client.get(f"{API}/{profile_id}/cv-drafts/{uuid4()}/review").status_code == 404

    token = api_client.headers.pop("X-CSRF-Token")
    try:
        assert api_client.post(f"{API}/{profile_id}/cv-drafts/{draft['id']}/approval", json={}).status_code == 403
        assert api_client.post(f"{API}/{profile_id}/cv-drafts/{draft['id']}/revisions",
                               json={"edits": [{"key": "summary:0", "text": "Changed"}]}).status_code == 403
    finally:
        api_client.headers["X-CSRF-Token"] = token
    with factory() as session:
        assert session.get(TailoredCvDraft, UUID(draft["id"])).structured_content["review"]["approval_status"] == "pending_review"


def test_incomplete_profile_gets_actionable_errors_not_a_crash(api_client: TestClient) -> None:
    profile = api_client.post(API, json={"name": "New Candidate"}).json()
    job = api_client.post(f"{API}/{profile['id']}/job-descriptions", json={"job_title": "Analyst", "description": JOB}).json()
    response = api_client.post(f"{API}/{profile['id']}/job-descriptions/{job['id']}/cv-drafts", json={"writer": "reviewed"})
    # Saved as incomplete with grouped, actionable issues instead of an error.
    assert response.status_code == 201
    results = response.json()["validation_results"]
    assert response.json()["status"] == "needs_review" and results["completeness"] == "incomplete"
    messages = " ".join(issue["message"] for issue in results["issues"])
    assert "headline" in messages and "summary" in messages and "no roles" in messages
    assert {issue["group"] for issue in results["issues"]} == {"profile_evidence", "experience_evidence"}


def test_review_reports_pre_export_checks_and_plain_text_preview(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    draft = generate(api_client, profile_id, job_id)
    details = review(api_client, profile_id, draft["id"])
    checks = {check["name"]: check["status"] for check in details["checks"]["checks"]}
    assert details["checks"]["passed"] is True
    assert checks["Sections"] == checks["Job titles, employers and dates"] == checks["Bullets"] == "pass"
    assert details["checks"]["plain_text"] == draft["generated_content"]
    assert details["trace"]["job_description"]["id"] == job_id


# --- Unit-level guarantees --------------------------------------------------

def test_restate_never_introduces_numbers_or_new_words() -> None:
    samples = [
        "responsible for managing payroll & onboarding",
        "Worked on a 3 month upgrade",
        "I built dashboards",
        "Successfully handled 45 calls a day",
        "duties included answering phones and logging tickets",
        "assisted with the office move",
    ]
    for sample in samples:
        for past in (True, False):
            proposed, _, _ = restate(sample, past=past)
            assert introduced_words(proposed, sample) == [], (sample, proposed)
            assert proposed[0].isupper() and proposed.endswith(".")


def test_verify_export_detects_missing_lines() -> None:
    text = "Amina\nAnalyst\n\nProfessional Summary\n\n- First line of text here.\n- Second line of text here."
    document = Document()
    for line in ["Amina", "Analyst", "Professional Summary", "First line of text here."]:
        document.add_paragraph(line)
    output = BytesIO()
    document.save(output)
    result = verify_export(output.getvalue(), "docx", text)
    assert result["ok"] is False and result["missing_lines"] == ["Second line of text here."]


def test_own_single_column_pdf_is_not_reported_as_columns(api_client: TestClient, database) -> None:
    profile_id, job_id = setup_candidate(api_client, database[1])
    content = CVStructuredContent.model_validate(generate(api_client, profile_id, job_id)["structured_content"])
    assert not [risk for risk in pdf_layout_risks(render_pdf(content).content) if risk["code"] == "columns"]
    assert render_docx(content).content[:2] == b"PK"
