"""Deterministic, explainable job fit for one saved job description.

Fit compares the job's stated requirements with information the candidate
entered or confirmed. It never decides geographic eligibility: that comes only
from the reviewed listing assessment (app.services.eligibility) and is reported
separately, so a high skills coverage can never outweigh a stated exclusion.
Keyword matches only propose passages; anything not established stays uncertain.
"""

import re
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateEligibilityDetails,
    CandidateEvidence,
    CandidateJobDescription,
    CandidateSkill,
    CandidateWorkAuthorization,
    CandidateWorkExperience,
    JobListing,
)
from app.services.countries import COUNTRIES, countries_named_in
from app.services.cv_provider import TOOLS_AND_PLATFORMS, extract_required_skills
from app.services.eligibility import effective_eligibility, latest_assessments_for
from app.services.evidence_integrity import current_only

MAX_REQUIREMENTS = 40
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
WORK_AUTHORIZATION = re.compile(
    r"\b(authori[sz]ed to work|authori[sz]ation to work|right to work|work permit|work visa|"
    r"eligible to work|visa sponsorship)\b",
    re.I,
)
STRICT_WORK_AUTHORIZATION = re.compile(
    r"\b(must|required to|need to|should)\s+(?:\w+\s+){0,3}?(be\s+(?:legally\s+)?authori[sz]ed to work|"
    r"have\s+(?:the\s+)?(?:legal\s+)?right to work|hold\s+(?:a\s+)?(?:valid\s+)?work (?:permit|visa))",
    re.I,
)
SPONSORSHIP_OFFERED = re.compile(
    r"\b(sponsorship (?:is |may be )?(?:available|offered|provided)|(?:we|will|can) (?:provide |offer )?sponsor|visa support)\b",
    re.I,
)
NO_SPONSORSHIP = re.compile(
    r"\b(without (?:visa )?sponsorship|(?:not|unable to|cannot|can't) (?:provide |offer )?(?:visa )?sponsor)", re.I
)
RESIDENCY = re.compile(
    r"\b(reside|residing|residents?|located in|based in|live in|living in)\b",
    re.I,
)
STRICT_RESIDENCY = re.compile(
    r"\b(must\s+(?:currently\s+)?(?:reside|live|be\s+(?:located|based))\b|"
    r"\bonly\b[^.]{0,60}\b(residents|applicants|candidates)\b|"
    r"\b(residents|applicants|candidates)\b[^.]{0,40}\bonly\b)",
    re.I,
)
RELOCATION = re.compile(r"\brelocat\w*", re.I)
TIME_ZONE = re.compile(r"\b(time ?zones?|overlap\w*|working hours|business hours)\b", re.I)
WORLDWIDE = re.compile(
    r"\b(anywhere in the world|from any country|in any country|worldwide|work from anywhere|globally remote)\b",
    re.I,
)
ARRANGEMENT_PATTERNS = {
    "onsite": re.compile(
        r"\b(on-?site (?:role|position|job)|office-based|\d+ days? (?:a|per) week in (?:the|our) office|in[- ]office (?:role|position))\b",
        re.I,
    ),
    "hybrid": re.compile(r"\bhybrid (?:role|position|work|schedule|model|working)\b", re.I),
    "remote": re.compile(r"\b(fully remote|100% remote|remote-first|remote (?:role|position|job))\b", re.I),
}


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _mentions(phrase: str, text: str) -> bool:
    phrase = _norm(phrase)
    return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", _norm(text)) is not None


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]


def stated_requirements(description: str) -> list[str]:
    found = list(extract_required_skills(description))
    for tool in sorted(TOOLS_AND_PLATFORMS):
        match = re.search(rf"(?<!\w){re.escape(tool)}(?!\w)", description, re.I)
        if match and not any(_norm(tool) == _norm(item) for item in found):
            found.append(match.group(0))  # keep the job's own wording, e.g. "Power BI"
    unique: list[str] = []
    for item in found:
        if item and _norm(item) not in {_norm(existing) for existing in unique}:
            unique.append(item)
    return unique[:MAX_REQUIREMENTS]


def _source(source_type: str, source_id: UUID, label: str) -> dict:
    return {"source_type": source_type, "source_id": str(source_id), "label": label}


