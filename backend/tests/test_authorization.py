from datetime import date, timedelta
import importlib
import pkgutil
import re
import secrets
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import app.api.v1 as api_v1_package
from app.main import app
from app.models import (
    CandidateCertification,
    CandidateDocument,
    CandidateEducation,
    CandidateEvidence,
    CandidateJobDescription,
    CandidateProfile,
    CandidateSkill,
    DocumentExtraction,
    TailoredCvDraft,
    TailoredCvExport,
)
from app.models.candidate_profile import CandidateWorkExperience
from app.models.user import AuthSession, User
from app.services.auth import hash_token, utc_now
from app.services.documents import DocumentStorageError, LocalDocumentStorage

API = "/api/v1/candidate-profiles"


def _create_foreign_resources(factory: sessionmaker[Session]) -> dict[str, UUID]:
    ids = {
        "owner_profile": uuid4(),
        "foreign_profile": uuid4(),
        "legacy_profile": uuid4(),
        "experience": uuid4(),
        "document": uuid4(),
        "evidence": uuid4(),
        "job": uuid4(),
        "draft": uuid4(),
        "export_document": uuid4(),
        "export": uuid4(),
    }
    with factory.begin() as session:
        other_user = User(
            email="other-owner@example.com",
            password_hash="$argon2id$test-fixture",
        )
        session.add(other_user)
        session.flush()
        session.add_all(
            [
                CandidateProfile(
                    id=ids["owner_profile"],
                    name="Owned synthetic profile",
                    user_id=session.scalar(
                        select(User.id).where(User.email == "test-owner@example.com")
                    ),
                ),
                CandidateProfile(
                    id=ids["foreign_profile"],
                    name="Foreign synthetic profile",
                    user_id=other_user.id,
                ),
                CandidateProfile(
                    id=ids["legacy_profile"],
                    name="Unassigned synthetic profile",
                    user_id=None,
                ),
                CandidateWorkExperience(
                    id=ids["experience"],
                    candidate_profile_id=ids["foreign_profile"],
                    employer="Synthetic employer",
                    job_title="Synthetic role",
                    start_date=date(2020, 1, 1),
                    current_role=True,
                    achievements=[],
                ),
                CandidateDocument(
                    id=ids["document"],
                    candidate_profile_id=ids["foreign_profile"],
                    document_kind="source_cv",
                    provenance="candidate_uploaded",
                    original_filename="synthetic-source.txt",
                    media_type="text/plain",
                    storage_key=f"{uuid4().hex}.txt",
                    size_bytes=1,
                    sha256="0" * 64,
                ),
                CandidateJobDescription(
                    id=ids["job"],
                    candidate_profile_id=ids["foreign_profile"],
                    job_title="Synthetic job",
                    description="Synthetic job description",
                ),
                CandidateDocument(
                    id=ids["export_document"],
                    candidate_profile_id=ids["foreign_profile"],
                    document_kind="tailored_cv",
                    provenance="system_generated",
                    original_filename=f"jobpilot-cv-{uuid4().hex}.pdf",
                    media_type="application/pdf",
                    storage_key=f"{uuid4().hex}.pdf",
                    size_bytes=1,
                    sha256="1" * 64,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                DocumentExtraction(
                    source_document_id=ids["document"],
                    status="failed",
                    extracted_text=None,
                    character_count=0,
                    extractor_version="test",
                    error_category="missing_file",
                ),
                CandidateEvidence(
                    id=ids["evidence"],
                    candidate_profile_id=ids["foreign_profile"],
                    source_document_id=ids["document"],
                    category="project",
                    description="Synthetic evidence",
                    source_excerpt="x",
                    source_start=0,
                    source_end=1,
                    confirmation_status="unreviewed",
                ),
                TailoredCvDraft(
                    id=ids["draft"],
                    candidate_profile_id=ids["foreign_profile"],
                    job_description_id=ids["job"],
                    status="failed",
                    generated_content=None,
                    structured_content=None,
                    validation_results={"errors": ["synthetic"]},
                    source_references=[],
                ),
            ]
        )
        session.flush()
        session.add(
            TailoredCvExport(
                id=ids["export"],
                candidate_profile_id=ids["foreign_profile"],
                cv_draft_id=ids["draft"],
                document_id=ids["export_document"],
                export_format="pdf",
            )
        )
    return ids


def test_anonymous_requests_are_rejected_for_each_resource_family(
    unauthenticated_client: TestClient,
) -> None:
    profile_id, document_id, job_id, draft_id, export_id = (
        str(uuid4()) for _ in range(5)
    )
    requests = [
        ("GET", API),
        ("GET", f"{API}/{profile_id}"),
        ("POST", API),
        ("GET", f"{API}/{profile_id}/experiences"),
        ("POST", f"{API}/{profile_id}/experiences", {"json": {}}),
        ("PATCH", f"{API}/{profile_id}/experiences/{document_id}", {"json": {}}),
        ("DELETE", f"{API}/{profile_id}/experiences/{document_id}"),
        ("GET", f"{API}/{profile_id}/education"),
        ("POST", f"{API}/{profile_id}/education", {"json": {}}),
        ("GET", f"{API}/{profile_id}/skills"),
        ("POST", f"{API}/{profile_id}/skills", {"json": {}}),
        ("GET", f"{API}/{profile_id}/certifications"),
        ("POST", f"{API}/{profile_id}/certifications", {"json": {}}),
        ("GET", f"{API}/{profile_id}/documents"),
        (
            "POST",
            f"{API}/{profile_id}/documents",
            {"files": {"file": ("synthetic.txt", b"synthetic", "text/plain")}},
        ),
        ("GET", f"{API}/{profile_id}/documents/{document_id}"),
        ("GET", f"{API}/{profile_id}/documents/{document_id}/download"),
        ("POST", f"{API}/{profile_id}/documents/{document_id}/extraction"),
        ("GET", f"{API}/{profile_id}/documents/{document_id}/extraction"),
        ("GET", f"{API}/{profile_id}/documents/{document_id}/extraction/text"),
        ("GET", f"{API}/{profile_id}/evidence"),
        ("POST", f"{API}/{profile_id}/evidence", {"json": {}}),
        ("PATCH", f"{API}/{profile_id}/evidence/{document_id}", {"json": {}}),
        ("DELETE", f"{API}/{profile_id}/evidence/{document_id}"),
        ("GET", f"{API}/{profile_id}/job-descriptions"),
        ("POST", f"{API}/{profile_id}/job-descriptions", {"json": {}}),
        ("GET", f"{API}/{profile_id}/job-descriptions/{job_id}"),
        (
            "POST",
            f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts",
        ),
        ("GET", f"{API}/{profile_id}/cv-drafts"),
        ("GET", f"{API}/{profile_id}/cv-drafts/{draft_id}"),
        (
            "GET",
            f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports",
        ),
        (
            "GET",
            f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports/{export_id}/download",
        ),
        (
            "POST",
            f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports",
            {"json": {}},
        ),
    ]

    for request_spec in requests:
        method, path, *kwargs_args = request_spec
        response = unauthenticated_client.request(
            method,
            path,
            **(kwargs_args[0] if kwargs_args else {}),
        )
        assert response.status_code == 401, (method, path, response.text)


PUBLIC_API_ROUTES = {
    ("GET", "/api/v1/auth/pre-auth-csrf"),
    ("POST", "/api/v1/auth/login"),
}


def test_every_registered_api_route_requires_a_session_except_documented_exceptions(
    unauthenticated_client: TestClient,
) -> None:
    checked: list[tuple[str, str]] = []
    for module_info in pkgutil.iter_modules(api_v1_package.__path__):
        module = importlib.import_module(f"{api_v1_package.__name__}.{module_info.name}")
        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            continue
        for route in router.routes:
            assert isinstance(route, APIRoute)
            path = f"/api/v1{route.path}"
            for method in sorted(route.methods):
                if (method, path) in PUBLIC_API_ROUTES:
                    continue
                concrete_path = re.sub(r"\{[^}]+\}", str(uuid4()), path)
                response = unauthenticated_client.request(method, concrete_path)
                assert response.status_code == 401, (method, path, response.status_code)
                checked.append((method, path))

    assert ("GET", API) in checked
    assert ("POST", "/api/v1/auth/logout") in checked
    assert len(checked) >= 40


def test_owned_profile_creation_derives_owner_from_session(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    response = api_client.post(API, json={"name": "Synthetic owned profile"})
    assert response.status_code == 201

    _, factory = database
    with factory() as session:
        profile = session.get(CandidateProfile, UUID(response.json()["id"]))
        user = session.query(User).filter_by(email="test-owner@example.com").one()
        assert profile is not None
        assert profile.user_id == user.id


def test_profile_list_contains_only_profiles_owned_by_the_session_user(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    ids = _create_foreign_resources(factory)
    created = api_client.post(API, json={"name": "Second owned profile"})
    assert created.status_code == 201

    response = api_client.get(API)

    assert response.status_code == 200
    listed_ids = {item["id"] for item in response.json()}
    assert listed_ids == {str(ids["owner_profile"]), created.json()["id"]}
    assert str(ids["foreign_profile"]) not in listed_ids
    assert str(ids["legacy_profile"]) not in listed_ids


def test_candidate_mutations_require_session_csrf_and_exact_origin(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    csrf_token = api_client.headers["X-CSRF-Token"]
    api_client.headers["X-CSRF-Token"] = ""
    missing_csrf = api_client.post(API, json={"name": "Must not be created"})
    api_client.headers["X-CSRF-Token"] = "invalid-csrf-token"
    invalid_csrf = api_client.post(API, json={"name": "Must not be created"})
    api_client.headers["X-CSRF-Token"] = csrf_token

    api_client.headers["Origin"] = "http://attacker.invalid"
    invalid_origin = api_client.post(API, json={"name": "Must not be created"})

    assert missing_csrf.status_code == 403
    assert invalid_csrf.status_code == 403
    assert invalid_origin.status_code == 403
    with factory() as session:
        assert session.query(CandidateProfile).count() == 0


def test_every_resource_router_checks_origin_and_csrf_before_mutation(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    profile_id, record_id, document_id, job_id, draft_id = (
        str(uuid4()) for _ in range(5)
    )
    csrf_token = api_client.headers["X-CSRF-Token"]
    requests = [
        ("POST", API, {"json": {"name": "Synthetic"}}),
        (
            "PATCH",
            f"{API}/{profile_id}",
            {"json": {"name": "Synthetic"}},
        ),
        (
            "POST",
            f"{API}/{profile_id}/experiences",
            {
                "json": {
                    "employer": "Synthetic",
                    "job_title": "Synthetic",
                    "start_date": "2020-01-01",
                }
            },
        ),
        (
            "PATCH",
            f"{API}/{profile_id}/experiences/{record_id}",
            {"json": {"employer": "Synthetic"}},
        ),
        ("DELETE", f"{API}/{profile_id}/experiences/{record_id}", {}),
        (
            "POST",
            f"{API}/{profile_id}/education",
            {
                "json": {
                    "institution": "Synthetic",
                    "qualification": "Synthetic",
                    "start_date": "2020-01-01",
                }
            },
        ),
        (
            "POST",
            f"{API}/{profile_id}/skills",
            {"json": {"name": "Synthetic"}},
        ),
        (
            "POST",
            f"{API}/{profile_id}/certifications",
            {
                "json": {
                    "name": "Synthetic",
                    "issuer": "Synthetic",
                    "issue_date": "2020-01-01",
                }
            },
        ),
        (
            "POST",
            f"{API}/{profile_id}/documents",
            {"files": {"file": ("synthetic.txt", b"synthetic", "text/plain")}},
        ),
        (
            "POST",
            f"{API}/{profile_id}/documents/{document_id}/extraction",
            {},
        ),
        (
            "POST",
            f"{API}/{profile_id}/evidence",
            {
                "json": {
                    "source_document_id": document_id,
                    "category": "project",
                    "description": "Synthetic evidence",
                    "source_excerpt": "synthetic",
                }
            },
        ),
        (
            "PATCH",
            f"{API}/{profile_id}/evidence/{record_id}",
            {"json": {"confirmation_status": "rejected"}},
        ),
        ("DELETE", f"{API}/{profile_id}/evidence/{record_id}", {}),
        (
            "POST",
            f"{API}/{profile_id}/job-descriptions",
            {"json": {"job_title": "Synthetic", "description": "Synthetic"}},
        ),
        (
            "POST",
            f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts",
            {},
        ),
        (
            "POST",
            f"{API}/{profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports",
            {"json": {"export_format": "pdf"}},
        ),
    ]

    for method, path, kwargs in requests:
        api_client.headers["Origin"] = "http://attacker.invalid"
        api_client.headers["X-CSRF-Token"] = csrf_token
        wrong_origin = api_client.request(method, path, **kwargs)
        api_client.headers["Origin"] = "http://127.0.0.1:5173"
        api_client.headers["X-CSRF-Token"] = ""
        missing_csrf = api_client.request(method, path, **kwargs)
        api_client.headers["X-CSRF-Token"] = csrf_token

        assert wrong_origin.status_code == 403, (method, path, wrong_origin.text)
        assert missing_csrf.status_code == 403, (method, path, missing_csrf.text)

    with factory() as session:
        assert session.query(CandidateProfile).count() == 0


def test_two_authenticated_users_cannot_read_change_or_delete_each_others_data(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = database
    owned_response = api_client.post(API, json={"name": "First synthetic profile"})
    assert owned_response.status_code == 201
    owned_profile_id = UUID(owned_response.json()["id"])
    document_id = uuid4()
    experience_id = uuid4()
    education_id = uuid4()
    skill_id = uuid4()
    certification_id = uuid4()
    evidence_id = uuid4()
    job_id = uuid4()
    draft_id = uuid4()
    export_document_id = uuid4()
    export_id = uuid4()
    now = utc_now()
    other_session_token = secrets.token_urlsafe(32)
    other_csrf_token = secrets.token_urlsafe(32)
    with factory.begin() as session:
        other_user = User(
            email="second-owner@example.com",
            password_hash="$argon2id$test-fixture",
        )
        session.add(other_user)
        session.flush()
        other_profile = CandidateProfile(
            name="Second synthetic profile",
            user_id=other_user.id,
        )
        session.add(other_profile)
        session.flush()
        other_profile_id = other_profile.id
        session.add(
            CandidateDocument(
                id=document_id,
                candidate_profile_id=owned_profile_id,
                document_kind="source_cv",
                provenance="candidate_uploaded",
                original_filename="synthetic.txt",
                media_type="text/plain",
                storage_key=f"{uuid4().hex}.txt",
                size_bytes=1,
                sha256="0" * 64,
            )
        )
        session.add(
            CandidateWorkExperience(
                id=experience_id,
                candidate_profile_id=owned_profile_id,
                employer="Synthetic employer",
                job_title="Synthetic role",
                start_date=date(2020, 1, 1),
                current_role=True,
                achievements=[],
            )
        )
        session.add_all(
            [
                CandidateEducation(
                    id=education_id,
                    candidate_profile_id=owned_profile_id,
                    institution="Synthetic institute",
                    qualification="Synthetic qualification",
                    start_date=date(2020, 1, 1),
                ),
                CandidateSkill(
                    id=skill_id,
                    candidate_profile_id=owned_profile_id,
                    name="Synthetic skill",
                ),
                CandidateCertification(
                    id=certification_id,
                    candidate_profile_id=owned_profile_id,
                    name="Synthetic certification",
                    issuer="Synthetic issuer",
                    issue_date=date(2020, 1, 1),
                ),
                CandidateJobDescription(
                    id=job_id,
                    candidate_profile_id=owned_profile_id,
                    job_title="Synthetic job",
                    description="Synthetic job description",
                ),
                CandidateDocument(
                    id=export_document_id,
                    candidate_profile_id=owned_profile_id,
                    document_kind="tailored_cv",
                    provenance="system_generated",
                    original_filename=f"jobpilot-cv-{uuid4().hex}.pdf",
                    media_type="application/pdf",
                    storage_key=f"{uuid4().hex}.pdf",
                    size_bytes=1,
                    sha256="1" * 64,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                DocumentExtraction(
                    source_document_id=document_id,
                    status="succeeded",
                    extracted_text="Synthetic evidence source text",
                    character_count=len("Synthetic evidence source text"),
                    extractor_version="test",
                ),
                CandidateEvidence(
                    id=evidence_id,
                    candidate_profile_id=owned_profile_id,
                    source_document_id=document_id,
                    category="project",
                    description="Synthetic evidence",
                    source_excerpt="Synthetic",
                    source_start=0,
                    source_end=9,
                    confirmation_status="candidate_confirmed",
                ),
                TailoredCvDraft(
                    id=draft_id,
                    candidate_profile_id=owned_profile_id,
                    job_description_id=job_id,
                    status="generated",
                    generated_content="Synthetic CV content",
                    structured_content={},
                    validation_results={},
                    source_references=[],
                ),
            ]
        )
        session.flush()
        session.add(
            TailoredCvExport(
                id=export_id,
                candidate_profile_id=owned_profile_id,
                cv_draft_id=draft_id,
                document_id=export_document_id,
                export_format="pdf",
            )
        )
        session.add(
            AuthSession(
                user_id=other_user.id,
                token_hash=hash_token(other_session_token),
                csrf_token_hash=hash_token(other_csrf_token),
                created_at=now,
                last_seen_at=now,
                idle_expires_at=now + timedelta(hours=12),
                absolute_expires_at=now + timedelta(days=7),
            )
        )

    assert api_client.get(f"{API}/{other_profile_id}").status_code == 404
    api_client.cookies.clear()
    api_client.cookies.set(
        "jobpilot_session",
        other_session_token,
        domain="testserver.local",
        path="/",
    )
    api_client.headers["X-CSRF-Token"] = other_csrf_token

    assert api_client.get(f"{API}/{other_profile_id}").status_code == 200

    from app.services.documents import DocumentStorageError, LocalDocumentStorage

    resolved_keys: list[str] = []

    def forbid_storage_resolution(storage: LocalDocumentStorage, key: str):
        resolved_keys.append(key)
        raise DocumentStorageError("authorization must precede file resolution")

    monkeypatch.setattr(LocalDocumentStorage, "resolve", forbid_storage_resolution)
    requests = [
        ("GET", f"{API}/{owned_profile_id}"),
        ("PATCH", f"{API}/{owned_profile_id}", {"json": {"name": "Unauthorized"}}),
        ("GET", f"{API}/{owned_profile_id}/experiences"),
        ("GET", f"{API}/{owned_profile_id}/experiences/{experience_id}"),
        (
            "PATCH",
            f"{API}/{owned_profile_id}/experiences/{experience_id}",
            {"json": {"employer": "Unauthorized"}},
        ),
        ("DELETE", f"{API}/{owned_profile_id}/experiences/{experience_id}"),
        ("GET", f"{API}/{owned_profile_id}/education"),
        ("GET", f"{API}/{owned_profile_id}/education/{education_id}"),
        (
            "PATCH",
            f"{API}/{owned_profile_id}/education/{education_id}",
            {"json": {"institution": "Unauthorized"}},
        ),
        ("DELETE", f"{API}/{owned_profile_id}/education/{education_id}"),
        ("GET", f"{API}/{owned_profile_id}/skills"),
        ("GET", f"{API}/{owned_profile_id}/skills/{skill_id}"),
        (
            "PATCH",
            f"{API}/{owned_profile_id}/skills/{skill_id}",
            {"json": {"name": "Unauthorized"}},
        ),
        ("DELETE", f"{API}/{owned_profile_id}/skills/{skill_id}"),
        ("GET", f"{API}/{owned_profile_id}/certifications"),
        ("GET", f"{API}/{owned_profile_id}/certifications/{certification_id}"),
        (
            "PATCH",
            f"{API}/{owned_profile_id}/certifications/{certification_id}",
            {"json": {"name": "Unauthorized"}},
        ),
        ("DELETE", f"{API}/{owned_profile_id}/certifications/{certification_id}"),
        ("GET", f"{API}/{owned_profile_id}/documents"),
        ("GET", f"{API}/{owned_profile_id}/documents/{document_id}"),
        (
            "GET",
            f"{API}/{owned_profile_id}/documents/{document_id}/download",
        ),
        (
            "POST",
            f"{API}/{owned_profile_id}/documents/{document_id}/extraction",
        ),
        (
            "GET",
            f"{API}/{owned_profile_id}/documents/{document_id}/extraction",
        ),
        (
            "GET",
            f"{API}/{owned_profile_id}/documents/{document_id}/extraction/text",
        ),
        ("GET", f"{API}/{owned_profile_id}/evidence"),
        ("GET", f"{API}/{owned_profile_id}/evidence/{evidence_id}"),
        (
            "PATCH",
            f"{API}/{owned_profile_id}/evidence/{evidence_id}",
            {"json": {"confirmation_status": "rejected"}},
        ),
        ("DELETE", f"{API}/{owned_profile_id}/evidence/{evidence_id}"),
        ("GET", f"{API}/{owned_profile_id}/job-descriptions"),
        ("GET", f"{API}/{owned_profile_id}/job-descriptions/{job_id}"),
        (
            "POST",
            f"{API}/{owned_profile_id}/job-descriptions",
            {
                "json": {
                    "job_title": "Unauthorized job",
                    "description": "Unauthorized description",
                }
            },
        ),
        (
            "POST",
            f"{API}/{owned_profile_id}/job-descriptions/{job_id}/cv-drafts",
        ),
        ("GET", f"{API}/{owned_profile_id}/cv-drafts"),
        ("GET", f"{API}/{owned_profile_id}/cv-drafts/{draft_id}"),
        (
            "GET",
            f"{API}/{owned_profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports",
        ),
        (
            "POST",
            f"{API}/{owned_profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports",
            {"json": {"export_format": "pdf"}},
        ),
        (
            "GET",
            f"{API}/{owned_profile_id}/job-descriptions/{job_id}/cv-drafts/"
            f"{draft_id}/exports/{export_id}/download",
        ),
    ]
    for method, path, *kwargs_args in requests:
        response = api_client.request(
            method,
            path,
            **(kwargs_args[0] if kwargs_args else {}),
        )
        assert response.status_code == 404, (method, path, response.text)
    assert resolved_keys == []

    with factory() as session:
        owned_profile = session.get(CandidateProfile, owned_profile_id)
        assert owned_profile is not None
        assert owned_profile.name == "First synthetic profile"
        assert session.get(CandidateWorkExperience, experience_id) is not None
        assert session.get(CandidateEducation, education_id) is not None
        assert session.get(CandidateSkill, skill_id) is not None
        assert session.get(CandidateCertification, certification_id) is not None
        assert session.get(CandidateEvidence, evidence_id) is not None
        assert session.get(CandidateJobDescription, job_id) is not None
        assert session.get(TailoredCvDraft, draft_id) is not None
        assert session.get(TailoredCvExport, export_id) is not None


def test_foreign_and_unassigned_profiles_are_not_found_across_resource_chains(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    ids = _create_foreign_resources(factory)
    paths = [
        f"{API}/{{profile}}",
        f"{API}/{{profile}}/experiences",
        f"{API}/{{profile}}/education",
        f"{API}/{{profile}}/skills",
        f"{API}/{{profile}}/certifications",
        f"{API}/{{profile}}/documents",
        f"{API}/{{profile}}/documents/{ids['document']}",
        f"{API}/{{profile}}/documents/{ids['document']}/download",
        f"{API}/{{profile}}/documents/{ids['document']}/extraction",
        f"{API}/{{profile}}/documents/{ids['document']}/extraction/text",
        f"{API}/{{profile}}/evidence",
        f"{API}/{{profile}}/evidence/{ids['evidence']}",
        f"{API}/{{profile}}/job-descriptions",
        f"{API}/{{profile}}/job-descriptions/{ids['job']}",
        f"{API}/{{profile}}/cv-drafts",
        f"{API}/{{profile}}/cv-drafts/{ids['draft']}",
        (
            f"{API}/{{profile}}/job-descriptions/{ids['job']}/cv-drafts/"
            f"{ids['draft']}/exports"
        ),
        (
            f"{API}/{{profile}}/job-descriptions/{ids['job']}/cv-drafts/"
            f"{ids['draft']}/exports/{ids['export']}/download"
        ),
    ]
    for profile_name in ("foreign_profile", "legacy_profile"):
        for template in paths:
            response = api_client.get(
                template.format(profile=ids[profile_name])
            )
            assert response.status_code == 404, (template, response.text)
            assert response.json() == {"detail": "Candidate profile not found"}


def test_foreign_child_ids_and_mismatched_parent_ids_return_not_found(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    ids = _create_foreign_resources(factory)
    owned_profile = ids["owner_profile"]

    paths = [
        f"{API}/{owned_profile}/experiences/{ids['experience']}",
        f"{API}/{owned_profile}/documents/{ids['document']}",
        f"{API}/{owned_profile}/documents/{ids['document']}/extraction",
        f"{API}/{owned_profile}/evidence/{ids['evidence']}",
        f"{API}/{owned_profile}/job-descriptions/{ids['job']}",
        f"{API}/{owned_profile}/cv-drafts/{ids['draft']}",
        (
            f"{API}/{owned_profile}/job-descriptions/{ids['job']}/cv-drafts/"
            f"{ids['draft']}/exports/{ids['export']}/download"
        ),
    ]
    for path in paths:
        response = api_client.get(path)
        assert response.status_code == 404, (path, response.text)


def test_private_file_access_requires_auth_and_traversal_stays_inaccessible(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, factory = database
    foreign_ids = _create_foreign_resources(factory)
    profile_response = api_client.post(API, json={"name": "Synthetic file owner"})
    assert profile_response.status_code == 201
    profile_id = UUID(profile_response.json()["id"])
    document_id = uuid4()
    with factory.begin() as session:
        session.add(
            CandidateDocument(
                id=document_id,
                candidate_profile_id=profile_id,
                document_kind="source_cv",
                provenance="candidate_uploaded",
                original_filename="synthetic.txt",
                media_type="text/plain",
                storage_key="../outside.txt",
                size_bytes=1,
                sha256="0" * 64,
            )
        )

    resolved: list[str] = []

    def record_resolution(storage: LocalDocumentStorage, key: str):
        resolved.append(key)
        raise DocumentStorageError("invalid document storage key")

    monkeypatch.setattr(LocalDocumentStorage, "resolve", record_resolution)
    path = f"{API}/{profile_id}/documents/{document_id}/download"
    with TestClient(app) as anonymous_client:
        anonymous = anonymous_client.get(path)
        assert anonymous.status_code == 401
        assert resolved == []

    foreign_path = (
        f"{API}/{foreign_ids['foreign_profile']}/documents/"
        f"{foreign_ids['document']}/download"
    )
    foreign = api_client.get(foreign_path)
    assert foreign.status_code == 404
    assert resolved == []

    authorized = api_client.get(path)
    assert authorized.status_code == 404
    assert resolved == ["../outside.txt"]
