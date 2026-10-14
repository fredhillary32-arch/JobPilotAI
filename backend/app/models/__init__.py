"""ORM models registered with the shared SQLAlchemy metadata."""

from app.db import Base
from app.models.candidate_profile import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)
from app.models.candidate_document import CandidateDocument

__all__ = [
    "Base",
    "CandidateDocument",
    "CandidateCertification",
    "CandidateEducation",
    "CandidateProfile",
    "CandidateSkill",
    "CandidateWorkExperience",
]
