import argparse
import getpass
import hmac
from collections.abc import Callable, Sequence
import warnings
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_session_factory
from app.services.auth import (
    AccountNotFoundError,
    ProfilesAlreadyAssignedError,
    ProfilesNotFoundError,
    OwnerAlreadyExistsError,
    UnsupportedAuthDatabaseError,
    adopt_candidate_profiles,
    bootstrap_owner,
    normalize_login_email,
    reset_password,
    validate_password,
)
import time

from app.services.job_discovery import JobSource, run_discovery
from app.services.job_sources.greenhouse import GreenhouseBoardSource
from app.services.link_verification import listings_due_for_check, verify_listing_links
from app.services.discovery_runner import DiscoveryBusy, discovery_lock, effective_run_status, run_sources
from app.services.source_registry import REGISTRY_PATH, RegistryError, load_registry, parse_registry


class HiddenPasswordPromptUnavailable(RuntimeError):
    pass


def _get_hidden_password(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except getpass.GetPassWarning:
            raise HiddenPasswordPromptUnavailable from None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "bootstrap-owner",
        help="Create the single local owner account if none exists.",
    )
    commands.add_parser(
        "reset-password",
        help="Reset a local account password and revoke its sessions.",
    )
    adoption = commands.add_parser(
        "adopt-profiles",
        help="Explicitly assign listed legacy profiles to the confirmed local account.",
    )
    adoption.add_argument(
        "--profile-id",
        action="append",
        required=True,
        type=UUID,
        help="Candidate profile UUID to adopt; repeat for each profile.",
    )
    greenhouse = commands.add_parser(
        "discover-greenhouse",
        help="Fetch one employer's public Greenhouse job board and store its listings.",
    )
    greenhouse.add_argument("--board", required=True, help="Greenhouse board token.")
    greenhouse.add_argument(
        "--employer",
        required=True,
        help="Employer name for this board (the list endpoint does not state it).",
    )
    commands.add_parser("list-sources", help="List the verified job-source registry.")
    registry_run = commands.add_parser(
        "discover-registry",
        help="Run discovery for enabled registry sources; one failing source never stops the rest.",
    )
    registry_run.add_argument("--source", action="append", default=[], help="Registry id; repeat to choose several.")
    registry_run.add_argument("--force", action="store_true", help="Ignore per-source minimum intervals (use sparingly).")
    registry_run.add_argument("--full", action="store_true", help="Read each source's whole window, not only what is new.")
    commands.add_parser("validate-sources", help="Validate the source registry file without contacting any source.")
    commands.add_parser("discovery-status", help="Summarise the latest run of every enabled source.")
    links = commands.add_parser(
        "verify-links",
        help="Check vacancy and application links for stored listings, rate-limited.",
    )
    links.add_argument("--limit", type=int, default=20, help="Listings to check this run (1-200).")
    links.add_argument("--delay", type=float, default=2.0, help="Seconds between requests (at least 1).")
    links.add_argument("--source", default=None, help="Only listings from this registry id.")
    return parser


