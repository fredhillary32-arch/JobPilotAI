"""Requirement analysis, the candidate's skill confirmations, incomplete drafts and their export.

The fixture mirrors a real failure: a customer-support role with only one
supported bullet, and a job advert whose "Who you are" section mixes
communication skills with personality traits and whose "How we work together"
section is context, not requirements. All content is synthetic.
"""
from datetime import date
from io import BytesIO
from uuid import UUID

import pymupdf
from docx import Document
from fastapi.testclient import TestClient

from app.models import CandidateWorkExperience
from app.services.job_requirements import extract_requirements

API = "/api/v1/candidate-profiles"
JOB = """The Role
You will own customer support for our email product. Most tickets involve DNS records and campaign setup.
You will triage the Help Scout queue and report bugs with steps to reproduce.

Who You Are
You build rapport fast. You are warm and relatable in writing and on calls.
You are a good communicator who can explain technical problems clearly.
You have a low ego. You handle disagreement as a discussion, not a personal attack.
Growth mindset. You are positive about new process changes.
You act with a constant sense of urgency.
You build rapport fast. You are warm and relatable in writing and on calls.

A Plus If You Have
Working knowledge of DNS, SPF and DKIM.

How We Work Together
You'll work directly with the founder and with our lead developer.
The founder can stay frustrated about a problem until it's solved.

Benefits
Paid time off.
"""
TOURISM_DESCRIPTION = "Answered member questions by phone and email and kept case notes accurate for every enquiry."


def setup(client: TestClient, factory) -> tuple[str, str, str]:
    profile = client.post(API, json={"name": "Wanjiku Test", "professional_headline": "Customer Support Specialist",
                                     "summary": "Customer support specialist who resolves member questions clearly and calmly."}).json()
    with factory() as session:
        role = CandidateWorkExperience(candidate_profile_id=UUID(profile["id"]), employer="Tourism Fund",
                                       job_title="Customer Support Specialist", start_date=date(2022, 1, 3),
                                       end_date=date(2023, 12, 13), current_role=False, description=TOURISM_DESCRIPTION,
                                       achievements=[])
        session.add(role)
        session.commit()
        role_id = str(role.id)
    job = client.post(f"{API}/{profile['id']}/job-descriptions",
                      json={"job_title": "Technical Customer Support", "company": "Example Mail", "description": JOB}).json()
    return profile["id"], job["id"], role_id


