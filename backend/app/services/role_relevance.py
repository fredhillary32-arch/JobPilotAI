"""Deterministic role relevance from a job title.

Title-only by design: descriptions mention "support" or "network" incidentally.
Matching is case-insensitive and whole-word, so "Credit Specialist" never
matches "IT Specialist" and "Dispatch" never matches "ISP". Generic words
(support, network, telecom, technical account) never qualify a title on their
own; a title qualifies only through an explicit role phrase such as
"Help Desk", "NOC", "Seller Support" or "Customer Service". When in doubt it
does not match.

Families are grouped into the selectable role groups in ROLE_GROUPS. Leadership,
DevOps/SRE and customer-success management titles are always excluded, and
business functions (sales, HR, finance, ...) are excluded unless the title names
a clearly technical support role.

This is independent of Kenya eligibility: it never reads or changes it.
"""

import re
from dataclasses import dataclass

ROLE_GROUPS = {
    "support_it": "Technical and IT support",
    "customer_support": "Customer support and service",
    "ecommerce_support": "E-commerce and marketplace support",
    "operations_support": "Related support operations",
}
_ROLE = r"(?:support|technician|specialist|analyst|engineer|administrator|admin|officer|associate|agent|representative)"
_ROLE_WORDS = _ROLE[3:-1]
_PERSON = r"(?:specialist|analyst|agent|associate|representative|advisor|adviser|executive|officer|coordinator|consultant|engineer|technician|lead)"


@dataclass(frozen=True)
class Family:
    id: str
    group: str
    label: str
    pattern: re.Pattern[str]
    strong: bool  # technical enough to override a business-function word


def _family(family_id: str, group: str, label: str, pattern: str, strong: bool = False) -> Family:
    return Family(family_id, group, label, re.compile(pattern, re.I), strong)


# Checked in order; the first family whose phrase appears in the title wins.
FAMILIES: list[Family] = [
    _family("help_desk", "support_it", "Help desk and service desk", r"\b(?:help\s?desk|service\s?desk)\b", True),
    _family(
        "technical_support",
        "support_it",
        "Technical support",
        # Separators vary in real titles: "Tier 1 Support", "Tier 1 - Support Agent", "First Level Support".
        r"\b(?:technical|tech)\s+support\b|\b(?:L[1-3]|tier\s?[1-3]|level\s?[1-3])(?:\s*[-–]\s*|\s+)support\b|"
        r"\b(?:first|second|third|1st|2nd|3rd)[\s-]+level\s+support\b|\bsupport\s+(?:L[1-3]|tier\s?[1-3])\b",
        True,
    ),
    _family(
        "application_support",
        "support_it",
        "Application, software and production support",
        r"\b(?:applications?|app|production|software)\s+support\b",
        True,
    ),
    _family(
        "desktop_support",
        "support_it",
        "Desktop and end-user computing",
        r"\bdesktop\s+"
        + _ROLE
        + r"\b|\bdesktop\s+(?:&|and)\s+devices\s+support\b|\bend[\s-]user\s+(?:computing|support)\b|\bEUC\b",
        True,
    ),
    _family(
        "network_support",
        "support_it",
        "Network and operations support",
        r"\bnetwork\s+(?:operations|" + _ROLE_WORDS + r")\b|\bNOC\b",
        True,
    ),
    _family(
        "systems_support",
        "support_it",
        "Systems and infrastructure support",
        r"\bsystems?\s+(?:administrator|admin|support)\b|\bsysadmin\b|\bsystemadministrator(?:in)?\b|\binfrastructure\s+(?:support|technician|administrator)\b",
        True,
    ),
    _family(
        "voip_communications",
        "support_it",
        "VoIP, telephony and telecom support",
        r"\b(?:voip|telephony|unified\s+communications)\b|\btelecom(?:munications)?\s+(?:support|technician|engineer)\b",
        True,
    ),
    # "IT" only as its own word directly before a role word ("IT Support", "Workplace IT Engineer").
    _family(
        "it_support", "support_it", "IT support", r"\bIT(?:\s+|-)(?:operations|helpdesk|" + _ROLE_WORDS + r")\b", True
    ),
    # E-commerce and marketplace support.
    _family(
        "ecommerce_support",
        "ecommerce_support",
        "E-commerce support and operations",
        r"\be-?commerce\s+(?:customer\s+support|support|operations|" + _PERSON[3:-1] + r")\b",
    ),
    _family(
        "marketplace_support",
        "ecommerce_support",
        "Marketplace, seller and merchant support",
        r"\b(?:marketplace|seller|merchant|vendor|partner)\s+(?:support|operations\s+"
        + _PERSON
        + r"|success\s+"
        + _PERSON
        + r")\b",
    ),
    _family(
        "order_support",
        "ecommerce_support",
        "Orders, returns and refunds",
        r"\border\s+(?:management|support|fulfil?lment)\b|\b(?:returns?|refunds?)\s+(?:and\s+refunds?\s+)?(?:support|"
        + _PERSON[3:-1]
        + r")\b",
    ),
    _family(
        "payments_support",
        "ecommerce_support",
        "Payments support",
        # Support-type words only: a "Payments Engineer" builds payment systems.
        r"\bpayments?\s+(?:support|operations\s+" + _PERSON + r"|specialist|analyst|agent|associate|representative)\b",
    ),
    _family(
        "delivery_support",
        "ecommerce_support",
        "Delivery and logistics support",
        r"\b(?:delivery|logistics|shipping)\s+support\b",
    ),
    _family(
        "trust_safety",
        "ecommerce_support",
        "Trust and safety operations",
        r"\btrust\s+(?:and|&)\s+safety\s+(?:operations|" + _PERSON[3:-1] + r"|moderator)\b",
    ),
    # Related support operations.
    _family(
        "product_support", "operations_support", "SaaS and product support", r"\b(?:saas|product|platform)\s+support\b"
    ),
    _family(
        "implementation_support",
        "operations_support",
        "Implementation and onboarding",
        r"\bimplementation\s+(?:support|specialist|analyst|consultant|engineer)\b|\b(?:customer\s+)?onboarding\s+(?:specialist|associate|coordinator|analyst)\b",
    ),
    _family(
        "service_operations",
        "operations_support",
        "Service operations",
        r"\bservice\s+operations\s+(?:" + _PERSON[3:-1] + r")\b|\bremote\s+support\b",
    ),
    # Customer support and service phrases that are specific enough to come before the
    # generic "Support Engineer/Analyst" check below.
    _family(
        "customer_support",
        "customer_support",
        "Customer support and service",
        r"\bcustomer\s+(?:service|care)\b|\bcustomer\s+experience\s+" + _PERSON + r"\b|"
        r"\bcustomer\s+operations\s+" + _PERSON + r"\b|\b(?:client|member|user|player|guest)\s+support\b|"
        r"\bescalations?\s+(?:specialist|analyst|engineer|agent|manager)\b|\bcustomer\s+success\s+support\b",
    ),
    _family(
        "technical_customer_support",
        "support_it",
        "Technical customer support",
        r"\btechnical\s+customer\s+support\b|\bcustomer\s+support\s+(?:engineer|technician)\b|\bsupport\s+(?:engineer|analyst|technician)\b",
    ),
    # Plain "Customer Support Specialist/Agent" (not engineer/technician, handled above).
    _family("customer_support", "customer_support", "Customer support and service", r"\bcustomer\s+support\b"),
]
FAMILY_LABELS = {family.id: family.label for family in FAMILIES}
FAMILY_GROUP = {family.id: family.group for family in FAMILIES}

