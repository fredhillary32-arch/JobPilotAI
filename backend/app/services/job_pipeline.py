"""Sort discovered listings into actionable queues for one candidate.

Deterministic and explainable: every listing lands in exactly one queue with
structured reasons.

- ``auto_apply``: Kenya-eligible, no exclusions, and an automatic submission
  channel exists (none does today; see app.services.application_methods);
- ``needs_action``: eligible but the candidate must act (manual submission),
  or eligibility depends on a fact the candidate must confirm;
- ``review_needed``: eligibility unverified or conflicting, or the source is not
  a verified employer board;
- ``not_eligible``: ineligible, or excluded (expired, stale, duplicate, unsafe
  link, already tracked, or a work arrangement the candidate does not accept).

A listing's eligibility is never upgraded by its fit, and fit never hides an
exclusion.
"""

from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CandidateCertification,
    CandidateEligibilityDetails,
    CandidateJobDescription,
    CandidateProfile,
    CandidateSkillConfirmation,
    JobApplication,
    JobApplicationEvent,
    JobListing,
    TailoredCvDraft,
)
from app.services.application_methods import PREPARED_BY_JOBPILOT, automatic_submission_available, method_for
from app.services.ats_match import build_ats_report
from app.services.auth import utc_now
from app.services.cover_letter import draft_cover_letter
from app.services.cv_generation import generate_cv_draft, persist_cv_draft
from app.services.cv_writer import ReviewedCvWriter
from app.services.documents import DocumentStorage
from app.services.eligibility import latest_assessments_for
from app.services.kenya_eligibility import (
    ELIGIBLE,
    INELIGIBLE,
    NEEDS_INPUT,
    CandidateFacts,
    candidate_facts,
    decide,
    decide_cached,
)
from app.services.link_verification import latest_link_checks
from app.services.role_relevance import classify_title
from app.services.source_registry import entry_for_source

QUEUES = ("auto_apply", "needs_action", "review_needed", "not_eligible")
STALE_AFTER_DAYS = 14
UNSAFE_LINK_OUTCOMES = {"redirected_off_domain", "insecure", "unverified_domain"}
CATEGORY_RANK = {"direct_employer": 0, "recruitment_outsourcing": 1, "staffing_agency": 2, "aggregator": 3}
MAX_FIT_REPORTS = 25


# Imported text must fit the pasted-job limits; it is never truncated to fit.
MAX_IMPORTED_TITLE_LENGTH = 240
MAX_IMPORTED_DESCRIPTION_LENGTH = 50_000


class ImportRefused(ValueError):
    pass


def imported_job_for(session: Session, profile_id: UUID, listing_id: UUID) -> CandidateJobDescription | None:
    return session.scalar(
        select(CandidateJobDescription).where(
            CandidateJobDescription.candidate_profile_id == profile_id,
            CandidateJobDescription.source_job_listing_id == listing_id,
        )
    )


