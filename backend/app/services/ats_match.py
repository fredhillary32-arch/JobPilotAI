"""Transparent, deterministic CV-to-job match assessment.

How requirements are judged:

- ``matched``: shown by work experience, confirmed evidence, a certification or
  education in the candidate's own records;
- ``partial``: only listed as a skill or in the profile summary (a keyword is
  not proof of competence), only part of the requirement is shown, or a stated
  experience or degree level is not fully met;
- ``uncertain``: mentioned only in unreviewed evidence or in the uploaded CV,
  which the candidate has not confirmed;
- ``missing``: not found anywhere;
- ``candidate_confirmed``: the candidate said they have it (half credit: a
  confirmed skill is not the same as shown professional experience);
- ``not_possessed``: the candidate said they do not have it;
- ``unverified``: the candidate chose to leave it unverified.

A candidate's example of using a skill in a recorded role counts like the work
history they entered themselves; ``evidence_strength`` keeps such statements
apart from document-backed evidence. Personal qualities and work style
("work_style") are listed for interview preparation and are not scored.

The score is a weighted share of credited requirements (see ``WEIGHTS``). It is
an aid for deciding what to improve, not a prediction of any employer's
screening software. Geographic eligibility is assessed separately and always
takes precedence over the score.
"""

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CandidateCertification,
    CandidateDocument,
    CandidateEducation,
    CandidateEvidence,
    CandidateJobDescription,
    CandidateProfile,
    CandidateSkill,
    CandidateSkillConfirmation,
    CandidateWorkExperience,
    DocumentExtraction,
)
from app.models.skill_confirmation import CLAIMABLE_RESPONSES
from app.services.ats_vocabulary import content_words, degree_level, phrase_in, stem
from app.services.cv_document_analysis import analyze_cv_document
from app.services.documents import DocumentStorage, is_candidate_source_document
from app.services.evidence_integrity import current_only
from app.services.job_fit import compute_job_fit
from app.services.job_requirements import extract_requirements

ANALYSIS_VERSION = "ats-analysis/1"
WEIGHTS = {"essential": 55, "preferred": 15, "responsibilities": 15, "keywords": 15}
CREDIT = {
    "matched": 1.0,
    "partial": 0.5,
    "candidate_confirmed": 0.5,
    "uncertain": 0.0,
    "missing": 0.0,
    "not_possessed": 0.0,
    "unverified": 0.0,
}
ALIASES = {
    "microsoft 365": ("office 365", "m365", "o365"),
    "office 365": ("microsoft 365", "m365", "o365"),
    "active directory": ("entra id", "azure ad", "azure active directory"),
    "macos": ("mac os", "os x", "osx"),
    "google cloud": ("gcp",),
    "gcp": ("google cloud",),
    "postgresql": ("postgres",),
    "javascript": ("js",),
    "kubernetes": ("k8s",),
    "comptia a+": ("a+",),
    "microsoft excel": ("excel",),
    "react.js": ("react", "reactjs"),
    "node.js": ("nodejs", "node"),
}
LIMITATIONS = [
    "Employers use many different screening systems and settings; this score does not reproduce any of them and does not predict an interview.",
    "Matching is literal: it finds the job's own terms and close word forms in your records, so a skill described in different words may be reported as missing.",
    "Only your profile records and evidence you confirmed count as demonstrated. Your uploaded CV and unreviewed evidence count as uncertain until you confirm them.",
    "Eligibility (location, work authorization) is assessed separately and is never offset by a high score.",
    "A skill you confirm earns half credit: it is your statement, not shown professional experience. An example you give of using it in a recorded role counts like the work history you entered.",
    "Personal qualities and work style (for example a growth mindset) are listed for interview preparation and are not scored.",
]
ACTIONS = {
    "matched": None,
    "partial": "Add a truthful example from a role, or confirm the part you have.",
    "candidate_confirmed": "Add an example of using it in a role to strengthen it.",
    "uncertain": "Confirm the evidence in Evidence review if it is accurate.",
    "missing": "If you genuinely have this, confirm it or add an example. Otherwise mark it as not possessed.",
    "not_possessed": None,
    "unverified": "Left unverified. It will not appear on your CV.",
}


