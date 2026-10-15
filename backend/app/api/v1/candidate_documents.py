from http import HTTPStatus
from pathlib import PurePath, PureWindowsPath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateDocument
from app.schemas.candidate_document import CandidateDocumentRead, DocumentKind
from app.services.documents import (
    DocumentStorage,
    DocumentStorageError,
    DocumentTooLargeError,
    DocumentValidationError,
    EmptyDocumentError,
    get_document_storage,
    validate_document,
)

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["candidate documents"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def _safe_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            detail="A filename is required",
        )
    name = PureWindowsPath(filename).name
    name = PurePath(name).name.strip()
    if not name or len(name) > 255 or any(ord(character) < 32 for character in name):
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            detail="Invalid filename",
        )
    return name


@router.post(
    "/{profile_id}/documents",
    response_model=CandidateDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_candidate_document(
    profile_id: UUID,
    session: DatabaseSession,
    document_storage: Annotated[DocumentStorage, Depends(get_document_storage)],
    file: UploadFile = File(...),
    document_kind: DocumentKind = Form(default="source_cv"),
) -> CandidateDocument:
    get_profile_or_404(session, profile_id)
    filename = _safe_filename(file.filename)
    try:
        suffix, media_type = validate_document(
            file.file,
            filename=filename,
            declared_media_type=file.content_type or "",
        )
        stored = document_storage.store(file.file, suffix=suffix)
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=HTTPStatus.CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except EmptyDocumentError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except DocumentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    document = CandidateDocument(
        candidate_profile_id=profile_id,
        document_kind=document_kind,
        provenance="candidate_uploaded",
        original_filename=filename,
        media_type=media_type,
        storage_key=stored.storage_key,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
    )
    session.add(document)
    try:
        session.commit()
        session.refresh(document)
    except SQLAlchemyError:
        session.rollback()
        document_storage.remove(stored.storage_key)
        raise
    return document


@router.get(
    "/{profile_id}/documents",
    response_model=list[CandidateDocumentRead],
)
def list_candidate_documents(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateDocument]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateDocument)
            .where(CandidateDocument.candidate_profile_id == profile_id)
            .order_by(CandidateDocument.created_at.desc())
        )
    )


@router.get(
    "/{profile_id}/documents/{document_id}",
    response_model=CandidateDocumentRead,
)
def read_candidate_document(
    profile_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
) -> CandidateDocument:
    document = session.scalar(
        select(CandidateDocument).where(
            CandidateDocument.id == document_id,
            CandidateDocument.candidate_profile_id == profile_id,
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate document not found",
        )
    return document


@router.get(
    "/{profile_id}/documents/{document_id}/download",
    response_class=FileResponse,
    response_model=None,
)
def download_candidate_document(
    profile_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
    document_storage: Annotated[DocumentStorage, Depends(get_document_storage)],
) -> FileResponse:
    document = read_candidate_document(profile_id, document_id, session)
    try:
        path = document_storage.resolve(document.storage_key)
    except DocumentStorageError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate document file not found",
        ) from None
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate document file not found",
        )
    return FileResponse(
        path,
        media_type=document.media_type,
        filename=document.original_filename,
    )
