"""Deterministic extraction of requirements from a job description.

Every requirement keeps the exact source text and its character offsets, the
heading it appeared under, and how it was established:

- ``explicit``: the wording or a clearly labelled heading states it;
- ``inferred``: derived from a listed duty or a tool named in descriptive text;
- ``ambiguous``: the wording mixes required and optional signals.

Descriptive text (about the company, benefits, legal notices) is not turned
into requirements, and neither is context about how the team works ("How we
work together", "Working with the founder can be intense"): that is kept as
``context`` for interview preparation. Eligibility wording is extracted but
scored separately.

Each requirement also says how it is used: ``cv_use`` is "cv" when a CV can
truthfully show it, or "interview" for personal qualities and work style
("You have a low ego", "Growth mindset"), which a CV cannot evidence and which
are better shown in an interview. ``key`` is a stable identifier derived from
the source wording, so a candidate's answer stays attached to the requirement.
"""

import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from app.services.ats_vocabulary import (
    CERTIFICATIONS,
    DEGREE_NAMES,
    PAST_TENSE,
    THIRD_PERSON,
    content_words,
    degree_level,
    named_terms,
    stem,
)
from app.services.countries import countries_named_in

MAX_REQUIREMENTS = 60
MAX_KEYWORDS = 25

SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # How the team works: context for the candidate, never a requirement or a CV gap.
    (
        "context",
        re.compile(
            r"\b(how we work|working (?:together|with (?:us|me|the founder|the team|our team))|our (?:culture|working style|ways? of working)|team culture|what to expect|what (?:it'?s|working here is) like|a day in the life|how we operate)\b",
            re.I,
        ),
    ),
    (
        "preferred",
        re.compile(
            r"\b(nice[- ]to[- ]haves?|preferred|bonus|desirable|a plus|plus points|extra credit|would be great|ideally)\b",
            re.I,
        ),
    ),
    (
        "essential",
        re.compile(
            r"\b(requirements?|required|must[- ]haves?|minimum|basic qualifications|what you('ll| will)? (need|bring)|what we('re| are) looking for|who you are|about you|you (have|bring|are)|qualifications|skills|experience|competencies|role (?:actually )?(?:demands|requires)|what (?:it|this role) takes)\b",
            re.I,
        ),
    ),
    (
        "responsibility",
        re.compile(
            r"\b(responsibilities|what you('ll| will) do|your role|the role|duties|day[- ]to[- ]day|in this role|key tasks|you will|your impact|what you('ll| will) be doing)\b",
            re.I,
        ),
    ),
    (
        "eligibility",
        re.compile(r"\b(location|work authori[sz]ation|eligibility|where you('ll| will)? work|remote policy)\b", re.I),
    ),
    (
        "descriptive",
        re.compile(
            r"\b(benefits|perks|about us|who we are|our (company|mission|values|team)|why (join|work)|compensation|salary|equal (employment )?opportunity|diversity|what we offer|how to apply|our offer|privacy|about the (team|company)|supports? [\w -]*employees|life at)\b",
            re.I,
        ),
    ),
]
ESSENTIAL_WORDS = re.compile(
    r"\b(must|required|requirement|essential|mandatory|need to|needs to|you need|minimum of|at least)\b", re.I
)
# Outside a requirements section only unmistakable wording makes a sentence a
# requirement; "maintain required standards" or "stock needs to be governed" are duties.
STRONG_ESSENTIAL = re.compile(
    r"\b(you must|must (?:have|be|hold|possess)|(?:is|are) (?:required|essential|mandatory)|required:|minimum of|at least \d|\d+\+? years)\b",
    re.I,
)
DUTY_VERBS = frozenset(
    {
        *PAST_TENSE,
        "oversee",
        "ensure",
        "own",
        "drive",
        "partner",
        "lead",
        "deliver",
        "build",
        "manage",
        "maintain",
        "support",
        "articulate",
        "focus",
        "contribute",
        "collaborate",
        "act",
        "serve",
        "champion",
        "define",
        "establish",
        "execute",
    }
)
PREFERRED_WORDS = re.compile(
    r"\b(preferred|nice to have|a plus|is a bonus|bonus|desirable|ideally|advantageous|beneficial|would be great|not required|optional)\b",
    re.I,
)
YEARS = re.compile(r"\b(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?(?:\+\s*)?years?\b", re.I)
CERTIFICATION_WORD = re.compile(r"\b(certifi(?:ed|cation|cations)|licen[cs]e[ds]?)\b", re.I)
EQUIVALENT = re.compile(r"\bor equivalent\b|\bequivalent (practical |work |professional )?experience\b", re.I)
EMPLOYMENT_TYPE = re.compile(
    r"\b(full[- ]time|part[- ]time|contract(?:or)?|freelance|temporary|permanent|internship|fixed[- ]term)\b", re.I
)
WORK_AUTH = re.compile(
    r"\b(authori[sz]ed to work|authori[sz]ation to work|right to work|work permit|work visa|eligible to work|visa sponsorship|sponsor)\b",
    re.I,
)
LOCATION_WORDS = re.compile(
    r"\b(reside|residing|residents?|located in|based in|live in|living in|time ?zones?|overlap|relocat\w*|on-?site|hybrid|in[- ]office)\b",
    re.I,
)
BULLET = re.compile(r"^\s*(?:[-*•▪◦●·]|\d{1,2}[.)])\s+")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
DUTY_START = re.compile(r"^(you will|you'll|you are going to)\b", re.I)
INLINE_HEADING = re.compile(r"^([A-Z][A-Za-z '’/&-]{1,40}):\s+(\S.*)$")
# Customer-facing and communication skills a CV can show through examples.
COMMUNICATION = re.compile(
    r"\b(communicat\w*|rapport|empath\w*|written|writing|verbal|on calls|phone|video|presentation\w*|customer[- ]facing|explain\w*|listen\w*|de-?escalat\w*|relationship[- ]building)\b",
    re.I,
)
# Personal qualities and work style: real requirements, but evidenced in an interview.
WORK_STYLE = re.compile(
    r"\b(ego|mindset|disagreement|urgency|resourceful\w*|count on you|reliab\w*|dependab\w*|minimal (?:instructions?|supervision|direction)|self[- ]starter|autonom\w*|adaptab\w*|positive|attitude|emotional intelligence|personally|offen[cs]e|proactive|owner'?s? mentality|curio\w*|humble|integrity|work ethic|hustle|initiative|team player|what you said|do what you|feedback without|thrive|composure|calm under)\b",
    re.I,
)
FIELD_OF_STUDY = re.compile(
    r"\b(?:degree|diploma|bachelor'?s?|master'?s?|bsc|msc)\b[^.;,]{0,20}?\b(?:in|of)\s+([A-Z][A-Za-z&]+(?:\s+(?:[A-Z][A-Za-z&]+|and|or))*)"
)