def _requirement_item(
    requirement: str,
    skills: Iterable[CandidateSkill],
    certifications: Iterable[CandidateCertification],
    experiences: Iterable[CandidateWorkExperience],
    education: Iterable[CandidateEducation],
    evidence: Iterable[CandidateEvidence],
) -> dict:
    confirmed: list[dict] = []
    for skill in skills:
        if (
            _norm(skill.name) == _norm(requirement)
            or _mentions(skill.name, requirement)
            or _mentions(requirement, skill.name)
        ):
            confirmed.append(_source("skill", skill.id, f"Skill: {skill.name}"))
    for certification in certifications:
        if _mentions(requirement, certification.name) or _mentions(certification.name, requirement):
            confirmed.append(_source("certification", certification.id, f"Certification: {certification.name}"))
    for experience in experiences:
        text = " ".join([experience.job_title, experience.description or "", *experience.achievements])
        if _mentions(requirement, text):
            confirmed.append(
                _source(
                    "work_experience", experience.id, f"Experience: {experience.job_title} at {experience.employer}"
                )
            )
    for record in education:
        if _mentions(requirement, f"{record.qualification} {record.field_of_study or ''}"):
            confirmed.append(_source("education", record.id, f"Education: {record.qualification}"))
    unreviewed: list[dict] = []
    for item in evidence:
        text = f"{item.description} {item.source_excerpt or ''}"
        if not _mentions(requirement, text):
            continue
        if item.confirmation_status == "candidate_confirmed":
            confirmed.append(_source("evidence", item.id, f"Confirmed evidence: {item.description}"))
        elif item.confirmation_status == "unreviewed":
            unreviewed.append(_source("evidence", item.id, f"Unreviewed evidence: {item.description}"))
    if confirmed:
        return {
            "kind": "skill",
            "requirement": requirement,
            "status": "met",
            "explanation": f"Supported by your own information ({len(confirmed)} source{'s' if len(confirmed) != 1 else ''}).",
            "quotation": None,
            "sources": confirmed,
        }
    if unreviewed:
        return {
            "kind": "skill",
            "requirement": requirement,
            "status": "uncertain",
            "explanation": "Only unreviewed evidence mentions this. Review that evidence before relying on it.",
            "quotation": None,
            "sources": unreviewed,
        }
    return {
        "kind": "skill",
        "requirement": requirement,
        "status": "missing",
        "explanation": "None of your profile records or confirmed evidence mention this. It is not added to your CV.",
        "quotation": None,
        "sources": [],
    }


def _location_items(
    description: str,
    details: CandidateEligibilityDetails | None,
    authorizations: dict[str, str],
) -> list[dict]:
    items: list[dict] = []
    sentences = _sentences(description)
    sponsorship_offered = any(SPONSORSHIP_OFFERED.search(s) and not NO_SPONSORSHIP.search(s) for s in sentences)
    residence = details.country_of_residence if details else None
    relocation = details.relocation_willingness if details else None
    relocation_countries = set(details.relocation_countries) if details else set()
    restrictions: list[str] = []

    for sentence in sentences:
        countries = countries_named_in(sentence)
        names = ", ".join(COUNTRIES[code] for code in countries)
        if WORK_AUTHORIZATION.search(sentence) and not SPONSORSHIP_OFFERED.search(sentence):
            strict = bool(STRICT_WORK_AUTHORIZATION.search(sentence))
            if strict:
                restrictions.append(sentence)
            denied = [c for c in countries if authorizations.get(c) == "not_authorized"]
            granted = countries and all(authorizations.get(c) == "authorized" for c in countries)
            if strict and denied and not sponsorship_offered:
                status, explanation = (
                    "disqualifier",
                    (
                        f"The job asks for the right to work in {names}, and you confirmed you are not authorized to "
                        f"work in {', '.join(COUNTRIES[c] for c in denied)}. No sponsorship is mentioned."
                    ),
                )
            elif strict and granted:
                status, explanation = (
                    "met",
                    f"The job asks for the right to work in {names}, which you confirmed you have.",
                )
            elif not countries:
                status, explanation = (
                    "uncertain",
                    "The job mentions work authorization but names no country this check recognises. Read the sentence and decide.",
                )
            else:
                status, explanation = (
                    "uncertain",
                    (
                        f"The job mentions work authorization for {names}. "
                        + ("Sponsorship is mentioned elsewhere in the listing. " if sponsorship_offered else "")
                        + "Your authorization there is not confirmed; record it on your profile."
                    ),
                )
            items.append(
                {
                    "kind": "work_authorization",
                    "requirement": "Work authorization",
                    "status": status,
                    "explanation": explanation,
                    "quotation": sentence,
                    "sources": _confirmation_sources(details, countries, authorizations),
                }
            )
        elif RESIDENCY.search(sentence) and countries:
            strict = bool(STRICT_RESIDENCY.search(sentence))
            if strict:
                restrictions.append(sentence)
            if strict and residence in countries:
                status, explanation = "met", f"The job requires being in {names}, where you confirmed you live."
            elif strict and residence and residence not in countries:
                movable = relocation == "willing" and (
                    not relocation_countries or relocation_countries & set(countries)
                )
                status, explanation = (
                    (
                        "uncertain",
                        f"The job requires being in {names}. You live in {COUNTRIES[residence]} but confirmed you are willing to relocate; check whether the employer supports relocation.",
                    )
                    if movable
                    else (
                        "disqualifier",
                        f"The job requires being in {names}, and you confirmed you live in {COUNTRIES[residence]}"
                        + (
                            " and are not willing to relocate."
                            if relocation == "not_willing"
                            else " with no confirmed plan to relocate there."
                        ),
                    )
                )
            elif strict:
                status, explanation = (
                    "uncertain",
                    f"The job requires being in {names}. Your country of residence is not confirmed.",
                )
            else:
                status, explanation = (
                    "uncertain",
                    f"The job mentions {names}, but the wording does not clearly say applicants must be there.",
                )
            items.append(
                {
                    "kind": "location",
                    "requirement": "Location",
                    "status": status,
                    "explanation": explanation,
                    "quotation": sentence,
                    "sources": _confirmation_sources(details, [], {}),
                }
            )
        elif RELOCATION.search(sentence):
            stance = {
                "willing": "You confirmed you are willing to relocate.",
                "not_willing": "You confirmed you are not willing to relocate.",
            }.get(relocation or "", "Your relocation willingness is not confirmed.")
            items.append(
                {
                    "kind": "relocation",
                    "requirement": "Relocation",
                    "status": "uncertain",
                    "explanation": f"The job mentions relocation. {stance}",
                    "quotation": sentence,
                    "sources": _confirmation_sources(details, [], {}),
                }
            )
        elif TIME_ZONE.search(sentence):
            items.append(
                {
                    "kind": "schedule",
                    "requirement": "Time zone or working hours",
                    "status": "uncertain",
                    "explanation": "The job mentions time zones or working hours. Check that you can meet them from where you work.",
                    "quotation": sentence,
                    "sources": [],
                }
            )

    worldwide = [s for s in sentences if WORLDWIDE.search(s)]
    if worldwide and restrictions:
        items.append(
            {
                "kind": "contradiction",
                "requirement": "Contradictory location wording",
                "status": "uncertain",
                "explanation": "The listing says the role is open widely but also states a location or authorization restriction. It is unclear which applies; treat eligibility as unknown until clarified.",
                "quotation": f"{worldwide[0]} … {restrictions[0]}",
                "sources": [],
            }
        )
    return items