def import_listing(session: Session, profile_id: UUID, listing: JobListing) -> tuple[CandidateJobDescription, bool]:
    """Copy a stored listing into the profile's job descriptions once; (job, created)."""
    existing = imported_job_for(session, profile_id, listing.id)
    if existing is not None:
        return existing, False
    if listing.source_status != "active":
        raise ImportRefused("This listing is no longer listed by its source and cannot be imported.")
    description = listing.description_text or ""
    if not description.strip():
        raise ImportRefused("The source did not provide a job description for this listing.")
    if len(listing.title) > MAX_IMPORTED_TITLE_LENGTH or len(description) > MAX_IMPORTED_DESCRIPTION_LENGTH:
        raise ImportRefused(
            "This listing is too long to import without shortening it. Paste the relevant part as a job description instead."
        )
    job = CandidateJobDescription(
        candidate_profile_id=profile_id,
        job_title=listing.title,
        company=listing.employer_name,
        description=description,
        source_url=listing.application_url,
        source_job_listing_id=listing.id,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent request imported the same listing first; return that one.
        session.rollback()
        existing = imported_job_for(session, profile_id, listing.id)
        if existing is None:
            raise
        return existing, False
    session.refresh(job)
    return job, True


def write_reviewed_draft(
    session: Session,
    profile_id: UUID,
    job: CandidateJobDescription,
    storage: DocumentStorage,
    *,
    source_document_id: UUID | None = None,
    report: dict | None = None,
) -> TailoredCvDraft:
    """Generate and save a reviewed-writer CV draft; failed validation is saved as failed."""
    report = report or build_ats_report(session, job, storage, source_document_id=source_document_id)
    certifications = list(
        session.scalars(select(CandidateCertification).where(CandidateCertification.candidate_profile_id == profile_id))
    )
    confirmations = list(
        session.scalars(
            select(CandidateSkillConfirmation).where(
                CandidateSkillConfirmation.candidate_profile_id == profile_id,
                CandidateSkillConfirmation.status == "active",
            )
        )
    )
    writer = ReviewedCvWriter(
        report=report,
        certifications=certifications,
        source_document_id=str(source_document_id) if source_document_id else None,
        confirmations=confirmations,
    )
    outcome = generate_cv_draft(session, profile_id, job, provider=writer)
    # Gaps come from the job's essential CV requirements (not work style or keyword guesses).
    labels = {
        "missing": "Essential requirement not shown in your records",
        "uncertain": "Essential requirement only in unconfirmed sources",
        "unverified": "Essential requirement you left unverified",
        "not_possessed": "Essential requirement you said you do not have",
    }
    gaps = [
        f"{labels[item['status']]}: {item['text'][:160]}"
        for item in report["requirements"]["essential"]
        if item["status"] in labels
    ]
    outcome = replace(outcome, validation_results=outcome.validation_results.model_copy(update={"gaps": gaps}))
    return persist_cv_draft(session, profile_id, job, outcome)


def _reason(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def canonical_ids(listings: list[JobListing]) -> dict[UUID, JobListing]:
    """For each dedupe group the preferred listing: the employer's own posting first."""
    preferred: dict[str, JobListing] = {}
    for listing in listings:
        current = preferred.get(listing.dedupe_key)
        rank = (CATEGORY_RANK.get(listing.source_category or "", 4), listing.first_seen_at, str(listing.id))
        if current is None or rank < (
            CATEGORY_RANK.get(current.source_category or "", 4),
            current.first_seen_at,
            str(current.id),
        ):
            preferred[listing.dedupe_key] = listing
    return {listing.id: preferred[listing.dedupe_key] for listing in listings}


def exclusions(
    listing: JobListing,
    checks: dict,
    preferred: JobListing,
    tracked: JobApplication | None,
    accepted_arrangements: set[str],
    today: date,
) -> list[dict]:
    reasons: list[dict] = []
    if listing.source_status != "active":
        reasons.append(_reason("no_longer_listed", "The source no longer lists this vacancy."))
    if any(check.outcome == "expired" for check in checks.values()):
        reasons.append(_reason("link_expired", "The vacancy or application page now reports the posting as gone."))
    if listing.application_deadline and listing.application_deadline < today:
        reasons.append(
            _reason(
                "deadline_passed", f"The application deadline ({listing.application_deadline.isoformat()}) has passed."
            )
        )
    verified = listing.last_verified_at
    if verified is not None and verified.tzinfo is None:
        verified = verified.replace(tzinfo=utc_now().tzinfo)
    if listing.source_status == "active" and verified and utc_now() - verified > timedelta(days=STALE_AFTER_DAYS):
        reasons.append(
            _reason("stale_listing", f"The source has not confirmed this vacancy for over {STALE_AFTER_DAYS} days.")
        )
    if preferred.id != listing.id:
        reasons.append(
            _reason("duplicate", f"The same vacancy is listed from {preferred.employer_name}'s preferred source.")
        )
    application_check = checks.get("application")
    if not (listing.application_url or "").startswith("https://") or (
        application_check and application_check.outcome in UNSAFE_LINK_OUTCOMES
    ):
        reasons.append(
            _reason(
                "unsafe_application_link", "The application link is not a secure link on the employer's own platform."
            )
        )
    if tracked is not None:
        reasons.append(
            _reason(
                "already_tracked",
                f"You already track an application for this job (stage: {tracked.status.replace('_', ' ')}).",
            )
        )
    if (
        accepted_arrangements
        and listing.stated_workplace_type
        and listing.stated_workplace_type not in accepted_arrangements
    ):
        reasons.append(
            _reason(
                "arrangement_not_accepted",
                f"The job is {listing.stated_workplace_type}, which is not among the arrangements you confirmed you accept.",
            )
        )
    return reasons


def classify(listing: JobListing, decision: dict, excluded: list[dict]) -> tuple[str, list[dict], str]:
    """(queue, reasons, next step)."""
    method = method_for(listing.source_kind)
    registered = entry_for_source(listing.source_kind, listing.source_key) is not None
    if excluded:
        return "not_eligible", excluded, "No action needed. This listing is kept only for your records."
    if decision["state"] == INELIGIBLE:
        return (
            "not_eligible",
            [_reason(decision["rule"], decision["explanation"])],
            "No action needed: the employer's wording rules out Kenya-based applicants.",
        )
    if not registered:
        return (
            "review_needed",
            [_reason("unregistered_source", "This listing did not come from a verified employer board.")],
            "Check that the employer and link are genuine before relying on this listing.",
        )
    if decision["state"] == NEEDS_INPUT:
        required = ", ".join(c for item in decision["requirements"] for c in item["countries"]) or "the stated country"
        return (
            "needs_action",
            [_reason(decision["rule"], decision["explanation"])],
            f"Confirm on your profile whether you are authorized to work in {required}; JobPilot will not assume it.",
        )
    if decision["state"] != ELIGIBLE:
        return (
            "review_needed",
            [_reason(decision["rule"], decision["explanation"])],
            "Read the quoted wording and record a Kenya eligibility review, or skip this job.",
        )
    if automatic_submission_available(listing.source_kind):
        return "auto_apply", [], "Prepare the application; JobPilot can submit it once you approve."
    return (
        "needs_action",
        [_reason("manual_submission", method.reason)],
        "Prepare the application here, then submit it yourself on the official page.",
    )


def fit_summary(session: Session, profile_id: UUID, listing: JobListing, storage: DocumentStorage) -> dict:
    """Fit against confirmed records, on an unsaved job description (nothing is stored)."""
    job = CandidateJobDescription(
        id=uuid4(),
        candidate_profile_id=profile_id,
        job_title=listing.title,
        company=listing.employer_name,
        description=listing.description_text or "",
        source_job_listing_id=listing.id,
    )
    report = build_ats_report(session, job, storage)
    essential, preferred = report["requirements"]["essential"], report["requirements"]["preferred"]
    return {
        "score": report["score"],
        "potential_score": report["potential_score"],
        "verdict": report["verdict"],
        "headline": report["headline"],
        "essential_met": sum(1 for item in essential if item["status"] == "matched"),
        "essential_total": len(essential),
        "missing_essential": [item["text"][:140] for item in essential if item["status"] in {"missing", "uncertain"}][
            :5
        ],
        "missing_preferred": [
            item["text"][:140] for item in preferred if item["status"] != "matched" and item["basis"] != "inferred"
        ][:5],
    }


class PrepareRefused(ValueError):
    def __init__(self, message: str, reasons: list[dict]) -> None:
        super().__init__(message)
        self.reasons = reasons


def prepare_application(
    session: Session, profile_id: UUID, listing: JobListing, storage: DocumentStorage, today: date | None = None
) -> dict:
    """Run the preparation steps for one listing. Never submits anything.

    Rechecks the listing, destination and eligibility now (not from a cached view),
    then imports the job, writes a reviewed CV draft from confirmed evidence, drafts
    a cover letter, and records the application in the tracker as "preparing" with
    an audit note. Running it again reuses the job, draft and application.
    """
    today = today or date.today()
    steps: list[dict] = []

    def step(name: str, status: str, detail: str) -> None:
        steps.append({"step": name, "status": status, "detail": detail})

    facts = candidate_facts(session, profile_id)
    details = session.get(CandidateEligibilityDetails, profile_id)
    group = list(session.scalars(select(JobListing).where(JobListing.dedupe_key == listing.dedupe_key)))
    preferred = canonical_ids(group)[listing.id]
    excluded = [
        reason
        for reason in exclusions(
            listing,
            latest_link_checks(session, [listing.id]).get(listing.id, {}),
            preferred,
            None,
            set(details.accepted_work_arrangements) if details else set(),
            today,
        )
    ]
    if excluded:
        raise PrepareRefused("This listing cannot be prepared: " + " ".join(r["message"] for r in excluded), excluded)
    step(
        "Listing is current and the destination is safe",
        "done",
        f"Listed by the source; application page {listing.application_url}",
    )

    if entry_for_source(listing.source_kind, listing.source_key) is None:
        raise PrepareRefused(
            "This listing did not come from a verified employer board.",
            [_reason("unregistered_source", "Unverified source.")],
        )
    # A fresh decision, not the cached view.
    decision = decide(listing, latest_assessments_for(session, [listing.id]).get(listing.id), facts)
    if decision["state"] != ELIGIBLE:
        raise PrepareRefused(
            f"Kenya eligibility is {decision['state'].replace('_', ' ')}: {decision['explanation']}",
            [_reason(decision["rule"], decision["explanation"])],
        )
    step(
        "Kenya eligibility rechecked",
        "done",
        f'{decision["explanation"]} Evidence: "{decision["evidence"][0]["quotation"][:200]}"',
    )

    sibling_ids = [item.id for item in group]
    existing = session.scalar(
        select(JobApplication)
        .join(CandidateJobDescription, JobApplication.job_description_id == CandidateJobDescription.id)
        .where(
            CandidateJobDescription.candidate_profile_id == profile_id,
            CandidateJobDescription.source_job_listing_id.in_(sibling_ids),
        )
    )
    try:
        job, created = import_listing(session, profile_id, listing)
    except ImportRefused as exc:
        raise PrepareRefused(str(exc), [_reason("import_refused", str(exc))]) from exc
    step("Job description saved", "done", "Imported from the listing." if created else "Already saved; reused.")

    report = build_ats_report(session, job, storage)
    step(
        "Fit checked against your confirmed records",
        "done",
        f"Match score {report['score']} / 100. {report['headline']}"
        if report["score"] is not None
        else report["headline"],
    )

    draft = session.scalar(
        select(TailoredCvDraft)
        .where(TailoredCvDraft.job_description_id == job.id, TailoredCvDraft.status.in_(("generated", "needs_review")))
        .order_by(TailoredCvDraft.created_at.desc())
    )
    if draft is None:
        draft = write_reviewed_draft(session, profile_id, job, storage, report=report)
    if draft.status == "generated":
        step(
            "Tailored CV draft written",
            "done",
            "Built from confirmed records only. Review the changes and approve it before exporting.",
        )
    elif draft.status == "needs_review":
        step(
            "Tailored CV draft written",
            "done",
            "Saved as incomplete: "
            + " ".join(issue["message"] for issue in draft.validation_results.get("issues", [])[:3])
            + " Add the missing evidence in Tailored CVs, or approve it as incomplete.",
        )
    else:
        step(
            "Tailored CV draft written",
            "blocked",
            "The draft needs more confirmed evidence: " + " ".join(draft.validation_results.get("errors", [])[:3]),
        )

    profile = session.get(CandidateProfile, profile_id)
    letter = draft_cover_letter(session, profile, job.job_title, job.company, report)
    step("Cover letter drafted", "done", "Uses your summary and confirmed work history only. Edit it before use.")

    method = method_for(listing.source_kind)
    if existing is not None:
        application = existing
        step(
            "Application tracked",
            "done",
            f"Already tracked (stage: {existing.status.replace('_', ' ')}); nothing duplicated.",
        )
    else:
        note = (
            f"Prepared by JobPilot on {today.isoformat()}. Eligibility: {decision['rule']}. "
            f"CV draft: {'ready for your review' if draft.status == 'generated' else 'incomplete, needs your review' if draft.status == 'needs_review' else 'needs more evidence'}. "
            f"Submission is manual: {method.reason}"
        )
        application = JobApplication(
            candidate_profile_id=profile_id,
            job_description_id=job.id,
            status="preparing",
            cv_draft_id=draft.id if draft.status in {"generated", "needs_review"} else None,
            deadline_on=listing.application_deadline,
        )
        application.events.append(
            JobApplicationEvent(from_status=None, to_status="preparing", note=note, occurred_at=utc_now())
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        step(
            "Application tracked",
            "done",
            "Added to Applications as Preparing application, with this preparation noted in its history.",
        )
    step("Submission", "handed_to_you", method.reason)

    return {
        "listing_id": str(listing.id),
        "job_description_id": str(job.id),
        "cv_draft_id": str(draft.id),
        "cv_draft_status": draft.status,
        "application_id": str(application.id),
        "application_status": application.status,
        "submitted": False,
        "steps": steps,
        "eligibility": decision,
        "fit": {"score": report["score"], "potential_score": report["potential_score"], "headline": report["headline"]},
        "cover_letter": letter,
        "handoff": {
            "application_url": listing.application_url,
            "reason": method.reason,
            "candidate_steps": list(method.candidate_steps),
        },
    }


def build_pipeline(
    session: Session,
    profile_id: UUID,
    listings: list[JobListing],
    storage: DocumentStorage,
    *,
    include_fit: bool = True,
    today: date | None = None,
    per_queue: int = 100,
) -> dict:
    today = today or date.today()
    facts: CandidateFacts = candidate_facts(session, profile_id)
    details = session.get(CandidateEligibilityDetails, profile_id)
    accepted = set(details.accepted_work_arrangements) if details else set()
    ids = [listing.id for listing in listings]
    assessments = latest_assessments_for(session, ids)
    checks = latest_link_checks(session, ids)
    preferred = canonical_ids(listings)
    tracked = {
        listing_id: application
        for listing_id, application in session.execute(
            select(CandidateJobDescription.source_job_listing_id, JobApplication)
            .join(JobApplication, JobApplication.job_description_id == CandidateJobDescription.id)
            .where(
                CandidateJobDescription.candidate_profile_id == profile_id,
                CandidateJobDescription.source_job_listing_id.is_not(None),
            )
        ).all()
    }

    queues: dict[str, list[dict]] = {name: [] for name in QUEUES}
    fits = 0
    for listing in sorted(
        listings,
        key=lambda item: (
            item.posted_at is None,
            -(item.posted_at.timestamp() if item.posted_at else 0),
            str(item.id),
        ),
    ):
        decision = decide_cached(listing, assessments.get(listing.id), facts)
        excluded = exclusions(
            listing, checks.get(listing.id, {}), preferred[listing.id], tracked.get(listing.id), accepted, today
        )
        queue, reasons, next_step = classify(listing, decision, excluded)
        method = method_for(listing.source_kind)
        entry = entry_for_source(listing.source_kind, listing.source_key)
        card = {
            "listing_id": str(listing.id),
            "title": listing.title,
            "employer": listing.employer_name,
            "location": listing.location_text,
            "workplace_type": listing.stated_workplace_type,
            "posted_at": listing.posted_at,
            "first_seen_at": listing.first_seen_at,
            "application_deadline": listing.application_deadline,
            "listing_url": listing.listing_url,
            "application_url": listing.application_url,
            "source": {
                "name": entry.name if entry else None,
                "category": listing.source_category,
                "registered": entry is not None,
            },
            "queue": queue,
            "reasons": reasons,
            "next_step": next_step,
            "eligibility": decision,
            "role_match": role_match.as_dict() if (role_match := classify_title(listing.title)) else None,
            "application_method": {
                "submission": method.submission,
                "reason": method.reason,
                "jobpilot_prepares": list(PREPARED_BY_JOBPILOT),
                "candidate_steps": list(method.candidate_steps),
            },
            "application": (
                {"id": str(tracked[listing.id].id), "status": tracked[listing.id].status}
                if listing.id in tracked
                else None
            ),
            "fit": None,
        }
        if include_fit and queue in {"auto_apply", "needs_action"} and fits < MAX_FIT_REPORTS:
            card["fit"] = fit_summary(session, profile_id, listing, storage)
            fits += 1
        queues[queue].append(card)
    return {
        "counts": {name: len(items) for name, items in queues.items()},
        "queues": {name: items[:per_queue] for name, items in queues.items()},
        "automation": {
            "automatic_submission_available": False,
            "explanation": (
                "None of the current job sources lets an applicant submit through an official channel: "
                "Greenhouse, Lever and Ashby only accept API applications with the employer's own credentials. "
                "JobPilot prepares each application and you submit the final form yourself."
            ),
        },
        "generated_at": utc_now(),
    }
