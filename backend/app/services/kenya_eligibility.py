"""Strict, evidence-based Kenya eligibility decisions for discovered listings.

Fails closed: only explicit positive evidence from an authoritative source makes a
listing ``eligible``. Remote wording, regions that merely contain Kenya (EMEA,
Africa), company marketing that mentions Kenya, and missing restrictions never
count. States:

- ``eligible``: positive evidence and no unresolved blocking requirement;
- ``ineligible``: explicit applicable evidence rules out a Kenya-based applicant;
- ``unverified``: missing, ambiguous, conflicting, stale or non-authoritative evidence;
- ``needs_candidate_input``: positive evidence, but a requirement (such as work
  authorization) depends on a fact the candidate has not confirmed.

A candidate's own current review (docs/JOB_ELIGIBILITY_SPEC.md) takes precedence
over the automatic rules; a stale review is never trusted. Every evidence item is
an exact substring of the stored listing text, so decisions re-evaluate
automatically when the source wording changes. Location and nationality are never
used to infer work authorization.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CandidateEligibilityDetails, CandidateWorkAuthorization, JobListing, ListingEligibilityAssessment
from app.services.countries import _EXTRA_NAMES, COUNTRIES
from app.services.eligibility import evidence_is_current
from app.services.job_fit import NO_SPONSORSHIP, SENTENCE_SPLIT, SPONSORSHIP_OFFERED, STRICT_RESIDENCY, STRICT_WORK_AUTHORIZATION
from app.services.source_registry import entry_for_source

# One pass over the text instead of a search per country name; same case-sensitive,
# whole-word matching as app.services.countries, longest name first.
_NAME_TO_CODE = {name: code for code, country in COUNTRIES.items() for name in (country, *_EXTRA_NAMES.get(code, ()))}
_COUNTRY_PATTERN = re.compile(
    r"(?<![\w.])(" + "|".join(re.escape(name) for name in sorted(_NAME_TO_CODE, key=len, reverse=True)) + r")(?![\w])"
)


def countries_named_in(text: str) -> list[str]:
    return list(dict.fromkeys(_NAME_TO_CODE[match.group(1)] for match in _COUNTRY_PATTERN.finditer(text)))


ELIGIBLE, INELIGIBLE, UNVERIFIED, NEEDS_INPUT ="eligible", "ineligible", "unverified", "needs_candidate_input"
STATES = (ELIGIBLE, INELIGIBLE, UNVERIFIED, NEEDS_INPUT)
KENYA = "KE"

KENYA_PLACES = re.compile(r"\b(Kenya(?:n|ns)?|Nairobi|Mombasa|Kisumu|Nakuru|Eldoret)\b")
WORLDWIDE_LABEL = re.compile(r"\b(world-?wide|global(?:ly)?|anywhere|any location|all locations|international)\b", re.I)
# Description phrases that state where the work may be done. A bare "worldwide"
# ("customers worldwide", "managing teams worldwide") is never enough.
WORLDWIDE_TEXT = re.compile(
    r"\b(anywhere in the world|from any country|in any country|work from anywhere|working from anywhere|"
    r"globally remote|remote[ ,-]+(?:world-?wide|global(?:ly)?)|(?:world-?wide|global(?:ly)?)[ ,-]+remote|"
    r"based anywhere|located anywhere|wherever you are in the world|regardless of (?:your )?location)\b",
    re.I,
)
# Regions that contain Kenya but do not name it: never positive evidence by themselves.
REGIONS_WITH_KENYA = re.compile(r"\b(EMEA|MEA|Africa|African|Sub-Saharan Africa|East Africa|Eastern Africa)\b", re.I)
REGIONS_WITHOUT_KENYA = re.compile(
    r"\b(Americas|North America|South America|Central America|LATAM|Latin America|APAC|Asia[- ]Pacific|Asia|"
    r"Europe|European Union|EU|EEA|Oceania|Nordics|DACH|Benelux|Middle East|MENA|GCC|Caribbean|Australasia|AMER|NAMER)\b"
)
# Worldwide wording only counts when it is about this role, not company culture
# ("Oyster has no borders") or hiring philosophy, and is not hedged ("almost anywhere").
ROLE_SCOPED = re.compile(
    r"\b(?:this (?:\w+ ){0,4}(?:role|position|job|opportunity)|the (?:role|position)|"
    r"you (?:can|may|will) (?:be based|work|live)|(?:candidates?|applicants?) (?:can|may) be based|open to candidates)\b"
    r"|\blocation\s*:|^\s*remote[\s,-]*(?:global|world-?wide)\s*$",
    re.I,
)
PAY_CONTEXT = re.compile(r"\b(salary|pay range|base pay|compensation|on-target earnings|OTE|equity)\b", re.I)
# Role-specific evidence (the employer's location field or the title) outranks
# generic worldwide wording elsewhere in the description.
ROLE_SPECIFIC_NEGATIVE = {"location_label_excludes_kenya", "title_names_other_country", "residency_restricted_elsewhere"}
# An exclusion word close to the Kenya mention, not anywhere in a long sentence.
_PLACE = r"(?:Kenya(?:n|ns)?|Nairobi|Mombasa|Kisumu|Nakuru|Eldoret)"
KENYA_EXCLUDED = re.compile(
    rf"\b(?:not|cannot|can't|unable to|except|excluding|exclude[sd]?|outside(?: of)?|other than|no longer)\W+(?:\w+\W+){{0,5}}{_PLACE}\b"
    rf"|\b{_PLACE}\W+(?:\w+\W+){{0,4}}(?:is|are)\s+(?:not|ineligible|excluded)\b",
    re.I,
)
HEDGED = re.compile(r"\b(almost|most|many|certain|select(?:ed)?|some|several|preference|prefer(?:red|ably)?)\b", re.I)
REMOTE_ONLY = re.compile(r"^\s*(remote|home[- ]based|work from home|distributed|virtual)\s*$", re.I)
HIRING_CONTEXT = re.compile(
    r"\b(based in|based out of|located in|location|reside|residing|residents?|live in|living in|work from|working from|"
    r"hire|hiring|candidates?|applicants?|eligible|open to|remote(?:ly)?|home[- ]based|relocat\w*|office in|position is in|role is in)\b",
    re.I,
)
EXCLUSION = re.compile(
    r"\b(not|cannot|can't|unable|except|excluding|exclude[sd]?|exclusion|outside of|ineligible|other than)\b", re.I
)
ONSITE_TEXT = re.compile(r"\b(on-?site|in[- ]office|office[- ]based|hybrid)\b", re.I)
# Cities seen in employer location labels, so "Lagos" or "Toronto, ON" are recognised.
CITY_COUNTRIES = {
    "Nairobi": "KE", "Mombasa": "KE", "Kisumu": "KE", "Lagos": "NG", "Abuja": "NG", "Ogun": "NG", "Accra": "GH",
    "Kampala": "UG", "Kigali": "RW", "Dar es Salaam": "TZ", "Addis Ababa": "ET", "Johannesburg": "ZA",
    "Cape Town": "ZA", "Gauteng": "ZA", "Cairo": "EG", "Casablanca": "MA", "London": "GB", "Manchester": "GB",
    "Edinburgh": "GB", "Dublin": "IE", "Berlin": "DE", "Munich": "DE", "Paris": "FR", "Amsterdam": "NL",
    "Madrid": "ES", "Barcelona": "ES", "Lisbon": "PT", "Warsaw": "PL", "Bucharest": "RO", "Stockholm": "SE",
    "Toronto": "CA", "Vancouver": "CA", "Montreal": "CA", "New York": "US", "San Francisco": "US",
    "Seattle": "US", "Austin": "US", "Boston": "US", "Chicago": "US", "Los Angeles": "US", "Denver": "US",
    "Bangalore": "IN", "Bengaluru": "IN", "Mumbai": "IN", "Hyderabad": "IN", "Pune": "IN", "Delhi": "IN",
    "Singapore": "SG", "Taipei": "TW", "Beijing": "CN", "Shanghai": "CN", "Tokyo": "JP", "Sydney": "AU",
    "Melbourne": "AU", "Dubai": "AE", "Tel Aviv": "IL", "KSA": "SA", "Riyadh": "SA", "Tampa": "US", "Sao Paulo": "BR", "São Paulo": "BR", "Mexico City": "MX",
}
CITY_PATTERN = re.compile(r"\b(" + "|".join(re.escape(city) for city in sorted(CITY_COUNTRIES, key=len, reverse=True)) + r")\b")
US_STATE = re.compile(r",\s*(?:[A-Z]{2})\s*$")
CA_PROVINCE = re.compile(r",\s*(?:ON|BC|QC|AB|MB|NS)\s*$")

RULE_EXPLANATIONS = {
    "candidate_review_confirmed": "Your current review recorded the employer's wording accepting Kenya-based applicants.",
    "candidate_review_excluded": "Your current review recorded the employer's wording ruling out Kenya-based applicants.",
    "candidate_review_not_established": "Your review found the wording does not establish Kenya eligibility.",
    "candidate_review_stale": "The listing wording changed after your review, so it must be reassessed.",
    "review_evidence_invalid": "The recorded review quotation is not in the current listing text, so it cannot be relied on.",
    "location_label_names_kenya": "The employer's location for this job names Kenya.",
    "location_label_worldwide": "The employer's location for this job is worldwide.",
    "description_names_kenya": "The listing names Kenya as a place applicants may be based or work from.",
    "description_worldwide": "The listing says the role can be done from anywhere, with no conflicting restriction.",
    "residency_includes_kenya": "The residency requirement includes Kenya.",
    "location_label_excludes_kenya": "The employer's location for this job lists only places outside Kenya.",
    "title_names_other_country": "The job title names a country or market other than Kenya.",
    "description_excludes_kenya": "The listing excludes Kenya.",
    "residency_restricted_elsewhere": "The listing requires applicants to be in places that do not include Kenya.",
    "work_authorization_not_held": "The listing requires work authorization that you confirmed you do not hold, and offers no sponsorship.",
    "work_authorization_unconfirmed": "The listing requires work authorization you have not confirmed on your profile.",
    "conflicting_evidence": "The listing contains both supporting and restricting statements; it needs reassessment.",
    "source_not_authoritative": "Supporting wording comes from a source that is not the employer's verified job board.",
    "no_source_url": "The listing has no secure source link, so its evidence cannot be traced.",
    "region_without_kenya_named": "The listing names a region that includes Kenya but does not name Kenya.",
    "remote_without_country": "The listing says remote but does not say which countries applicants may be in.",
    "no_kenya_evidence": "The listing does not establish whether Kenya-based applicants may apply.",
}


@dataclass(frozen=True)
class CandidateFacts:
    """Only facts the candidate confirmed; nothing is inferred from location."""

    residence: str | None = None
    authorizations: dict[str, str] = field(default_factory=dict)


def candidate_facts(session: Session, profile_id) -> CandidateFacts:
    details = session.get(CandidateEligibilityDetails, profile_id)
    authorizations = {
        row.country_code: row.status
        for row in session.scalars(select(CandidateWorkAuthorization).where(CandidateWorkAuthorization.candidate_profile_id == profile_id))
    }
    return CandidateFacts(residence=details.country_of_residence if details else None, authorizations=authorizations)


def _evidence(kind: str, rule: str, quotation: str, field_name: str, countries=()) -> dict:
    return {"kind": kind, "rule": rule, "quotation": quotation, "field": field_name,
            "countries": [COUNTRIES[c] for c in countries if c in COUNTRIES], "explanation": RULE_EXPLANATIONS[rule]}


def _places(part: str) -> set[str]:
    found = set(countries_named_in(part))
    found |= {CITY_COUNTRIES[city] for city in CITY_PATTERN.findall(part)}
    if not found and US_STATE.search(part) and not CA_PROVINCE.search(part):
        found.add("US")
    if not found and CA_PROVINCE.search(part):
        found.add("CA")
    return found


def _label_evidence(label: str) -> tuple[list[dict], list[dict], str | None]:
    """(positive, negative, neutral rule) from the employer's location label."""
    parts = [part.strip() for part in re.split(r"[;|/]", label) if part.strip()]
    kenya = any(KENYA_PLACES.search(part) for part in parts)
    if kenya:
        return [_evidence("positive", "location_label_names_kenya", label, "location", [KENYA])], [], None
    if any(WORLDWIDE_LABEL.search(part) for part in parts):
        return [_evidence("positive", "location_label_worldwide", label, "location")], [], None
    known_elsewhere, region_with_kenya, remote_only, unknown = set(), False, False, False
    for part in parts:
        places = _places(part)  # countries first: "South Africa" is a country, not the region
        if places:
            known_elsewhere |= places
        elif REGIONS_WITH_KENYA.search(part):
            region_with_kenya = True
        elif REGIONS_WITHOUT_KENYA.search(part):
            known_elsewhere.add("region")
        elif REMOTE_ONLY.match(part) or re.fullmatch(r"(?i)remote\W*", part):
            remote_only = True
        else:
            unknown = True  # e.g. a city not in CITY_COUNTRIES
    if region_with_kenya:
        neutral = "region_without_kenya_named"
    elif known_elsewhere:
        # Every recognised place is outside Kenya; Kenyan towns are matched explicitly,
        # so an unrecognised town listed alongside them is not treated as Kenya.
        neutral = None
    else:
        neutral = "remote_without_country" if remote_only and not unknown else "no_kenya_evidence"
    if known_elsewhere and neutral is None:
        countries = sorted(c for c in known_elsewhere if c in COUNTRIES)
        return [], [_evidence("negative", "location_label_excludes_kenya", label, "location", countries)], None
    return [], [], neutral


