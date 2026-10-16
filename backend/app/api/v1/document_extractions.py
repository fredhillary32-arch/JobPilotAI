from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import CandidateDocument, DocumentExtraction
from app.schemas.document_extraction import DocumentExtractionRead, ExtractedTextRead
from app.services.documents import (
    DocumentStorage,
    get_document_storage,
    is_candidate_source_document,
)
from app.services.extraction import ExtractionFailure, extract_document_text

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["document extraction"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def _get_document_or_404(
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


def _get_extraction_or_404(
    document_id: UUID,
    session: DatabaseSession,
) -> DocumentExtraction:
    extraction = session.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.source_document_id == document_id
        )
    )
    if extraction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document text extraction has not been run",
        )
    return extraction


@router.post(
    "/{profile_id}/documents/{document_id}/extraction",
    response_model=DocumentExtractionRead,
)
def run_document_extraction(
    profile_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
) -> DocumentExtraction:
    get_profile_or_404(session, profile_id)
    document = _get_document_or_404(profile_id, document_id, session)
    if not is_candidate_source_document(document.document_kind, document.provenance):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only candidate-uploaded source documents can be extracted",
        )
    try:
        outcome = extract_document_text(document, storage)
    except ExtractionFailure as exc:
        status_value = "failed"
        extracted_text = None
        character_count = 0
        error_category = exc.category
        extractor_version = "local-extractor/1"
    else:
        status_value = outcome.status
        extracted_text = outcome.extracted_text
        character_count = outcome.character_count
        error_category = outcome.error_category
        extractor_version = outcome.extractor_version

    extraction = session.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.source_document_id == document.id
        )
    )
    if extraction is None:
        extraction = DocumentExtraction(
            source_document_id=document.id,
            status=status_value,
            extracted_text=extracted_text,
            character_count=character_count,
            extractor_version=extractor_version,
            error_category=error_category,
        )
        session.add(extraction)
    else:
        extraction.status = status_value
        extraction.extracted_text = extracted_text
        extraction.character_count = character_count
        extraction.extractor_version = extractor_version
        extraction.error_category = error_category
    session.commit()
    session.refresh(extraction)
    return extraction


@router.get(
    "/{profile_id}/documents/{document_id}/extraction",
    response_model=DocumentExtractionRead,
)
def read_document_extraction(
    profile_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
) -> DocumentExtraction:
    get_profile_or_404(session, profile_id)
    _get_document_or_404(profile_id, document_id, session)
    return _get_extraction_or_404(document_id, session)


@router.get(
    "/{profile_id}/documents/{document_id}/extraction/text",
    response_model=ExtractedTextRead,
)
def read_extracted_text(
    profile_id: UUID,
    document_id: UUID,
    session: DatabaseSession,
) -> ExtractedTextRead:
    get_profile_or_404(session, profile_id)
    _get_document_or_404(profile_id, document_id, session)
    extraction = _get_extraction_or_404(document_id, session)
    return ExtractedTextRead(
        source_document_id=document_id,
        status=extraction.status,
        text=extraction.extracted_text,
        character_count=extraction.character_count,
    )
