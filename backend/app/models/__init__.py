"""ORM models registered with the shared SQLAlchemy metadata."""

from app.db import Base
from app.models.candidate_document import CandidateDocument
from app.models.candidate_eligibility import CandidateEligibilityDetails, CandidateWorkAuthorization
from app.models.candidate_evidence import CandidateEvidence
from app.models.candidate_profile import (
    CandidateCertification,
    CandidateEducation,
    CandidateProfile,
    CandidateSkill,
    CandidateWorkExperience,
)
from app.models.cv_generation import (
    CandidateJobDescription,
    TailoredCvDraft,
    TailoredCvExport,
)
from app.models.document_extraction import DocumentExtraction
from app.models.eligibility import ListingEligibilityAssessment
from app.models.job_application import JobApplication, JobApplicationEvent
from app.models.job_listing import JobDiscoveryRun, JobListing, JobListingLinkCheck
from app.models.skill_confirmation import CandidateSkillConfirmation
from app.models.user import (
    AuthSession,
    PreAuthChallenge,
    ProfileOwnershipAdoption,
    User,
)

__all__ = [
    "Base",
    "CandidateSkillConfirmation",
    "CandidateDocument",
    "CandidateEligibilityDetails",
    "CandidateWorkAuthorization",
    "CandidateEvidence",
    "DocumentExtraction",
    "CandidateJobDescription",
    "TailoredCvDraft",
    "TailoredCvExport",
    "JobApplication",
    "JobApplicationEvent",
    "ListingEligibilityAssessment",
    "JobDiscoveryRun",
    "JobListing",
    "JobListingLinkCheck",
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