@dataclass
class Requirement:
    id: str
    category: str  # skill | tool | experience | education | certification | responsibility | eligibility
    importance: str  # essential | preferred | not_scored
    basis: str  # explicit | inferred | ambiguous
    text: str
    source_text: str
    source_start: int
    source_end: int
    section: str | None
    terms: list[str] = field(default_factory=list)
    min_years: int | None = None
    degree_level: int | None = None
    allows_equivalent: bool = False
    note: str | None = None
    key: str = ""
    cv_use: str = "cv"  # cv | interview | not_applicable


@dataclass
class _Unit:
    text: str
    start: int
    end: int
    heading: str | None
    section: str | None
    bulleted: bool


def _heading_kind(line: str) -> str | None:
    line = line.replace("’", "'")
    for kind, pattern in SECTION_PATTERNS:
        if pattern.search(line):
            return kind
    return None


def _looks_like_heading(line: str, next_line: str | None) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80 or BULLET.match(line):
        return False
    if stripped.endswith(":"):
        return True
    words = stripped.split()
    if len(words) > 8 or stripped[-1] in ".!?,;":
        return False
    is_title = stripped.isupper() or all(w[0].isupper() or not w[0].isalpha() for w in words if len(w) > 3)
    followed_by_list = bool(next_line and BULLET.match(next_line))
    return bool(_heading_kind(stripped)) and (is_title or followed_by_list)


