from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.db import DatabaseSession
from app.models import CandidateDocument, CandidateEvidence, DocumentExtraction
from app.schemas.candidate_evidence import (
    CandidateEvidenceCreate,
    CandidateEvidenceRead,
    CandidateEvidenceUpdate,
)
from app.services.extraction import MAX_EXTRACTED_CHARACTERS

router = APIRouter(prefix="/candidate-profiles", tags=["candidate evidence"])


def _get_evidence_or_404(
    profile_id: UUID,
    evidence_id: UUID,
    session: DatabaseSession,
) -> CandidateEvidence:
    evidence = session.scalar(
        select(CandidateEvidence).where(
            CandidateEvidence.id == evidence_id,
            CandidateEvidence.candidate_profile_id == profile_id,
        )
    )
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate evidence not found",
        )
    return evidence


def _get_usable_extraction(
    document_id: UUID,
    session: DatabaseSession,
) -> DocumentExtraction:
    extraction = session.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.source_document_id == document_id
        )
    )
    if extraction is None or extraction.status != "succeeded" or not extraction.extracted_text:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Successful text extraction is required before adding evidence",
        )
    return extraction


def _validate_and_locate_source(
    *,
    text: str,
    source_excerpt: str | None,
    source_start: int | None,
    source_end: int | None,
) -> tuple[str, int, int]:
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Extracted text is outside the supported evidence size",
        )
    if source_start is not None and source_end is not None:
        if source_end <= source_start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="source_end must be greater than source_start",
            )
        if source_end > len(text):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Evidence offsets are outside the extracted text",
            )
        selected = text[source_start:source_end]
        if not selected.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Evidence source reference must select text",
            )
        if source_excerpt is not None and source_excerpt != selected:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Source excerpt does not match the referenced text",
            )
        return selected, source_start, source_end
    if source_excerpt is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A source excerpt or source offsets are required",
        )
    start = text.find(source_excerpt)
    if start < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Source excerpt does not occur in extracted text",
        )
    return source_excerpt, start, start + len(source_excerpt)


@router.get("/{profile_id}/evidence", response_model=list[CandidateEvidenceRead])
def list_candidate_evidence(
    profile_id: UUID,
    session: DatabaseSession,
) -> list[CandidateEvidence]:
    get_profile_or_404(session, profile_id)
    return list(
        session.scalars(
            select(CandidateEvidence)
            .where(CandidateEvidence.candidate_profile_id == profile_id)
            .order_by(CandidateEvidence.created_at.desc())
        )
    )


@router.post(
    "/{profile_id}/evidence",
    response_model=CandidateEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate_evidence(
    profile_id: UUID,
    payload: CandidateEvidenceCreate,
    session: DatabaseSession,
) -> CandidateEvidence:
    get_profile_or_404(session, profile_id)
    document = session.scalar(
        select(CandidateDocument).where(
            CandidateDocument.id == payload.source_document_id,
            CandidateDocument.candidate_profile_id == profile_id,
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source document not found for candidate profile",
        )
    extraction = _get_usable_extraction(document.id, session)
    excerpt, start, end = _validate_and_locate_source(
        text=extraction.extracted_text or "",
        source_excerpt=payload.source_excerpt,
        source_start=payload.source_start,
        source_end=payload.source_end,
    )
    evidence = CandidateEvidence(
        candidate_profile_id=profile_id,
        source_document_id=document.id,
        category=payload.category,
        description=payload.description,
        source_excerpt=excerpt,
        source_start=start,
        source_end=end,
        source_section=payload.source_section,
        confirmation_status="unreviewed",
    )
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


@router.get(
    "/{profile_id}/evidence/{evidence_id}",
    response_model=CandidateEvidenceRead,
)
def read_candidate_evidence(
    profile_id: UUID,
    evidence_id: UUID,
    session: DatabaseSession,
) -> CandidateEvidence:
    get_profile_or_404(session, profile_id)
    return _get_evidence_or_404(profile_id, evidence_id, session)


@router.patch(
    "/{profile_id}/evidence/{evidence_id}",
    response_model=CandidateEvidenceRead,
)
def update_candidate_evidence(
    profile_id: UUID,
    evidence_id: UUID,
    payload: CandidateEvidenceUpdate,
    session: DatabaseSession,
) -> CandidateEvidence:
    get_profile_or_404(session, profile_id)
    evidence = _get_evidence_or_404(profile_id, evidence_id, session)
    changes = payload.model_dump(exclude_unset=True)
    extraction = _get_usable_extraction(evidence.source_document_id, session)

    new_excerpt = changes.get("source_excerpt", evidence.source_excerpt)
    new_start = changes.get("source_start", evidence.source_start)
    new_end = changes.get("source_end", evidence.source_end)
    if ("source_start" in changes) != ("source_end" in changes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="source_start and source_end must be updated together",
        )
    if any(key in changes for key in ("source_excerpt", "source_start", "source_end")):
        excerpt, start, end = _validate_and_locate_source(
            text=extraction.extracted_text or "",
            source_excerpt=new_excerpt,
            source_start=new_start,
            source_end=new_end,
        )
        changes.update(
            source_excerpt=excerpt,
            source_start=start,
            source_end=end,
        )
    for field_name, value in changes.items():
        setattr(evidence, field_name, value)
    session.commit()
    session.refresh(evidence)
    return evidence


@router.delete(
    "/{profile_id}/evidence/{evidence_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_candidate_evidence(
    profile_id: UUID,
    evidence_id: UUID,
    session: DatabaseSession,
) -> Response:
    get_profile_or_404(session, profile_id)
    evidence = _get_evidence_or_404(profile_id, evidence_id, session)
    session.delete(evidence)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