def generate(client, profile_id, job_id):
    return client.post(f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts", json={"writer": "reviewed"})


def ats(client, profile_id, job_id):
    return client.get(f"{API}/{profile_id}/job-descriptions/{job_id}/ats-analysis").json()


def requirement(report, fragment, group="essential"):
    return next(item for item in report["requirements"][group] if fragment in item["source_text"])


# --- requirement analysis ------------------------------------------------------------


def test_context_work_style_and_boilerplate_are_not_cv_skill_requirements() -> None:
    result = extract_requirements(JOB, company="Example Mail")
    texts = {item["source_text"]: item for item in result["requirements"]}
    assert not any("founder" in text or "lead developer" in text for text in texts)  # context, not skills
    assert any("founder can stay frustrated" in item["text"] for item in result["context"])
    assert texts["You have a low ego. You handle disagreement as a discussion, not a personal attack."]["category"] == "work_style"
    assert texts["You have a low ego. You handle disagreement as a discussion, not a personal attack."]["cv_use"] == "interview"
    rapport = texts["You build rapport fast. You are warm and relatable in writing and on calls."]
    assert rapport["category"] == "communication" and rapport["importance"] == "essential" and rapport["cv_use"] == "cv"
    # The repeated sentence is listed once; every requirement keeps a stable key and its source offsets.
    assert sum(1 for item in result["requirements"] if item["source_text"].startswith("You build rapport")) == 1
    assert all(len(item["key"]) == 16 for item in result["requirements"])
    assert JOB[rapport["source_start"]:rapport["source_end"]] == rapport["source_text"]
    assert extract_requirements(JOB)["requirements"][0]["key"] == result["requirements"][0]["key"]
    keywords = {item["term"] for item in result["keywords"]}
    assert not keywords & {"when", "then", "something", "things", "most", "founder"}
    assert not any("Paid time off" in item["source_text"] for item in result["requirements"])


# --- the full workflow ---------------------------------------------------------------


def test_missing_evidence_gives_an_incomplete_draft_then_confirmations_improve_it(api_client: TestClient, database) -> None:
    profile_id, job_id, role_id = setup(api_client, database[1])

    # 1. The original failure: one supported bullet. Now an incomplete, reviewable draft.
    first = generate(api_client, profile_id, job_id)
    assert first.status_code == 201, first.text
    first = first.json()
    assert first["status"] == "needs_review" and first["validation_results"]["completeness"] == "incomplete"
    issue = first["validation_results"]["issues"][0]
    assert issue["role"] == "Customer Support Specialist at Tourism Fund" and "1 supported bullet;" in issue["message"]
    # Work style is not reported as a CV gap.
    assert not any("low ego" in gap or "Growth mindset" in gap for gap in first["validation_results"]["gaps"])

    report = ats(api_client, profile_id, job_id)
    rapport = requirement(report, "You build rapport fast")
    assert rapport["status"] == "missing" and rapport["action"]
    assert any("low ego" in item["source_text"] for item in report["requirements"]["work_style"])
    assert not any("low ego" in item["source_text"] for item in report["requirements"]["essential"])
    score_before = report["score"]

    # 2. The candidate answers four requirements.
    communicator = requirement(report, "good communicator")
    urgency = report["requirements"]["work_style"][-1]
    dns = requirement(report, "DNS, SPF", "preferred")
    used = api_client.post(f"{API}/{profile_id}/skill-confirmations", json={
        "job_description_id": job_id, "requirement_key": rapport["key"], "skill_name": "Building rapport with customers",
        "category": "communication", "response": "used_in_role", "work_experience_id": role_id,
        "example": "Built rapport with members on phone calls and resolved their booking questions in writing.",
    })
    assert used.status_code == 201, used.text
    assert used.json()["provenance"] == "candidate_confirmed" and used.json()["independently_verified"] is False
    assert used.json()["requirement_text"].startswith("You build rapport fast")  # taken from the server's analysis
    has = api_client.post(f"{API}/{profile_id}/skill-confirmations", json={
        "job_description_id": job_id, "requirement_key": communicator["key"], "skill_name": "Technical communication",
        "category": "communication", "response": "has_skill", "proficiency_level": "intermediate"}).json()
    no = api_client.post(f"{API}/{profile_id}/skill-confirmations", json={
        "job_description_id": job_id, "requirement_key": dns["key"], "skill_name": "SPF and DKIM",
        "category": "technical", "response": "not_possessed"}).json()
    unsure = api_client.post(f"{API}/{profile_id}/skill-confirmations", json={
        "job_description_id": job_id, "requirement_key": urgency["key"], "skill_name": "Sense of urgency",
        "category": "work_style", "response": "unsure"})
    assert unsure.status_code == 201
    # A skill recorded on its own, with no employer.
    standalone = api_client.post(f"{API}/{profile_id}/skill-confirmations", json={
        "skill_name": "Help Scout", "category": "tool", "response": "has_skill"})
    assert standalone.status_code == 201

    report = ats(api_client, profile_id, job_id)
    assert requirement(report, "You build rapport fast")["status"] == "matched"
    assert requirement(report, "You build rapport fast")["evidence_strength"] == "candidate_statement"
    assert requirement(report, "good communicator")["status"] == "candidate_confirmed"
    assert requirement(report, "DNS, SPF", "preferred")["status"] == "not_possessed"
    assert report["requirements"]["work_style"][-1]["status"] == "unverified"
    assert report["score"] > score_before and report["evidence_strength"]["essential"]["candidate_statement"] >= 2
    assert report["candidate_answers"]["not_possessed"] == 1

    # 3. Regenerate: a new draft; the first one is unchanged.
    second = generate(api_client, profile_id, job_id).json()
    assert second["id"] != first["id"]
    assert api_client.get(f"{API}/{profile_id}/cv-drafts/{first['id']}").json()["generated_content"] == first["generated_content"]
    text = second["generated_content"]
    assert "Built rapport with members on phone calls" in text
    assert "Technical communication" in text and "Help Scout" in text
    assert "SPF and DKIM" not in text and "Sense of urgency" not in text and "low ego" not in text
    references = {(ref["source_type"], ref["source_field"]) for ref in second["source_references"]}
    assert ("skill_confirmation", "example") in references and ("skill_confirmation", "skill_name") in references
    review = api_client.get(f"{API}/{profile_id}/cv-drafts/{second['id']}/review").json()
    assert {entry["proposed"] for entry in review["from_confirmations"]} >= {"Technical communication", "Help Scout"}
    assert second["status"] == "needs_review"  # two bullets still: no invented ones

    # 4. Export policy: an incomplete draft needs explicit approval as incomplete.
    export_url = f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/{second['id']}/exports"
    assert api_client.post(export_url, json={"export_format": "pdf"}).status_code == 409
    refused = api_client.post(f"{API}/{profile_id}/cv-drafts/{second['id']}/approval", json={})
    assert refused.status_code == 409 and "incomplete" in refused.json()["detail"]
    approved = api_client.post(f"{API}/{profile_id}/cv-drafts/{second['id']}/approval", json={"acknowledge_incomplete": True})
    assert approved.status_code == 200 and approved.json()["structured_content"]["review"]["acknowledged_incomplete"] is True
    pdf = api_client.post(export_url, json={"export_format": "pdf"})
    docx = api_client.post(export_url, json={"export_format": "docx"})
    assert pdf.status_code == 201 and docx.status_code == 201, (pdf.text, docx.text)
    pdf_bytes = api_client.get(f"{export_url}/{pdf.json()['id']}/download")
    docx_bytes = api_client.get(f"{export_url}/{docx.json()['id']}/download")
    assert pdf_bytes.headers["content-type"] == "application/pdf" and pdf_bytes.content.startswith(b"%PDF")
    pdf_text = "".join(page.get_text() for page in pymupdf.open(stream=pdf_bytes.content, filetype="pdf"))
    assert "Built rapport with members" in pdf_text and "Professional Experience" in pdf_text
    document = Document(BytesIO(docx_bytes.content))
    docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Technical communication" in docx_text and "Tourism Fund" in docx_text

    # 5. The approved draft is linked to a tracked application, which is not marked submitted.
    application = api_client.post(f"{API}/{profile_id}/applications",
                                  json={"job_description_id": job_id, "status": "preparing", "cv_draft_id": second["id"]})
    assert application.status_code == 201, application.text
    assert application.json()["cv_draft_id"] == second["id"] and application.json()["status"] == "preparing"

    # 6. Withdrawing an answer stops it being used; it is kept for history.
    withdrawn = api_client.post(f"{API}/{profile_id}/skill-confirmations/{has['id']}/withdraw")
    assert withdrawn.json()["status"] == "withdrawn"
    third = generate(api_client, profile_id, job_id).json()
    assert "Technical communication" not in third["generated_content"]
    history = api_client.get(f"{API}/{profile_id}/skill-confirmations", params={"include_withdrawn": True}).json()
    assert {item["id"] for item in history} >= {has["id"], no["id"]}
    # The earlier export no longer validates against a withdrawn statement.
    assert api_client.post(export_url, json={"export_format": "pdf"}).status_code == 409


def test_confirmations_are_validated_and_private_to_their_profile(api_client: TestClient, database) -> None:
    profile_id, job_id, role_id = setup(api_client, database[1])
    other_id, other_job, other_role = setup(api_client, database[1])
    key = requirement(ats(api_client, profile_id, job_id), "You build rapport fast")["key"]

    def post(pid, **body):
        return api_client.post(f"{API}/{pid}/skill-confirmations", json={"skill_name": "Rapport", "category": "communication", **body})

    assert post(profile_id, job_description_id=job_id, requirement_key=key, response="used_in_role").status_code == 422  # no example
    assert post(profile_id, job_description_id=job_id, requirement_key="0" * 16, response="has_skill").status_code == 422
    assert post(profile_id, job_description_id=other_job, requirement_key=key, response="has_skill").status_code == 404
    assert post(profile_id, job_description_id=job_id, requirement_key=key, response="used_in_role",
                work_experience_id=other_role, example="Built rapport with customers on daily support calls.").status_code == 422
    assert post(profile_id, response="not_possessed").status_code == 422  # needs a requirement
    created = post(profile_id, job_description_id=job_id, requirement_key=key, response="has_skill")
    assert created.status_code == 201
    duplicate = post(profile_id, job_description_id=job_id, requirement_key=key, response="unsure")
    assert duplicate.status_code == 409 and duplicate.json()["detail"]["confirmation_id"] == created.json()["id"]
    item_id = created.json()["id"]
    # Another profile cannot read, edit or withdraw it, and never sees it.
    assert api_client.get(f"{API}/{other_id}/skill-confirmations").json() == []
    assert api_client.put(f"{API}/{other_id}/skill-confirmations/{item_id}",
                          json={"skill_name": "X", "category": "other", "response": "has_skill"}).status_code == 404
    assert api_client.post(f"{API}/{other_id}/skill-confirmations/{item_id}/withdraw").status_code == 404
    assert requirement(ats(api_client, other_id, other_job), "You build rapport fast")["status"] == "missing"
    # Editing keeps one answer per requirement.
    edited = api_client.put(f"{API}/{profile_id}/skill-confirmations/{item_id}", json={
        "skill_name": "Rapport", "category": "communication", "response": "used_in_role", "work_experience_id": role_id,
        "example": "Built rapport with members on daily support calls and email."})
    assert edited.status_code == 200 and edited.json()["response"] == "used_in_role"


def test_confirmation_routes_require_a_session(unauthenticated_client: TestClient) -> None:
    assert unauthenticated_client.get(f"{API}/00000000-0000-0000-0000-000000000000/skill-confirmations").status_code == 401
