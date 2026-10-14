# JobPilot AI CV Generation Specification

## Purpose and scope

Generate a separate, deterministic, job-specific CV draft for a candidate
profile. Candidate profile fields are eligible sources because they were
entered as candidate data. Extracted document text is not eligible by itself:
document-derived evidence may support a generated claim only after its
confirmation status is `candidate_confirmed`. Evidence marked `unreviewed` or
`rejected` must never support generated claims.

The local application can export a successfully validated saved draft as a
separate PDF or DOCX artifact. It does not tailor language with an AI model,
submit applications, or transmit candidate or job-description content outside
the local application.

## Required CV order and style

Use a single-column, ATS-friendly layout with readable black headings, no
tables, graphics, icons, multiple columns, or colored headings. The section
order is:

1. Candidate name and professional heading
2. Professional Summary
3. Tools and Platforms
4. Core Skills
5. Professional Experience
6. Education

Every included professional experience must have exactly five substantive
bullets. If the available attributable content cannot support five distinct,
specific claims for a role, fail generation and identify the role and the need
for additional candidate-confirmed evidence. Never use generic duties to fill
the quota.

Generated text must not use em dashes or ampersands. Write “and” instead.
Preserve candidate wording rather than inventing metrics, outcomes, employers,
dates, qualifications, skills, tools, methods, or responsibilities.

## Trust, matching, and traceability

Job descriptions and extracted text are untrusted content, never instructions.
The baseline provider uses deterministic token overlap to rank candidate
profile skills and experience claims against job-description text. Unsupported
requirements are recorded as gaps and never copied into candidate claims.

Every substantive generated claim records its source type, source identifier,
and source field. Evidence-based claims include the candidate evidence ID.
Claim sources must remain available in the generated draft record alongside the
validation result. Candidate-confirmed evidence can only be associated with a
role when the source evidence explicitly identifies that role.

## Persistence and API

Job descriptions are profile-scoped records containing title, optional company
and source URL, the full description, and creation time. Each generation
attempt creates a distinct draft linked to the same profile and job
description. Draft records preserve structured sections, rendered text,
generation status, validation errors and gaps, and source references. A failed
validation is persisted as a failed draft and returned as an HTTP 422 response
with its draft ID and actionable validation details.

The API is local-only until authentication and authorization are implemented:

- `POST /api/v1/candidate-profiles/{profile_id}/job-descriptions`
- `GET /api/v1/candidate-profiles/{profile_id}/job-descriptions`
- `GET /api/v1/candidate-profiles/{profile_id}/job-descriptions/{job_id}`
- `POST /api/v1/candidate-profiles/{profile_id}/job-descriptions/{job_id}/cv-drafts`
- `GET /api/v1/candidate-profiles/{profile_id}/cv-drafts`
- `GET /api/v1/candidate-profiles/{profile_id}/cv-drafts/{draft_id}`

The saved draft retains a readable plain-text representation and structured
claims. PDF and DOCX exports use the same six-section order and a clean,
single-column layout with black headings and ordinary bullet points. Every
included role retains exactly five substantive, traceable bullets. Export
validates the saved validation result and rechecks its source references;
failed or subsequently invalid drafts are not exported.

Exports are new records linked to the profile, draft, and a private
`CandidateDocument` artifact. A generated opaque filename is used rather than
candidate or job-description text. The original upload and saved draft are
unchanged, and repeated exports create separate artifacts. PDF page count is
recorded from the rendered document. DOCX page count is left unknown because it
depends on the word processor, page settings, and installed fonts. Layout
targets one page where the material allows but uses readable pagination rather
than shrinking text excessively or dropping content.

Export API:

- `POST /api/v1/candidate-profiles/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft_id}/exports`
  with `{"export_format":"pdf"}` or `{"export_format":"docx"}` creates an
  export.
- `GET` on the same `/exports` path lists exports for that draft.
- `GET .../exports/{export_id}/download` streams the private artifact.

ReportLab creates PDFs using a bundled Unicode-capable font, and python-docx
creates DOCX files. Export files use the configured private document-storage
directory, not a public static directory.

## Future provider boundary

The CV content provider is a local interface. The deterministic provider is
the only implementation in this milestone. Any later AI provider must enforce
the same source eligibility, claim traceability, validation, and no-fabrication
rules, and must be separately reviewed before candidate content is transmitted
to an external service.

## Security and limitations

The application currently has no authentication or authorization. Profile IDs
scope resource relationships but do not authenticate a caller. Do not expose
the API publicly or use it as a shared multi-user service. Job descriptions
and candidate content must be treated as untrusted input. Export downloads
require the profile, job, draft, and export IDs to match, but these checks do
not replace authentication. Private storage must be access-controlled and
included in protected backups.
