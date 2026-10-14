"""ORM models registered with the shared SQLAlchemy metadata."""

from app.db import Base
from app.models.candidate_profile import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)

__all__ = [
    "Base",
    "CandidateCertification",
    "CandidateEducation",
    "CandidateProfile",
    "CandidateSkill",
    "CandidateWorkExperience",
]