def _prompt_password(
    password_prompt: Callable[[str], str],
    output: Callable[[str], object],
    prompt: str,
    confirmation_prompt: str,
) -> str | None:
    try:
        password = password_prompt(prompt)
    except HiddenPasswordPromptUnavailable:
        output("Hidden password entry is unavailable; no account was changed.")
        return None
    try:
        validate_password(password)
    except ValueError as error:
        output(str(error))
        return None

    confirmation = password_prompt(confirmation_prompt)
    if not hmac.compare_digest(password.encode("utf-8"), confirmation.encode("utf-8")):
        output("Passwords did not match; no account was changed.")
        return None
    return password


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] | None = None,
    password_prompt: Callable[[str], str] | None = None,
    output: Callable[[str], object] | None = None,
    session_factory: sessionmaker[Session] | None = None,
    source_factory: Callable[[str, str], JobSource] | None = None,
    registry_source_factory: Callable[[object], JobSource] | None = None,
    link_opener: Callable | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    args = _build_parser().parse_args(argv)
    input_fn = input if input_fn is None else input_fn
    password_prompt = _get_hidden_password if password_prompt is None else password_prompt
    output = print if output is None else output

    if args.command == "reset-password":
        return _reset_password(input_fn, password_prompt, output, session_factory)
    if args.command == "discover-greenhouse":
        return _discover_greenhouse(output, session_factory, args.board, args.employer, source_factory)
    if args.command == "list-sources":
        return _list_sources(output)
    if args.command == "discover-registry":
        return _discover_registry(output, session_factory, args.source, registry_source_factory, args.force, args.full)
    if args.command == "validate-sources":
        return _validate_sources(output)
    if args.command == "discovery-status":
        return _discovery_status(output, session_factory)
    if args.command == "verify-links":
        return _verify_links(output, session_factory, args.limit, args.delay, args.source, link_opener, sleep)
    if args.command == "adopt-profiles":
        return _adopt_profiles(
            input_fn,
            output,
            session_factory,
            args.profile_id,
        )

    return _bootstrap_owner(input_fn, password_prompt, output, session_factory)


def _bootstrap_owner(
    input_fn: Callable[[str], str],
    password_prompt: Callable[[str], str],
    output: Callable[[str], object],
    session_factory: sessionmaker[Session] | None,
) -> int:
    try:
        email = normalize_login_email(input_fn("Owner email: "))
    except ValueError as error:
        output(str(error))
        return 2

    password = _prompt_password(
        password_prompt,
        output,
        "Owner password: ",
        "Confirm owner password: ",
    )
    if password is None:
        return 2

    factory = get_session_factory() if session_factory is None else session_factory
    try:
        with factory() as session:
            bootstrap_owner(session, email, password)
    except OwnerAlreadyExistsError:
        output("An owner account already exists; bootstrap refused.")
        return 1
    except UnsupportedAuthDatabaseError:
        output("Owner bootstrap is unsupported for this database engine.")
        return 1
    except SQLAlchemyError:
        output("The owner account could not be created because the database operation failed.")
        return 1

    output("Owner account created.")
    return 0


def _reset_password(
    input_fn: Callable[[str], str],
    password_prompt: Callable[[str], str],
    output: Callable[[str], object],
    session_factory: sessionmaker[Session] | None,
) -> int:
    try:
        email = normalize_login_email(input_fn("Account email to reset: "))
        confirmation = normalize_login_email(input_fn("Re-enter account email to confirm: "))
    except ValueError as error:
        output(str(error))
        return 2
    if not hmac.compare_digest(email.encode("utf-8"), confirmation.encode("utf-8")):
        output("Account confirmation did not match; no account was changed.")
        return 2

    password = _prompt_password(
        password_prompt,
        output,
        "New password: ",
        "Confirm new password: ",
    )
    if password is None:
        return 2

    factory = get_session_factory() if session_factory is None else session_factory
    try:
        with factory() as session:
            reset_password(session, email, password)
    except AccountNotFoundError:
        output("The requested account could not be reset.")
        return 1
    except UnsupportedAuthDatabaseError:
        output("Password reset is unsupported for this database engine.")
        return 1
    except SQLAlchemyError:
        output("The password could not be reset because the database operation failed.")
        return 1

    output("Password reset; existing sessions were revoked.")
    return 0


