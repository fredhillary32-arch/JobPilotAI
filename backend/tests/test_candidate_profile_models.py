from datetime import date

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)


def test_profile_relationships_support_multiple_records(
    database: tuple[Engine, sessionmaker[Session]],
    candidate_profile: CandidateProfile,
) -> None:
    _, factory = database
    with factory.begin() as session:
        session.add(candidate_profile)
        candidate_profile.work_experiences.extend(
            [
                CandidateWorkExperience(
                    employer="First Employer",
                    job_title="Engineer",
                    start_date=date(2020, 1, 1),
                    end_date=date(2021, 1, 1),
                ),
                CandidateWorkExperience(
                    employer="Second Employer",
                    job_title="Senior Engineer",
                    start_date=date(2021, 2, 1),
                    current_role=True,
                ),
            ]
        )
        candidate_profile.education_records.append(
            CandidateEducation(
                institution="University",
                qualification="BSc",
                start_date=date(2016, 1, 1),
            )
        )
        candidate_profile.skills.extend(
            [
                CandidateSkill(name="Python"),
                CandidateSkill(name="SQL", proficiency_level="intermediate"),
            ]
        )
        candidate_profile.certifications.append(
            CandidateCertification(
                name="Certificate",
                issuer="Issuer",
                issue_date=date(2022, 1, 1),
                expires_on=date(2025, 1, 1),
            )
        )

    with factory() as session:
        stored = session.get(CandidateProfile, candidate_profile.id)
        assert stored is not None
        assert len(stored.work_experiences) == 2
        assert len(stored.education_records) == 1
        assert len(stored.skills) == 2
        assert len(stored.certifications) == 1


def test_duplicate_skills_are_rejected_case_and_whitespace_insensitively(
    database: tuple[Engine, sessionmaker[Session]],
    candidate_profile: CandidateProfile,
) -> None:
    _, factory = database
    with factory.begin() as session:
        session.add(candidate_profile)
        session.flush()
        session.add(CandidateSkill(candidate_profile_id=candidate_profile.id, name="Python"))

    with factory.begin() as session:
        session.add(
            CandidateSkill(
                candidate_profile_id=candidate_profile.id,
                name=" python ",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize(
    "record",
    [
        CandidateWorkExperience(
            employer="Employer",
            job_title="Engineer",
            start_date=date(2023, 1, 1),
            end_date=date(2022, 1, 1),
        ),
        CandidateWorkExperience(
            employer="Employer",
            job_title="Engineer",
            start_date=date(2022, 1, 1),
            end_date=date(2023, 1, 1),
            current_role=True,
        ),
        CandidateEducation(
            institution="University",
            qualification="Degree",
            start_date=date(2023, 1, 1),
            end_date=date(2022, 1, 1),
        ),
        CandidateCertification(
            name="Certificate",
            issuer="Issuer",
            issue_date=date(2023, 1, 1),
            expires_on=date(2022, 1, 1),
        ),
    ],
)
def test_invalid_date_ranges_are_rejected_by_database(
    database: tuple[Engine, sessionmaker[Session]],
    candidate_profile: CandidateProfile,
    record: CandidateWorkExperience | CandidateEducation | CandidateCertification,
) -> None:
    _, factory = database
    with factory.begin() as session:
        session.add(candidate_profile)
        session.flush()
        record.candidate_profile_id = candidate_profile.id
        session.add(record)
        with pytest.raises(IntegrityError):
            session.flush()
