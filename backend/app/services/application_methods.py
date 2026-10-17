"""What JobPilot can and cannot do for each application platform.

Automatic submission is only legitimate through an official channel the employer
and platform authorize for the applicant. Each platform's documentation (checked
2026-10-17) puts application submission behind employer credentials:

- Greenhouse Job Board API: the submit endpoint requires Basic Auth with the
  employer's Job Board API key.
- Lever Postings API: POST requires an API key a Super Admin of the employer's
  account generates.
- Ashby: applicationForm.submit requires an authenticated key with the
  candidatesWrite permission.

A candidate cannot use those, and filling the employer's web form by automation
would mean working around bot protection, which JobPilot does not do. So every
current platform is ``manual_submission``: JobPilot prepares everything it can
and hands the final step to the candidate. A platform only becomes automatable
by adding an adapter here with a real, authorized submission channel.
"""
from dataclasses import dataclass

PREPARED_BY_JOBPILOT = (
    "Kenya eligibility check with quoted evidence",
    "Fit check against your confirmed records",
    "Tailored CV draft from confirmed evidence (you review and approve it)",
    "Cover letter draft from confirmed records (you review and edit it)",
    "Application record in your tracker, with each step noted",
)


@dataclass(frozen=True)
class ApplicationMethod:
    platform: str
    submission: str  # "automatic" | "manual_submission"
    reason: str
    candidate_steps: tuple[str, ...]


_MANUAL_STEPS = (
    "Open the official application page from this card.",
    "Upload the PDF or DOCX of your approved tailored CV.",
    "Paste or adapt the cover letter if the form asks for one.",
    "Answer screening questions yourself; JobPilot does not answer them for you.",
    "Read and accept any declarations or consent statements yourself.",
    "Submit, then record the submission date in Applications.",
)
_REASONS = {
    "greenhouse": "Greenhouse only accepts applications through its API with the employer's private API key.",
    "lever": "Lever only accepts applications through its API with a key from the employer's administrator.",
    "ashby": "Ashby only accepts applications through its API with an employer key that can write candidates.",
}


def method_for(source_kind: str) -> ApplicationMethod:
    reason = _REASONS.get(
        source_kind,
        "This application page is not supported for automatic submission.",
    )
    return ApplicationMethod(
        platform=source_kind,
        submission="manual_submission",
        reason=reason + " JobPilot does not automate employer web forms or bypass bot checks, so you submit the final form.",
        candidate_steps=_MANUAL_STEPS,
    )


def automatic_submission_available(source_kind: str) -> bool:
    return method_for(source_kind).submission == "automatic"
