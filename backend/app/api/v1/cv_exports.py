import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import (
    CandidateDocument,
    CandidateJobDescription,
    TailoredCvDraft,
    TailoredCvExport,
)
from app.schemas.cv_export import TailoredCvExportCreate, TailoredCvExportRead
from app.services.cv_export import (
    ExportFileUnavailable,
    InvalidDraftForExport,
    create_cv_export,
    load_export_file,
)
from app.services.documents import DocumentStorage, get_document_storage

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["CV exports"],
    dependencies=[Depends(require_authenticated_resource_access)],
)
GENERATED_FILENAME = re.compile(r"jobpilot-cv-[0-9a-f]{32}\.(?:pdf|docx)\Z")


def _get_related_draft(
    profile_id: UUID,
    job_id: UUID,
    draft_id: UUID,
    session: DatabaseSession,
) -> TailoredCvDraft:
    draft = session.scalar(
        select(TailoredCvDraft)
        .join(
            CandidateJobDescription,
            CandidateJobDescription.id == TailoredCvDraft.job_description_id,
        )
        .where(
            TailoredCvDraft.id == draft_id,
            TailoredCvDraft.candidate_profile_id == profile_id,
            CandidateJobDescription.id == job_id,
            CandidateJobDescription.candidate_profile_id == profile_id,
        )
    )
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV draft not found for the candidate profile and job description",
        )
    return draft


def _get_export(
    profile_id: UUID,
    job_id: UUID,
    draft_id: UUID,
    export_id: UUID,
    session: DatabaseSession,
) -> TailoredCvExport:
    _get_related_draft(profile_id, job_id, draft_id, session)
    result = session.scalar(
        select(TailoredCvExport)
        .options(joinedload(TailoredCvExport.document))
        .where(
            TailoredCvExport.id == export_id,
            TailoredCvExport.candidate_profile_id == profile_id,
            TailoredCvExport.cv_draft_id == draft_id,
        )
    )
    if result is None or result.document.candidate_profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV export not found for the candidate profile and draft",
        )
    return result


def _export_response(export: TailoredCvExport) -> TailoredCvExportRead:
    document = export.document
    if not GENERATED_FILENAME.fullmatch(document.original_filename):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CV export metadata is invalid",
        )
    return TailoredCvExportRead(
        id=export.id,
        candidate_profile_id=export.candidate_profile_id,
        cv_draft_id=export.cv_draft_id,
        document_id=export.document_id,
        export_format=export.export_format,
        page_count=export.page_count,
        filename=document.original_filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        created_at=export.created_at,
    )


@router.post(
    "/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft_id}/exports",
    response_model=TailoredCvExportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tailored_cv_export(
    profile_id: UUID,
    job_id: UUID,
    draft_id: UUID,
    payload: TailoredCvExportCreate,
    session: DatabaseSession,
    storage: DocumentStorage = Depends(get_document_storage),
) -> TailoredCvExportRead:
    get_profile_or_404(session, profile_id)
    draft = _get_related_draft(profile_id, job_id, draft_id, session)
    try:
        result = create_cv_export(
            session,
            storage,
            profile_id,
            draft,
            payload.export_format,
        )
    except InvalidDraftForExport as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ExportFileUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CV export storage is unavailable",
        ) from exc
    result.document = session.get(CandidateDocument, result.document_id)
    return _export_response(result)


@router.get(
    "/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft_id}/exports",
    response_model=list[TailoredCvExportRead],
)
def list_tailored_cv_exports(
    profile_id: UUID,
    job_id: UUID,
    draft_id: UUID,
    session: DatabaseSession,
) -> list[TailoredCvExportRead]:
    get_profile_or_404(session, profile_id)
    _get_related_draft(profile_id, job_id, draft_id, session)
    exports = session.scalars(
        select(TailoredCvExport)
        .options(joinedload(TailoredCvExport.document))
        .where(
            TailoredCvExport.candidate_profile_id == profile_id,
            TailoredCvExport.cv_draft_id == draft_id,
        )
        .order_by(TailoredCvExport.created_at.desc())
    )
    return [_export_response(export) for export in exports]


@router.get(
    "/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft_id}/exports/"
    "{export_id}/download",
    response_class=FileResponse,
    response_model=None,
)
def download_tailored_cv_export(
    profile_id: UUID,
    job_id: UUID,
    draft_id: UUID,
    export_id: UUID,
    session: DatabaseSession,
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResponse:
    get_profile_or_404(session, profile_id)
    export = _get_export(
        profile_id,
        job_id,
        draft_id,
        export_id,
        session,
    )
    document = export.document
    expected_media_type = (
        "application/pdf"
        if export.export_format == "pdf"
        else "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    )
    if (
        document.document_kind != "tailored_cv"
        or document.provenance != "system_generated"
        or document.media_type != expected_media_type
        or not GENERATED_FILENAME.fullmatch(document.original_filename)
        or document.original_filename.rsplit(".", 1)[-1] != export.export_format
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CV export metadata does not match the saved artifact",
        )
    try:
        path = load_export_file(storage, document)
    except ExportFileUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="CV export file is unavailable",
        ) from exc
    return FileResponse(
        path,
        media_type=expected_media_type,
        filename=document.original_filename,
    )
