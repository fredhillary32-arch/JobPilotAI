"""Reviewed CV writer: tailors a CV from the candidate's own confirmed records.

The writer may only restate what the records already say. It reorders bullets
by relevance to the job, starts them with the candidate's own action verb,
removes filler ("responsible for", "successfully", first person), and keeps a
reason for every change. A rewrite that would introduce any word or number not
present in the source (beyond a small set of connecting words and verb forms)
is discarded and the original wording is kept. Nothing from the job advert is
copied in, and nothing is added that the records do not support.

Skills the candidate confirmed for this job (or that the job names) can appear
in Core Skills or Tools, marked by their source as the candidate's own
statement; work-style traits never do. An example the candidate gave of using a
skill in a recorded role can become a bullet for that role, restated under the
same no-new-words rule. A confirmed skill is never turned into an achievement
or a number of years.
"""

import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateEvidence,
    CandidateJobDescription,
    CandidateProfile,
    CandidateSkill,
    CandidateSkillConfirmation,
    CandidateWorkExperience,
)
from app.models.skill_confirmation import CLAIMABLE_RESPONSES
from app.schemas.cv_generation import (
    CVClaim,
    CVReview,
    CVRole,
    CVSection,
    CVSourceReference,
    CVStructuredContent,
)
from app.services.ats_vocabulary import (
    BUZZWORDS,
    GERUNDS,
    PAST_TENSE,
    REWRITE_WORDS,
    THIRD_PERSON,
    content_words,
    named_terms,
    phrase_in,
    stem,
)
from app.services.cv_provider import _date_range, _education_claim
from app.services.cv_validation import is_substantive_bullet

WRITER_VERSION = "reviewed-writer/1"
MAX_BULLETS = 5
TOKEN = re.compile(r"[A-Za-z0-9+#']+")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
EVIDENCE_CATEGORIES = {"achievement", "employment_responsibility", "metric", "project"}
VERB_FORMS = set(PAST_TENSE) | {value.casefold() for value in PAST_TENSE.values()} | set(THIRD_PERSON)


def _clean(value: str) -> str:
    return " ".join(value.replace("•", " ").split()).strip(" -*")


def introduced_words(proposed: str, original: str) -> list[str]:
    """Words or numbers in ``proposed`` that ``original`` does not contain."""
    known = {token.casefold() for token in TOKEN.findall(original)} | {stem(t) for t in TOKEN.findall(original)}
    extra = []
    for token in TOKEN.findall(proposed):
        lowered = token.casefold()
        if lowered in known or stem(lowered) in known or lowered in REWRITE_WORDS:
            continue
        if any(char.isdigit() for char in token) or lowered not in extra:
            extra.append(token)
    numbers = set(NUMBER.findall(proposed)) - set(NUMBER.findall(original))
    return list(dict.fromkeys([*extra, *sorted(numbers)]))