def _adopt_profiles(
    input_fn: Callable[[str], str],
    output: Callable[[str], object],
    session_factory: sessionmaker[Session] | None,
    profile_ids: list[UUID],
) -> int:
    if len(set(profile_ids)) != len(profile_ids):
        output("Duplicate profile IDs were supplied; no profiles were changed.")
        return 2
    try:
        email = normalize_login_email(input_fn("Owner account email: "))
        confirmation = normalize_login_email(
            input_fn("Re-enter owner account email to confirm: ")
        )
    except ValueError as error:
        output(str(error))
        return 2
    if not hmac.compare_digest(email.encode("utf-8"), confirmation.encode("utf-8")):
        output("Account confirmation did not match; no profiles were changed.")
        return 2
    phrase = f"ADOPT {len(profile_ids)} PROFILES"
    if input_fn(f"Type {phrase} to confirm: ") != phrase:
        output("Adoption confirmation did not match; no profiles were changed.")
        return 2

    factory = get_session_factory() if session_factory is None else session_factory
    try:
        with factory() as session:
            adopted_count = adopt_candidate_profiles(session, email, profile_ids)
    except AccountNotFoundError:
        output("The requested owner account could not be verified.")
        return 1
    except ProfilesNotFoundError:
        output("One or more requested profiles could not be verified.")
        return 1
    except ProfilesAlreadyAssignedError:
        output("One or more requested profiles are already assigned; no profiles changed.")
        return 1
    except UnsupportedAuthDatabaseError:
        output("Profile adoption is unsupported for this database engine.")
        return 1
    except SQLAlchemyError:
        output("Profile adoption failed because of a database operation error.")
        return 1

    output(f"Adopted {adopted_count} explicitly selected profile(s).")
    return 0


def _discover_greenhouse(
    output: Callable[[str], object],
    session_factory: sessionmaker[Session] | None,
    board: str,
    employer: str,
    source_factory: Callable[[str, str], JobSource] | None,
) -> int:
    try:
        source = (source_factory or GreenhouseBoardSource)(board, employer)
    except ValueError as error:
        output(str(error))
        return 2
    factory = get_session_factory() if session_factory is None else session_factory
    try:
        with factory() as session:
            run = run_discovery(session, source)
    except SQLAlchemyError:
        output("Discovery failed because of a database operation error.")
        return 1
    if run.status != "succeeded":
        output(f"Discovery failed for greenhouse:{source.key} ({run.error_category}); stored listings were not changed.")
        return 1
    output(
        f"Discovery succeeded for greenhouse:{source.key}: fetched {run.fetched_count}, "
        f"new {run.created_count}, updated {run.updated_count}, unchanged {run.unchanged_count}, "
        f"no longer listed {run.missing_count}, skipped {run.skipped_count}."
    )
    return 0


def _list_sources(output: Callable[[str], object]) -> int:
    registry = load_registry()
    enabled = [entry for entry in registry if entry.enabled]
    output(f"{len(registry)} registered sources, {len(enabled)} enabled for automatic discovery.")
    for entry in registry:
        target = f"{entry.method}:{entry.board}" if entry.board else "manual only"
        output(f"- {entry.id} [{entry.category}] {target} ({entry.verification.get('outcome')}, checked {entry.verification.get('checked_at')})")
    return 0


def _discover_registry(
    output: Callable[[str], object],
    session_factory: sessionmaker[Session] | None,
    chosen: Sequence[str],
    registry_source_factory: Callable[[object], JobSource] | None,
    force: bool = False,
    full: bool = False,
) -> int:
    """Exit codes: 0 all ran or were paced, 1 a source failed, 2 bad input, 3 another pass is running."""
    registry = {entry.id: entry for entry in load_registry()}
    unknown = [identifier for identifier in chosen if identifier not in registry]
    if unknown:
        output(f"Unknown registry id(s): {', '.join(unknown)}")
        return 2
    selected = [registry[i] for i in chosen] if chosen else [e for e in registry.values() if e.enabled]
    manual = [entry.id for entry in selected if not entry.enabled]
    if manual:
        output(f"Manual-only sources are never fetched: {', '.join(manual)}")
        return 2
    factory = get_session_factory() if session_factory is None else session_factory
    try:
        with discovery_lock(factory):
            outcomes = run_sources(factory, selected, force=force, full=full, builder=registry_source_factory)
    except DiscoveryBusy:
        output("Another discovery pass is running; nothing was fetched.")
        return 3
    for outcome in outcomes:
        output(f"{outcome.source_id}: {'skipped, ' if outcome.status == 'skipped' else ''}{outcome.message}.")
    failures = sum(outcome.status in ("failed", "error") for outcome in outcomes)
    paced = sum(outcome.status == "skipped" for outcome in outcomes)
    output(f"{len(selected) - failures - paced} of {len(selected)} sources succeeded"
           + (f", {paced} skipped for pacing" if paced else "") + ".")
    return 1 if failures else 0


def _validate_sources(output: Callable[[str], object]) -> int:
    import json

    try:
        registry = parse_registry(json.loads(REGISTRY_PATH.read_text(encoding="utf-8")))
    except (RegistryError, ValueError, KeyError, OSError) as error:
        output(f"The source registry is invalid: {error}")
        return 2
    enabled = [entry for entry in registry if entry.enabled]
    by_method: dict[str, int] = {}
    for entry in enabled:
        by_method[entry.method] = by_method.get(entry.method, 0) + 1
    output(f"Registry valid: {len(registry)} sources, {len(enabled)} enabled ("
           + ", ".join(f"{method} {count}" for method, count in sorted(by_method.items())) + ").")
    return 0


def _discovery_status(output: Callable[[str], object], session_factory: sessionmaker[Session] | None) -> int:
    from sqlalchemy import select

    from app.models import JobDiscoveryRun

    factory = get_session_factory() if session_factory is None else session_factory
    problems = 0
    with factory() as session:
        for entry in (item for item in load_registry() if item.enabled):
            run = session.scalar(
                select(JobDiscoveryRun)
                .where(JobDiscoveryRun.source_kind == entry.source_kind, JobDiscoveryRun.source_key == entry.source_key)
                .order_by(JobDiscoveryRun.started_at.desc()).limit(1)
            )
            if run is None:
                output(f"- {entry.id}: never run")
                continue
            state = effective_run_status(run)
            problems += state in ("failed", "interrupted")
            counts = (f"fetched {run.fetched_count}, new {run.created_count}, updated {run.updated_count}, "
                      f"skipped {run.skipped_count}") if state == "succeeded" else (run.error_category or "")
            output(f"- {entry.id}: {state} at {run.started_at:%Y-%m-%d %H:%M} UTC; {counts}")
    return 1 if problems else 0


def _verify_links(
    output: Callable[[str], object],
    session_factory: sessionmaker[Session] | None,
    limit: int,
    delay: float,
    source_id: str | None,
    link_opener: Callable | None,
    sleep: Callable[[float], None],
) -> int:
    if not 1 <= limit <= 200 or delay < 1:
        output("Use --limit between 1 and 200 and --delay of at least 1 second.")
        return 2
    kind = key = None
    if source_id is not None:
        entry = next((item for item in load_registry() if item.id == source_id), None)
        if entry is None or entry.source_key is None:
            output(f"Unknown or manual-only registry id: {source_id}")
            return 2
        kind, key = entry.source_kind, entry.source_key
    factory = get_session_factory() if session_factory is None else session_factory
    outcomes: dict[str, int] = {}
    with factory() as session:
        listings = listings_due_for_check(session, limit, kind, key)
        for index, listing in enumerate(listings):
            if index:
                sleep(delay)
            for row in verify_listing_links(session, listing, opener=link_opener, sleep=sleep, delay_seconds=delay):
                outcomes[f"{row.url_kind}:{row.outcome}"] = outcomes.get(f"{row.url_kind}:{row.outcome}", 0) + 1
            session.commit()
    summary = ", ".join(f"{key}={count}" for key, count in sorted(outcomes.items())) or "nothing to check"
    output(f"Checked {len(listings)} listing(s): {summary}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
