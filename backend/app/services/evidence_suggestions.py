"""Deterministic evidence suggestions from a candidate's own extracted CV text.

Runs locally with fixed rules; no text leaves the machine. Each suggestion is an
exact slice of the current extracted text (its offsets are stored), described in
the CV's own words, and saved as ``unreviewed`` so the candidate must confirm or
reject it. Suggestions never repeat an excerpt that already has evidence for the
same document, whatever its review status, so repeated runs do not duplicate
claims or bring back rejected ones. Contact details and sections that are not
evidence of work (summary, references, interests) are skipped.
"""
import re
from dataclasses import dataclass

from app.models import CandidateEvidence
from app.services.ats_vocabulary import PAST_TENSE, THIRD_PERSON, degree_level, named_terms

MAX_SUGGESTIONS_PER_DOCUMENT = 50
MAX_SKILL_SUGGESTIONS = 25
MAX_LINE_CHARACTERS = 600

SECTION_KINDS = {
    "experience": {"experience", "work experience", "professional experience", "employment",
                   "employment history", "work history", "career history", "relevant experience"},
    "education": {"education", "education and training", "academic background", "academic qualifications"},
    "skills": {"skills", "technical skills", "core skills", "key skills", "skills and tools", "tools",
               "tools and platforms", "core competencies", "competencies", "technologies"},
    "certifications": {"certifications", "certificates", "licenses and certifications",
                       "licences and certifications", "training", "professional development", "qualifications"},
    "projects": {"projects", "key projects", "selected projects"},
    "achievements": {"achievements", "key achievements", "awards", "awards and achievements", "accomplishments"},
    "ignore": {"summary", "profile", "professional summary", "personal statement", "objective", "about me",
               "career objective", "references", "referees", "contact", "contact details", "personal details",
               "personal information", "interests", "hobbies", "hobbies and interests", "languages",
               "declaration"},
}
HEADING_KIND = {name: kind for kind, names in SECTION_KINDS.items() for name in names}
CONTACT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+|https?://|www\.|linkedin\.com|github\.com|(?:\+?\d[\d ()-]{7,}\d)|\bp\.?\s?o\.?\s?box\b", re.I)
BULLET = re.compile(r"^\s*(?:[-*•▪◦●·–]|\d{1,2}[.)])\s+")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
METRIC = re.compile(r"\d[\d,.]*\s*(?:%|percent\b)|[$£€]\s?\d|\b(?:ksh|kes|usd)\s?\d|\b\d{2,}[\d,]*\b", re.I)
ACHIEVEMENT_WORDS = re.compile(r"\b(achieved|awarded|won|recognised|recognized|exceeded|improved|increased|reduced|saved|cut|grew|launched|promoted)\b", re.I)
# A wrapped line continues the previous one only when that one ends mid-phrase.
CONTINUES = re.compile(r"(?:,|\b(?:and|or|the|of|for|to|with|a|an|in|on|at|across|by|from|including))\s*$", re.I)
SKILL_SPLIT =re.compile(r"\s*(?:,|;|\||•|·)\s*")
VERBS = {verb.casefold() for verb in PAST_TENSE.values()} | set(PAST_TENSE) | set(THIRD_PERSON)


@dataclass(frozen=True)
class Suggestion:
    category: str
    start: int
    end: int
    excerpt: str
    section: str | None


@dataclass
class _Line:
    start: int
    end: int
    text: str
    bulleted: bool


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _heading(text: str) -> str | None:
    key = _normalise(text.rstrip(":").replace("&", "and"))
    if key in HEADING_KIND:
        return HEADING_KIND[key]
    return None


def _lines(text: str) -> list[_Line]:
    lines: list[_Line] = []
    offset = 0
    for raw in text.split("\n"):
        line_start = offset
        offset += len(raw) + 1
        bullet = BULLET.match(raw)
        body_start = bullet.end() if bullet else len(raw) - len(raw.lstrip())
        body = raw[body_start:].rstrip()
        if body:
            lines.append(_Line(line_start + body_start, line_start + body_start + len(body), body, bool(bullet)))
    return lines


def _starts_with_verb(text: str) -> bool:
    first = text.split()[0].casefold().strip(",.;:") if text.split() else ""
    return first in VERBS


def _statement_category(text: str, kind: str | None) -> str:
    if kind == "projects":
        return "project"
    # Product names ("Microsoft 365") and years are not figures.
    figures = YEAR.sub(" ", text)
    for term in named_terms(figures):
        figures = re.sub(re.escape(term), " ", figures, flags=re.I)
    if METRIC.search(figures):
        return "metric"
    if kind == "achievements" or ACHIEVEMENT_WORDS.search(text):
        return "achievement"
    return "employment_responsibility"


