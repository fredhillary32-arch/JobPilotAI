from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CandidateProfile(TimestampMixin, Base):
    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_candidate_profile_name"),
        CheckConstraint(
            "remote_work_preference IS NULL OR remote_work_preference IN "
            "('remote', 'hybrid', 'onsite', 'flexible')",
            name="ck_candidate_profile_remote_preference",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    professional_headline: Mapped[str | None] = mapped_column(String(240))
    summary: Mapped[str | None] = mapped_column(String(5000))
    location: Mapped[str | None] = mapped_column(String(200))
    remote_work_preference: Mapped[str | None] = mapped_column(String(20))
    target_job_categories: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    work_experiences: Mapped[list["CandidateWorkExperience"]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CandidateWorkExperience.start_date.desc()",
    )
    education_records: Mapped[list["CandidateEducation"]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CandidateEducation.start_date.desc()",
    )
    skills: Mapped[list["CandidateSkill"]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CandidateSkill.name",
    )
    certifications: Mapped[list["CandidateCertification"]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CandidateCertification.issue_date.desc()",
    )
    documents: Mapped[list["CandidateDocument"]] = relationship(
        back_populates="candidate_profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CandidateDocument.created_at.desc()",
    )


class CandidateWorkExperience(TimestampMixin, Base):
    __tablename__ = "candidate_work_experiences"
    __table_args__ = (
        CheckConstraint("length(trim(employer)) > 0", name="ck_work_experience_employer"),
        CheckConstraint("length(trim(job_title)) > 0", name="ck_work_experience_job_title"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_work_experience_date_order",
        ),
        CheckConstraint(
            "is_current_role = false OR end_date IS NULL",
            name="ck_work_experience_current_end_date",
        ),
        CheckConstraint(
            "work_arrangement IS NULL OR work_arrangement IN "
            "('remote', 'hybrid', 'onsite')",
            name="ck_work_experience_work_arrangement",
        ),
        Index("ix_candidate_work_experiences_profile_start", "candidate_profile_id", "start_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    employer: Mapped[str] = mapped_column(String(200), nullable=False)
    job_title: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    work_arrangement: Mapped[str | None] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    current_role: Mapped[bool] = mapped_column(
        "is_current_role",
        nullable=False,
        default=False,
        server_default="false",
    )
    description: Mapped[str | None] = mapped_column(String(5000))
    achievements: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    candidate_profile: Mapped[CandidateProfile] = relationship(
        back_populates="work_experiences"
    )


class CandidateEducation(TimestampMixin, Base):
    __tablename__ = "candidate_education"
    __table_args__ = (
        CheckConstraint(
            "length(trim(institution)) > 0",
            name="ck_candidate_education_institution",
        ),
        CheckConstraint(
            "length(trim(qualification)) > 0",
            name="ck_candidate_education_qualification",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_candidate_education_date_order",
        ),
        Index("ix_candidate_education_profile_start", "candidate_profile_id", "start_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    institution: Mapped[str] = mapped_column(String(200), nullable=False)
    qualification: Mapped[str] = mapped_column(String(200), nullable=False)
    field_of_study: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)

    candidate_profile: Mapped[CandidateProfile] = relationship(
        back_populates="education_records"
    )


class CandidateSkill(TimestampMixin, Base):
    __tablename__ = "candidate_skills"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_candidate_skill_name"),
        CheckConstraint(
            "proficiency_level IS NULL OR proficiency_level IN "
            "('beginner', 'intermediate', 'advanced', 'expert')",
            name="ck_candidate_skill_proficiency",
        ),
        UniqueConstraint(
            "candidate_profile_id",
            "normalized_name",
            name="uq_candidate_skills_profile_name_ci",
        ),
        Index("ix_candidate_skills_profile", "candidate_profile_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(100),
        Computed("lower(trim(name))", persisted=True),
        nullable=False,
    )
    proficiency_level: Mapped[str | None] = mapped_column(String(20))

    candidate_profile: Mapped[CandidateProfile] = relationship(back_populates="skills")


class CandidateCertification(TimestampMixin, Base):
    __tablename__ = "candidate_certifications"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_candidate_certification_name"),
        CheckConstraint("length(trim(issuer)) > 0", name="ck_candidate_certification_issuer"),
        CheckConstraint(
            "expires_on IS NULL OR expires_on >= issue_date",
            name="ck_candidate_certification_expiry_order",
        ),
        Index(
            "ix_candidate_certifications_profile_issue_date",
            "candidate_profile_id",
            "issue_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    candidate_profile_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)

    candidate_profile: Mapped[CandidateProfile] = relationship(
        back_populates="certifications"
    )
