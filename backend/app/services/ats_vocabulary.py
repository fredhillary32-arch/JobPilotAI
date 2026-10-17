"""Fixed word lists used by the local ATS analysis and CV writer.

Everything here is deterministic and reviewable; nothing is learned or fetched.
"""
import re

# Tools, platforms and named technologies matched as whole phrases.
TOOLS = frozenset({
    ".net", "active directory", "agile", "airflow", "android", "angular", "ansible",
    "asana", "aws", "azure", "azure ad", "bash", "bigquery", "c#", "c++",
    "ci/cd", "cisco", "confluence", "css", "dbt", "dhcp", "django", "dns", "docker",
    "elasticsearch", "entra id", "fastapi", "figma", "flask", "freshdesk",
    "gcp", "git", "github", "github actions", "gitlab", "golang", "google analytics",
    "google cloud", "google workspace", "graphql", "hubspot", "html", "intercom",
    "intune", "ios", "java", "javascript", "jenkins", "jira", "jira service management",
    "kafka", "kotlin", "kubernetes", "linux", "looker", "macos", "microsoft 365",
    "microsoft excel", "microsoft office", "mongodb", "mysql", "next.js", "nginx",
    "node.js", "office 365", "okta", "pandas", "php", "postgresql", "power bi",
    "powershell", "python", "quickbooks", "react.js", "redis", "rest api", "rest apis",
    "restful", "ruby", "rust",
    "salesforce", "sap", "scrum", "servicenow", "sharepoint", "slack", "snowflake",
    "sql", "tableau", "tcp/ip", "terraform", "typescript", "vmware",
    "vpn", "vue", "windows", "windows server", "xero", "zendesk",
})

CERTIFICATIONS = frozenset({
    "a+", "comptia a+", "comptia network+", "comptia security+", "network+", "security+",
    "ccna", "ccnp", "cissp", "cism", "cisa", "itil", "pmp", "prince2", "csm",
    "aws certified", "azure fundamentals", "az-900", "az-104", "ms-900", "md-102",
    "google it support", "ceh", "oscp", "cpa", "acca", "cfa",
})

# Words that describe a requirement without naming one ("strong", "skills").
GENERIC_WORDS = frozenset({
    "a", "about", "ability", "able", "across", "all", "also", "an", "and", "any", "are",
    "as", "at", "be", "being", "both", "but", "by", "can", "candidate", "candidates",
    "closely", "company", "demonstrated", "do", "does", "each", "ensure", "etc", "excellent",
    "experience", "experienced", "familiar", "familiarity", "for", "from", "good", "great",
    "have", "having", "help", "high", "highly", "ideal", "ideally", "in", "including",
    "into", "is", "it", "its", "job", "knowledge", "level", "like", "more", "must", "need",
    "needed", "new", "of", "on", "one", "or", "other", "our", "out", "own", "plus",
    "preferred", "proficiency", "proficient", "proven", "related", "relevant", "required",
    "requirement", "requirements", "role", "should", "skill", "skills", "solid", "some",
    "strong", "such", "team", "teams", "that", "the", "their", "them", "this", "through",
    "to", "understanding", "us", "use", "using", "very", "we", "well", "what", "who",
    "will", "with", "within", "work", "working", "would", "year", "years", "you", "your",
    "you'll", "we're", "minimum", "nice", "bonus", "least", "equivalent", "similar",
    "environment", "fast", "paced", "every", "day", "based",
    # Filler that is never a skill or keyword ("when something breaks", "then decide").
    "when", "then", "than", "something", "things", "thing", "most", "keep", "keeping", "done",
    "find", "happen", "happens", "get", "gets", "got", "make", "makes", "made", "know", "lot",
    "lots", "really", "just", "always", "often", "still", "even", "way", "ways", "there", "here",
    "these", "those", "they", "not", "was", "were", "has", "had", "may", "might", "could", "want",
    "wants", "take", "takes", "before", "after", "while", "where", "which", "why", "how",
    "important", "many", "much", "few", "less", "only", "until", "because", "without", "again",
    "back", "next", "via", "whether", "don't", "isn't", "doesn't", "you're", "they're", "it's",
    "that's", "sure", "come", "comes", "give", "look", "looks", "going", "goes",
})