# Always excluded, whatever else the title says.
LEADERSHIP = re.compile(r"\b(?:director|manager|head|vp|vice\s+president|chief|cto|cio|managing)\b", re.I)
DEVOPS_SRE = re.compile(r"\b(?:devops|site\s+reliability|SRE)\b", re.I)
# Customer success is account management unless it says "support"; customer experience
# design/research is not support.
NOT_SUPPORT = re.compile(
    r"\bcustomer\s+success\b(?!\s+support)|\bcustomer\s+experience\s+(?:designer|design|research\w*)\b", re.I
)
# Business functions: excluded unless a strong technical family matched.
BUSINESS = re.compile(
    r"\b(?:sales|account\s+executive|account\s+manager|business\s+development|telesales|recruit\w*|talent|"
    r"people|HR|human\s+resources|finance|financial|accounting|accountant|credit|audit\w*|marketing|content|"
    r"design|designer|legal|counsel)\b",
    re.I,
)

# Every family pattern needs one of these substrings, so a database ILIKE on them
# narrows candidates without ever dropping a title the classifier would accept.
CANDIDATE_SUBSTRINGS = (
    "help desk",
    "helpdesk",
    "service desk",
    "servicedesk",
    "support",
    "desktop",
    "end user",
    "end-user",
    "euc",
    "network",
    "noc",
    "system",
    "sysadmin",
    "infrastructure",
    "voip",
    "telephony",
    "unified communications",
    "telecom",
    "it ",
    "customer",
    "commerce",
    "order",
    "return",
    "refund",
    "payment",
    "trust",
    "implementation",
    "onboarding",
    "service operations",
    "escalation",
)


@dataclass(frozen=True)
class RoleMatch:
    family: str
    group: str
    label: str
    matched_text: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "group": self.group,
            "group_label": ROLE_GROUPS[self.group],
            "label": self.label,
            "matched_text": self.matched_text,
            "reason": self.reason,
        }


def classify_title(title: str | None) -> RoleMatch | None:
    """The role family a title names, or None when it does not clearly name one."""
    text = " ".join((title or "").split())
    if not text or LEADERSHIP.search(text) or DEVOPS_SRE.search(text) or NOT_SUPPORT.search(text):
        return None
    for family in FAMILIES:
        match = family.pattern.search(text)
        if match is None:
            continue
        if not family.strong and BUSINESS.search(text):
            return None  # e.g. "Sales Support Engineer", "Finance Support Analyst"
        matched = match.group(0)
        return RoleMatch(
            family.id,
            family.group,
            family.label,
            matched,
            f'The title contains "{matched}" (role family: {family.label}).',
        )
    return None


def matches_groups(title: str | None, groups: set[str]) -> RoleMatch | None:
    """The match when it belongs to one of the selected groups."""
    match = classify_title(title)
    return match if match is not None and match.group in groups else None
