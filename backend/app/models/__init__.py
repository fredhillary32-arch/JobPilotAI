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
from app.models.cv_generation import (
    CandidateJobDescription,
    TailoredCvDraft,
    TailoredCvExport,
)
from app.models.job_listing import JobDiscoveryRun, JobListing
from app.models.user import (
    AuthSession,
    PreAuthChallenge,
    ProfileOwnershipAdoption,
    User,
)

__all__ = [
    "Base",
    "CandidateDocument",
    "CandidateEvidence",
    "DocumentExtraction",
    "CandidateJobDescription",
    "TailoredCvDraft",
    "TailoredCvExport",
    "JobDiscoveryRun",
    "JobListing",
    "AuthSession",
    "PreAuthChallenge",
    "ProfileOwnershipAdoption",
    "User",
    "CandidateCertification",
    "CandidateEducation",
    "CandidateProfile",
    "CandidateSkill",
    "CandidateWorkExperience",
]
