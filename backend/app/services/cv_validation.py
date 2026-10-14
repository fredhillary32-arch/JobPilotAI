import re

from app.schemas.cv_generation import CVStructuredContent

EXPECTED_SECTION_ORDER = [
    "Professional Summary",
    "Tools and Platforms",
    "Core Skills",
    "Professional Experience",
    "Education",
]
WORD_PATTERN = re.compile(r"[A-Za-z0-9+#]+")
ACTION_WORDS = {
    "analyzed", "automated", "built", "created", "delivered", "designed",
    "developed", "enabled", "established", "implemented", "improved",
    "increased", "introduced", "launched", "led", "maintained", "managed",
    "migrated", "optimized", "organized", "reduced", "resolved", "secured",
    "streamlined", "strengthened", "supported", "tested", "transformed",
    "upgraded", "used", "wrote",
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


def validate_cv_content(
    content: CVStructuredContent,
    rendered_text: str,
) -> list[str]:
    errors: list[str] = []
    if [section.heading for section in content.sections] != EXPECTED_SECTION_ORDER:
        errors.append("CV sections do not follow the required section order.")
    if not content.professional_heading.strip():
        errors.append("Add a professional headline to the candidate profile.")
    if not any(
        section.heading == "Professional Summary" and section.claims
        for section in content.sections
    ):
        errors.append("Add a candidate-provided professional summary to the profile.")
    if not content.header_source_references:
        errors.append("Candidate name and heading require profile source references.")

    if "\u2014" in rendered_text:
        errors.append("Generated CV contains a prohibited em dash.")
    if "&" in rendered_text:
        errors.append("Generated CV contains a prohibited ampersand; use 'and'.")

    for section in content.sections:
        for claim in section.claims:
            if not claim.source_references:
                errors.append(
                    f"{section.heading} contains a claim without a source reference."
                )
        if section.heading == "Professional Experience":
            if not section.roles:
                errors.append(
                    "Professional Experience has no candidate-provided roles."
                )
            for role in section.roles:
                label = f"{role.job_title} at {role.employer}"
                if len(role.bullets) != 5:
                    errors.append(
                        f"{label} needs five substantive supported bullets; "
                        f"only {len(role.bullets)} are available. Add "
                        "candidate-confirmed evidence."
                    )
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
