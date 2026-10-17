"""A short cover-letter draft from the candidate's own confirmed records.

The only claims are the profile summary (the candidate's own words) and work
history statements that demonstrate the job's matched requirements, quoted as
written. The surrounding sentences are fixed courtesy text that asserts nothing
about the candidate. Every claim keeps its source so the candidate can check it,
and the draft is returned for editing, never sent anywhere.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CandidateProfile, CandidateWorkExperience
from app.services.ats_vocabulary import phrase_in

MAX_EXAMPLES = 3


def draft_cover_letter(session: Session, profile: CandidateProfile, job_title: str, company: str | None,
                       report: dict) -> dict:
    experiences = list(session.scalars(
        select(CandidateWorkExperience).where(CandidateWorkExperience.candidate_profile_id == profile.id)
    ))
    terms = [term for item in report["requirements"]["essential"] + report["requirements"]["preferred"]
             if item["status"] == "matched" for term in item["terms"]]
    examples: list[dict] = []
    seen: set[str] = set()
    for term in dict.fromkeys(terms):
        for experience in experiences:
            for index, statement in enumerate([experience.description or "", *experience.achievements]):
                text = " ".join(statement.split())
                if text and phrase_in(term, text) and text.casefold() not in seen and len(examples) < MAX_EXAMPLES:
                    seen.add(text.casefold())
                    field = "description" if index == 0 else f"achievements[{index - 1}]"
                    examples.append({"text": text, "role": f"{experience.job_title} at {experience.employer}",
                                     "source": {"source_type": "work_experience", "source_id": str(experience.id), "source_field": field}})
    employer = company or "your team"
    lines = [f"Dear Hiring Team at {employer}," if company else "Dear Hiring Team,", "",
             f"I am applying for the {job_title} role."]
    sources: list[dict] = []
    notes: list[str] = []
    if profile.summary and profile.summary.strip():
        lines.append(" ".join(profile.summary.split()))
        sources.append({"source_type": "profile_field", "source_id": str(profile.id), "source_field": "summary"})
    else:
        notes.append("Your profile has no summary, so the letter has no introduction about you. Add one to your profile or write it here.")
    if examples:
        lines += ["", "Examples from my work that relate to this role:"]
        for example in examples:
            lines.append(f"- {example['text'].rstrip('.')}. ({example['role']})")
            sources.append(example["source"])
    else:
        notes.append("None of the job's requirements are demonstrated in your work history yet, so no examples were added.")
    lines += ["", "Thank you for considering my application. I would welcome the opportunity to discuss the role.", "",
              "Kind regards,", " ".join(profile.name.split())]
    contact = " | ".join(" ".join(value.split()) for value in (profile.contact_email, profile.contact_phone) if value)
    if contact:
        lines.append(contact)
    notes.append("Draft only: read it, edit it in your own words, and only send what is true.")
    return {"text": "\n".join(lines), "sources": sources, "notes": notes}
