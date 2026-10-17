"""Run discovery for registry sources: locking, isolation, pacing and progress.

Used by the operator CLI and by the authenticated refresh endpoint, which starts
this in a background thread so no page request waits on external sources.

- One discovery pass at a time: an in-process lock plus, on PostgreSQL, a
  session-level advisory lock, so a CLI run and a UI refresh never overlap.
- Each source runs in its own session; one failing source never stops the rest.
- Sources whose terms ask for a minimum gap (Jobicy: one pass per hour) are
  skipped, with the reason, when they ran too recently, unless forced.
- Incremental: sources that support it read only what is new since their last
  successful run; ``full=True`` reads their whole window instead.
- A run row left "running" longer than STALE_AFTER is reported as interrupted;
  stored history is never rewritten.
"""
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import threading

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models import JobDiscoveryRun
from app.services.auth import normalize_database_datetime, utc_now
from app.services.job_discovery import JobSource, run_discovery
from app.services.source_registry import SourceEntry

STALE_AFTER = timedelta(hours=1)
ADVISORY_LOCK_KEY = 0x4A6F6250  # "JobP"; one discovery pass per database
_process_lock = threading.Lock()


class DiscoveryBusy(RuntimeError):
    """Another discovery pass holds the lock."""


@dataclass
class SourceOutcome:
    source_id: str
    status: str  # succeeded | failed | skipped | error
    message: str
    run_id: str | None = None
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: int = 0
    skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    error_category: str | None = None


@dataclass
class RefreshState:
    """Progress of the current (or last) pass, for the UI; kept in memory only."""

    state: str = "idle"  # idle | running | finished
    started_at: datetime | None = None
    finished_at: datetime | None = None
    requested: list[str] = field(default_factory=list)
    current: str | None = None
    outcomes: list[SourceOutcome] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


refresh_state = RefreshState()


def effective_run_status(run: JobDiscoveryRun, now: datetime | None = None) -> str:
    """'interrupted' for a run still marked running long after it started."""
    if run.status != "running":
        return run.status
    started = normalize_database_datetime(run.started_at)
    return "interrupted" if (now or utc_now()) - started > STALE_AFTER else "running"


def last_success(session: Session, kind: str, key: str) -> JobDiscoveryRun | None:
    return session.scalar(
        select(JobDiscoveryRun)
        .where(JobDiscoveryRun.source_kind == kind, JobDiscoveryRun.source_key == key,
               JobDiscoveryRun.status == "succeeded")
        .order_by(JobDiscoveryRun.started_at.desc())
        .limit(1)
    )


@contextmanager
def discovery_lock(factory: sessionmaker[Session]) -> Iterator[None]:
    if not _process_lock.acquire(blocking=False):
        raise DiscoveryBusy
    try:
        with factory() as session:
            postgres = session.get_bind().dialect.name == "postgresql"
            if postgres and not session.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}):
                raise DiscoveryBusy
            try:
                yield
            finally:
                if postgres:
                    session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY})
                    session.commit()
    finally:
        _process_lock.release()


def _default_builder(entry: SourceEntry) -> JobSource:
    return entry.build_source()


def run_sources(
    factory: sessionmaker[Session],
    entries: Sequence[SourceEntry],
    *,
    force: bool = False,
    full: bool = False,
    builder: Callable[[SourceEntry], JobSource] | None = None,
    state: RefreshState | None = None,
) -> list[SourceOutcome]:
    """Run each source in turn; the caller holds discovery_lock."""
    outcomes: list[SourceOutcome] = []
    for entry in entries:
        if state is not None:
            state.current = entry.id
        outcome = _run_one(factory, entry, force=force, full=full, builder=builder or _default_builder)
        outcomes.append(outcome)
        if state is not None:
            state.outcomes.append(outcome)
    if state is not None:
        state.current = None
    return outcomes


def _run_one(factory, entry: SourceEntry, *, force: bool, full: bool, builder) -> SourceOutcome:
    try:
        source = builder(entry)
        source.category = entry.category
        with factory() as session:
            previous = last_success(session, source.kind, source.key)
            previous_at = normalize_database_datetime(previous.started_at) if previous else None
            gap = getattr(source, "min_interval", None)
            if not force and gap and previous_at is not None and utc_now() - previous_at < gap:
                minutes = int(gap.total_seconds() // 60)
                return SourceOutcome(entry.id, "skipped",
                                     f"ran at {previous_at:%H:%M} UTC; its terms ask for at least {minutes} minutes between passes")
            if hasattr(source, "since"):
                source.since = None if full else previous_at
            run = run_discovery(session, source)
    except Exception as error:  # noqa: BLE001 - one broken source must not stop the others
        return SourceOutcome(entry.id, "error", f"failed with an internal error ({type(error).__name__}); other sources continue",
                             error_category="internal_error")
    if run.status != "succeeded":
        return SourceOutcome(entry.id, "failed", f"failed ({run.error_category}); stored listings were not changed",
                             run_id=str(run.id), error_category=run.error_category)
    reasons = dict(run.skip_reasons or {})
    detail = ", ".join(f"{reason}: {count}" for reason, count in sorted(reasons.items()))
    message = (f"fetched {run.fetched_count}, new {run.created_count}, updated {run.updated_count}, "
               f"unchanged {run.unchanged_count}, no longer listed {run.missing_count}, skipped {run.skipped_count}"
               + (f" ({detail})" if detail else ""))
    return SourceOutcome(entry.id, "succeeded", message, run_id=str(run.id), fetched=run.fetched_count,
                         created=run.created_count, updated=run.updated_count, unchanged=run.unchanged_count,
                         missing=run.missing_count, skipped=run.skipped_count, skip_reasons=reasons)


def run_refresh_in_background(
    factory: sessionmaker[Session],
    entries: Sequence[SourceEntry],
    *,
    full: bool = False,
    launch: Callable[[Callable[[], None]], None] | None = None,
) -> RefreshState:
    """Start a pass and return immediately; raises DiscoveryBusy when one is running."""
    global refresh_state
    if refresh_state.state == "running" or _process_lock.locked():
        raise DiscoveryBusy
    state = RefreshState(state="running", started_at=utc_now(), requested=[entry.id for entry in entries])
    refresh_state = state

    def work() -> None:
        try:
            with discovery_lock(factory):
                run_sources(factory, entries, full=full, state=state)
        except DiscoveryBusy:
            state.outcomes.append(SourceOutcome("all", "skipped", "another discovery pass was already running"))
        finally:
            state.state, state.finished_at, state.current = "finished", utc_now(), None

    (launch or (lambda target: threading.Thread(target=target, name="jobpilot-discovery", daemon=True).start()))(work)
    return state