def _confirmation_sources(details, countries: list[str], authorizations: dict[str, str]) -> list[dict]:
    if details is None:
        return []
    sources = [_source("eligibility_details", details.candidate_profile_id, "Your confirmed eligibility details")]
    for code in countries:
        if code in authorizations:
            sources.append(
                {
                    "source_type": "work_authorization",
                    "source_id": code,
                    "label": f"Your confirmed work authorization: {COUNTRIES[code]} ({authorizations[code].replace('_', ' ')})",
                }
            )
    return sources


def _preference_items(description: str, details: CandidateEligibilityDetails | None) -> list[dict]:
    stated = [arrangement for arrangement, pattern in ARRANGEMENT_PATTERNS.items() if pattern.search(description)]
    accepted = set(details.accepted_work_arrangements) if details else set()
    items = []
    for arrangement in stated:
        quote = next(s for s in _sentences(description) if ARRANGEMENT_PATTERNS[arrangement].search(s))
        if not accepted:
            status, explanation = (
                "uncertain",
                f"The job describes a {arrangement} arrangement. You have not confirmed which arrangements you accept.",
            )
        elif arrangement in accepted:
            status, explanation = "met", f"The job describes a {arrangement} arrangement, which you accept."
        else:
            status, explanation = (
                "mismatch",
                f"The job describes a {arrangement} arrangement, which is not among the arrangements you accept. This is a preference, not an eligibility rule.",
            )
        items.append(
            {
                "kind": "work_arrangement",
                "requirement": "Work arrangement",
                "status": status,
                "explanation": explanation,
                "quotation": quote,
                "sources": [],
            }
        )
    return items