class _Source:
    __slots__ = ("kind", "source_type", "source_id", "label", "text", "stems")

    def __init__(self, kind: str, source_type: str, source_id: str, label: str, text: str) -> None:
        self.kind = kind  # demonstrated | listed | unconfirmed
        self.source_type = source_type
        self.source_id = source_id
        self.label = label
        self.text = text
        self.stems = {stem(word) for word in content_words(text)}

    def ref(self, excerpt: str | None = None) -> dict:
        return {
            "kind": self.kind,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "label": self.label,
            "excerpt": excerpt,
        }


def _term_found(term: str, text: str) -> bool:
    return any(phrase_in(alias, text) for alias in (term, *ALIASES.get(term, ())))


def _excerpt(term: str, text: str) -> str | None:
    lowered = text.casefold()
    for alias in (term, *ALIASES.get(term, ())):
        index = lowered.find(alias.casefold())
        if index >= 0:
            start = max(0, lowered.rfind(".", 0, index) + 1)
            end = lowered.find(".", index)
            return " ".join(text[start : end if end >= 0 else len(text)].split())[:240]
    return None


def _confirmation_label(item: CandidateSkillConfirmation, roles: dict) -> str:
    where = roles.get(item.work_experience_id) or (f"project {item.project_name}" if item.project_name else None)
    return f"Your confirmation: {item.skill_name}" + (f" (used at {where})" if where else "")


def _sources(profile, skills, certifications, experiences, education, evidence, cv, confirmations=()) -> list[_Source]:
    sources: list[_Source] = []
    roles = {item.id: f"{item.job_title} at {item.employer}" for item in experiences}
    for item in confirmations:
        if item.response not in CLAIMABLE_RESPONSES:
            continue
        # An example of use counts like work history the candidate entered; a bare skill like a listed skill.
        kind = "demonstrated" if item.response == "used_in_role" else "listed"
        sources.append(
            _Source(
                kind,
                "skill_confirmation",
                str(item.id),
                _confirmation_label(item, roles),
                f"{item.skill_name}. {item.example or ''}",
            )
        )
    for item in experiences:
        sources.append(
            _Source(
                "demonstrated",
                "work_experience",
                str(item.id),
                f"{item.job_title} at {item.employer}",
                " ".join([item.job_title, item.description or "", *item.achievements]),
            )
        )
    for item in evidence:
        if item.confirmation_status == "candidate_confirmed":
            sources.append(
                _Source(
                    "demonstrated",
                    "candidate_evidence",
                    str(item.id),
                    f"Confirmed evidence: {item.description[:80]}",
                    f"{item.description} {item.source_excerpt or ''}",
                )
            )
        elif item.confirmation_status == "unreviewed":
            sources.append(
                _Source(
                    "unconfirmed",
                    "candidate_evidence",
                    str(item.id),
                    f"Unreviewed evidence: {item.description[:80]}",
                    f"{item.description} {item.source_excerpt or ''}",
                )
            )
    for item in certifications:
        sources.append(
            _Source(
                "demonstrated",
                "certification",
                str(item.id),
                f"Certification: {item.name}",
                f"{item.name} {item.issuer}",
            )
        )
    for item in education:
        sources.append(
            _Source(
                "demonstrated",
                "education",
                str(item.id),
                f"Education: {item.qualification}",
                f"{item.qualification} {item.field_of_study or ''} {item.institution}",
            )
        )
    for item in skills:
        sources.append(_Source("listed", "skill", str(item.id), f"Listed skill: {item.name}", item.name))
    summary = " ".join(filter(None, [profile.professional_headline, profile.summary]))
    if summary:
        sources.append(_Source("listed", "profile_field", str(profile.id), "Profile headline and summary", summary))
    if cv and cv.get("text"):
        sources.append(
            _Source("unconfirmed", "source_document", cv["document_id"], "Your uploaded CV (not confirmed)", cv["text"])
        )
    return sources


