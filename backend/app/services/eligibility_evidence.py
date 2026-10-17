"""Passages a reviewer should read before recording Kenya eligibility.

This only proposes text to review, across the whole description and the
location label. It never decides eligibility. Conflicts block a confirmation:
a listing that excludes Kenya, or claims worldwide hiring while restricting
locations elsewhere, cannot be recorded as accepting Kenya-based applicants.
"""
import re

from app.services.countries import countries_named_in
from app.services.job_fit import (
    NO_SPONSORSHIP,
    SENTENCE_SPLIT,
    SPONSORSHIP_OFFERED,
    STRICT_RESIDENCY,
    TIME_ZONE,
    WORK_AUTHORIZATION,
    WORLDWIDE,
)

KENYA = re.compile(r"\bKenya(?:n|ns)?\b")
EXCLUSION = re.compile(
    r"\b(not|cannot|can't|unable|except|excluding|exclude[sd]?|exclusion|outside of|no longer|isn't|aren't|ineligible)\b",
    re.I,
)
REGION = re.compile(
    r"\b(Africa|African|EMEA|Europe|European Union|EU|Americas|North America|LATAM|Latin America|APAC|Asia[- ]Pacific|Middle East|MENA)\b"
)
EMPLOYMENT_MODEL = re.compile(
    r"\b(independent contractor|contractor|freelance\w*|employer of record|EOR|B2B contract|full-time employee|permanent employee)\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT.split(text or "") if part.strip()]


def eligibility_passages(description: str | None, location: str | None) -> dict:
    passages: list[dict] = []

    def add(kind: str, field: str, sentence: str) -> None:
        passages.append({"kind": kind, "field": field, "sentence": sentence, "countries": countries_named_in(sentence)})

    if location:
        add("location_label", "location", location)
        if KENYA.search(location):
            add("kenya_named", "location", location)
    for sentence in _sentences(description or ""):
        if KENYA.search(sentence):
            add("kenya_exclusion" if EXCLUSION.search(sentence) else "kenya_named", "description", sentence)
        if WORLDWIDE.search(sentence):
            add("worldwide_claim", "description", sentence)
        if REGION.search(sentence):
            add("region", "description", sentence)
        if STRICT_RESIDENCY.search(sentence):
            add("residency_restriction", "description", sentence)
        if WORK_AUTHORIZATION.search(sentence):
            add("work_authorization", "description", sentence)
        if SPONSORSHIP_OFFERED.search(sentence) or NO_SPONSORSHIP.search(sentence):
            add("sponsorship", "description", sentence)
        if TIME_ZONE.search(sentence):
            add("time_zone", "description", sentence)
        if EMPLOYMENT_MODEL.search(sentence):
            add("employment_model", "description", sentence)

    kinds = {passage["kind"] for passage in passages}
    conflicts: list[str] = []
    if "kenya_exclusion" in kinds:
        conflicts.append("The listing contains a statement excluding Kenya.")
    if "worldwide_claim" in kinds and ({"residency_restriction", "kenya_exclusion"} & kinds):
        conflicts.append("The listing claims worldwide hiring but also restricts or excludes locations.")
    if "kenya_named" in kinds and "kenya_exclusion" in kinds:
        conflicts.append("The listing both names Kenya and excludes it.")
    return {"passages": passages, "conflicts": conflicts}