def _units(description: str) -> list[_Unit]:
    units: list[_Unit] = []
    heading: str | None = None
    section: str | None = None
    lines = description.split("\n")
    offset = 0
    for index, line in enumerate(lines):
        line_start = offset
        offset += len(line) + 1
        if not line.strip():
            continue
        next_line = next((candidate for candidate in lines[index + 1 :] if candidate.strip()), None)
        if _looks_like_heading(line, next_line):
            heading = line.strip().rstrip(":").strip()
            section = _heading_kind(heading)
            continue
        if _is_subheading(line, next_line, section):
            heading = line.strip()  # "Keeping the product solid" groups duties; the section is unchanged
            continue
        bullet = BULLET.match(line)
        body_start = line_start + (bullet.end() if bullet else len(line) - len(line.lstrip()))
        body = description[body_start : line_start + len(line)].rstrip()
        inline = INLINE_HEADING.match(body)
        if inline and not bullet and _heading_kind(inline.group(1)):
            # "Location: Remote in Kenya" labels only this line's text.
            label_heading, label_section = inline.group(1).strip(), _heading_kind(inline.group(1))
            body_start += inline.start(2)
            body = inline.group(2)
            for unit in _sentence_units(body, body_start, label_heading, label_section):
                units.append(unit)
            continue
        if bullet:
            units.append(_Unit(body, body_start, body_start + len(body), heading, section, True))
            continue
        if section in {"essential", "preferred"} and len(body.split()) <= 60:
            # In a requirements list each line is one requirement, even when it has several
            # sentences ("You have a low ego. You handle disagreement calmly.").
            units.append(_Unit(body, body_start, body_start + len(body), heading, section, False))
            continue
        units.extend(_sentence_units(body, body_start, heading, section))
    return units


def _is_subheading(line: str, next_line: str | None, section: str | None) -> bool:
    """A short unpunctuated title inside a duties section, followed by fuller text."""
    stripped = line.strip()
    if section != "responsibility" or BULLET.match(line) or not stripped or not next_line:
        return False
    return (
        len(stripped.split()) <= 5
        and stripped[-1] not in ".!?:;,"
        and stripped[0].isupper()
        and len(next_line.split()) >= 6
    )


def requirement_key(text: str) -> str:
    """Stable identifier for a requirement: its normalised wording."""
    normalised = " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


def _sentence_units(body: str, body_start: int, heading: str | None, section: str | None) -> list[_Unit]:
    units: list[_Unit] = []
    cursor = 0
    for part in SENTENCE.split(body):
        position = body.find(part, cursor)
        cursor = position + len(part)
        text = part.strip()
        if len(text) >= 3:
            start = body_start + position + (len(part) - len(part.lstrip()))
            units.append(_Unit(text, start, start + len(text), heading, section, False))
    return units


def _importance(unit: _Unit) -> tuple[str, str] | None:
    """(importance, basis) for a unit, or None when it states no requirement."""
    in_requirements = unit.section in {"essential", "preferred"}
    essential = bool((ESSENTIAL_WORDS if in_requirements else STRONG_ESSENTIAL).search(unit.text))
    preferred = bool(PREFERRED_WORDS.search(unit.text))
    if not in_requirements and not essential and _starts_with_duty(unit.text):
        return None
    if essential and preferred:
        return ("essential", "ambiguous")
    if preferred:
        return ("preferred", "explicit")
    if essential:
        return ("essential", "explicit")
    if unit.section == "preferred":
        return ("preferred", "explicit")
    if unit.section == "essential":
        return ("essential", "explicit")
    return None


def _starts_with_duty(text: str) -> bool:
    first = text.split()[0].casefold().strip(",.:;") if text.split() else ""
    return first in DUTY_VERBS or first in THIRD_PERSON