def _status_for_terms(terms: list[str], sources: list[_Source]) -> tuple[str, str, list[dict]]:
    refs: list[dict] = []
    best: dict[str, str] = {}
    rank = {"demonstrated": 3, "listed": 2, "unconfirmed": 1}
    for term in terms:
        for source in sources:
            if _term_found(term, source.text):
                refs.append(source.ref(_excerpt(term, source.text) if source.kind != "listed" else None))
                if rank[source.kind] > rank.get(best.get(term, ""), 0):
                    best[term] = source.kind
    demonstrated = [t for t in terms if best.get(t) == "demonstrated"]
    listed = [t for t in terms if best.get(t) == "listed"]
    unconfirmed = [t for t in terms if best.get(t) == "unconfirmed"]
    absent = [t for t in terms if t not in best]
    if len(demonstrated) == len(terms):
        return "matched", "Shown in your work history, confirmed evidence, certifications or education.", refs
    if demonstrated or listed:
        parts = []
        if demonstrated:
            parts.append(f"shown: {', '.join(demonstrated)}")
        if listed:
            parts.append(
                f"listed as a skill but not shown in your experience or confirmed evidence: {', '.join(listed)}"
            )
        if unconfirmed:
            parts.append(f"only in unconfirmed sources: {', '.join(unconfirmed)}")
        if absent:
            parts.append(f"not found: {', '.join(absent)}")
        return "partial", "Partly supported (" + "; ".join(parts) + ").", refs
    if unconfirmed:
        return (
            "uncertain",
            "Mentioned only in your uploaded CV or unreviewed evidence. Confirm it in Evidence review before relying on it.",
            refs,
        )
    return "missing", "Not found in your records. It will not be added to your CV.", refs


def _status_for_words(text: str, sources: list[_Source]) -> tuple[str, str, list[dict]]:
    wanted = {stem(word) for word in content_words(text)}
    if not wanted:
        return (
            "uncertain",
            "This requirement has no specific terms that can be checked automatically. Judge it yourself.",
            [],
        )
    best: dict[str, tuple[float, _Source]] = {}
    for source in sources:
        share = len(wanted & source.stems) / len(wanted)
        if share > best.get(source.kind, (0.0, None))[0]:
            best[source.kind] = (share, source)
    demonstrated = best.get("demonstrated", (0.0, None))
    listed = best.get("listed", (0.0, None))
    unconfirmed = best.get("unconfirmed", (0.0, None))
    refs = [source.ref() for share, source in (demonstrated, listed, unconfirmed) if source and share >= 0.25]
    if demonstrated[0] >= 0.6:
        return (
            "matched",
            f"Your records describe this ({round(demonstrated[0] * 100)}% of its key words appear in {demonstrated[1].label}).",
            refs,
        )
    if demonstrated[0] >= 0.3 or listed[0] >= 0.6:
        return "partial", "Your records cover part of this. Add confirmed evidence if you have done it.", refs
    if unconfirmed[0] >= 0.5:
        return (
            "uncertain",
            "Only your uploaded CV or unreviewed evidence describes this. Confirm it before relying on it.",
            refs,
        )
    return "missing", "Not described in your records. It will not be added to your CV.", refs


def _intervals(experiences: Sequence[CandidateWorkExperience], today: date) -> list[tuple[date, date]]:
    spans = sorted((e.start_date, (today if e.current_role or e.end_date is None else e.end_date)) for e in experiences)
    merged: list[tuple[date, date]] = []
    for start, end in spans:
        if end < start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _years(intervals: list[tuple[date, date]]) -> float:
    return round(sum((end - start).days for start, end in intervals) / 365.25, 1)