def restate(text: str, *, past: bool) -> tuple[str, list[str], list[str]]:
    """Return (proposed text, reasons for changes, suggestions not applied)."""
    original = _clean(text)
    value = original
    reasons: list[str] = []
    suggestions: list[str] = []

    if "&" in value:
        value = value.replace(" & ", " and ").replace("&", " and ")
        reasons.append('Wrote "and" instead of "&", which some parsers drop.')
    if "—" in value or "–" in value:
        value = re.sub(r"\s*[—–]\s*", ", ", value)
        reasons.append("Replaced a long dash with a comma so the sentence reads and parses cleanly.")
    person = re.match(r"^(?:I|We)\s+(?:have\s+|had\s+)?(\w+)\b", value)
    if person and person.group(1).casefold() in VERB_FORMS:
        value = value[person.start(1) :]
        reasons.append("Removed first-person wording; CV statements conventionally start with the action.")
    match = re.match(
        r"^(?:was\s+|were\s+)?(?:responsible for|in charge of|tasked with)\s+(\w+ing)\b\s*(.*)$", value, re.I
    ) or re.match(
        r"^(?:my\s+)?(?:duties|responsibilities)\s+(?:included|include|were)\s+(\w+ing)\b\s*(.*)$", value, re.I
    )
    if match and match.group(1).casefold() in GERUNDS:
        converted = f"{PAST_TENSE[GERUNDS[match.group(1).casefold()]]} {match.group(2)}".strip()
        # Keep a list parallel: "managed X and onboarding Y" -> "managed X and onboarded Y".
        converted = re.sub(
            r"(\b(?:and|or)\s+|,\s+)(\w+ing)\b",
            lambda m: (
                m.group(1) + PAST_TENSE[GERUNDS[m.group(2).casefold()]].lower()
                if m.group(2).casefold() in GERUNDS
                else m.group(0)
            ),
            converted,
        )
        if re.search(r"(?:\b(?:and|or)\s+|,\s+)\w+ing\b", converted):
            suggestions.append(
                f'"{value[:60]}…" lists several duties; consider rewriting it to start with what you did.'
            )
        else:
            value = converted
            reasons.append('Starts with what you did rather than "responsible for" or "duties included".')
    elif re.match(r"^(?:was\s+)?involved in\s+", value, re.I):
        value = re.sub(r"^(?:was\s+)?involved in\s+", "Contributed to ", value, flags=re.I)
        reasons.append('"Contributed to" states your involvement more directly than "involved in".')
    elif re.match(r"^worked on\s+", value, re.I):
        value = re.sub(r"^worked on\s+", "Contributed to ", value, flags=re.I)
        reasons.append('"Contributed to" states your involvement more directly than "worked on".')
    elif re.match(r"^assisted (?:with|in)\s+(?!\w+ing\b)", value, re.I):
        value = re.sub(r"^assisted (?:with|in)\s+", "Supported ", value, flags=re.I)
        reasons.append('"Supported" is a clearer opening verb than "assisted with".')
    if re.match(r"^successfully\s+", value, re.I):
        value = re.sub(r"^successfully\s+", "", value, flags=re.I)
        reasons.append('Removed "successfully"; the result speaks for itself.')

    first = value.split()[0] if value.split() else ""
    base = THIRD_PERSON.get(first.casefold()) or (first.casefold() if first.casefold() in PAST_TENSE else None)
    if past and base and base in PAST_TENSE:
        value = PAST_TENSE[base] + value[len(first) :]
        reasons.append("Used the past tense for a role you have finished.")
    if value and value[0].islower():
        value = value[0].upper() + value[1:]
        reasons.append("Started with a capital letter.")
    if value and value[-1] not in ".!?":
        value += "."
        reasons.append("Ended with a full stop so every statement is punctuated the same way.")

    if re.match(r"^(?:was\s+)?responsible for\b", value, re.I):
        suggestions.append(f'"{value[:60]}…" still starts with "responsible for". Describe what you did if you can.')
    hits = [word for word in BUZZWORDS if phrase_in(word, value)]
    if hits:
        suggestions.append(
            f'"{hits[0]}" is a common filler phrase; replace it with a specific example if you have one.'
        )
    if len(value.split()) > 38:
        suggestions.append(f'"{value[:60]}…" is long. Consider splitting it so it is easier to scan.')

    extra = introduced_words(value, original)
    if extra:
        # Never let a restatement add content: fall back to the candidate's wording.
        fallback = original if original.endswith((".", "!", "?")) else original + "."
        return (
            fallback,
            (["Ended with a full stop so every statement is punctuated the same way."] if fallback != original else []),
            suggestions,
        )
    return value, reasons, suggestions


def language_quality(statements: Sequence[str]) -> dict:
    """Measurable writing-quality signals; none of them depends on an exact sentence."""
    openers = [s.split()[0].casefold().strip(",.") for s in statements if s.split()]
    counts = Counter(openers)
    words = [len(s.split()) for s in statements]
    return {
        "statements": len(statements),
        "distinct_openers": len(counts),
        "opener_diversity": round(len(counts) / len(openers), 2) if openers else 1.0,
        "repeated_openers": sorted(word for word, count in counts.items() if count > 2),
        "first_person": sum(1 for s in statements if re.search(r"\b(I|me|my|we|our)\b", s)),
        "weak_openers": sum(
            1
            for s in statements
            if re.match(
                r"^(?:was\s+)?(?:responsible for|duties included|worked on|involved in|assisted with)\b", s, re.I
            )
        ),
        "buzzwords": sorted({word for s in statements for word in BUZZWORDS if phrase_in(word, s)}),
        "average_words": round(sum(words) / len(words), 1) if words else 0.0,
        "long_statements": sum(1 for count in words if count > 38),
    }


def _vary_openers(claims: list[CVClaim]) -> list[CVClaim]:
    """Keep relevance order but avoid two neighbouring statements opening with the same word."""
    remaining = list(claims)
    ordered: list[CVClaim] = []
    while remaining:
        previous = ordered[-1].text.split()[0].casefold() if ordered else None
        choice = next((claim for claim in remaining if claim.text.split()[0].casefold() != previous), remaining[0])
        ordered.append(choice)
        remaining.remove(choice)
    return ordered


