from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.cli import main
from app.models import CandidateProfile
from app.models.user import ProfileOwnershipAdoption, User


def _add_owner_and_profiles(
    factory: sessionmaker[Session],
    *,
    assigned_count: int = 0,
    unassigned_count: int = 1,
) -> tuple[User, list[CandidateProfile]]:
    with factory.begin() as session:
        owner = User(
            email="owner@example.com",
            password_hash="$argon2id$test-fixture",
        )
        session.add(owner)
        session.flush()
        profiles = [
            CandidateProfile(
                name=f"Synthetic profile {index}",
                user_id=owner.id if index < assigned_count else None,
            )
            for index in range(assigned_count + unassigned_count)
        ]
        session.add_all(profiles)
        session.flush()
        return owner, profiles


def _run_adoption(
    factory: sessionmaker[Session],
    profile_ids: list[str],
    answers: list[str],
) -> tuple[int, str]:
    prompts: Iterator[str] = iter(answers)
    output: list[str] = []
    result = main(
        [
            "adopt-profiles",
            *[argument for profile_id in profile_ids for argument in ("--profile-id", profile_id)],
        ],
        input_fn=lambda _: next(prompts),
        output=output.append,
        session_factory=factory,
    )
    return result, "\n".join(output)


def test_profile_adoption_requires_explicit_ids_and_writes_audit_rows(database) -> None:
    _, factory = database
    owner, profiles = _add_owner_and_profiles(
        factory,
        unassigned_count=2,
    )
    selected_ids = [str(profile.id) for profile in profiles]

    result, output = _run_adoption(
        factory,
        selected_ids,
        [
            " OWNER@example.com ",
            "owner@example.com",
            "ADOPT 2 PROFILES",
        ],
    )

    assert result == 0
    assert output == "Adopted 2 explicitly selected profile(s)."
    with factory() as session:
        adopted = session.query(CandidateProfile).order_by(CandidateProfile.id).all()
        assert all(profile.user_id == owner.id for profile in adopted)
        audits = session.query(ProfileOwnershipAdoption).all()
        assert len(audits) == 2
        assert {audit.candidate_profile_id for audit in audits} == {profile.id for profile in profiles}
        assert all(audit.previous_user_id is None for audit in audits)
        assert all(audit.new_user_id == owner.id for audit in audits)
        assert all(audit.actor_user_id == owner.id for audit in audits)
        assert all(audit.action == "adopt" for audit in audits)
        assert all(audit.occurred_at is not None for audit in audits)


def test_profile_adoption_refuses_mixed_assigned_and_unassigned_ids_atomically(
    database,
) -> None:
    _, factory = database
    _, profiles = _add_owner_and_profiles(
        factory,
        assigned_count=1,
        unassigned_count=1,
    )
    selected_ids = [str(profile.id) for profile in profiles]

    result, output = _run_adoption(
        factory,
        selected_ids,
        [
            "owner@example.com",
            "owner@example.com",
            "ADOPT 2 PROFILES",
        ],
    )

    assert result == 1
    assert "already assigned" in output
    with factory() as session:
        refreshed = [session.get(CandidateProfile, profile.id) for profile in profiles]
        assert refreshed[0] is not None and refreshed[0].user_id is not None
        assert refreshed[1] is not None and refreshed[1].user_id is None
        assert session.query(ProfileOwnershipAdoption).count() == 0


def test_profile_adoption_refuses_bad_confirmation_without_changes(database) -> None:
    _, factory = database
    _, profiles = _add_owner_and_profiles(factory)

    result, output = _run_adoption(
        factory,
        [str(profiles[0].id)],
        [
            "owner@example.com",
            "other@example.com",
            "ADOPT 1 PROFILES",
        ],
    )

    assert result == 2
    assert "confirmation did not match" in output
    with factory() as session:
        assert session.get(CandidateProfile, profiles[0].id).user_id is None
        assert session.query(ProfileOwnershipAdoption).count() == 0


def test_profile_adoption_rejects_duplicate_profile_ids_before_database_changes(
    database,
) -> None:
    _, factory = database
    _, profiles = _add_owner_and_profiles(factory)
    profile_id = str(profiles[0].id)

    result, output = _run_adoption(
        factory,
        [profile_id, profile_id],
        [],
    )

    assert result == 2
    assert "Duplicate profile IDs" in output
    with factory() as session:
        assert session.get(CandidateProfile, profiles[0].id).user_id is None
        assert session.query(ProfileOwnershipAdoption).count() == 0


def test_profile_adoption_does_not_log_candidate_details(database) -> None:
    _, factory = database
    _, profiles = _add_owner_and_profiles(factory)
    private_name = profiles[0].name
    result, output = _run_adoption(
        factory,
        [str(profiles[0].id)],
        [
            "missing@example.com",
            "missing@example.com",
            "ADOPT 1 PROFILES",
        ],
    )

    assert result == 1
    assert private_name not in output


def test_profile_adoption_rejects_unknown_profile_id_atomically(database) -> None:
    _, factory = database
    _, profiles = _add_owner_and_profiles(factory)
    missing_profile_id = str(uuid4())

    result, output = _run_adoption(
        factory,
        [missing_profile_id],
        [
            "owner@example.com",
            "owner@example.com",
            "ADOPT 1 PROFILES",
        ],
    )

    assert result == 1
    assert "could not be verified" in output
    with factory() as session:
        assert session.get(CandidateProfile, profiles[0].id).user_id is None
        assert session.query(ProfileOwnershipAdoption).count() == 0


def test_profile_adoption_rejects_malformed_profile_uuid_before_database_access(
    database,
    capsys,
) -> None:
    _, factory = database
    _, profiles = _add_owner_and_profiles(factory)

    with pytest.raises(SystemExit) as exit_info:
        main(
            ["adopt-profiles", "--profile-id", "not-a-uuid"],
            session_factory=factory,
        )

    assert exit_info.value.code == 2
    assert "invalid UUID value" in capsys.readouterr().err
    with factory() as session:
        assert session.get(CandidateProfile, profiles[0].id).user_id is None
        assert session.query(ProfileOwnershipAdoption).count() == 0
