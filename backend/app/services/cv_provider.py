import re
from collections.abc import Sequence
from typing import Protocol

from app.models import (
    CandidateEducation,
    CandidateEvidence,
    CandidateJobDescription,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)
from app.schemas.cv_generation import (
    CVClaim,
    CVRole,
    CVSection,
    CVSourceReference,
    CVStructuredContent,
)
from app.services.cv_validation import is_substantive_bullet

WORD_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
TOOLS_AND_PLATFORMS = {
    "aws",
    "azure",
    "docker",
    "figma",
    "git",
    "github",
    "google cloud",
    "kubernetes",
    "linux",
    "microsoft excel",
    "mongodb",
    "mysql",
    "postgresql",
    "power bi",
    "python",
    "react",
    "redis",
    "salesforce",
    "sql",
    "tableau",
    "terraform",
    "typescript",
}
REQUIRED_SKILLS_PATTERN = re.compile(
    r"\b(?:required\s+skills?|requirements|must[- ]have(?:\s+skills?)?)\s*:?\s*(.*)",
    re.IGNORECASE,
)
HEADING_PATTERN = re.compile(r"^\s*[A-Z][A-Za-z /&-]{1,50}\s*:\s*$")


class CVContentProvider(Protocol):
    def generate(
        self,
        profile: CandidateProfile,
        job: CandidateJobDescription,
        skills: Sequence[CandidateSkill],
        experiences: Sequence[CandidateWorkExperience],
        education: Sequence[CandidateEducation],
        evidence: Sequence[CandidateEvidence],
    ) -> CVStructuredContent: ...


def _clean(value: str) -> str:
    return " ".join(value.split())


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in WORD_PATTERN.findall(value) if token.casefold() not in STOP_WORDS}


def _score(value: str, job_tokens: set[str]) -> int:
    return len(_tokens(value) & job_tokens)


def extract_required_skills(description: str) -> list[str]:
    required: list[str] = []
    lines = description.splitlines()
    collecting_bullets = False
    for line in lines:
        match = REQUIRED_SKILLS_PATTERN.search(line)
        if match:
            collecting_bullets = True
            remainder = match.group(1).split(".", 1)[0].strip()
            if remainder:
                required.extend(item.strip(" -*\t") for item in re.split(r"[,;|]|\s+\band\b\s+", remainder, flags=re.I))
            continue
        if collecting_bullets:
            stripped = line.strip()
            if stripped.startswith(("-", "*", "•")):
                required.append(stripped.lstrip("-*• ").strip())
            elif not stripped:
                continue
            elif HEADING_PATTERN.match(stripped):
                collecting_bullets = False
    unique: list[str] = []
    seen: set[str] = set()
    for item in required:
        item = _clean(item)
        key = item.casefold()
        if item and key not in seen:
            unique.append(item)
            seen.add(key)
    return unique


def _contains_role_reference(
    evidence: CandidateEvidence,
    experience: CandidateWorkExperience,
) -> bool:
    source_label = " ".join(
        filter(
            None,
            (
                evidence.source_section,
                evidence.description,
                evidence.source_excerpt,
            ),
        )
    ).casefold()
    return any(
        len(term.strip()) >= 3
        and re.search(
            rf"(?<!\w){re.escape(term.strip().casefold())}(?!\w)",
            source_label,
        )
        for term in (experience.employer, experience.job_title)
    )


def _profile_reference(profile: CandidateProfile, field: str, text: str) -> CVSourceReference:
    return CVSourceReference(
        source_type="profile_field",
        source_id=str(profile.id),
        source_field=field,
        claim_text=text,
    )


def _skill_claim(skill: CandidateSkill) -> CVClaim:
    text = _clean(skill.name)
    return CVClaim(
        text=text,
        source_references=[
            CVSourceReference(
                source_type="skill",
                source_id=str(skill.id),
                source_field="name",
                claim_text=text,
            )
        ],
    )


def _experience_claims(
    experience: CandidateWorkExperience,
    evidence: Sequence[CandidateEvidence],
    job_tokens: set[str],
) -> list[CVClaim]:
    claims: list[CVClaim] = []
    if experience.description:
        text = _clean(experience.description)
        if is_substantive_bullet(text):
            claims.append(
                CVClaim(
                    text=text,
                    source_references=[
                        CVSourceReference(
                            source_type="work_experience",
                            source_id=str(experience.id),
                            source_field="description",
                            claim_text=text,
                        )
                    ],
                )
            )
    for index, achievement in enumerate(experience.achievements):
        text = _clean(achievement)
        if is_substantive_bullet(text):
            claims.append(
                CVClaim(
                    text=text,
                    source_references=[
                        CVSourceReference(
                            source_type="work_experience",
                            source_id=str(experience.id),
                            source_field=f"achievements[{index}]",
                            claim_text=text,
                        )
                    ],
                )
            )
    for item in evidence:
        if (
            item.confirmation_status != "candidate_confirmed"
            or item.category
            not in {
                "achievement",
                "employment_responsibility",
                "metric",
                "project",
            }
            or not _contains_role_reference(item, experience)
        ):
            continue
        text = _clean(item.description)
        if is_substantive_bullet(text):
            claims.append(
                CVClaim(
                    text=text,
                    source_references=[
                        CVSourceReference(
                            source_type="candidate_evidence",
                            source_id=str(item.id),
                            source_field="description",
                            claim_text=text,
                            source_document_id=str(item.source_document_id),
                            source_excerpt=item.source_excerpt,
                            source_start=item.source_start,
                            source_end=item.source_end,
                            evidence_confirmation_status="candidate_confirmed",
                        )
                    ],
                )
            )

    distinct: dict[str, CVClaim] = {}
    for claim in claims:
        distinct.setdefault(claim.text.casefold(), claim)
    return sorted(
        distinct.values(),
        key=lambda claim: (-_score(claim.text, job_tokens), claim.text.casefold()),
    )