def _description_evidence(text: str, facts: CandidateFacts | None) -> tuple[list, list, list, list]:
    positive, negative, needs, conflicts = [], [], [], []
    # Check each pattern once over the whole text; most descriptions contain none of them.
    has_kenya, has_worldwide = bool(KENYA_PLACES.search(text)), bool(WORLDWIDE_TEXT.search(text))
    has_residency, has_authorization = bool(STRICT_RESIDENCY.search(text)), bool(STRICT_WORK_AUTHORIZATION.search(text))
    if not (has_kenya or has_worldwide or has_residency or has_authorization):
        return positive, negative, needs, conflicts
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
    sponsorship = has_authorization and any(SPONSORSHIP_OFFERED.search(s) and not NO_SPONSORSHIP.search(s) for s in sentences)
    for sentence in sentences:
        residency = has_residency and STRICT_RESIDENCY.search(sentence)
        authorization = has_authorization and STRICT_WORK_AUTHORIZATION.search(sentence)
        # Country lookup is the expensive step; only sentences that can matter need it.
        countries = (countries_named_in(sentence) + [CITY_COUNTRIES[c] for c in CITY_PATTERN.findall(sentence)]
                     if residency or authorization else [])
        if has_kenya and KENYA_PLACES.search(sentence) and HIRING_CONTEXT.search(sentence):
            if KENYA_EXCLUDED.search(sentence):
                negative.append(_evidence("negative", "description_excludes_kenya", sentence, "description", [KENYA]))
            else:
                positive.append(_evidence("positive", "description_names_kenya", sentence, "description", [KENYA]))
        elif has_worldwide and WORLDWIDE_TEXT.search(sentence) and ROLE_SCOPED.search(sentence):
            if EXCLUSION.search(sentence) or HEDGED.search(sentence):
                conflicts.append(_evidence("conflict", "conflicting_evidence", sentence, "description"))
            elif not (REGIONS_WITH_KENYA.search(sentence) or REGIONS_WITHOUT_KENYA.search(sentence) or countries_named_in(sentence)):
                # "anywhere in the AMER or EMEA regions" is a region list, not worldwide.
                positive.append(_evidence("positive", "description_worldwide", sentence, "description"))
        if residency and not PAY_CONTEXT.search(sentence):  # "salary range ... for US residents" is about pay
            if KENYA in countries:
                positive.append(_evidence("positive", "residency_includes_kenya", sentence, "description", [KENYA]))
            elif countries or REGIONS_WITHOUT_KENYA.search(sentence):
                negative.append(_evidence("negative", "residency_restricted_elsewhere", sentence, "description", countries))
        if authorization and not SPONSORSHIP_OFFERED.search(sentence):
            required = countries or ([facts.residence] if facts and facts.residence else [])
            held = facts.authorizations if facts else {}
            if not required:
                needs.append(_evidence("requirement", "work_authorization_unconfirmed", sentence, "description"))
            elif any(held.get(code) == "not_authorized" for code in required) and not sponsorship:
                negative.append(_evidence("negative", "work_authorization_not_held", sentence, "description", required))
            elif not all(held.get(code) == "authorized" for code in required):
                needs.append(_evidence("requirement", "work_authorization_unconfirmed", sentence, "description", required))
    return positive, negative, needs, conflicts


