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
from app.models.candidate_evidence import CandidateEvidence
from app.models.document_extraction import DocumentExtraction

__all__ = [
    "Base",
    "CandidateDocument",
    "CandidateEvidence",
    "DocumentExtraction",
    "CandidateCertification",
    "CandidateEducation",
    "CandidateProfile",
    "CandidateSkill",
    "CandidateWorkExperience",
]