def _role_terms(report: dict | None) -> list[str]:
    if not report:
        return []
    terms: list[str] = []
    for group in ("essential", "preferred"):
        for item in report["requirements"][group]:
            terms.extend(item["terms"])
    terms.extend(keyword["term"] for keyword in report["keywords"])
    return list(dict.fromkeys(terms))


def _relevance(text: str, terms: list[str], job_stems: set[str]) -> int:
    return 3 * sum(1 for term in terms if phrase_in(term, text)) + len(
        job_stems & {stem(w) for w in content_words(text)}
    )


def _role_claims(experience, evidence, past: bool, terms, job_stems, suggestions, confirmations=()) -> list[CVClaim]:
    raw: list[tuple[str, CVSourceReference]] = []
    for item in confirmations:
        if item.response == "used_in_role" and item.work_experience_id == experience.id and item.example:
            raw.append(
                (
                    item.example,
                    CVSourceReference(
                        source_type="skill_confirmation",
                        source_id=str(item.id),
                        source_field="example",
                        claim_text=_clean(item.example),
                    ),
                )
            )
    if experience.description:
        raw.append(
            (
                experience.description,
                CVSourceReference(
                    source_type="work_experience",
                    source_id=str(experience.id),
                    source_field="description",
                    claim_text=_clean(experience.description),
                ),
            )
        )
    for index, achievement in enumerate(experience.achievements):
        raw.append(
            (
                achievement,
                CVSourceReference(
                    source_type="work_experience",
                    source_id=str(experience.id),
                    source_field=f"achievements[{index}]",
                    claim_text=_clean(achievement),
                ),
            )
        )
    for item in evidence:
        label = " ".join(filter(None, (item.source_section, item.description, item.source_excerpt))).casefold()
        linked = any(
            len(term) >= 3 and re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", label)
            for term in (experience.employer, experience.job_title)
        )
        if item.confirmation_status != "candidate_confirmed" or item.category not in EVIDENCE_CATEGORIES or not linked:
            continue
        raw.append(
            (
                item.description,
                CVSourceReference(
                    source_type="candidate_evidence",
                    source_id=str(item.id),
                    source_field="description",
                    claim_text=_clean(item.description),
                    source_document_id=str(item.source_document_id),
                    source_excerpt=item.source_excerpt,
                    source_start=item.source_start,
                    source_end=item.source_end,
                    evidence_confirmation_status="candidate_confirmed",
                ),
            )
        )
    claims: dict[str, tuple[int, CVClaim]] = {}
    for text, reference in raw:
        proposed, reasons, notes = restate(text, past=past)
        suggestions.extend(notes)
        if not is_substantive_bullet(proposed) or proposed.casefold() in claims:
            continue
        claim = CVClaim(
            text=proposed,
            source_references=[reference],
            origin="rewritten" if _clean(proposed) != _clean(text) else "source",
            change_reasons=reasons,
        )
        claims[proposed.casefold()] = (_relevance(proposed, terms, job_stems), claim)
    ranked = [claim for _, claim in sorted(claims.values(), key=lambda pair: (-pair[0], pair[1].text.casefold()))]
    chosen = _vary_openers(ranked[:MAX_BULLETS])
    for index, claim in enumerate(chosen):
        claim.key = f"role:{experience.id}:{index}"
    return chosen