# Empty claims that make a CV sound generic unless backed by evidence.
BUZZWORDS = (
    "results-driven", "results driven", "dynamic professional", "go-getter", "synergy",
    "hard-working", "hardworking", "detail-oriented", "team player", "self-starter",
    "think outside the box", "proven track record", "best-in-class", "rockstar",
    "ninja", "guru", "highly motivated", "passionate about", "dynamic", "go getter",
)

# Gerund or base form -> past tense, used only to restate the candidate's own verb.
PAST_TENSE = {
    "administer": "Administered", "analyse": "Analysed", "analyze": "Analyzed",
    "answer": "Answered", "assist": "Assisted", "automate": "Automated", "build": "Built",
    "collaborate": "Collaborated", "communicate": "Communicated", "configure": "Configured",
    "coordinate": "Coordinated", "create": "Created", "deliver": "Delivered",
    "deploy": "Deployed", "design": "Designed", "develop": "Developed",
    "document": "Documented", "ensure": "Ensured", "escalate": "Escalated",
    "handle": "Handled", "help": "Helped", "implement": "Implemented",
    "improve": "Improved", "increase": "Increased", "install": "Installed",
    "lead": "Led", "liaise": "Liaised", "maintain": "Maintained", "manage": "Managed",
    "mentor": "Mentored", "migrate": "Migrated", "monitor": "Monitored",
    "negotiate": "Negotiated", "onboard": "Onboarded", "operate": "Operated",
    "organise": "Organised", "organize": "Organized", "oversee": "Oversaw",
    "plan": "Planned", "prepare": "Prepared", "process": "Processed",
    "provide": "Provided", "recruit": "Recruited", "reduce": "Reduced",
    "report": "Reported", "resolve": "Resolved", "respond": "Responded",
    "review": "Reviewed", "run": "Ran", "schedule": "Scheduled", "sell": "Sold",
    "support": "Supported", "teach": "Taught", "test": "Tested", "track": "Tracked",
    "train": "Trained", "troubleshoot": "Troubleshot", "update": "Updated",
    "work": "Worked", "write": "Wrote", "log": "Logged", "fix": "Fixed",
    "record": "Recorded", "guide": "Guided", "conduct": "Conducted", "perform": "Performed",
    "identify": "Identified", "investigate": "Investigated", "diagnose": "Diagnosed",
    "set up": "Set up", "upgrade": "Upgraded", "patch": "Patched", "audit": "Audited",
    "launch": "Launched", "streamline": "Streamlined", "standardise": "Standardised",
    "standardize": "Standardized", "secure": "Secured", "backup": "Backed up",
    "cut": "Cut", "achieve": "Achieved", "save": "Saved", "own": "Owned", "drive": "Drove",
    "consolidate": "Consolidated", "decommission": "Decommissioned", "replace": "Replaced",
}
GERUNDS = {
    "administering": "administer", "analysing": "analyse", "analyzing": "analyze",
    "answering": "answer", "assisting": "assist", "automating": "automate",
    "building": "build", "collaborating": "collaborate", "communicating": "communicate",
    "configuring": "configure", "coordinating": "coordinate", "creating": "create",
    "delivering": "deliver", "deploying": "deploy", "designing": "design",
    "developing": "develop", "documenting": "document", "ensuring": "ensure",
    "escalating": "escalate", "handling": "handle", "helping": "help",
    "implementing": "implement", "improving": "improve", "increasing": "increase",
    "installing": "install", "leading": "lead", "liaising": "liaise",
    "maintaining": "maintain", "managing": "manage", "mentoring": "mentor",
    "migrating": "migrate", "monitoring": "monitor", "negotiating": "negotiate",
    "onboarding": "onboard", "operating": "operate", "organising": "organise",
    "organizing": "organize", "overseeing": "oversee", "planning": "plan",
    "preparing": "prepare", "processing": "process", "providing": "provide",
    "recruiting": "recruit", "reducing": "reduce", "reporting": "report",
    "resolving": "resolve", "responding": "respond", "reviewing": "review",
    "running": "run", "scheduling": "schedule", "selling": "sell",
    "supporting": "support", "teaching": "teach", "testing": "test",
    "tracking": "track", "training": "train", "troubleshooting": "troubleshoot",
    "updating": "update", "working": "work", "writing": "write", "logging": "log",
    "fixing": "fix", "recording": "record", "guiding": "guide", "conducting": "conduct",
    "performing": "perform", "identifying": "identify", "investigating": "investigate",
    "diagnosing": "diagnose", "upgrading": "upgrade", "patching": "patch",
    "auditing": "audit", "launching": "launch", "streamlining": "streamline",
    "standardising": "standardise", "standardizing": "standardize", "securing": "secure",
}
THIRD_PERSON = {f"{base}s": base for base in PAST_TENSE} | {
    "analyses": "analyse", "analyzes": "analyze", "oversees": "oversee",
    "teaches": "teach", "processes": "process", "liaises": "liaise",
}
# Words the writer itself may introduce when restating a statement.
REWRITE_WORDS = frozenset(
    {value.casefold() for value in PAST_TENSE.values()}
    | {"contributed", "to", "supported", "and", "with", "experience", "in", "roles", "at", "the", "role"}
)