def _experience_status(
    requirement: dict, job: CandidateJobDescription, experiences, today: date
) -> tuple[str, str, list[dict]]:
    minimum = requirement["min_years"] or 0
    total = _years(_intervals(experiences, today))
    role_words = {stem(w) for w in content_words(f"{job.job_title} {requirement['source_text']}")}
    relevant = [
        e
        for e in experiences
        if role_words & {stem(w) for w in content_words(" ".join([e.job_title, e.description or "", *e.achievements]))}
    ]
    relevant_years = _years(_intervals(relevant, today))
    refs = [
        {
            "kind": "demonstrated",
            "source_type": "work_experience",
            "source_id": str(e.id),
            "label": f"{e.job_title} at {e.employer}",
            "excerpt": None,
        }
        for e in relevant
    ]
    if not experiences:
        return "missing", f"The job asks for {minimum}+ years; no work experience is recorded on your profile.", []
    if relevant_years >= minimum:
        return "matched", f"About {relevant_years} years in roles related to this job (asked: {minimum}+).", refs
    if total >= minimum:
        return (
            "partial",
            f"About {total} years in total, of which about {relevant_years} are in roles that clearly relate to this job (asked: {minimum}+).",
            refs,
        )
    return "missing", f"About {total} years of recorded experience; the job asks for {minimum}+.", refs


def _education_status(requirement: dict, education, sources: list[_Source], experiences) -> tuple[str, str, list[dict]]:
    wanted = requirement["degree_level"] or 0
    field_terms = requirement["terms"]
    best = max(education, key=lambda e: degree_level(e.qualification), default=None)
    have = degree_level(best.qualification) if best else 0
    if best and have >= wanted:
        ref = [
            {
                "kind": "demonstrated",
                "source_type": "education",
                "source_id": str(best.id),
                "label": f"{best.qualification} at {best.institution}",
                "excerpt": None,
            }
        ]
        if field_terms and not any(
            phrase_in(term, f"{e.qualification} {e.field_of_study or ''}") for e in education for term in field_terms
        ):
            return (
                "partial",
                f"Your qualification meets the level but the job names {field_terms[0]}, which your education records do not mention.",
                ref,
            )
        return "matched", "Your recorded education meets this level.", ref
    if requirement["allows_equivalent"] and experiences:
        return (
            "partial",
            "Your recorded education is below the level named, but the job accepts equivalent experience. Show that experience clearly.",
            [],
        )
    status, _, refs = _status_for_words(requirement["source_text"], [s for s in sources if s.kind == "unconfirmed"])
    if refs:
        return (
            "uncertain",
            "Your uploaded CV or unreviewed evidence mentions a qualification that is not in your profile. Add it to your profile if accurate.",
            refs,
        )
    return "missing", "No qualification at this level is recorded on your profile.", []


def _strength(refs: list[dict]) -> str:
    """How strong the best support is, kept apart from the score."""
    types = {(ref["kind"], ref["source_type"]) for ref in refs}
    if any(
        kind == "demonstrated" and source in {"candidate_evidence", "certification", "education"}
        for kind, source in types
    ):
        return "document_or_record"
    if ("demonstrated", "work_experience") in types:
        return "work_history"
    if any(source == "skill_confirmation" for _, source in types):
        return "candidate_statement"
    if any(kind == "listed" for kind, _ in types):
        return "listed_only"
    return "none"