def _date_range(experience: CandidateWorkExperience) -> str:
    start = experience.start_date.strftime("%b %Y")
    end = (
        "Present" if experience.current_role else (experience.end_date.strftime("%b %Y") if experience.end_date else "")
    )
    return f"{start} to {end}" if end else start


def _education_claim(education: CandidateEducation) -> CVClaim:
    parts = [education.qualification]
    if education.field_of_study:
        parts.append(f"in {education.field_of_study}")
    parts.append(f"at {education.institution}")
    start_year = education.start_date.strftime("%Y")
    end_year = education.end_date.strftime("%Y") if education.end_date else ""
    date_range = f"{start_year} to {end_year}" if end_year else start_year
    text = _clean(f"{' '.join(parts)} ({date_range})")
    references = [
        CVSourceReference(
            source_type="education",
            source_id=str(education.id),
            source_field=field,
            claim_text=_clean(value),
        )
        for field, value in [
            ("qualification", education.qualification),
            ("institution", education.institution),
            ("start_date", education.start_date.isoformat()),
            ("end_date", education.end_date.isoformat() if education.end_date else ""),
        ]
        if value
    ]
    if education.field_of_study:
        references.append(
            CVSourceReference(
                source_type="education",
                source_id=str(education.id),
                source_field="field_of_study",
                claim_text=_clean(education.field_of_study),
            )
        )
    return CVClaim(text=text, source_references=references)


class DeterministicCVContentProvider:
    def generate(
        self,
        profile: CandidateProfile,
        job: CandidateJobDescription,
        skills: Sequence[CandidateSkill],
        experiences: Sequence[CandidateWorkExperience],
        education: Sequence[CandidateEducation],
        evidence: Sequence[CandidateEvidence],
    ) -> CVStructuredContent:
        job_tokens = _tokens(f"{job.job_title}\n{job.description}")
        header_references = [_profile_reference(profile, "name", _clean(profile.name))]
        if profile.professional_headline:
            header_references.append(
                _profile_reference(
                    profile,
                    "professional_headline",
                    _clean(profile.professional_headline),
                )
            )

        ordered_skills = sorted(
            skills,
            key=lambda skill: (
                -_score(skill.name, job_tokens),
                skill.name.casefold(),
            ),
        )
        tool_skills = [skill for skill in ordered_skills if skill.name.casefold().strip() in TOOLS_AND_PLATFORMS]
        core_skills = [skill for skill in ordered_skills if skill not in tool_skills]

        ranked_experiences = sorted(
            experiences,
            key=lambda experience: (
                -_score(
                    " ".join(
                        [
                            experience.job_title,
                            experience.employer,
                            experience.description or "",
                            *experience.achievements,
                        ]
                    ),
                    job_tokens,
                ),
                -experience.start_date.toordinal(),
            ),
        )
        roles: list[CVRole] = []
        for experience in ranked_experiences:
            bullets = _experience_claims(experience, evidence, job_tokens)[:5]
            roles.append(
                CVRole(
                    work_experience_id=experience.id,
                    job_title=_clean(experience.job_title),
                    employer=_clean(experience.employer),
                    dates=_date_range(experience),
                    bullets=bullets,
                    source_references=[
                        CVSourceReference(
                            source_type="work_experience",
                            source_id=str(experience.id),
                            source_field="job_title",
                            claim_text=_clean(experience.job_title),
                        ),
                        CVSourceReference(
                            source_type="work_experience",
                            source_id=str(experience.id),
                            source_field="employer",
                            claim_text=_clean(experience.employer),
                        ),
                        CVSourceReference(
                            source_type="work_experience",
                            source_id=str(experience.id),
                            source_field="dates",
                            claim_text=_date_range(experience),
                        ),
                    ],
                )
            )

        summary_claims = []
        if profile.summary and _clean(profile.summary):
            summary = _clean(profile.summary)
            summary_claims.append(
                CVClaim(
                    text=summary,
                    source_references=[_profile_reference(profile, "summary", summary)],
                )
            )

        sections = [
            CVSection(heading="Professional Summary", claims=summary_claims),
            CVSection(
                heading="Tools and Platforms",
                claims=[_skill_claim(skill) for skill in tool_skills],
            ),
            CVSection(
                heading="Core Skills",
                claims=[_skill_claim(skill) for skill in core_skills],
            ),
            CVSection(heading="Professional Experience", roles=roles),
            CVSection(
                heading="Education",
                claims=[_education_claim(item) for item in education],
            ),
        ]
        return CVStructuredContent(
            candidate_name=_clean(profile.name),
            professional_heading=_clean(profile.professional_headline or ""),
            header_source_references=header_references,
            sections=sections,
        )