def _eligibility(unit: _Unit) -> Requirement | None:
    countries = countries_named_in(unit.text)
    if WORK_AUTH.search(unit.text):
        kind = "Work authorization"
    elif LOCATION_WORDS.search(unit.text) and (
        countries or re.search(r"time ?zone|overlap|relocat|on-?site|hybrid|in[- ]office", unit.text, re.I)
    ):
        kind = "Location or working pattern"
    elif EMPLOYMENT_TYPE.search(unit.text) and len(unit.text.split()) <= 25:
        kind = "Employment type"
    else:
        return None
    return Requirement(
        id="",
        category="eligibility",
        importance="not_scored",
        basis="explicit" if ESSENTIAL_WORDS.search(unit.text) or unit.section == "eligibility" else "ambiguous",
        text=kind,
        source_text=unit.text,
        source_start=unit.start,
        source_end=unit.end,
        section=unit.heading,
        note="Eligibility is assessed separately from skills and never adds to the score.",
    )


def _requirement_for(unit: _Unit, importance: str, basis: str) -> Requirement:
    terms = named_terms(unit.text)
    years = YEARS.search(unit.text)
    level = degree_level(unit.text)
    base = dict(
        importance=importance,
        basis=basis,
        source_text=unit.text,
        source_start=unit.start,
        source_end=unit.end,
        section=unit.heading,
        terms=terms,
    )
    if years and re.search(r"experience|background|working|in (a|an) ", unit.text, re.I):
        minimum = int(years.group(1))
        return Requirement(
            id="",
            category="experience",
            text=f"{minimum}+ years of relevant experience",
            min_years=minimum,
            allows_equivalent=False,
            **base,
        )
    if level and re.search(
        r"degree|diploma|bachelor|master|phd|doctorate|graduate|school|bsc|msc|mba", unit.text, re.I
    ):
        study = FIELD_OF_STUDY.search(unit.text)
        field_name = re.sub(r"(\s+(?:or|and))+$", "", study.group(1)).strip() if study else ""
        base["terms"] = [field_name.casefold()] if field_name else []
        label = f"{DEGREE_NAMES[level].capitalize()} or higher" + (f" in {field_name}" if field_name else "")
        return Requirement(
            id="",
            category="education",
            text=label,
            degree_level=level,
            allows_equivalent=bool(EQUIVALENT.search(unit.text)),
            **base,
        )
    certs = [term for term in terms if term in CERTIFICATIONS]
    if certs or CERTIFICATION_WORD.search(unit.text):
        return Requirement(id="", category="certification", text=unit.text, **base)
    if COMMUNICATION.search(unit.text):
        return Requirement(id="", category="communication", text=unit.text, **base)
    if terms:
        return Requirement(id="", category="tool", text=unit.text, **base)
    if WORK_STYLE.search(unit.text):
        return Requirement(
            id="",
            category="work_style",
            text=unit.text,
            cv_use="interview",
            note="A personal quality or way of working. Show it with an example in an interview; "
            "it is not scored as a CV skill.",
            **base,
        )
    return Requirement(id="", category="skill", text=unit.text, **base)