def _apply_confirmation(item: dict, confirmation: CandidateSkillConfirmation | None, roles: dict) -> dict:
    """The candidate's own answer to this requirement, without upgrading it into proof."""
    if confirmation is None:
        return {**item, "confirmation": None}
    summary = {
        "id": str(confirmation.id),
        "response": confirmation.response,
        "skill_name": confirmation.skill_name,
        "category": confirmation.category,
        "work_experience_id": str(confirmation.work_experience_id) if confirmation.work_experience_id else None,
        "project_name": confirmation.project_name,
        "example": confirmation.example,
        "proficiency_level": confirmation.proficiency_level,
        "confirmed_at": confirmation.confirmed_at.isoformat() if confirmation.confirmed_at else None,
        "provenance": "candidate_confirmed",
        "independently_verified": False,
    }
    status, explanation = item["status"], item["explanation"]
    if confirmation.response == "not_possessed":
        status, explanation = (
            "not_possessed",
            "You said you do not have this. It stays off your CV and is listed as a gap you accept.",
        )
    elif confirmation.response == "unsure":
        if status not in {"matched", "partial"}:
            status, explanation = "unverified", "You left this unverified. It stays off your CV until you confirm it."
    elif status not in {"matched"}:
        if confirmation.response == "used_in_role":
            where = (
                roles.get(confirmation.work_experience_id)
                or (confirmation.project_name and f"project {confirmation.project_name}")
                or "a role or project"
            )
            status, explanation = (
                "matched",
                f"Shown by your own example from {where}. It is your statement; keep it accurate.",
            )
        else:
            status = "candidate_confirmed"
            explanation = "You confirmed you have this. It counts as a skill you state, not as shown experience" + (
                "; add the details when you can." if confirmation.response == "needs_details" else "."
            )
    refs = item["evidence"]
    if confirmation.response in CLAIMABLE_RESPONSES:
        refs = [
            {
                "kind": "demonstrated" if confirmation.response == "used_in_role" else "listed",
                "source_type": "skill_confirmation",
                "source_id": str(confirmation.id),
                "label": _confirmation_label(confirmation, roles),
                "excerpt": confirmation.example,
            },
            *refs,
        ][:6]
    return {**item, "status": status, "explanation": explanation, "evidence": refs, "confirmation": summary}


def _assess(requirement: dict, job, sources, experiences, education, today) -> dict:
    if requirement["category"] == "experience":
        status, explanation, refs = _experience_status(requirement, job, experiences, today)
    elif requirement["category"] == "education":
        status, explanation, refs = _education_status(requirement, education, sources, experiences)
    elif requirement["terms"]:
        status, explanation, refs = _status_for_terms(requirement["terms"], sources)
    else:
        status, explanation, refs = _status_for_words(requirement["source_text"], sources)
    return {**requirement, "status": status, "explanation": explanation, "evidence": refs[:6]}


def _finish(item: dict) -> dict:
    return {**item, "evidence_strength": _strength(item["evidence"]), "action": ACTIONS.get(item["status"])}


def _keyword_status(keyword: dict, sources: list[_Source]) -> str:
    term = keyword["term"]
    hits = {
        source.kind
        for source in sources
        if (_term_found(term, source.text) if keyword["kind"] == "tool" else stem(term) in source.stems)
    }
    for kind, label in (("demonstrated", "shown"), ("listed", "listed_only"), ("unconfirmed", "unconfirmed_only")):
        if kind in hits:
            return label
    return "absent"


def _score(essential, preferred, responsibilities, keywords, *, optimistic: bool) -> tuple[int | None, list[dict]]:
    def credit(status: str) -> float:
        return 1.0 if optimistic and status == "uncertain" else CREDIT[status]

    keyword_credit = {"shown": 1.0, "listed_only": 0.5, "unconfirmed_only": 1.0 if optimistic else 0.0, "absent": 0.0}
    parts = {
        "essential": [credit(item["status"]) for item in essential],
        "preferred": [credit(item["status"]) for item in preferred],
        "responsibilities": [credit(item["status"]) for item in responsibilities],
    }
    keyword_weights = [2 if k["importance"] == "high" else 1 for k in keywords]
    keyword_earned = sum(w * keyword_credit[k["status"]] for w, k in zip(keyword_weights, keywords))
    components: list[dict] = []
    total_weight = sum(WEIGHTS[name] for name, values in parts.items() if values) + (
        WEIGHTS["keywords"] if keywords else 0
    )
    if not total_weight:
        return None, []
    score = 0.0
    for name in ("essential", "preferred", "responsibilities", "keywords"):
        if name == "keywords":
            count, fraction = len(keywords), (keyword_earned / sum(keyword_weights) if keywords else None)
        else:
            values = parts[name]
            count, fraction = len(values), (sum(values) / len(values) if values else None)
        weight = WEIGHTS[name] * 100 / total_weight if count else 0.0
        points = (fraction or 0.0) * weight
        score += points
        components.append(
            {
                "name": name,
                "items": count,
                "base_weight": WEIGHTS[name],
                "effective_weight": round(weight, 1),
                "fraction_credited": round(fraction, 3) if fraction is not None else None,
                "points": round(points, 1),
            }
        )
    return round(score), components