def _composed_relevance_claim(report, experiences, evidence) -> CVClaim | None:
    """'Relevant experience with X, Y and Z at Employer.' built only from demonstrated matches."""
    if not report:
        return None
    by_id = {str(e.id): e for e in experiences}
    evidence_by_id = {str(e.id): e for e in evidence if e.confirmation_status == "candidate_confirmed"}
    picked: list[tuple[str, CVSourceReference, str | None]] = []
    for item in report["requirements"]["essential"] + report["requirements"]["preferred"]:
        if item["status"] != "matched" or item["category"] not in {"tool", "certification"}:
            continue
        for term in item["terms"]:
            if any(term == chosen for chosen, _, _ in picked) or len(picked) >= 4:
                continue
            for ref in item["evidence"]:
                if ref["kind"] != "demonstrated":
                    continue
                experience = by_id.get(ref["source_id"]) if ref["source_type"] == "work_experience" else None
                if experience:
                    fields = [("description", experience.description or "")] + [
                        (f"achievements[{i}]", a) for i, a in enumerate(experience.achievements)
                    ]
                    for field, value in fields:
                        if value and phrase_in(term, value):
                            picked.append(
                                (
                                    term,
                                    CVSourceReference(
                                        source_type="work_experience",
                                        source_id=str(experience.id),
                                        source_field=field,
                                        claim_text=_clean(value),
                                    ),
                                    experience.employer,
                                )
                            )
                            break
                elif ref["source_type"] == "candidate_evidence" and ref["source_id"] in evidence_by_id:
                    record = evidence_by_id[ref["source_id"]]
                    picked.append(
                        (
                            term,
                            CVSourceReference(
                                source_type="candidate_evidence",
                                source_id=str(record.id),
                                source_field="description",
                                claim_text=_clean(record.description),
                                source_document_id=str(record.source_document_id),
                                source_excerpt=record.source_excerpt,
                                source_start=record.source_start,
                                source_end=record.source_end,
                                evidence_confirmation_status="candidate_confirmed",
                            ),
                            None,
                        )
                    )
                if picked and picked[-1][0] == term:
                    break
    if len(picked) < 2:
        return None

    def display(term: str, reference: CVSourceReference) -> str:
        found = re.search(rf"(?<![\w+#]){re.escape(term)}(?![\w+#])", reference.claim_text, re.I)
        return found.group(0) if found else term

    names = [display(term, ref) for term, ref, _ in picked]
    listed = ", ".join(names[:-1]) + " and " + names[-1]
    employers = list(dict.fromkeys(employer for _, _, employer in picked if employer))
    text = f"Experience with {listed}" + (f" in roles at {' and '.join(employers)}." if employers else ".")
    references = list({(r.source_type, r.source_id, r.source_field): r for _, r, _ in picked}.values())
    return CVClaim(
        text=text,
        source_references=references,
        key="summary:relevance",
        origin="composed",
        change_reasons=["Added a sentence naming the job's requirements that your own work records demonstrate."],
    )


def _contact(profile: CandidateProfile) -> tuple[str, list[CVSourceReference]]:
    parts, refs = [], []
    for field in ("contact_email", "contact_phone", "location"):
        value = getattr(profile, field)
        if value and _clean(value):
            parts.append(_clean(value))
            refs.append(
                CVSourceReference(
                    source_type="profile_field", source_id=str(profile.id), source_field=field, claim_text=_clean(value)
                )
            )
    return " | ".join(parts), refs