def compute_job_fit(session: Session, job: CandidateJobDescription) -> dict:
    profile_id = job.candidate_profile_id
    skills = session.scalars(select(CandidateSkill).where(CandidateSkill.candidate_profile_id == profile_id)).all()
    certifications = session.scalars(
        select(CandidateCertification).where(CandidateCertification.candidate_profile_id == profile_id)
    ).all()
    experiences = session.scalars(
        select(CandidateWorkExperience).where(CandidateWorkExperience.candidate_profile_id == profile_id)
    ).all()
    education = session.scalars(
        select(CandidateEducation).where(CandidateEducation.candidate_profile_id == profile_id)
    ).all()
    evidence = current_only(
        session,
        session.scalars(select(CandidateEvidence).where(CandidateEvidence.candidate_profile_id == profile_id)).all(),
    )
    details = session.get(CandidateEligibilityDetails, profile_id)
    authorizations = {
        row.country_code: row.status
        for row in session.scalars(
            select(CandidateWorkAuthorization).where(CandidateWorkAuthorization.candidate_profile_id == profile_id)
        )
    }

    requirement_items = [
        _requirement_item(requirement, skills, certifications, experiences, education, evidence)
        for requirement in stated_requirements(job.description)
    ]
    location_items = _location_items(job.description, details, authorizations)
    preference_items = _preference_items(job.description, details)

    geographic = _geographic(session, job)
    met = [item for item in requirement_items if item["status"] == "met"]
    disqualifiers = [item for item in location_items if item["status"] == "disqualifier"]
    total = len(requirement_items)
    coverage = {
        "met": len(met),
        "total": total,
        "summary": (
            f"{len(met)} of {total} stated skill requirements are supported by your own information. "
            "This measures skills coverage only; it is not eligibility."
            if total
            else "No explicit skill requirements were found in this job description, so skills coverage is not measured."
        ),
    }
    if geographic["status"] == "not_eligible":
        verdict, headline = (
            "excluded_by_employer",
            ("The employer's own wording excludes applicants based in Kenya. Skills coverage does not change this."),
        )
    elif disqualifiers:
        verdict, headline = (
            "potential_disqualifiers",
            (
                f"{len(disqualifiers)} potential disqualifier{'s' if len(disqualifiers) != 1 else ''} need your attention before you apply."
            ),
        )
    elif geographic["status"] == "eligibility_unknown":
        verdict, headline = (
            "eligibility_unknown",
            "Kenya eligibility has not been established for this job. Review it before applying.",
        )
    else:
        verdict, headline = (
            "no_blockers_found",
            (
                "The employer accepts applicants based in Kenya and no blockers were found in the stated requirements. "
                "Check the uncertain items before applying."
            ),
        )
    return {
        "job_description_id": job.id,
        "verdict": verdict,
        "headline": headline,
        "geographic_eligibility": geographic,
        "candidate_details_confirmed": details is not None,
        "candidate_country_of_residence": details.country_of_residence if details else None,
        "coverage": coverage,
        "matched": met,
        "missing": [item for item in requirement_items if item["status"] == "missing"],
        "uncertain": [item for item in requirement_items if item["status"] == "uncertain"]
        + [item for item in location_items if item["status"] == "uncertain"],
        "disqualifiers": disqualifiers,
        "location_requirements_met": [item for item in location_items if item["status"] == "met"],
        "preferences": preference_items,
    }


def _geographic(session: Session, job: CandidateJobDescription) -> dict:
    if job.source_job_listing_id is None:
        return {
            "status": "eligibility_unknown",
            "currency": "not_assessed",
            "listing_id": None,
            "reason": "This job was pasted, not imported from a discovered listing, so no eligibility review exists for it.",
            "quotation": None,
            "assessment_id": None,
            "assessed_at": None,
        }
    listing = session.get(JobListing, job.source_job_listing_id)
    if listing is None:
        return {
            "status": "eligibility_unknown",
            "currency": "not_assessed",
            "listing_id": None,
            "reason": "The discovered listing this job came from is no longer stored.",
            "quotation": None,
            "assessment_id": None,
            "assessed_at": None,
        }
    assessment = latest_assessments_for(session, [listing.id]).get(listing.id)
    if assessment is None:
        # No review yet: use the strict automatic decision (explicit evidence only).
        from app.services.kenya_eligibility import ELIGIBLE, INELIGIBLE, candidate_facts, decide

        decision = decide(listing, None, candidate_facts(session, job.candidate_profile_id))
        status_map = {ELIGIBLE: "eligible_confirmed", INELIGIBLE: "not_eligible"}
        return {
            "status": status_map.get(decision["state"], "eligibility_unknown"),
            "currency": "automatic",
            "listing_id": listing.id,
            "reason": decision["explanation"],
            "quotation": decision["evidence"][0]["quotation"] if decision["evidence"] else None,
            "assessment_id": None,
            "assessed_at": None,
        }
    effective = effective_eligibility(listing, assessment)
    return {
        "status": effective["status"],
        "currency": effective["currency"],
        "listing_id": listing.id,
        "reason": effective["reason"],
        "quotation": effective.get("quotation"),
        "assessment_id": effective.get("assessment_id"),
        "assessed_at": effective.get("assessed_at"),
    }
