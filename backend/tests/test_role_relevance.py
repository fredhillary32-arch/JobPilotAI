"""Support/IT role relevance: title-only, whole-word, deterministic, independent of eligibility."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.models import JobListing
from app.services.role_relevance import CANDIDATE_SUBSTRINGS, FAMILY_LABELS, classify_title

API = "/api/v1/job-listings"
NOW = datetime.now(UTC)

POSITIVE = {
    "it_support": [
        "IT Support Specialist",
        "IT Support Engineer",
        "IT Technician",
        "IT Specialist",
        "IT Analyst",
        "IT Engineer",
        "IT Operations Analyst",
        "IT Administrator",
        "IT Officer",
        "Workplace IT Engineer",
        "IT Support Engineer - Finance Systems",
        "IT-Support Client Management (m/w/d)",
        "Werkstudentin (m/w/d) IT-Support",
    ],
    "technical_support": [
        "Technical Support Engineer",
        "Technical Support Specialist",
        "Tech Support",
        "L1 Support",
        "L2 Support Analyst",
        "L3 Support",
        "Tier 1 Support",
        "Tier 3 Support Technician",
        "Software Engineer - L3 Support",
        "Tier 1 - Support Agent",
        "First Level Support (m/w/d)",
        "2nd-Level Support",
    ],
    "help_desk": ["Help Desk Analyst", "Helpdesk Technician", "Service Desk Analyst", "IT Service Desk Engineer"],
    "application_support": [
        "Application Support Engineer",
        "Application Support Analyst",
        "Production Support Engineer",
        "Production Support Analyst",
        "Software Support Engineer",
    ],
    "desktop_support": [
        "Desktop Support",
        "Desktop Engineer",
        "Desktop Technician",
        "End User Computing Engineer",
        "Linux Desktop Support Associate (London UK office)",
    ],
    "network_support": [
        "Network Support Engineer",
        "Network Engineer",
        "Network Administrator",
        "Network Technician",
        "NOC Engineer",
        "Network Operations Engineer",
        "VoIP Network Technician",
    ],
    "systems_support": [
        "System Administrator",
        "Systems Administrator",
        "Sysadmin",
        "Systems Support Engineer",
        "Infrastructure Support Engineer",
        "Systemadministrator Teilzeit (m/w/d)",
    ],
    "voip_communications": [
        "VoIP Support Engineer",
        "Telephony Engineer",
        "Unified Communications Engineer",
        "Telecom Support Engineer",
    ],
    # Customer service and care were added to this family by the multi-source directive.
    "customer_support": [
        "Customer Support Specialist",
        "Customer Support Agent",
        "Customer Service Representative",
        "Customer Support Representative",
        "Customer Experience Specialist",
        "Customer Care Agent",
        "Customer Care Quality Analyst",
        "Client Support Specialist",
        "Member Support Associate",
        "User Support Analyst",
        "Customer Operations Specialist",
        "Escalations Specialist",
        "Customer Success Support Specialist",
    ],
    "ecommerce_support": ["E-commerce Customer Support", "E-commerce Operations Specialist"],
    "marketplace_support": [
        "Marketplace Support Specialist",
        "Seller Support Associate",
        "Merchant Support Representative",
    ],
    "order_support": [
        "Order Management Specialist",
        "Order Support Agent",
        "Returns and Refunds Specialist",
        "Refunds Specialist",
    ],
    "payments_support": ["Payments Support Analyst", "Payment Operations Specialist"],
    "delivery_support": ["Delivery Support Agent", "Logistics Support Specialist"],
    "trust_safety": ["Trust and Safety Operations Specialist", "Trust & Safety Analyst"],
    "product_support": ["SaaS Support Specialist", "Product Support Specialist"],
    "implementation_support": [
        "Implementation Specialist",
        "Implementation Support Engineer",
        "Customer Onboarding Specialist",
    ],
    "service_operations": ["Service Operations Analyst", "Remote Support Specialist"],
    "technical_customer_support": [
        "Customer Support Engineer",
        "Technical Customer Support Specialist",
        "Support Engineer",
        "Support Analyst",
        "Cloud Support Engineer",
    ],
}
FALSE_POSITIVES = [
    "Finance Intern - Technical Accounting & Treasury",
    "Telecom Account Executive",
    "Staff Design Engineer - Cloud Networking UX",
    "Open Source Networking Software Engineer",
    "Customer Success Manager",
    "Customer Success Architect",
    "Senior Technical Account Manager",
    "Credit Specialist",
    "Audit Technician",
    "Credit Administrator",
    "Dispatch Coordinator",
    "Sales Support Representative",
    "HR Support Officer",
    "Finance Support Analyst",
    "Social Network Marketing Lead",
    "Network Sales Manager",
    "Director of Customer Service",
    "Customer Experience Designer",
    "Supportive Housing Worker",
    "Head of Workplace IT",
    "Director of Support",
    "Manager, Support Engineering",
    "DevOps Engineer",
    "Site Reliability Engineer",
]
AMBIGUOUS = [
    "Support",
    "Support Specialist",
    "Network",
    "Telecom Specialist",
    "Distributed Systems Engineer",
    "Senior Backend Engineer",
    "Make it happen",
    "Visit Engineer",
    "Order Picker",
    "Payment Engineer",
    "Payments Engineer",
    "Returns Processor",
    "Trust Officer",
    "Logistics Coordinator",
    "Implementation Manager",
    "Customer Success Engineer",
    "Sales Support Engineer",
    "Senior SRE (Platform)",
]


@pytest.mark.parametrize(("family", "title"), [(f, t) for f, titles in POSITIVE.items() for t in titles])
def test_approved_titles_match_their_family_with_a_reason_naming_the_evidence(family: str, title: str) -> None:
    match = classify_title(title)
    assert match is not None, title
    assert match.family == family and match.label == FAMILY_LABELS[family]
    assert match.matched_text.casefold() in title.casefold()
    assert f'"{match.matched_text}"' in match.reason and FAMILY_LABELS[family] in match.reason


@pytest.mark.parametrize("title", FALSE_POSITIVES + AMBIGUOUS)
def test_known_false_positives_and_ambiguous_titles_do_not_match(title: str) -> None:
    assert classify_title(title) is None


def test_matching_is_case_insensitive_and_whitespace_tolerant() -> None:
    for title in ("it support specialist", "HELP DESK ANALYST", "noc engineer", "  Network   Engineer  "):
        assert classify_title(title) is not None, title


@pytest.mark.parametrize(
    "title",
    [
        "Credit Specialist",
        "Audit Technician",
        "Dispatch Coordinator",
        "Supportive Housing Worker",
        "Networking Software Engineer",
        "Helpdeskless Operations",
        "Systematic Analyst",
    ],
)
def test_whole_words_only(title: str) -> None:
    assert classify_title(title) is None


@pytest.mark.parametrize("title", [None, "", "   ", "!!!", "—", "IT", "Support / Network / Desk"])
def test_empty_null_and_unusual_titles(title) -> None:
    assert classify_title(title) is None


def test_candidate_substrings_cover_every_accepted_title() -> None:
    """The SQL pre-filter must never drop a title the classifier would accept."""
    for titles in POSITIVE.values():
        for title in titles:
            assert any(term in title.casefold() + " " for term in CANDIDATE_SUBSTRINGS), title


# --- API: filtering happens before totals and paging, on both endpoints -------


def _store(factory, title: str, location: str = "Remote, United States") -> str:
    with factory.begin() as session:
        item = JobListing(
            source_kind="greenhouse",
            source_key="gitlab",
            source_listing_id=str(uuid4()),
            source_url="https://boards-api.greenhouse.io/v1/boards/gitlab/jobs?content=true",
            listing_url="https://job-boards.greenhouse.io/gitlab/jobs/1",
            application_url="https://job-boards.greenhouse.io/gitlab/jobs/1",
            employer_name="GitLab",
            title=title,
            description_text="Join us.",
            location_text=location,
            source_category="direct_employer",
            content_hash=uuid4().hex * 2,
            dedupe_key=uuid4().hex * 2,
            source_status="active",
            posted_at=NOW - timedelta(hours=1),
            first_seen_at=NOW,
            last_seen_at=NOW,
            last_verified_at=NOW,
        )
        session.add(item)
        session.flush()
        return str(item.id)


def _seed(factory) -> tuple[set[str], set[str]]:
    relevant = {
        "Help Desk Analyst",
        "NOC Engineer",
        "IT Support Specialist",
        "Systems Administrator",
        "Telephony Engineer",
    }
    # Many titles the old substring list matched, placed to fill the first page of candidates.
    noise = {
        "Dispatch Coordinator",
        "Telecom Account Executive",
        "Customer Success Manager",
        "Credit Specialist",
        "Network Sales Manager",
        "Sales Support Representative",
        "Director of Support",
        "Finance Support Analyst",
    }
    for title in sorted(noise) + sorted(relevant):
        _store(factory, title)
    return relevant, noise


def test_listing_filter_returns_only_classified_titles_with_correct_totals_and_paging(
    api_client: TestClient, database
) -> None:
    relevant, _ = _seed(database[1])
    first = api_client.get(API, params={"role_family": "support_it", "limit": 2}).json()
    assert first["total"] == len(relevant) and len(first["items"]) == 2
    seen, offset = [], 0
    while offset < first["total"]:
        page = api_client.get(API, params={"role_family": "support_it", "limit": 2, "offset": offset}).json()
        assert page["total"] == len(relevant)
        seen += page["items"]
        offset += 2
    assert {item["title"] for item in seen} == relevant and len(seen) == len(relevant)
    for item in seen:
        assert item["role_match"]["family"] in FAMILY_LABELS and item["role_match"]["reason"]


def test_role_filter_combines_with_search_and_kenya_filters(api_client: TestClient, database) -> None:
    factory = database[1]
    _seed(factory)
    _store(factory, "Service Desk Analyst", location="Nairobi, Kenya")
    both = api_client.get(API, params={"role_family": "support_it", "kenya": "eligible"}).json()
    assert [item["title"] for item in both["items"]] == ["Service Desk Analyst"] and both["total"] == 1
    searched = api_client.get(API, params={"role_family": "support_it", "q": "noc"}).json()
    assert [item["title"] for item in searched["items"]] == ["NOC Engineer"]


def test_role_filter_never_changes_kenya_decisions(api_client: TestClient, database) -> None:
    factory = database[1]
    _seed(factory)
    _store(factory, "Service Desk Analyst", location="Nairobi, Kenya")
    unfiltered = {
        item["id"]: item["kenya_eligibility"] for item in api_client.get(API, params={"limit": 200}).json()["items"]
    }
    filtered = api_client.get(API, params={"role_family": "support_it", "limit": 200}).json()["items"]
    assert filtered and all(item["kenya_eligibility"] == unfiltered[item["id"]] for item in filtered)
    assert {item["kenya_eligibility"]["state"] for item in filtered} == {"ineligible", "eligible"}


def test_unfiltered_listings_still_report_role_match_or_none(api_client: TestClient, database) -> None:
    factory = database[1]
    _store(factory, "NOC Engineer")
    _store(factory, "Credit Specialist")
    items = {item["title"]: item for item in api_client.get(API).json()["items"]}
    assert items["NOC Engineer"]["role_match"]["matched_text"] == "NOC"
    assert items["Credit Specialist"]["role_match"] is None


def test_pipeline_role_filter_uses_the_same_classifier(api_client: TestClient, database) -> None:
    factory = database[1]
    relevant, _ = _seed(factory)
    profile_id = api_client.post("/api/v1/candidate-profiles", json={"name": "Amina Wanjiru"}).json()["id"]
    unfiltered = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/job-pipeline", params={"include_fit": False}
    ).json()
    result = api_client.get(
        f"/api/v1/candidate-profiles/{profile_id}/job-pipeline",
        params={"role_family": "support_it", "include_fit": False},
    ).json()
    cards = [card for items in result["queues"].values() for card in items]
    assert {card["title"] for card in cards} == relevant and sum(result["counts"].values()) == len(relevant)
    assert all(card["role_match"]["family"] in FAMILY_LABELS for card in cards)
    before = {
        card["listing_id"]: (card["queue"], card["eligibility"])
        for items in unfiltered["queues"].values()
        for card in items
    }
    assert all(before[card["listing_id"]] == (card["queue"], card["eligibility"]) for card in cards)
