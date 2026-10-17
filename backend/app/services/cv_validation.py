import re

from app.schemas.cv_generation import CVStructuredContent
from app.services.ats_vocabulary import PAST_TENSE, THIRD_PERSON

EXPECTED_SECTION_ORDER = [
    "Professional Summary",
    "Tools and Platforms",
    "Core Skills",
    "Professional Experience",
    "Education",
]
WORD_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
ACTION_WORDS = {
    "analyzed",
    "automated",
    "built",
    "created",
    "delivered",
    "designed",
    "developed",
    "enabled",
    "established",
    "implemented",
    "improved",
    "increased",
    "introduced",
    "launched",
    "led",
    "maintained",
    "managed",
    "migrated",
    "optimized",
    "organized",
    "reduced",
    "resolved",
    "secured",
    "streamlined",
    "strengthened",
    "supported",
    "tested",
    "transformed",
    "upgraded",
    "used",
    "wrote",
    # Present-tense forms (current roles) and the CV writer's verb vocabulary.
    *PAST_TENSE,
    *(verb.casefold() for verb in PAST_TENSE.values()),
    *THIRD_PERSON,
}
GENERIC_PHRASES = (
    "responsible for",
    "worked on",
    "duties included",
    "assisted with",
    "various tasks",
)


def is_substantive_bullet(value: str) -> bool:
    normalized = value.casefold()
    words = [word.casefold() for word in WORD_PATTERN.findall(value)]
    return (
        len(words) >= 6
        and any(word in ACTION_WORDS for word in words)
        and not any(phrase in normalized for phrase in GENERIC_PHRASES)
    )


TARGET_BULLETS = 5


def validate_cv_content(
    content: CVStructuredContent,
    rendered_text: str,
) -> list[str]:
    """Integrity errors: anything that would make a claim untraceable or malformed.

    These fail a draft. How complete the draft is (for example a role with fewer
    than five supported bullets) is reported separately by ``completeness_issues``
    so missing evidence becomes an action for the candidate, not a dead end.
    """
    errors: list[str] = []
    headings = [section.heading for section in content.sections]
    # Certifications may follow Education; every other section is fixed.
    if headings not in (EXPECTED_SECTION_ORDER, [*EXPECTED_SECTION_ORDER, "Certifications"]):
        errors.append("CV sections do not follow the required section order.")
    if not content.header_source_references:
        errors.append("Candidate name and heading require profile source references.")

    if "\u2014" in rendered_text:
        errors.append("Generated CV contains a prohibited em dash.")
    if "&" in rendered_text:
        errors.append("Generated CV contains a prohibited ampersand; use 'and'.")

    for section in content.sections:
        for claim in section.claims:
            if not claim.source_references:
                errors.append(f"{section.heading} contains a claim without a source reference.")
        if section.heading == "Professional Experience":
            for role in section.roles:
                label = f"{role.job_title} at {role.employer}"
                if len(role.bullets) > TARGET_BULLETS:
                    errors.append(f"{label} has more than {TARGET_BULLETS} bullets.")
                if not role.source_references:
                    errors.append(f"{label} is missing role source references.")
                seen: set[str] = set()
                for bullet in role.bullets:
                    if not bullet.source_references:
                        errors.append(f"{label} has a bullet without a source reference.")
                    if not is_substantive_bullet(bullet.text):
                        errors.append(
                            f"{label} has a non-substantive or generic bullet. "
                            "Add specific candidate-confirmed actions or outcomes."
                        )
                    if bullet.text.casefold() in seen:
                        errors.append(f"{label} contains a duplicate bullet.")
                    seen.add(bullet.text.casefold())
    return errors


def completeness_issues(content: CVStructuredContent) -> list[dict]:
    """What the candidate's records do not yet support; never filled with invented text.

    Each issue names its group, what is missing and what the candidate can do.
    """
    issues: list[dict] = []
    if not content.professional_heading.strip():
        issues.append(
            {
                "group": "profile_evidence",
                "message": "The CV has no professional headline.",
                "action": "Add a professional headline to your candidate profile.",
            }
        )
    if not any(section.heading == "Professional Summary" and section.claims for section in content.sections):
        issues.append(
            {
                "group": "profile_evidence",
                "message": "The CV has no professional summary.",
                "action": "Add a summary in your own words to your candidate profile.",
            }
        )
    for section in content.sections:
        if section.heading != "Professional Experience":
            continue
        if not section.roles:
            issues.append(
                {
                    "group": "experience_evidence",
                    "message": "Professional Experience has no roles.",
                    "action": "Add your work history to your candidate profile.",
                }
            )
        for role in section.roles:
            if len(role.bullets) < TARGET_BULLETS:
                issues.append(
                    {
                        "group": "experience_evidence",
                        "role": f"{role.job_title} at {role.employer}",
                        "work_experience_id": str(role.work_experience_id),
                        "message": (
                            f"{role.job_title} at {role.employer} has {len(role.bullets)} supported "
                            f"bullet{'s' if len(role.bullets) != 1 else ''}; the CV layout aims for {TARGET_BULLETS}."
                        ),
                        "action": (
                            "Add truthful achievements to this role in your profile, or give an example of using a "
                            "skill in this role below. JobPilot will not invent bullets to fill the gap."
                        ),
                    }
                )
    return issues