DEGREE_LEVELS = (
    (5, re.compile(r"\b(ph\.?d|doctorate|doctoral)\b", re.I)),
    (4, re.compile(r"\b(master'?s?|msc|m\.sc|mba|ma|m\.a\.|meng)\b", re.I)),
    (3, re.compile(r"\b(bachelor'?s?|bsc|b\.sc|ba|b\.a\.|beng|bcom|undergraduate degree|university degree|degree)\b", re.I)),
    (2, re.compile(r"\b(higher national diploma|diploma|associate'?s?|hnd)\b", re.I)),
    (1, re.compile(r"\b(high school|secondary school|a-levels?|kcse|ged)\b", re.I)),
)
DEGREE_NAMES = {5: "doctorate", 4: "master's degree", 3: "bachelor's degree", 2: "diploma", 1: "secondary school"}

WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#/.'-]*[A-Za-z0-9+#]|[A-Za-z]")


def degree_level(text: str) -> int:
    for level, pattern in DEGREE_LEVELS:
        if pattern.search(text):
            return level
    return 0


def stem(word: str) -> str:
    """A light, predictable stemmer: enough to match "troubleshooting" with "troubleshoot"."""
    word = word.casefold().strip(".'-/")
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "es", "ed", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            base = word[: -len(suffix)]
            return base + "y" if suffix in {"ies", "ied"} else base
    return word


def content_words(text: str) -> list[str]:
    return [
        word.casefold()
        for word in WORD.findall(text)
        if len(word) > 2 and word.casefold() not in GENERIC_WORDS
    ]


def phrase_in(phrase: str, text: str) -> bool:
    return re.search(rf"(?<![\w+#]){re.escape(phrase.casefold())}(?![\w+#])", text.casefold()) is not None


# Tool names that are also ordinary words ("react quickly", "excel at"): matched only
# when capitalised mid-sentence.
CASE_SENSITIVE_TOOLS = ("React", "Excel", "Go", "Swift", "Spark")
SENTENCE_STARTERS = frozenset(".!?:\n•*-")


def named_terms(text: str) -> list[str]:
    """Tools and certifications named in the text, longest phrase first, no overlaps."""
    found: list[str] = []
    lowered = text.casefold()
    for term in sorted(TOOLS | CERTIFICATIONS, key=len, reverse=True):
        if phrase_in(term, lowered) and not any(phrase_in(term, existing) for existing in found):
            found.append(term)
    for term in CASE_SENSITIVE_TOOLS:
        if term.casefold() in found or any(phrase_in(term, existing) for existing in found):
            continue
        for match in re.finditer(rf"\b{term}(?![\w+#])", text):
            before = text[: match.start()].rstrip(" \t")
            if before and before[-1] not in SENTENCE_STARTERS:
                found.append(term.casefold())
                break
    return found