def _employment_gaps(experiences, today: date) -> list[str]:
    intervals = _intervals(experiences, today)
    gaps = []
    for (_, previous_end), (next_start, _) in zip(intervals, intervals[1:]):
        months = (next_start.year - previous_end.year) * 12 + next_start.month - previous_end.month
        if months > 6:
            gaps.append(
                f"A gap of about {months} months between {previous_end.strftime('%b %Y')} and {next_start.strftime('%b %Y')} may prompt questions; be ready to explain it."
            )
    return gaps


def _recommendations(essential, preferred, keywords, fit, cv, unreviewed_relevant) -> list[dict]:
    items: list[tuple[int, str, str]] = []
    geo = fit["geographic_eligibility"]
    if geo["status"] == "not_eligible":
        items.append(
            (
                1,
                "eligibility",
                "The employer's wording excludes Kenya-based applicants. Improving the CV will not change this; consider other roles.",
            )
        )
    for item in fit["disqualifiers"]:
        items.append((1, "eligibility", f"Resolve before applying: {item['explanation']}"))
    if geo["status"] == "eligibility_unknown":
        items.append(
            (
                2,
                "eligibility",
                "Kenya eligibility is not established for this job. Review the listing's location wording or ask the employer before investing time.",
            )
        )
    for item in essential:
        if item["status"] == "uncertain":
            items.append(
                (
                    2,
                    "evidence",
                    f'Review and confirm the evidence for "{item["text"][:90]}" if it is accurate; it is currently not counted.',
                )
            )
    for item in essential:
        if item["status"] == "partial":
            items.append(
                (
                    3,
                    "evidence",
                    f'Strengthen "{item["text"][:90]}": {item["explanation"]} Add a confirmed example from your work if you have one.',
                )
            )
    for item in essential:
        if item["status"] == "missing":
            items.append(
                (
                    4,
                    "gap",
                    f'Essential requirement not shown: "{item["text"][:90]}". Do not claim it unless it is true; if you have done it, record it in your profile or evidence.',
                )
            )
    for risk in (cv or {}).get("formatting_risks", []):
        if risk["severity"] == "high":
            items.append(
                (3, "formatting", f"{risk['title']}: {risk['detail']} The CV that JobPilot exports avoids this layout.")
            )
    for contradiction in (cv or {}).get("contradictions", []):
        items.append(
            (3, "accuracy", f"Resolve a date difference for {contradiction['record']}. {contradiction['explanation']}")
        )
    if unreviewed_relevant:
        items.append(
            (
                4,
                "evidence",
                f"{unreviewed_relevant} unreviewed evidence item(s) mention this job's requirements. Review them in Evidence review.",
            )
        )
    for item in preferred:
        if item["status"] in {"missing", "partial"} and item["basis"] != "inferred":
            items.append((6, "gap", f'Preferred, not required: "{item["text"][:90]}" ({item["status"]}).'))
    absent = [
        k["term"] for k in keywords if k["status"] in {"absent", "unconfirmed_only"} and k["importance"] == "high"
    ]
    if absent:
        items.append(
            (
                7,
                "keywords",
                "Important terms not shown in your confirmed records: "
                + ", ".join(absent[:6])
                + ". Use them only where they truthfully describe your work.",
            )
        )
    for risk in (cv or {}).get("formatting_risks", []):
        if risk["severity"] == "medium":
            items.append((5, "formatting", f"{risk['title']}: {risk['detail']}"))
    ordered = sorted(enumerate(items), key=lambda pair: (pair[1][0], pair[0]))
    return [
        {"rank": rank, "priority": priority, "category": category, "text": text}
        for rank, (_, (priority, category, text)) in enumerate(ordered, start=1)
    ]