class ReviewedCvWriter:
    """CVContentProvider that writes a tailored, reviewable draft."""

    def __init__(
        self,
        *,
        report: dict | None,
        certifications: Sequence[CandidateCertification] = (),
        source_document_id: str | None = None,
        confirmations: Sequence[CandidateSkillConfirmation] = (),
    ) -> None:
        self.report = report
        self.certifications = list(certifications)
        self.confirmations = [
            item for item in confirmations if item.status == "active" and item.response in CLAIMABLE_RESPONSES
        ]
        self.source_document_id = source_document_id
        self.suggestions: list[str] = []

    def generate(
        self,
        profile: CandidateProfile,
        job: CandidateJobDescription,
        skills: Sequence[CandidateSkill],
        experiences: Sequence[CandidateWorkExperience],
        education: Sequence[CandidateEducation],
        evidence: Sequence[CandidateEvidence],
    ) -> CVStructuredContent:
        terms = _role_terms(self.report)
        job_stems = {stem(w) for w in content_words(f"{job.job_title} {job.description}")}
        header = [
            CVSourceReference(
                source_type="profile_field",
                source_id=str(profile.id),
                source_field="name",
                claim_text=_clean(profile.name),
            )
        ]
        if profile.professional_headline:
            header.append(
                CVSourceReference(
                    source_type="profile_field",
                    source_id=str(profile.id),
                    source_field="professional_headline",
                    claim_text=_clean(profile.professional_headline),
                )
            )
        contact, contact_refs = _contact(profile)
        header.extend(contact_refs)

        summary_claims: list[CVClaim] = []
        if profile.summary and _clean(profile.summary):
            summary = _clean(profile.summary)
            proposed, reasons, notes = restate(summary, past=False)
            if proposed != summary and introduced_words(proposed, summary):
                proposed, reasons = summary, []
            self.suggestions.extend(notes)
            if re.search(r"\b(I|my)\b", summary):
                self.suggestions.append(
                    'Your summary uses "I" or "my". CV summaries usually leave these out; edit it if you prefer.'
                )
            summary_claims.append(
                CVClaim(
                    text=proposed,
                    key="summary:0",
                    origin="rewritten" if proposed != summary else "source",
                    change_reasons=reasons,
                    source_references=[
                        CVSourceReference(
                            source_type="profile_field",
                            source_id=str(profile.id),
                            source_field="summary",
                            claim_text=summary,
                        )
                    ],
                )
            )
            composed = _composed_relevance_claim(self.report, experiences, evidence)
            if composed:
                summary_claims.append(composed)

        def skill_rank(skill: CandidateSkill) -> tuple:
            relevant = any(phrase_in(term, skill.name) or phrase_in(skill.name, term) for term in terms)
            return (not relevant, skill.name.casefold())

        ordered = sorted(skills, key=skill_rank)
        tools = [s for s in ordered if named_terms(s.name)]
        core = [s for s in ordered if s not in tools]

        def skill_claim(skill: CandidateSkill) -> CVClaim:
            return CVClaim(
                text=_clean(skill.name),
                key=f"skill:{skill.id}",
                source_references=[
                    CVSourceReference(
                        source_type="skill", source_id=str(skill.id), source_field="name", claim_text=_clean(skill.name)
                    )
                ],
            )

        # Confirmed skills relevant to this job only: no keyword stuffing, no traits as skills.
        listed = {_clean(s.name).casefold() for s in skills}
        confirmed_tools: list[CVClaim] = []
        confirmed_core: list[CVClaim] = []
        for item in sorted(self.confirmations, key=lambda c: c.skill_name.casefold()):
            name = _clean(item.skill_name)
            relevant = item.job_description_id == job.id or phrase_in(name, f"{job.job_title} {job.description}")
            if not relevant or item.category == "work_style" or name.casefold() in listed or len(name.split()) > 6:
                continue
            listed.add(name.casefold())
            claim = CVClaim(
                text=name,
                key=f"confirmed-skill:{item.id}",
                source_references=[
                    CVSourceReference(
                        source_type="skill_confirmation",
                        source_id=str(item.id),
                        source_field="skill_name",
                        claim_text=name,
                    )
                ],
            )
            (confirmed_tools if item.category == "tool" or named_terms(name) else confirmed_core).append(claim)

        roles: list[CVRole] = []
        for experience in sorted(
            experiences,
            key=lambda e: (not e.current_role, -(e.end_date or e.start_date).toordinal(), -e.start_date.toordinal()),
        ):
            bullets = _role_claims(
                experience,
                evidence,
                not experience.current_role,
                terms,
                job_stems,
                self.suggestions,
                self.confirmations,
            )
            dates = _date_range(experience)
            roles.append(
                CVRole(
                    work_experience_id=experience.id,
                    job_title=_clean(experience.job_title),
                    employer=_clean(experience.employer),
                    dates=dates,
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
                            claim_text=dates,
                        ),
                    ],
                )
            )

        sections = [
            CVSection(heading="Professional Summary", claims=summary_claims),
            CVSection(heading="Tools and Platforms", claims=[skill_claim(s) for s in tools] + confirmed_tools),
            CVSection(heading="Core Skills", claims=[skill_claim(s) for s in core] + confirmed_core),
            CVSection(heading="Professional Experience", roles=roles),
            CVSection(heading="Education", claims=[_education_claim(item) for item in education]),
        ]
        if self.certifications:
            sections.append(
                CVSection(
                    heading="Certifications",
                    claims=[
                        CVClaim(
                            text=f"{_clean(c.name)}, {_clean(c.issuer)} ({c.issue_date.year})",
                            key=f"certification:{c.id}",
                            source_references=[
                                CVSourceReference(
                                    source_type="certification",
                                    source_id=str(c.id),
                                    source_field="name",
                                    claim_text=_clean(c.name),
                                ),
                                CVSourceReference(
                                    source_type="certification",
                                    source_id=str(c.id),
                                    source_field="issuer",
                                    claim_text=_clean(c.issuer),
                                ),
                                CVSourceReference(
                                    source_type="certification",
                                    source_id=str(c.id),
                                    source_field="issue_date",
                                    claim_text=c.issue_date.isoformat(),
                                ),
                            ],
                        )
                        for c in sorted(self.certifications, key=lambda c: c.issue_date, reverse=True)
                    ],
                )
            )
        return CVStructuredContent(
            candidate_name=_clean(profile.name),
            professional_heading=_clean(profile.professional_headline or ""),
            contact_details=contact,
            header_source_references=header,
            sections=sections,
            review=CVReview(
                writer_version=WRITER_VERSION,
                job_description_id=str(job.id),
                source_document_id=self.source_document_id,
                suggestions=list(dict.fromkeys(self.suggestions))[:12],
                ats_score=self.report["score"] if self.report else None,
                ats_potential_score=self.report["potential_score"] if self.report else None,
            ),
        )


