import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CandidateEducation,
    CandidateEvidence,
    CandidateJobDescription,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
    TailoredCvDraft,
)
from app.schemas.cv_generation import (
    CVSourceReference,
    CVStructuredContent,
    CVValidationResults,
)
from app.services.cv_provider import (
    CVContentProvider,
    DeterministicCVContentProvider,
    extract_required_skills,
)
from app.services.cv_validation import completeness_issues, validate_cv_content
from app.services.evidence_integrity import current_only


@dataclass(frozen=True)
class CVGenerationOutcome:
    status: str
    generated_content: str | None
    structured_content: CVStructuredContent | None
    validation_results: CVValidationResults
    source_references: list[CVSourceReference]


def render_cv(content: CVStructuredContent) -> str:
    lines = [content.candidate_name]
    if content.professional_heading:
        lines.append(content.professional_heading)
    if content.contact_details:
        lines.append(content.contact_details)
    lines.append("")

    for section in content.sections:
        lines.extend((section.heading, ""))
        if section.heading == "Professional Experience":
            for role in section.roles:
                lines.append(f"{role.job_title} at {role.employer} | {role.dates}")
                lines.extend(f"- {bullet.text}" for bullet in role.bullets)
                lines.append("")
        else:
            lines.extend(f"- {claim.text}" for claim in section.claims)
            lines.append("")
    return "\n".join(lines).strip()


def _collect_references(content: CVStructuredContent) -> list[CVSourceReference]:
    references = list(content.header_source_references)
    for section in content.sections:
        for claim in section.claims:
            references.extend(claim.source_references)
        for role in section.roles:
            references.extend(role.source_references)
            for bullet in role.bullets:
                references.extend(bullet.source_references)
    return references


def _required_skill_gaps(
    job: CandidateJobDescription,
    profile: CandidateProfile,
    skills: Sequence[CandidateSkill],
    experiences: Sequence[CandidateWorkExperience],
    evidence: Sequence[CandidateEvidence],
) -> list[str]:
    supported_material = " ".join(
        [
            profile.professional_headline or "",
            profile.summary or "",
            *(skill.name for skill in skills),
            *(
                " ".join(
                    [
                        experience.job_title,
                        experience.employer,
                        experience.description or "",
                        *experience.achievements,
                    ]
                )
                for experience in experiences
            ),
            *(
                " ".join([item.description, item.source_excerpt or ""])
                for item in evidence
                if item.confirmation_status == "candidate_confirmed"
            ),
        ]
    ).casefold()
    return [
        f"Required skill not supported by candidate-provided or confirmed information: {skill}"
        for skill in extract_required_skills(job.description)
        if not re.search(
            rf"(?<![a-z0-9]){re.escape(skill.casefold())}(?![a-z0-9])",
            supported_material,
        )
    ]


def generate_cv_draft(
    session: Session,
    profile_id: UUID,
    job: CandidateJobDescription,
    *,
    provider: CVContentProvider | None = None,
) -> CVGenerationOutcome:
    profile = session.get(CandidateProfile, profile_id)
    if profile is None:
        raise ValueError("Candidate profile not found")
    if job.candidate_profile_id != profile_id:
        raise ValueError("Job description does not belong to candidate profile")

    skills = list(
        session.scalars(
            select(CandidateSkill)
            .where(CandidateSkill.candidate_profile_id == profile_id)
            .order_by(CandidateSkill.name)
        )
    )
    experiences = list(
        session.scalars(
            select(CandidateWorkExperience)
            .where(CandidateWorkExperience.candidate_profile_id == profile_id)
            .order_by(CandidateWorkExperience.start_date.desc())
        )
    )
    education = list(
        session.scalars(
            select(CandidateEducation)
            .where(CandidateEducation.candidate_profile_id == profile_id)
            .order_by(CandidateEducation.start_date.desc())
        )
    )
    # Evidence whose excerpt no longer matches the current extraction is left out.
    evidence = current_only(
        session,
        list(
            session.scalars(
                select(CandidateEvidence)
                .where(CandidateEvidence.candidate_profile_id == profile_id)
                .order_by(CandidateEvidence.created_at)
            )
        ),
    )

    content = (provider or DeterministicCVContentProvider()).generate(
        profile,
        job,
        skills,
        experiences,
        education,
        evidence,
    )
    rendered = render_cv(content)
    references = _collect_references(content)
    errors = validate_cv_content(content, rendered)
    if len(rendered) > 4500:
        warnings = ["This draft may exceed one page; readability takes priority over reducing font size."]
    else:
        warnings = []
    gaps = _required_skill_gaps(job, profile, skills, experiences, evidence)
    issues = completeness_issues(content)
    results = CVValidationResults(
        is_valid=not errors,
        errors=errors,
        gaps=gaps,
        warnings=warnings,
        completeness="incomplete" if issues else "complete",
        issues=issues,
    )
    if errors:
        return CVGenerationOutcome(
            status="failed",
            generated_content=None,
            structured_content=None,
            validation_results=results,
            source_references=references,
        )
    return CVGenerationOutcome(
        # Sound but incomplete content is saved for the candidate to review, never padded.
        status="needs_review" if issues else "generated",
        generated_content=rendered,
        structured_content=content,
        validation_results=results,
        source_references=references,
    )


def persist_cv_draft(
    session: Session,
    profile_id: UUID,
    job: CandidateJobDescription,
    outcome: CVGenerationOutcome,
) -> TailoredCvDraft:
    draft = TailoredCvDraft(
        candidate_profile_id=profile_id,
        job_description_id=job.id,
        status=outcome.status,
        generated_content=outcome.generated_content,
        structured_content=(outcome.structured_content.model_dump(mode="json") if outcome.structured_content else None),
        validation_results=outcome.validation_results.model_dump(mode="json"),
        source_references=[reference.model_dump(mode="json") for reference in outcome.source_references],
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft
