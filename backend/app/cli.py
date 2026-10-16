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
from app.services.job_discovery import JobSource, run_discovery
from app.services.job_sources.greenhouse import GreenhouseBoardSource


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
) -> int:
    args = _build_parser().parse_args(argv)
    input_fn = input if input_fn is None else input_fn
    password_prompt = _get_hidden_password if password_prompt is None else password_prompt
    output = print if output is None else output

    if args.command == "reset-password":
        return _reset_password(input_fn, password_prompt, output, session_factory)
    if args.command == "discover-greenhouse":
        return _discover_greenhouse(output, session_factory, args.board, args.employer, source_factory)
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


if __name__ == "__main__":
    raise SystemExit(main())