def suggest_evidence(text: str) -> tuple[list[Suggestion], bool]:
    """(suggestions in document order, whether the per-document limit cut the list)."""
    lines = _lines(text)
    kind: str | None = None
    heading: str | None = None
    found: list[Suggestion] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if len(line.text) <= 60 and not line.bulleted and _heading(line.text):
            kind, heading = _heading(line.text), line.text.rstrip(":").strip()
            continue
        if kind == "ignore" or CONTACT.search(line.text) or len(line.text) > MAX_LINE_CHARACTERS:
            continue

        if kind == "skills":
            body, body_start = line.text, line.start
            label = re.match(r"^[A-Za-z][\w &/-]{0,30}:\s*", body)
            if label:
                body, body_start = body[label.end():], body_start + label.end()
            cursor = 0
            for item in SKILL_SPLIT.split(body):
                position = body.find(item, cursor)
                cursor = position + len(item)
                item = item.strip(" .")
                if not item or not re.search(r"[A-Za-z]", item) or len(item.split()) > 5 or len(item) > 60:
                    continue
                start = body_start + body.find(item, position)
                found.append(Suggestion("technical_skill", start, start + len(item), item, heading))
            continue

        if kind == "education":
            if degree_level(line.text):
                found.append(Suggestion("qualification", line.start, line.end, line.text, heading))
            continue

        if kind == "certifications":
            if len(line.text.split()) >= 2 and not (YEAR.fullmatch(line.text.strip())):
                found.append(Suggestion("qualification", line.start, line.end, line.text, heading))
            continue

        # Statements: experience, projects, achievements, or bullets under an unknown heading.
        end = line.end
        # Join wrapped continuation lines of a bullet (common in PDF text).
        while (line.bulleted and index < len(lines) and not lines[index].bulleted
               and not _heading(lines[index].text) and not CONTACT.search(lines[index].text)
               and not lines[index].text.isupper() and not YEAR.search(lines[index].text)
               and (lines[index].text[:1].islower() or lines[index].text[:1].isdigit()
                    or CONTINUES.search(text[line.start:end])
                    # "...using" / "Microsoft 365 ...": unfinished sentence, long non-verb line
                    or (text[end - 1] not in ".!?;:" and len(lines[index].text.split()) >= 6
                        and not _starts_with_verb(lines[index].text)))):
            end = lines[index].end
            index += 1
        excerpt = text[line.start:end]
        words = len(excerpt.split())
        if words < 5 or len(excerpt) > MAX_LINE_CHARACTERS:
            continue
        if kind in {"experience", "projects", "achievements"}:
            if not line.bulleted and not _starts_with_verb(excerpt):
                continue  # role titles, employers and dates are profile facts, not claims
        elif not (line.bulleted and _starts_with_verb(excerpt)):
            continue  # outside known sections only clear action bullets count
        found.append(Suggestion(_statement_category(excerpt, kind), line.start, end, excerpt, heading))

    unique: list[Suggestion] = []
    seen: set[str] = set()
    for suggestion in found:
        key = _normalise(suggestion.excerpt)
        if key not in seen:
            seen.add(key)
            unique.append(suggestion)
    # Statements and qualifications first; a long skills list must not crowd them out.
    statements = [s for s in unique if s.category != "technical_skill"][:MAX_SUGGESTIONS_PER_DOCUMENT]
    room = min(MAX_SKILL_SUGGESTIONS, MAX_SUGGESTIONS_PER_DOCUMENT - len(statements))
    skills = [s for s in unique if s.category == "technical_skill"][:room]
    chosen = sorted(statements + skills, key=lambda s: s.start)
    return chosen, len(chosen) < len(unique)


def new_evidence_for(
    profile_id,
    document_id,
    text: str,
    existing: list[CandidateEvidence],
) -> tuple[list[CandidateEvidence], int, bool]:
    """Unsaved evidence records for suggestions not already recorded for this document."""
    suggestions, limited = suggest_evidence(text)
    taken_spans = {(item.source_start, item.source_end) for item in existing}
    taken_text = {_normalise(item.source_excerpt) for item in existing if item.source_excerpt}
    records: list[CandidateEvidence] = []
    skipped = 0
    for suggestion in suggestions:
        if (suggestion.start, suggestion.end) in taken_spans or _normalise(suggestion.excerpt) in taken_text:
            skipped += 1
            continue
        if text[suggestion.start:suggestion.end] != suggestion.excerpt:
            continue  # never store an excerpt that is not the exact source slice
        records.append(CandidateEvidence(
            candidate_profile_id=profile_id,
            source_document_id=document_id,
            category=suggestion.category,
            description=" ".join(suggestion.excerpt.split())[:2000],
            source_excerpt=suggestion.excerpt,
            source_start=suggestion.start,
            source_end=suggestion.end,
            source_section=(suggestion.section or None) and suggestion.section[:200],
            confirmation_status="unreviewed",
        ))
    return records, skipped, limited
