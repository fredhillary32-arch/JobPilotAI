"""The verified job-source registry (backend/app/data/source_registry.json).

Entries are research records, not crawl targets: only entries with a verified
board on a supported public API are enabled, and manual-only entries are never
fetched. Validation runs on load so a malformed registry fails loudly.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from app.services.job_discovery import JobSource
from app.services.job_sources.aggregators import AGGREGATOR_SOURCES
from app.services.job_sources.ashby import AshbyJobBoardSource
from app.services.job_sources.greenhouse import GreenhouseBoardSource
from app.services.job_sources.lever import LeverPostingsSource

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "data" / "source_registry.json"
CATEGORIES = ("direct_employer", "staffing_agency", "recruitment_outsourcing", "aggregator")
METHODS = ("greenhouse", "lever", "ashby", "jobicy", "arbeitnow", "remoteok", "manual")
# Free public aggregator APIs: discovery sources only, never eligibility authorities.
# Their board is always "public" and they are enabled on documented API terms.
AGGREGATOR_METHODS = tuple(AGGREGATOR_SOURCES)
# Hosts each platform serves vacancy pages and application forms from.
ATS_PAGE_HOSTS = {
    "greenhouse": ("job-boards.greenhouse.io", "boards.greenhouse.io", "job-boards.eu.greenhouse.io"),
    "lever": ("jobs.lever.co", "jobs.eu.lever.co"),
    "ashby": ("jobs.ashbyhq.com",),
}
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
DOMAIN_PATTERN = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,}\Z")


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class SourceEntry:
    id: str
    name: str
    category: str
    official_domain: str
    additional_domains: tuple[str, ...]
    careers_url: str
    method: str
    board: str | None
    instance: str | None
    enabled: bool
    verification: dict
    terms: str
    limitations: str
    focus: tuple[str, ...] = field(default_factory=tuple)

    @property
    def source_kind(self) -> str:
        return self.method

    @property
    def source_key(self) -> str | None:
        if self.board is None:
            return None
        if self.method == "ashby":
            return self.board.lower()
        if self.method == "lever" and self.instance == "eu":
            return f"eu:{self.board.lower()}"
        return self.board.lower()

    def owns_host(self, host: str | None) -> bool:
        """Whether a link host belongs to this source's platform or official domains."""
        if not host:
            return False
        host = host.lower()
        if host in ATS_PAGE_HOSTS.get(self.method, ()):
            return True
        if self.method in AGGREGATOR_METHODS and any(
            host == item or host.endswith(f".{item}") for item in AGGREGATOR_SOURCES[self.method].page_hosts
        ):
            return True
        return any(host == domain or host.endswith(f".{domain}") for domain in (self.official_domain, *self.additional_domains))

    def build_source(self) -> JobSource:
        if not self.enabled or self.board is None:
            raise RegistryError(f"Source {self.id} is manual-only and is never fetched automatically.")
        if self.method in AGGREGATOR_METHODS:
            source = AGGREGATOR_SOURCES[self.method]()
        elif self.method == "greenhouse":
            source = GreenhouseBoardSource(self.board, self.name)
        elif self.method == "lever":
            source = LeverPostingsSource(self.board, self.name, instance=self.instance or "global")
        else:
            source = AshbyJobBoardSource(self.board, self.name)
        source.category = self.category
        source.registry_id = self.id
        return source


def _https_host(url: str) -> str | None:
    parts = urlsplit(url)
    return parts.hostname if parts.scheme == "https" else None


def parse_registry(data: dict) -> tuple[SourceEntry, ...]:
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise RegistryError("Registry must contain an 'entries' list.")
    parsed: list[SourceEntry] = []
    seen_ids: set[str] = set()
    seen_boards: set[tuple[str, str]] = set()
    for raw in entries:
        identifier = raw.get("id", "")
        if not ID_PATTERN.fullmatch(identifier) or identifier in seen_ids:
            raise RegistryError(f"Invalid or duplicate registry id: {identifier!r}")
        seen_ids.add(identifier)
        category = raw.get("category")
        if category not in CATEGORIES:
            raise RegistryError(f"{identifier}: unknown category {category!r}")
        domains = (raw.get("official_domain", ""), *raw.get("additional_domains", []))
        if not all(DOMAIN_PATTERN.fullmatch(domain or "") for domain in domains):
            raise RegistryError(f"{identifier}: invalid official domain")
        careers_host = _https_host(raw.get("careers_url") or "")
        if careers_host is None or not any(careers_host == d or careers_host.endswith(f".{d}") for d in domains):
            raise RegistryError(f"{identifier}: careers URL must be https on the official domain")
        discovery = raw.get("discovery") or {}
        method = discovery.get("method")
        board = discovery.get("board")
        if method not in METHODS:
            raise RegistryError(f"{identifier}: unknown discovery method {method!r}")
        enabled = bool(raw.get("enabled"))
        if method == "manual" and (board is not None or enabled):
            raise RegistryError(f"{identifier}: manual sources have no board and cannot be enabled")
        if method != "manual" and not board:
            raise RegistryError(f"{identifier}: {method} sources need a verified board identifier")
        verification = raw.get("verification") or {}
        if method in AGGREGATOR_METHODS:
            if category != "aggregator" or board != "public":
                raise RegistryError(f"{identifier}: {method} is an aggregator API with board 'public'")
            if enabled and verification.get("outcome") != "public_api_documented":
                raise RegistryError(f"{identifier}: aggregator APIs are enabled only on documented public API terms")
            if enabled and not raw.get("terms"):
                raise RegistryError(f"{identifier}: record the API terms before enabling")
        elif enabled and verification.get("outcome") != "board_found_on_official_page":
            raise RegistryError(f"{identifier}: only sources whose board was found on the official page can be enabled")
        checked = verification.get("checked_at")
        if checked is not None:
            datetime.fromisoformat(checked.replace("Z", "+00:00"))
        entry = SourceEntry(
            id=identifier, name=raw["name"], category=category,
            official_domain=domains[0], additional_domains=tuple(domains[1:]),
            careers_url=raw["careers_url"], method=method, board=board,
            instance=discovery.get("instance"), enabled=enabled, verification=verification,
            terms=raw.get("terms", ""), limitations=raw.get("limitations", ""),
            focus=tuple(raw.get("focus", [])),
        )
        if entry.source_key is not None:
            board_identity = (method, entry.source_key)
            if board_identity in seen_boards:
                raise RegistryError(f"{identifier}: board already registered")
            seen_boards.add(board_identity)
        if enabled:
            entry.build_source()  # validates the board identifier format
        parsed.append(entry)
    return tuple(parsed)


@lru_cache
def load_registry(path: Path = REGISTRY_PATH) -> tuple[SourceEntry, ...]:
    return parse_registry(json.loads(path.read_text(encoding="utf-8")))


def entry_for_source(kind: str, key: str, registry: tuple[SourceEntry, ...] | None = None) -> SourceEntry | None:
    for entry in registry if registry is not None else load_registry():
        if entry.source_kind == kind and entry.source_key == key:
            return entry
    return None
