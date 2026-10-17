"""ATS analysis, draft review, candidate edits and approval before export."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.v1.candidate_profiles import get_profile_or_404
from app.api.v1.dependencies import require_authenticated_resource_access
from app.db import DatabaseSession
from app.models import (
    CandidateDocument,
    CandidateEvidence,
    CandidateJobDescription,
    TailoredCvDraft,
)
from app.schemas.cv_generation import (
    CvDraftApproval,
    CvDraftRevisionCreate,
    CVStructuredContent,
    CVValidationResults,
    TailoredCvDraftRead,
)
from app.services.ats_match import build_ats_report
from app.services.cv_export import InvalidDraftForExport, validate_saved_draft
from app.services.cv_export_checks import pre_export_checks
from app.services.cv_generation import _collect_references, render_cv
from app.services.cv_validation import completeness_issues, validate_cv_content
from app.services.cv_writer import RevisionError, apply_edits, approve, change_log
from app.services.documents import DocumentStorage, get_document_storage

router = APIRouter(
    prefix="/candidate-profiles",
    tags=["CV review"],
    dependencies=[Depends(require_authenticated_resource_access)],
)


def _job(session: DatabaseSession, profile_id: UUID, job_id: UUID) -> CandidateJobDescription:
    job = session.scalar(
        select(CandidateJobDescription).where(
            CandidateJobDescription.id == job_id, CandidateJobDescription.candidate_profile_id == profile_id
        )
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job description not found for candidate profile"
        )
    return job


def _draft(session: DatabaseSession, profile_id: UUID, draft_id: UUID) -> TailoredCvDraft:
    draft = session.scalar(
        select(TailoredCvDraft).where(
            TailoredCvDraft.id == draft_id, TailoredCvDraft.candidate_profile_id == profile_id
        )
    )
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CV draft not found for candidate profile")
    return draft


def _content(draft: TailoredCvDraft) -> CVStructuredContent:
    if draft.status not in {"generated", "needs_review"} or not draft.structured_content:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This draft failed validation and has no content to review."
        )
    return CVStructuredContent.model_validate(draft.structured_content)


@router.get("/{profile_id}/job-descriptions/{job_id}/ats-analysis")
def read_ats_analysis(
    profile_id: UUID,
    job_id: UUID,
    session: DatabaseSession,
    storage: Annotated[DocumentStorage, Depends(get_document_storage)],
    source_document_id: Annotated[UUID | None, Query()] = None,
) -> dict:
    """Read-only: analyses the saved job and the candidate's records; nothing is stored."""
    get_profile_or_404(session, profile_id)
    job = _job(session, profile_id, job_id)
    try:
        return build_ats_report(session, job, storage, source_document_id=source_document_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{profile_id}/cv-drafts/{draft_id}/review")
def read_cv_draft_review(profile_id: UUID, draft_id: UUID, session: DatabaseSession) -> dict:
    get_profile_or_404(session, profile_id)
    draft = _draft(session, profile_id, draft_id)
    content = _content(draft)
    review = content.review
    job = session.get(CandidateJobDescription, draft.job_description_id)
    document = None
    if review and review.source_document_id:
        document = session.scalar(
            select(CandidateDocument).where(
                CandidateDocument.id == UUID(review.source_document_id),
                CandidateDocument.candidate_profile_id == profile_id,
            )
        )
    evidence_ids = {
        UUID(ref["source_id"]) for ref in draft.source_references if ref.get("source_type") == "candidate_evidence"
    }
    evidence = (
        list(
            session.scalars(
                select(CandidateEvidence).where(
                    CandidateEvidence.id.in_(evidence_ids), CandidateEvidence.candidate_profile_id == profile_id
                )
            )
        )
        if evidence_ids
        else []
    )

    blockers: list[str] = []
    try:
        validate_saved_draft(session, profile_id, draft)
    except InvalidDraftForExport as exc:
        blockers.append(str(exc))
    if review and review.approval_status != "approved":
        blockers.append("Review the changes and approve this draft before exporting it.")
    log = change_log(content)
    return {
        "draft_id": str(draft.id),
        "writer_version": review.writer_version if review else "standard",
        "requires_approval": review is not None,
        "approval": review.model_dump(
            mode="json",
            include={"approval_status", "approved_at", "attested_unconfirmed_statements", "parent_draft_id"},
        )
        if review
        else None,
        "ats_score": review.ats_score if review else None,
        "ats_potential_score": review.ats_potential_score if review else None,
        "change_log": log,
        "needs_confirmation": sum(1 for entry in log if entry["needs_confirmation"]),
        "suggestions": review.suggestions if review else [],
        "checks": pre_export_checks(content, draft.generated_content or render_cv(content)),
        "trace": {
            "job_description": {
                "id": str(job.id),
                "job_title": job.job_title,
                "company": job.company,
                "source_job_listing_id": str(job.source_job_listing_id) if job.source_job_listing_id else None,
            }
            if job
            else None,
            "source_document": {"id": str(document.id), "filename": document.original_filename} if document else None,
            "evidence_used": [
                {"id": str(item.id), "description": item.description, "confirmation_status": item.confirmation_status}
                for item in evidence
            ],
            "parent_draft_id": review.parent_draft_id if review else None,
        },
        "export_ready": not blockers,
        "export_blockers": blockers,
        "status": draft.status,
        "completeness": draft.validation_results.get("completeness", "complete"),
        "issues": draft.validation_results.get("issues", []),
        "acknowledged_incomplete": bool(review and review.acknowledged_incomplete),
        # Statements that exist because the candidate confirmed a skill or gave an example.
        "from_confirmations": [
            entry for entry in log if any(ref["source_type"] == "skill_confirmation" for ref in entry["evidence"])
        ]
        + [
            {"section": section.heading, "proposed": claim.text}
            for section in content.sections
            if section.heading in {"Core Skills", "Tools and Platforms"}
            for claim in section.claims
            if any(ref.source_type == "skill_confirmation" for ref in claim.source_references)
        ],
    }


@router.post(
    "/{profile_id}/cv-drafts/{draft_id}/revisions",
    response_model=TailoredCvDraftRead,
    status_code=status.HTTP_201_CREATED,
)
def create_cv_draft_revision(
    profile_id: UUID,
    draft_id: UUID,
    payload: CvDraftRevisionCreate,
    session: DatabaseSession,
) -> TailoredCvDraft:
    """Save the candidate's edits as a new draft version; the original stays unchanged."""
    get_profile_or_404(session, profile_id)
    parent = _draft(session, profile_id, draft_id)
    content = _content(parent)
    if content.review is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Only drafts from the reviewed CV writer can be edited here."
        )
    try:
        revised = apply_edits(content, {edit.key: edit.text for edit in payload.edits}, parent_draft_id=str(parent.id))
    except RevisionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    rendered = render_cv(revised)
    errors = validate_cv_content(revised, rendered)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "The edited draft does not pass validation.", "errors": errors},
        )
    previous = CVValidationResults.model_validate(parent.validation_results)
    issues = completeness_issues(revised)
    draft = TailoredCvDraft(
        candidate_profile_id=profile_id,
        job_description_id=parent.job_description_id,
        status="needs_review" if issues else "generated",
        generated_content=rendered,
        structured_content=revised.model_dump(mode="json"),
        validation_results=CVValidationResults(
            is_valid=True,
            errors=[],
            gaps=previous.gaps,
            warnings=previous.warnings,
            completeness="incomplete" if issues else "complete",
            issues=issues,
        ).model_dump(mode="json"),
        source_references=[reference.model_dump(mode="json") for reference in _collect_references(revised)],
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


@router.post("/{profile_id}/cv-drafts/{draft_id}/approval", response_model=TailoredCvDraftRead)
def approve_cv_draft(
    profile_id: UUID,
    draft_id: UUID,
    payload: CvDraftApproval,
    session: DatabaseSession,
) -> TailoredCvDraft:
    get_profile_or_404(session, profile_id)
    draft = _draft(session, profile_id, draft_id)
    content = _content(draft)
    incomplete = draft.status == "needs_review"
    if incomplete and not payload.acknowledge_incomplete:
        missing = "; ".join(issue["message"] for issue in draft.validation_results.get("issues", [])[:5])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This draft is incomplete ({missing}). Confirm that you want to approve it as incomplete, "
            "or add the missing evidence and generate it again.",
        )
    try:
        validate_saved_draft(session, profile_id, draft, for_approval=True)
        approved = approve(content, attest=payload.attest_unconfirmed_statements, acknowledge_incomplete=incomplete)
    except (InvalidDraftForExport, RevisionError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    draft.structured_content = approved.model_dump(mode="json")
    session.commit()
    session.refresh(draft)
    return draft
