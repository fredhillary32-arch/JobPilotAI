from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import CandidateDocument, CandidateJobDescription
from app.request_limits import (
    DEFAULT_BODY_LIMIT_BYTES,
    UPLOAD_BODY_LIMIT_BYTES,
    body_limit_for,
)
from app.services.documents import MAX_DOCUMENT_SIZE_BYTES

API = "/api/v1/candidate-profiles"


def _profile(client: TestClient) -> str:
    response = client.post(API, json={"name": "Limit Tester"})
    assert response.status_code == 201
    return response.json()["id"]


def _count(database, model) -> int:
    _, factory = database
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model))


def test_upload_route_allows_a_full_size_document_plus_form_overhead() -> None:
    profile_path = "/api/v1/candidate-profiles/3f2a8c1e-0000-0000-0000-000000000000/documents"
    assert body_limit_for("POST", profile_path) == UPLOAD_BODY_LIMIT_BYTES > MAX_DOCUMENT_SIZE_BYTES
    assert body_limit_for("POST", "/api/v1/candidate-profiles") == DEFAULT_BODY_LIMIT_BYTES
    assert body_limit_for("GET", profile_path) == DEFAULT_BODY_LIMIT_BYTES


def test_declared_oversized_upload_is_refused_before_it_is_read(api_client: TestClient, database) -> None:
    profile_id = _profile(api_client)
    payload = b"x" * (UPLOAD_BODY_LIMIT_BYTES + 1)

    response = api_client.post(
        f"{API}/{profile_id}/documents",
        files={"file": ("huge.txt", payload, "text/plain")},
        data={"document_kind": "source_cv"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "The request body is too large."}
    assert _count(database, CandidateDocument) == 0


def test_streamed_body_without_a_declared_length_is_stopped_at_the_limit(api_client: TestClient, database) -> None:
    profile_id = _profile(api_client)

    def chunks() -> Iterator[bytes]:
        yield b'{"job_title": "Support", "description": "'
        for _ in range(DEFAULT_BODY_LIMIT_BYTES // 65_536 + 2):
            yield b"a" * 65_536
        yield b'"}'

    response = api_client.post(
        f"{API}/{profile_id}/job-descriptions",
        content=chunks(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert _count(database, CandidateJobDescription) == 0


def test_oversized_json_body_is_refused(api_client: TestClient, database) -> None:
    profile_id = _profile(api_client)

    response = api_client.post(
        f"{API}/{profile_id}/job-descriptions",
        json={"job_title": "Support", "description": "a" * (DEFAULT_BODY_LIMIT_BYTES + 10)},
    )

    assert response.status_code == 413
    assert _count(database, CandidateJobDescription) == 0


def test_normal_requests_are_unaffected(api_client: TestClient, database) -> None:
    profile_id = _profile(api_client)

    upload = api_client.post(
        f"{API}/{profile_id}/documents",
        files={"file": ("cv.txt", b"Synthetic CV text for limits.", "text/plain")},
        data={"document_kind": "source_cv"},
    )
    job = api_client.post(
        f"{API}/{profile_id}/job-descriptions",
        json={"job_title": "Support", "description": "a" * 50_000},
    )

    assert (upload.status_code, job.status_code) == (201, 201)