def build_ats_report(
    session: Session,
    job: CandidateJobDescription,
    storage: DocumentStorage,
    *,
    source_document_id: UUID | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    profile_id = job.candidate_profile_id
    profile = session.get(CandidateProfile, profile_id)

    def rows(model):
        return list(session.scalars(select(model).where(model.candidate_profile_id == profile_id)))

    skills, certifications = rows(CandidateSkill), rows(CandidateCertification)
    confirmations = [item for item in rows(CandidateSkillConfirmation) if item.status == "active"]
    experiences, education = rows(CandidateWorkExperience), rows(CandidateEducation)
    evidence = current_only(session, rows(CandidateEvidence))  # stale excerpts never count

    cv = None
    if source_document_id is not None:
        document = session.scalar(
            select(CandidateDocument).where(
                CandidateDocument.id == source_document_id, CandidateDocument.candidate_profile_id == profile_id
            )
        )
        if document is None or not is_candidate_source_document(document.document_kind, document.provenance):
            raise LookupError("Source document not found for this profile")
        extraction = session.scalar(
            select(DocumentExtraction).where(DocumentExtraction.source_document_id == document.id)
        )
        cv = analyze_cv_document(
            document, extraction, storage, experiences=experiences, education=education, evidence=evidence
        )

    analysis = extract_requirements(job.description, company=job.company)
    sources = _sources(profile, skills, certifications, experiences, education, evidence, cv, confirmations)
    roles = {item.id: f"{item.job_title} at {item.employer}" for item in experiences}
    answers = {
        item.requirement_key: item
        for item in sorted(confirmations, key=lambda c: c.confirmed_at or c.created_at)
        if item.job_description_id == job.id and item.requirement_key
    }
    assessed = [
        _finish(
            _apply_confirmation(
                _assess(item, job, sources, experiences, education, today), answers.get(item["key"]), roles
            )
        )
        for item in analysis["requirements"]
        if item["category"] != "eligibility"
    ]
    # Work style is listed for interview preparation, never scored or treated as a CV gap.
    work_style = [item for item in assessed if item["category"] == "work_style"]
    essential = [item for item in assessed if item["importance"] == "essential" and item["category"] != "work_style"]
    preferred = [item for item in assessed if item["importance"] == "preferred" and item["category"] != "work_style"]
    responsibilities = [item for item in assessed if item["category"] == "responsibility"]
    keywords = [{**k, "status": _keyword_status(k, sources)} for k in analysis["keywords"]]
    score, components = _score(essential, preferred, responsibilities, keywords, optimistic=False)
    potential, _ = _score(essential, preferred, responsibilities, keywords, optimistic=True)

    fit = compute_job_fit(session, job)
    geo = fit["geographic_eligibility"]
    eligibility_items = [item for item in analysis["requirements"] if item["category"] == "eligibility"]
    blocked = geo["status"] == "not_eligible" or bool(fit["disqualifiers"])
    if geo["status"] == "not_eligible":
        verdict = "excluded_by_employer"
        headline = (
            "The employer's wording excludes Kenya-based applicants. The skills score below does not change this."
        )
    elif fit["disqualifiers"]:
        verdict = "potential_disqualifiers"
        headline = (
            "A location or work-authorization requirement may rule you out. Resolve it before relying on the score."
        )
    elif score is None:
        verdict = "not_measurable"
        headline = "No checkable requirements were found in this job description."
    else:
        band = "strong" if score >= 75 else "moderate" if score >= 50 else "limited"
        verdict = f"{band}_match"
        headline = {
            "strong": "Your confirmed records support most of what this job asks for.",
            "moderate": "Your confirmed records support part of what this job asks for.",
            "limited": "Your confirmed records support little of what this job asks for.",
        }[band]
        if geo["status"] == "eligibility_unknown":
            headline += " Kenya eligibility is not established yet."

    concerns: list[dict] = []
    for item in fit["disqualifiers"]:
        concerns.append({"severity": "high", "text": item["explanation"]})
    for item in essential:
        if item["status"] == "missing":
            concerns.append(
                {
                    "severity": "high"
                    if item["category"] in {"experience", "education", "certification"}
                    else "medium",
                    "text": f"Essential requirement not shown: {item['text'][:120]}",
                }
            )
    for gap in _employment_gaps(experiences, today):
        concerns.append({"severity": "low", "text": gap})
    for contradiction in (cv or {}).get("contradictions", []):
        concerns.append({"severity": "medium", "text": contradiction["explanation"]})

    unreviewed_relevant = len(
        {
            ref["source_id"]
            for item in essential + preferred
            for ref in item["evidence"]
            if ref["source_type"] == "candidate_evidence" and ref["kind"] == "unconfirmed"
        }
    )
    if cv is not None:
        cv = {key: value for key, value in cv.items() if key != "text"}
    return {
        "analysis_version": ANALYSIS_VERSION,
        "job_description_id": str(job.id),
        "source_document_id": str(source_document_id) if source_document_id else None,
        "verdict": verdict,
        "headline": headline,
        "eligibility_overrides_score": blocked,
        "score": score,
        "potential_score": potential,
        "score_explanation": {
            "method": "Each requirement earns full credit when your records demonstrate it, half credit when it is only listed or partly shown, and none when it is uncertain or missing. Keywords earn full credit when demonstrated and half when only listed; important keywords count double. Category weights are shown below; a category with nothing to measure is left out and the others are scaled to 100.",
            "components": components,
            "potential_note": "The potential score counts uncertain items as if you confirmed them. It shows what reviewing your evidence could change, not a promise.",
            "limitations": LIMITATIONS,
        },
        "requirements": {
            "essential": essential,
            "preferred": preferred,
            "responsibilities": responsibilities,
            "work_style": work_style,
            "context": analysis.get("context", []),
            "eligibility": eligibility_items,
            "counts": analysis["counts"],
            "sections_found": analysis["sections_found"],
        },
        "keywords": keywords,
        "evidence_strength": {
            "method": "Kept separate from the score. Document or record: confirmed evidence from your documents, certifications or education. Work history: your recorded roles. Your statement: skills or examples you confirmed here. None of these is independent verification.",
            "essential": {
                level: sum(1 for item in essential if item["evidence_strength"] == level)
                for level in ("document_or_record", "work_history", "candidate_statement", "listed_only", "none")
            },
        },
        # What the candidate answered, whatever the records already showed.
        "candidate_answers": {
            "confirmed": sum(
                1
                for item in essential + preferred + work_style
                if (item.get("confirmation") or {}).get("response") in CLAIMABLE_RESPONSES
            ),
            "not_possessed": sum(
                1
                for item in essential + preferred + work_style
                if (item.get("confirmation") or {}).get("response") == "not_possessed"
            ),
            "unverified": sum(
                1
                for item in essential + preferred + work_style
                if (item.get("confirmation") or {}).get("response") == "unsure"
            ),
        },
        "eligibility": {
            "geographic": geo,
            "disqualifiers": fit["disqualifiers"],
            "location_items": [item for item in fit["uncertain"] if item["kind"] != "skill"]
            + fit["location_requirements_met"],
            "candidate_details_confirmed": fit["candidate_details_confirmed"],
        },
        "screening_concerns": concerns,
        "cv_document": cv,
        "recommendations": _recommendations(essential, preferred, keywords, fit, cv, unreviewed_relevant),
        "experience_summary": {
            "total_years": _years(_intervals(experiences, today)),
            "roles": len(experiences),
        },
    }