def _editable_claims(content: CVStructuredContent):
    for section in content.sections:
        if section.heading == "Professional Summary":
            for claim in section.claims:
                yield section.heading, None, claim
        for role in section.roles:
            for claim in role.bullets:
                yield section.heading, role, claim


def change_log(content: CVStructuredContent) -> list[dict]:
    entries = []
    for heading, role, claim in _editable_claims(content):
        original = claim.source_references[0].claim_text if claim.origin != "composed" else None

        def bare(value: str) -> str:
            return value.strip().rstrip(".!?").casefold()

        # Capitalisation or a closing full stop alone is not a significant change.
        minor = original is not None and claim.origin == "rewritten" and bare(original) == bare(claim.text)
        entries.append(
            {
                "significance": "none" if claim.origin == "source" else "minor" if minor else "wording",
                "key": claim.key,
                "section": heading,
                "role": f"{role.job_title} at {role.employer}" if role else None,
                "original": original,
                "proposed": claim.text,
                "changed": claim.origin != "source",
                "origin": claim.origin,
                "reasons": claim.change_reasons,
                "evidence": [
                    {
                        "source_type": ref.source_type,
                        "source_field": ref.source_field,
                        "text": ref.claim_text,
                        "source_excerpt": ref.source_excerpt,
                        "confirmed": ref.evidence_confirmation_status == "candidate_confirmed"
                        or ref.source_type != "candidate_evidence",
                    }
                    for ref in claim.source_references
                ],
                "needs_confirmation": claim.needs_confirmation,
                "confirmation_note": claim.confirmation_note,
            }
        )
    return entries


class RevisionError(ValueError):
    pass


def apply_edits(content: CVStructuredContent, edits: dict[str, str], *, parent_draft_id: str) -> CVStructuredContent:
    """A new content version with the candidate's edits; the parent is not changed."""
    revised = content.model_copy(deep=True)
    claims = {claim.key: claim for _, _, claim in _editable_claims(revised) if claim.key}
    unknown = sorted(set(edits) - set(claims))
    if unknown:
        raise RevisionError(f"These statements cannot be edited: {', '.join(unknown)}")
    for key, text in edits.items():
        claim = claims[key]
        value = _clean(text).replace(" & ", " and ").replace("&", " and ")
        value = re.sub(r"\s*—\s*", ", ", value)
        if not value:
            raise RevisionError("An edited statement cannot be empty.")
        if value == claim.text:
            continue
        sources = " ".join(ref.claim_text for ref in claim.source_references)
        extra = introduced_words(value, sources)
        claim.text = value
        claim.origin = "candidate_edited"
        claim.change_reasons = ["Edited by you."]
        claim.needs_confirmation = bool(extra)
        claim.confirmation_note = (
            "Contains wording not found in your records: "
            + ", ".join(extra[:8])
            + ". Confirm it is accurate before exporting."
            if extra
            else None
        )
    revised.review = (revised.review or CVReview(writer_version=WRITER_VERSION, job_description_id="")).model_copy(
        update={
            "parent_draft_id": parent_draft_id,
            "approval_status": "pending_review",
            "approved_at": None,
            "attested_unconfirmed_statements": False,
            "acknowledged_incomplete": False,
        }
    )
    return revised


def approve(content: CVStructuredContent, *, attest: bool, acknowledge_incomplete: bool = False) -> CVStructuredContent:
    if content.review is None:
        raise RevisionError("Only drafts from the reviewed CV writer need approval.")
    pending = [claim for _, _, claim in _editable_claims(content) if claim.needs_confirmation]
    if pending and not attest:
        raise RevisionError(
            f"{len(pending)} statement(s) contain wording that is not in your records. "
            "Confirm they are accurate to approve this draft."
        )
    approved = content.model_copy(deep=True)
    approved.review = approved.review.model_copy(
        update={
            "approval_status": "approved",
            "approved_at": datetime.now(UTC),
            "attested_unconfirmed_statements": bool(pending),
            "acknowledged_incomplete": acknowledge_incomplete,
        }
    )
    return approved


def all_statements(content: CVStructuredContent) -> list[str]:
    return [claim.text for _, _, claim in _editable_claims(content)]
