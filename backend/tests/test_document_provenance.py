from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import CandidateDocument, CandidateEvidence, DocumentExtraction
from app.services.documents import is_candidate_source_document

API = "/api/v1/candidate-profiles"
GENERATED_TEXT = "Generated CV text: Automated the release pipeline checks for services."


def _create_profile(client: TestClient) -> str:
    response = client.post(API, json={"name": "Provenance Owner"})
    assert response.status_code == 201
    return response.json()["id"]


def _upload_source(client: TestClient, profile_id: str) -> dict:
    response = client.post(
        f"{API}/{profile_id}/documents",
        files={"file": ("source.txt", b"Synthetic source CV text.", "text/plain")},
        data={"document_kind": "source_cv"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _insert_generated_export_document(
    factory: sessionmaker[Session],
    profile_id: str,
    *,
    with_succeeded_extraction: bool = False,
) -> UUID:
    document_id = uuid4()
    with factory.begin() as session:
        session.add(
            CandidateDocument(
                id=document_id,
                candidate_profile_id=UUID(profile_id),
                document_kind="tailored_cv",
                provenance="system_generated",
                original_filename=f"jobpilot-cv-{uuid4().hex}.pdf",
                media_type="application/pdf",
                storage_key=f"{uuid4().hex}.pdf",
                size_bytes=1,
                sha256="0" * 64,
            )
        )
        if with_succeeded_extraction:
            session.flush()
            session.add(
                DocumentExtraction(
                    source_document_id=document_id,
                    status="succeeded",
                    extracted_text=GENERATED_TEXT,
                    character_count=len(GENERATED_TEXT),
                    extractor_version="legacy-test",
                    error_category=None,
                )
            )
    return document_id


@pytest.mark.parametrize(
    ("document_kind", "provenance", "expected"),
    [
        ("source_cv", "candidate_uploaded", True),
        ("supporting_document", "candidate_uploaded", True),
        ("tailored_cv", "system_generated", False),
        ("source_cv", "system_generated", False),
        ("tailored_cv", "candidate_uploaded", False),
        ("final_cv", "candidate_confirmed", False),
        ("application_document", "ai_generated", False),
    ],
)
def test_only_candidate_uploaded_source_kinds_are_source_documents(
    document_kind: str, provenance: str, expected: bool
) -> None:
    assert is_candidate_source_document(document_kind, provenance) is expected


def test_generated_export_cannot_be_extracted(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    profile_id = _create_profile(api_client)
    document_id = _insert_generated_export_document(factory, profile_id)

    response = api_client.post(f"{API}/{profile_id}/documents/{document_id}/extraction")

    assert response.status_code == 409
    assert response.json()["detail"] == ("Only candidate-uploaded source documents can be extracted")
    with factory() as session:
        assert (
            session.scalar(select(DocumentExtraction).where(DocumentExtraction.source_document_id == document_id))
            is None
        )


def test_generated_export_cannot_become_evidence_even_with_legacy_extraction(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    profile_id = _create_profile(api_client)
    document_id = _insert_generated_export_document(factory, profile_id, with_succeeded_extraction=True)

    response = api_client.post(
        f"{API}/{profile_id}/evidence",
        json={
            "source_document_id": str(document_id),
            "category": "achievement",
            "description": "Automated the release pipeline checks for services",
            "source_excerpt": "Automated the release pipeline checks for services.",
        },
    )

    assert response.status_code == 409
    assert "candidate-uploaded source documents" in response.json()["detail"]
    with factory() as session:
        assert session.scalars(select(CandidateEvidence)).all() == []


def test_source_documents_can_still_be_extracted_and_used_as_evidence(
    api_client: TestClient,
) -> None:
    profile_id = _create_profile(api_client)
    source = _upload_source(api_client, profile_id)

    extraction = api_client.post(f"{API}/{profile_id}/documents/{source['id']}/extraction")
    evidence = api_client.post(
        f"{API}/{profile_id}/evidence",
        json={
            "source_document_id": source["id"],
            "category": "achievement",
            "description": "Synthetic source CV text",
            "source_excerpt": "Synthetic source CV text.",
        },
    )

    assert extraction.status_code == 200
    assert extraction.json()["status"] == "succeeded"
    assert evidence.status_code == 201
    assert evidence.json()["confirmation_status"] == "unreviewed"


def test_document_list_can_separate_sources_from_generated_exports(
    api_client: TestClient,
    database: tuple[object, sessionmaker[Session]],
) -> None:
    _, factory = database
    profile_id = _create_profile(api_client)
    source = _upload_source(api_client, profile_id)
    generated_id = str(_insert_generated_export_document(factory, profile_id))

    def listed(query: str = "") -> list[str]:
        response = api_client.get(f"{API}/{profile_id}/documents{query}")
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()]

    assert sorted(listed()) == sorted([source["id"], generated_id])
    assert sorted(listed("?origin=all")) == sorted([source["id"], generated_id])
    assert listed("?origin=source") == [source["id"]]
    assert listed("?origin=generated") == [generated_id]
    assert api_client.get(f"{API}/{profile_id}/documents?origin=other").status_code == 422


def test_filtered_document_list_still_enforces_profile_ownership(
    api_client: TestClient,
) -> None:
    for origin in ("source", "generated"):
        response = api_client.get(f"{API}/{uuid4()}/documents?origin={origin}")
        assert response.status_code == 404