def extract_requirements(description: str, *, company: str | None = None) -> dict:
    units = _units(description)
    requirements: list[Requirement] = []
    context: list[dict] = []
    seen: set[str] = set()
    seen_words: set[frozenset[str]] = set()
    descriptive_tools: Counter[str] = Counter()
    descriptive_first: dict[str, _Unit] = {}

    for unit in units:
        key = " ".join(unit.text.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        if unit.section == "descriptive":
            continue
        if unit.section == "context":
            context.append(
                {"text": unit.text, "section": unit.heading, "source_start": unit.start, "source_end": unit.end}
            )
            continue
        words = frozenset(stem(word) for word in content_words(unit.text))
        if len(words) >= 3 and words in seen_words:
            continue  # the same requirement repeated in other words order or punctuation
        seen_words.add(words)
        if len(unit.text.split()) <= 2 and not named_terms(unit.text):
            continue  # labels such as "Education" or "Remote-Global"
        eligibility = _eligibility(unit)
        if eligibility:
            requirements.append(eligibility)
            continue
        importance = _importance(unit)
        if importance:
            requirements.append(_requirement_for(unit, *importance))
        elif (
            unit.section == "responsibility"
            or DUTY_START.match(unit.text.replace("’", "'"))
            or (unit.section is None and _starts_with_duty(unit.text))
        ):
            if len(content_words(unit.text)) >= 2:
                requirements.append(
                    Requirement(
                        id="",
                        category="responsibility",
                        importance="not_scored",
                        basis="explicit",
                        text=unit.text,
                        source_text=unit.text,
                        source_start=unit.start,
                        source_end=unit.end,
                        section=unit.heading,
                        terms=named_terms(unit.text),
                    )
                )
            for term in named_terms(unit.text):
                descriptive_tools[term] += 1
                descriptive_first.setdefault(term, unit)
        else:
            for term in named_terms(unit.text):
                descriptive_tools[term] += 1
                descriptive_first.setdefault(term, unit)

    # Tools named only in duties or descriptive text are inferred, never stated requirements.
    stated_terms = {term for item in requirements if item.importance != "not_scored" for term in item.terms}
    for term, _count in descriptive_tools.most_common():
        if term in stated_terms:
            continue
        unit = descriptive_first[term]
        requirements.append(
            Requirement(
                id="",
                category="tool",
                importance="preferred",
                basis="inferred",
                text=term,
                source_text=unit.text,
                source_start=unit.start,
                source_end=unit.end,
                section=unit.heading,
                terms=[term],
                note="Named in the duties or description, not in a list of requirements.",
            )
        )

    requirements = requirements[:MAX_REQUIREMENTS]
    for index, item in enumerate(requirements, start=1):
        item.id = f"r{index}"
        item.key = requirement_key(
            item.source_text if item.category != "tool" or item.basis != "inferred" else f"tool:{item.text}"
        )
        if item.category == "eligibility":
            item.cv_use = "not_applicable"
    # Keywords come from the role itself, never from company, benefits or team-context text.
    role_text = "\n".join(unit.text for unit in units if unit.section not in {"descriptive", "context"})
    keywords = extract_keywords(role_text, requirements, company=company)
    return {
        "requirements": [asdict(item) for item in requirements],
        "context": context,
        "keywords": keywords,
        "counts": {
            "essential": sum(1 for item in requirements if item.importance == "essential"),
            "preferred": sum(1 for item in requirements if item.importance == "preferred"),
            "responsibilities": sum(1 for item in requirements if item.category == "responsibility"),
            "eligibility": sum(1 for item in requirements if item.category == "eligibility"),
        },
        "sections_found": sorted({unit.heading for unit in units if unit.heading}),
    }


def extract_keywords(description: str, requirements: list[Requirement], *, company: str | None = None) -> list[dict]:
    """Important role terms: named tools plus content words repeated or used in requirements."""
    company_words = {word.casefold() for word in (company or "").split()}
    scored: dict[str, dict] = {}
    requirement_text = " ".join(
        item.source_text
        for item in requirements
        if item.importance in {"essential", "preferred"} or item.category == "responsibility"
    )
    essential_text = " ".join(item.source_text for item in requirements if item.importance == "essential")
    for term in named_terms(description):
        count = len(re.findall(rf"(?<![\w+#]){re.escape(term)}(?![\w+#])", description, re.I)) or 1
        scored[term] = {
            "term": term,
            "count": count,
            "kind": "tool",
            "importance": "high" if named_terms(essential_text).count(term) or count >= 3 else "medium",
        }
    stems: Counter[str] = Counter()
    surface: dict[str, str] = {}
    for word in content_words(description):
        if word in company_words or word.isdigit() or len(word) < 4:
            continue
        key = stem(word)
        stems[key] += 1
        surface.setdefault(key, word)
    requirement_stems = {stem(word) for word in content_words(requirement_text)}
    for key, count in stems.most_common():
        word = surface[key]
        if any(word in term.split() for term in scored):
            continue
        if count >= 2 and key in requirement_stems:
            scored[word] = {
                "term": word,
                "count": count,
                "kind": "term",
                "importance": "high" if count >= 4 else "medium",
            }
    ordered = sorted(
        scored.values(),
        key=lambda item: (item["importance"] != "high", item["kind"] != "tool", -item["count"], item["term"]),
    )
    return ordered[:MAX_KEYWORDS]
