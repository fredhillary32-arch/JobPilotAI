from io import BytesIO
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi.testclient import TestClient
import pytest

from app.services.documents import MAX_DOCUMENT_SIZE_BYTES

PDF_TYPE = "application/pdf"


def create_profile(api_client: TestClient) -> str:
    response = api_client.post(
        "/api/v1/candidate-profiles",
        json={"name": "Document Owner"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def upload_pdf(
    api_client: TestClient,
    profile_id: str,
    *,
    filename: str = "source-cv.pdf",
    content: bytes = b"%PDF-1.7\ncandidate CV",
    content_type: str = PDF_TYPE,
):
    return api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/documents",
        files={"file": (filename, content, content_type)},
        data={"document_kind": "source_cv"},
    )


def test_upload_list_metadata_and_download_preserve_original(
    api_client: TestClient,
    tmp_path: Path,
) -> None:
    profile_id = create_profile(api_client)
    original = b"%PDF-1.7\nunaltered source CV bytes"

    uploaded = upload_pdf(api_client, profile_id, content=original)

    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["document_kind"] == "source_cv"
    assert document["provenance"] == "candidate_uploaded"
    assert document["original_filename"] == "source-cv.pdf"
    assert document["size_bytes"] == len(original)
    assert document["sha256"] == sha256(original).hexdigest()
    assert "storage_key" not in document
    assert str(tmp_path) not in str(document)

    listed = api_client.get(f"/api/v1/candidate-profiles/{profile_id}/documents")
    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()] == [document["id"]]

    metadata = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents/{document['id']}"
    )
    assert metadata.status_code == 200
    assert metadata.json() == document

    download = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents/{document['id']}/download"
    )
    assert download.status_code == 200
    assert download.content == original
    assert download.headers["content-type"] == PDF_TYPE
    assert 'filename="source-cv.pdf"' in download.headers["content-disposition"]

    replacement_upload = upload_pdf(
        api_client,
        profile_id,
        filename="another-copy.pdf",
        content=b"%PDF-1.7\nnew version, not an overwrite",
    )
    assert replacement_upload.status_code == 201
    preserved_download = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents/{document['id']}/download"
    )
    assert preserved_download.content == original


def test_upload_rejects_unsupported_and_malformed_documents(
    api_client: TestClient,
) -> None:
    profile_id = create_profile(api_client)

    unsupported = upload_pdf(api_client, profile_id, filename="candidate.doc")
    mismatched = upload_pdf(
        api_client,
        profile_id,
        filename="candidate.pdf",
        content_type="text/plain",
    )
    invalid_pdf = upload_pdf(
        api_client,
        profile_id,
        content=b"not a PDF document",
    )
    empty = upload_pdf(api_client, profile_id, content=b"")

    assert unsupported.status_code == 415
    assert mismatched.status_code == 415
    assert invalid_pdf.status_code == 415
    assert empty.status_code == 422
    assert api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents"
    ).json() == []


def test_upload_enforces_maximum_size(api_client: TestClient) -> None:
    profile_id = create_profile(api_client)

    response = upload_pdf(
        api_client,
        profile_id,
        content=b"%PDF-" + b"x" * MAX_DOCUMENT_SIZE_BYTES,
    )

    assert response.status_code == 413
    assert api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents"
    ).json() == []


def test_upload_requires_existing_profile(api_client: TestClient) -> None:
    response = upload_pdf(api_client, str(uuid4()))

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("notes.txt", "text/plain", b"UTF-8 candidate notes"),
        (
            "source.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            None,
        ),
    ],
)
def test_upload_accepts_supported_text_and_docx_files(
    api_client: TestClient,
    filename: str,
    content_type: str,
    content: bytes | None,
) -> None:
    profile_id = create_profile(api_client)
    if content is None:
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        content = buffer.getvalue()

    response = api_client.post(
        f"/api/v1/candidate-profiles/{profile_id}/documents",
        files={"file": (filename, content, content_type)},
        data={"document_kind": "supporting_document"},
    )

    assert response.status_code == 201
    assert response.json()["document_kind"] == "supporting_document"
    downloaded = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents/"
        f"{response.json()['id']}/download"
    )
    assert downloaded.content == content


def test_document_access_is_scoped_to_profile_and_handles_missing_file(
    api_client: TestClient,
) -> None:
    owner_id = create_profile(api_client)
    another_profile_id = create_profile(api_client)
    uploaded = upload_pdf(api_client, owner_id)
    document_id = uploaded.json()["id"]

    metadata = api_client.get(
        f"/api/v1/candidate-profiles/{another_profile_id}/documents/{document_id}"
    )
    download = api_client.get(
        f"/api/v1/candidate-profiles/{another_profile_id}/documents/"
        f"{document_id}/download"
    )
    missing = api_client.get(
        f"/api/v1/candidate-profiles/{owner_id}/documents/{uuid4()}"
    )

    assert metadata.status_code == 404
    assert download.status_code == 404
    assert missing.status_code == 404


def test_storage_rejects_path_traversal_and_detects_missing_file(
    api_client: TestClient,
    tmp_path: Path,
) -> None:
    from app.services.documents import DocumentStorageError, LocalDocumentStorage

    storage = LocalDocumentStorage(tmp_path / "private-documents")
    with pytest.raises(DocumentStorageError):
        storage.resolve("../outside.pdf")

    profile_id = create_profile(api_client)
    uploaded = upload_pdf(api_client, profile_id)
    document_id = uploaded.json()["id"]
    storage_root = tmp_path / "private-documents"
    stored_file = next(storage_root.iterdir())
    stored_file.unlink()

    missing_file = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/documents/{document_id}/download"
    )
    assert missing_file.status_code == 404