def _source(listing: JobListing) -> tuple[str | None, str, bool]:
    url = next((u for u in (listing.listing_url, listing.application_url) if u and u.startswith("https://")), None)
    entry = entry_for_source(listing.source_kind, listing.source_key)
    category = listing.source_category or (entry.category if entry else None)
    authoritative = entry is not None and category != "aggregator"
    source_type = f"{listing.source_kind} board" + (f" ({category.replace('_', ' ')})" if category else " (unregistered)")
    return url, source_type, authoritative


def _decision(state: str, rule: str, listing: JobListing, evidence: list[dict], conflicts: list[dict],
              requirements: list[dict], assessment_id=None) -> dict:
    url, source_type, authoritative = _source(listing)
    return {
        "state": state, "rule": rule, "explanation": RULE_EXPLANATIONS[rule],
        "evidence": evidence, "conflicts": conflicts, "requirements": requirements,
        "source_url": url, "source_type": source_type, "source_authoritative": authoritative,
        "checked_at": listing.last_verified_at, "assessment_id": assessment_id,
    }


def decide(listing: JobListing, assessment: ListingEligibilityAssessment | None = None,
           facts: CandidateFacts | None = None) -> dict:
    description, label = listing.description_text or "", listing.location_text or ""
    url, _, authoritative = _source(listing)

    if assessment is not None:
        if not evidence_is_current(listing, assessment):
            return _decision(UNVERIFIED, "candidate_review_stale", listing, [], [], [], assessment.id)
        quoted_field = description if assessment.evidence_field == "description" else label
        if assessment.outcome == "eligible_confirmed":
            if not assessment.quotation or assessment.quotation not in quoted_field:
                return _decision(UNVERIFIED, "review_evidence_invalid", listing, [], [], [], assessment.id)
            if url is None:
                return _decision(UNVERIFIED, "no_source_url", listing, [], [], [], assessment.id)
            item = _evidence("positive", "candidate_review_confirmed", assessment.quotation, assessment.evidence_field)
            return _decision(ELIGIBLE, "candidate_review_confirmed", listing, [item], [], [], assessment.id)
        if assessment.outcome == "not_eligible":
            items = ([_evidence("negative", "candidate_review_excluded", assessment.quotation, assessment.evidence_field)]
                     if assessment.quotation and assessment.quotation in quoted_field else [])
            return _decision(INELIGIBLE, "candidate_review_excluded", listing, items, [], [], assessment.id)
        return _decision(UNVERIFIED, "candidate_review_not_established", listing, [], [], [], assessment.id)

    positive, negative, neutral = _label_evidence(label) if label else ([], [], "no_kenya_evidence")
    label_lists_countries = any(countries_named_in(part) for part in re.split(r"[;|/]", label)) if label else False
    text_positive, text_negative, needs, conflicts = _description_evidence(description, facts)
    positive, negative = positive + text_positive, negative + text_negative
    # A title such as "Account Executive, US" or "Support Engineer (EMEA)" states the role's market.
    title_places = _places(listing.title) - {KENYA}
    if REGIONS_WITHOUT_KENYA.search(listing.title):
        title_places.add("region")
    if title_places and not KENYA_PLACES.search(listing.title):
        negative.append(_evidence("negative", "title_names_other_country", listing.title, "title", sorted(title_places)))
    if any(e["rule"] == "location_label_names_kenya" for e in positive):
        # An onsite or hybrid role whose own location includes Kenya is attendable.
        negative = [e for e in negative if e["rule"] != "location_label_excludes_kenya"]

    # A requirement the candidate confirmed they do not meet is not a conflict with
    # open location wording; it rules the candidate out.
    unmet = [e for e in negative if e["rule"] == "work_authorization_not_held"]
    if unmet:
        return _decision(INELIGIBLE, "work_authorization_not_held", listing, unmet + positive, conflicts, needs)
    generic_only = positive and all(e["rule"] == "description_worldwide" for e in positive)
    if generic_only and any(e["rule"] in ROLE_SPECIFIC_NEGATIVE for e in negative):
        # e.g. label "Remote, United Kingdom" with a template "Remote-Global" line: the
        # role's own location decides; the generic wording is kept as a recorded conflict.
        return _decision(INELIGIBLE, negative[0]["rule"], listing, negative, positive + conflicts, needs)
    if generic_only and label_lists_countries:
        # A country list in the location field narrows generic "work from anywhere" text.
        return _decision(UNVERIFIED, "conflicting_evidence", listing, positive, conflicts, needs)
    if positive and negative:
        return _decision(UNVERIFIED, "conflicting_evidence", listing, positive, negative + conflicts, needs)
    if negative:
        return _decision(INELIGIBLE, negative[0]["rule"], listing, negative, conflicts, needs)
    if positive and conflicts:
        return _decision(UNVERIFIED, "conflicting_evidence", listing, positive, conflicts, needs)
    if positive:
        if url is None:
            return _decision(UNVERIFIED, "no_source_url", listing, positive, [], needs)
        if not authoritative:
            return _decision(UNVERIFIED, "source_not_authoritative", listing, positive, [], needs)
        if needs:
            return _decision(NEEDS_INPUT, needs[0]["rule"], listing, positive, [], needs)
        return _decision(ELIGIBLE, positive[0]["rule"], listing, positive, [], [])
    return _decision(UNVERIFIED, neutral or "no_kenya_evidence", listing, [], conflicts, needs)


_CACHE: dict[tuple, dict] = {}
_CACHE_LIMIT = 5000


def decide_cached(listing: JobListing, assessment: ListingEligibilityAssessment | None,
                  facts: CandidateFacts | None) -> dict:
    """decide() memoised on every input it reads, so any wording change re-evaluates."""
    key = (
        listing.id, hash(listing.description_text), listing.location_text, listing.title,
        listing.listing_url, listing.application_url, listing.source_kind, listing.source_key,
        listing.source_category, listing.last_verified_at,
        (assessment.id, hash(assessment.examined_description), assessment.examined_location) if assessment else None,
        (facts.residence, tuple(sorted(facts.authorizations.items()))) if facts else None,
    )
    if key not in _CACHE:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[key] = decide(listing, assessment, facts)
    return _CACHE[key]
