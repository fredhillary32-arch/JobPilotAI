# JobPilot AI

JobPilot AI is a React/TypeScript frontend and FastAPI backend backed by
PostgreSQL. The backend database integration uses SQLAlchemy 2.x, Psycopg 3,
Pydantic Settings, and Alembic.

Implemented in the repository and covered by automated tests: local owner
sign-in with session and CSRF protection and per-request candidate-resource
ownership checks; candidate profile CRUD with work history, education, skills
and certifications; document upload, local text extraction and evidence review
(only candidate-uploaded source documents can become extracted text or
evidence); manually pasted job descriptions; a local ATS-style match report
(requirements, evidence, score, eligibility, formatting risks); deterministic,
evidence-backed tailored CV drafts with a reviewable change log, candidate
edits and approval; and PDF/DOCX CV exports that are read back before saving.

Job discovery: a verified source registry
(`backend/app/data/source_registry.json`,
38 organisations; 8 enabled for automatic discovery) with Greenhouse, Lever and
Ashby public-API adapters run from the CLI, separate rate-limited checks of each
listing's vacancy page and application link, cross-source duplicate collapsing
that prefers the employer's own posting, and a "Discovered jobs" page that opens
on listings posted in the last 24 hours with source, link, vacancy-status and
eligibility details. A listing can be
imported into a profile's job descriptions with one action, so it flows
straight into tailored CV generation and export.

Kenya eligibility is evidence-based and reviewed by the candidate: a listing
shows that Kenya-based applicants are accepted or excluded only after a review
records the exact sentence from the listing that says so (see
[docs/JOB_ELIGIBILITY_SPEC.md](./docs/JOB_ELIGIBILITY_SPEC.md)). If the
listing's wording later changes, the result reverts to "not established".

Application tracking: each saved job can be tracked once through the stages
Saved, Eligibility review, Preparing application, Ready for review, Applied,
Assessment or interview, Offer, Rejected, Withdrawn and Closed, with a status
history, deadline, follow-up date, contact, notes and the tailored CV used. An
application only counts as applied when the candidate records the date it was
submitted. The dashboard shows active applications and dates due within two
weeks.

Work eligibility details and job fit: the candidate can confirm their country
of residence, work authorization per country, relocation willingness and
accepted work arrangements on the profile page. Only confirmed details are
used; the free-text profile location is never treated as confirmed, and work
authorization is never inferred from residence or nationality. For each saved
job, a deterministic fit check lists requirements met (with the profile record
or confirmed evidence that supports each), requirements not found, uncertain
items (unreviewed evidence, unclear or contradictory location wording) and
potential disqualifiers (a strict location or work-authorization requirement
that conflicts with a confirmed detail). Kenya eligibility is shown separately
from skills coverage, comes only from the reviewed listing assessment, and an
employer's stated exclusion is never outweighed by skills coverage.

Not yet implemented: adapters for staffing-agency sites (none publishes a
documented public feed; they are registered as manual-only), Workable and other
ATS platforms, scheduled re-checks, cover letters and screening answers,
assisted submission, reminders beyond the dashboard, and interview preparation.

This is a local, single-owner application. No push to a shared remote or any
deployment is authorized; keep both servers bound to `127.0.0.1`.

## Local backend setup

Use Python 3.11 or newer. From the repository root, copy `.env.example` to
`.env` and set a private local PostgreSQL password. Never commit `.env` or put
credentials in source code.

The included Compose configuration maps PostgreSQL's container port 5432 to
`127.0.0.1:5433` on the host. Start the database with:

```powershell
docker compose up -d postgres
```

Install backend dependencies and start the API:

```powershell
Set-Location backend
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API reads database settings from environment variables, with the repository
root `.env` loaded for local development. `POSTGRES_USER`, `POSTGRES_PASSWORD`,
and `POSTGRES_DB` are required. `POSTGRES_HOST` defaults to `127.0.0.1` and
`POSTGRES_PORT` defaults to `5433`.

- `GET http://127.0.0.1:8000/healthz` reports process liveness without accessing
  the database.
- `GET http://127.0.0.1:8000/readyz` executes `SELECT 1`, then compares the
  database's Alembic revision with the repository head. It returns HTTP 503
  with a generic message if the database is unavailable or the schema has not
  been migrated; it never reports revision identifiers or connection details.
- Candidate profiles are available under `/api/v1/candidate-profiles`: create
  with `POST`, list the signed-in user's own profiles with `GET`, retrieve by
  ID with `GET /{profile_id}`, partially update with `PATCH`, and list
  profile records at `/{profile_id}/experiences`, `/education`, `/skills`, and
  `/certifications`. Each of those collection endpoints supports `GET` and
  `POST`; retrieve one record with `GET /{profile_id}/{collection}/{record_id}`,
  update it with `PATCH`, and delete it with `DELETE` on that same record path.
  Record IDs are scoped to their profile. Invalid date
  ranges and field values return HTTP 422, unknown or mismatched profile/record
  IDs return 404, and duplicate skills within one profile return HTTP 409.
  Profile history forms accept candidate-provided information. Enter only
  accurate facts; claims copied from extracted uploads remain unverified until
  reviewed through the evidence workflow.
- Original CVs and supporting documents can be uploaded to
  `/api/v1/candidate-profiles/{profile_id}/documents`, listed from the same
  endpoint, retrieved by document ID, and downloaded from the document's
  `/download` endpoint. Uploads accept PDF, DOCX, and UTF-8 TXT files up to 10
  MB. Every upload creates an immutable document record; uploading a new CV
  never replaces a prior source file. There is no document deletion endpoint.
  The list accepts `?origin=source` (candidate uploads only) or
  `?origin=generated` (system-generated CV exports); the default `all` returns
  both. Only candidate-uploaded source CVs and supporting documents can be
  extracted or used as evidence; generated exports return HTTP 409.
- Start or retry local text extraction with
  `POST /api/v1/candidate-profiles/{profile_id}/documents/{document_id}/extraction`.
  Read extraction status and metadata with `GET` on that path, or retrieve the
  text from its `/text` endpoint. The extractor supports embedded PDF text,
  DOCX paragraphs and tables, and UTF-8 TXT. Results are source text, not
  verification of a candidate's claims. Scanned PDFs receive a `no_text`
  status; OCR is not performed.
- List source-linked evidence at
  `/api/v1/candidate-profiles/{profile_id}/evidence`. `POST` creates evidence
  from an existing document's extracted text; source excerpts or offsets must
  match that text. `GET`, `PATCH`, and `DELETE` operate on an evidence record.
  New evidence starts as `unreviewed`; change `confirmation_status` explicitly
  to `candidate_confirmed` or `rejected` only after candidate review. Offsets
  refer to the normalized extracted text and evidence is not independently
  verified.
- Create, list, and retrieve profile-scoped job descriptions at
  `/api/v1/candidate-profiles/{profile_id}/job-descriptions`. Saved job
  descriptions cannot yet be edited or deleted. Create a tailored
  CV draft with
  `POST /api/v1/candidate-profiles/{profile_id}/job-descriptions/{job_id}/cv-drafts`.
  List drafts at `/api/v1/candidate-profiles/{profile_id}/cv-drafts` and
  retrieve an individual draft by ID. Each generation attempt creates a
  separate stored draft. Failed validation returns HTTP 422 with the persisted
  draft ID and actionable validation details; it does not return fabricated or
  partial CV content.

Run backend tests from `backend` with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Original document bytes are stored outside PostgreSQL in a private local
directory, `var/documents` by default. Set `DOCUMENT_STORAGE_PATH` in `.env` to
use another location. PostgreSQL stores extracted text and evidence metadata.
The parser does not execute macros or scripts, use OCR, or send documents to an
external service. Extraction has document-size, page-count, text-length, and
DOCX archive limits; it is not malware scanning or content sanitization.
Extracted content must be treated as untrusted input and is never an instruction
to the application or a future AI system. Restrict filesystem and database
access and include both in access-controlled backups.

The API now requires a valid session for candidate-resource routes. Profile
IDs are selectors only: the server checks ownership for each request, and
unassigned legacy profiles remain inaccessible until explicitly adopted by the
local operator. Login has no public registration flow. Keep the app local and
loopback-only. On 2026-10-17 a 28-step walkthrough passed in Google Chrome
(driven by Playwright) through the Vite proxy, FastAPI and PostgreSQL against a
freshly restored and migrated copy of the configured database; the real
account was not signed in to (see the handoff for the steps and limits).

**The configured database must be at the repository head before the full app
can run.** The latest migration is `d8b4f6a2c9e1` (source verification and link
checks). With approval, the configured `jobpilot` database was migrated from
`a17c3e5b9d24` to `d8b4f6a2c9e1` on 2026-10-17 after a fresh verified backup and
restore rehearsal; existing rows and documents were unchanged and `/readyz`
returned HTTP 200. The ATS and CV-review work added no migration. A database
below the head makes `/readyz` return 503. Follow the backup,
restore-verification, and migration runbook in
[docs/PROJECT_HANDOFF.md](./docs/PROJECT_HANDOFF.md) before any future
migration.

## Database migrations

Candidate profile models are registered with Alembic metadata. After inspecting
and editing the generated migration, create and apply future schema changes
from `backend` with:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe schema change"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
```

Review every generated migration before applying it. Alembic autogeneration
compares `Base.metadata` with the configured database; it does not replace
manual migration review.

## CV text extraction and evidence

The backend dependencies install PyMuPDF and python-docx for local PDF and DOCX
parsing. No additional configuration or external service is required. Run
extraction on an uploaded document using the `POST` endpoint above, inspect its
`status` and `error_category`, then fetch extracted text. A successful
extraction reports `trust_status: "unverified_source_text"`; only evidence
explicitly reviewed by the candidate should be marked candidate-confirmed.

After a successful extraction the Documents page also calls
`POST /api/v1/candidate-profiles/{profile_id}/documents/{document_id}/evidence-suggestions`
(also offered as "Suggest evidence" for documents extracted earlier). Fixed
local rules read the CV's sections and turn experience bullets, achievements,
figures, projects, listed skills, degrees and certifications into evidence
records. Each record is the exact extracted excerpt with its offsets and section,
described in the CV's own words and saved as `unreviewed`. Contact details and
summary, reference and interest sections are skipped. A document yields at most
50 suggestions, of which at most 25 are skills. Excerpts that already have
evidence for the document, in any review state, are skipped, so repeating the
request never duplicates claims, brings back rejected ones or changes a
decision. Nothing is sent to an external service.

Evidence is used only while its excerpt is still at its offsets in the
document's current successful extraction. After a failed or changed
re-extraction the API reports `source_current: false`; such evidence keeps its
review decision but is left out of CV drafts, ATS matching and job fit, blocks
export of drafts that cite it, and cannot be confirmed until it is re-linked
(`PATCH` with the same `source_excerpt` and null offsets) or rejected. No
migration was needed: currency is computed from the stored extraction.

The extraction and evidence tests use synthetic documents and in-memory
SQLite; they do not require PostgreSQL. From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_document_extraction_and_evidence.py
.\.venv\Scripts\python.exe -m pytest
```

## Strict Kenya eligibility and the job pipeline

`app/services/kenya_eligibility.py` decides, from stored listing text only, one
of `eligible`, `ineligible`, `unverified` or `needs_candidate_input`. It fails
closed: only the employer's own location field or a role-scoped sentence that
names Kenya (or says the role can be done from anywhere, unhedged and
unrestricted) makes a listing eligible, and only from a registry-verified,
non-aggregator source with a secure link. "Remote", EMEA or Africa, company
marketing, and missing restrictions never count. Location labels or titles
naming only other places, strict residency requirements, and work
authorization the candidate confirmed they lack make it ineligible; work
authorization the candidate has not confirmed makes it
`needs_candidate_input` (never inferred from residence). A current candidate
review takes precedence; a stale review or conflicting wording is `unverified`.
Each decision carries the exact quotation, field, source URL and type, the
date the text was checked, the rule and any conflicts. `GET /api/v1/job-listings`
returns it as `kenya_eligibility` and `?kenya=eligible` returns only eligible
listings.

`GET /api/v1/candidate-profiles/{profile_id}/job-pipeline` (optional
`posted_within_hours`, `q`, `role_family`) sorts listings into `auto_apply`,
`needs_action`, `review_needed` and `not_eligible`, with structured reasons for
expired, stale (not confirmed by the source for 14 days), duplicate, already
tracked, unsafe-link and unaccepted-arrangement exclusions, plus a fit summary.
`POST .../job-listings/{listing_id}/prepare-application` rechecks the listing,
destination and eligibility, imports the job, writes a reviewed CV draft and a
cover letter draft from confirmed records, and records the application as
"Preparing application" with an audit note. Repeating it reuses everything. It
never submits: Greenhouse, Lever and Ashby accept API applications only with
the employer's credentials (their documentation, checked 2026-10-17), and
JobPilot does not automate employer web forms, so the auto-apply queue stays
empty until an authorized submission channel exists.

## ATS match report and reviewed CV writer

Everything here runs locally and deterministically; no CV or profile data is
sent to any external service, and no AI provider is used.

`GET /api/v1/candidate-profiles/{profile_id}/job-descriptions/{job_id}/ats-analysis`
(optional `?source_document_id=`) is read-only. It splits the job description
into essential and preferred requirements, duties, tools, experience, education,
certifications and eligibility wording, keeping each item's exact source text
and offsets and whether it was stated, inferred (a tool named only in the
duties) or ambiguous. Company, salary and benefits text is ignored. Each
requirement is then judged against the candidate's records: **matched** only
when work history, confirmed evidence, a certification or education shows it;
**partial** when it is only in the skills list or summary (a keyword is not
proof) or only part of it is shown; **uncertain** when only unreviewed evidence
or the uploaded CV mentions it; otherwise **missing**. The score (0-100) weights
essential requirements 55, preferred 15, duties shown 15 and important terms 15,
drops empty parts and rescales, and is returned with its per-part arithmetic, a
"potential" score if uncertain items were confirmed, and its limitations. It is
not a reproduction of any employer's screening system. Kenya eligibility,
location and work-authorization findings are reported separately and always
take precedence: an employer exclusion or a confirmed conflict sets the verdict
regardless of score. The report also lists screening concerns (missing
essentials, experience shortfall, employment gaps), ranked recommendations,
and, for a selected uploaded CV, layout risks (tables used for layout, text
boxes, columns, contact details in headers or footers, images, icon-font
symbols, missing standard headings, mixed date formats), statements with
figures that are not in confirmed records, and dates that disagree with the
profile. The uploaded CV is only read; it is never modified or replaced.

`POST .../job-descriptions/{job_id}/cv-drafts` with `{"writer": "reviewed"}`
(the UI default; an empty body keeps the original writer) writes a tailored
draft: experience in reverse date order with the profile's titles and dates,
up to five bullets per role chosen by relevance to the job, contact details,
skills ordered by relevance, and certifications. Statements are restated only
by removing filler ("responsible for", "worked on", "successfully", first
person), using past tense for finished roles and consistent punctuation; any
restatement that would add a word or number not in the source is discarded in
favour of the original wording. A summary sentence naming the job's
requirements is added only when work records or confirmed evidence demonstrate
them. `GET /api/v1/candidate-profiles/{profile_id}/cv-drafts/{draft_id}/review`
returns, for every statement, the original, the proposed text, the reasons, the
evidence and whether confirmation is needed, plus writing suggestions that were
not applied, pre-export checks (sections, role dates, duplicates, characters,
keyword repetition, length, contact details, opener variety), the plain-text
preview and the source trace. `POST .../cv-drafts/{draft_id}/revisions` saves
the candidate's edits as a new draft version (the original is kept); edited
wording not found in the records is flagged. `POST .../cv-drafts/{draft_id}/approval`
approves a draft and requires `attest_unconfirmed_statements: true` when
flagged statements remain. Reviewed drafts cannot be exported until approved.
Every PDF or DOCX export is read back with the local extractors and refused
unless every approved line appears once and in order; the creation response
includes that `verification`. Review state is stored with the draft's
structured content.

### Incomplete drafts and the candidate's answers

A draft whose content is sound but incomplete (for example a role with fewer
than five supported bullets, or no summary) is saved with status
`needs_review` and grouped, actionable `issues`; nothing is invented to fill
the gaps. Approve it with `acknowledge_incomplete: true` to export it.
Integrity errors (an unsourced claim, a duplicate bullet) still fail a draft.

Answer a job requirement, or record a skill on its own, under
`/api/v1/candidate-profiles/{profile_id}/skill-confirmations` (`GET`, `POST`,
`PUT .../{id}`, `POST .../{id}/withdraw`). Responses are `has_skill`,
`used_in_role` (requires an example in your own words, and a recorded role or
a project), `needs_details`, `not_possessed` and `unsure`. The server takes the
requirement text from its own analysis of the saved job, and a role must belong
to the same profile. Answers are the candidate's statements, never marked as
independently verified: a confirmed skill earns half credit in the match score,
and `evidence_strength` keeps them apart from document-backed evidence. The ATS
report lists personal qualities and work style separately for interview
preparation (not scored) and keeps team context ("How we work together") out of
the requirements. This needs migration `e7c4a9d2b6f3`.

## Evidence-backed CV drafts

The local deterministic provider ranks candidate profile skills and work
experience against each stored job description. It uses profile data and
candidate-confirmed evidence only. Unreviewed and rejected document evidence
are excluded. Unsupported requirements are recorded as validation gaps and
are not copied into candidate claims. Every emitted claim has structured
source references saved with the draft. Roles need five distinct substantive
supported bullets; otherwise the attempt is saved as failed and the response
identifies the role that needs more evidence. The provider does not invent
claims, and does not contact an AI service.

CV drafts contain the required single-column section order and plain text.
The draft targets one page where the source material permits it, but does not
shrink text to force one page. The "Tailored CVs" page shows each draft's
generated text, validation errors and gaps, and offers PDF/DOCX export for
validated drafts; the API also returns `generated_content` and
`structured_content`. Export a successfully validated draft as PDF or DOCX through
`POST /api/v1/candidate-profiles/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft_id}/exports`
with `{"export_format":"pdf"}` or `{"export_format":"docx"}`. List exports on
that route with `GET`, and download one with
`GET .../exports/{export_id}/download`. Failed drafts or drafts whose saved
validation/source evidence no longer passes validation cannot be exported.
Export records include the draft association, format, creation time, safe
generated filename, and PDF page count. DOCX page count is `null` because it
depends on the word processor and its installed fonts. PDF exports report
rendered page count and paginate at readable font sizes rather than deleting
content or shrinking it to force one page.

PDF rendering uses ReportLab and its bundled Unicode-capable Vera font;
DOCX uses python-docx. The exported layout is a private, single-column
ATS-friendly document with the specified section order and five supported
bullets per included role. Exports are separate immutable artifacts stored
through the same private local document-storage service as source uploads;
metadata is stored in PostgreSQL. Generated filenames do not contain
candidate or job-description text. The original uploads, saved draft, and
earlier exports are not overwritten. No AI service receives candidate content.
See [CV_GENERATION_SPEC.md](./docs/CV_GENERATION_SPEC.md) for trust rules,
layout, provider boundary, export behavior, and current limitations.

These endpoints remain local-only. Authentication and ownership checks do not
make this a public or shared multi-user service; do not expose it beyond the
local machine.

CV generation tests use synthetic candidate data and the in-memory SQLite
test database. From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cv_generation.py
.\.venv\Scripts\python.exe -m pytest
```

Export tests use synthetic CV content and in-memory SQLite. Run them from
`backend` with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_cv_exports.py
```

## Job discovery

Discovery runs from the operator CLI, or from the **Refresh all sources** button
in Discovered jobs, which starts the same runner in a background thread
(`POST /api/v1/job-discovery/refresh`, authenticated and CSRF-checked) and
reports progress at `GET /api/v1/job-discovery/refresh`; no page request waits
on an external site, and the listing endpoints never contact one. From
`backend`, after confirming which database the process will use:

```powershell
.\.venv\Scripts\python.exe -m app.cli validate-sources                  # check the registry; no network
.\.venv\Scripts\python.exe -m app.cli list-sources
.\.venv\Scripts\python.exe -m app.cli discover-registry                 # every enabled source (incremental)
.\.venv\Scripts\python.exe -m app.cli discover-registry --source gitlab # one source
.\.venv\Scripts\python.exe -m app.cli discover-registry --full          # whole window, not only what is new
.\.venv\Scripts\python.exe -m app.cli discovery-status                  # latest run of every enabled source
.\.venv\Scripts\python.exe -m app.cli verify-links --limit 20 --delay 2
.\.venv\Scripts\python.exe -m app.cli discover-greenhouse --board <token> --employer "<Employer name>"
```

`discover-registry` exits 0 when every source ran or was paced, 1 when a source
failed, 2 for bad input and 3 when another discovery pass is running: a pass
holds an in-process lock and, on PostgreSQL, an advisory lock, so a CLI run and
a UI refresh never overlap. Sources whose terms ask for a gap between passes
(Jobicy: one per hour) are skipped with the reason until it has passed
(`--force` overrides; use sparingly). A run still marked `running` an hour after
it started is reported as interrupted; history is never rewritten. To schedule
discovery, register `discover-registry` with Windows Task Scheduler yourself,
for example every four hours; nothing is scheduled automatically.

Adapters use each platform's documented public API only: Greenhouse
(`boards-api.greenhouse.io`), Lever (`api.lever.co`, `api.eu.lever.co`) and
Ashby (`api.ashbyhq.com`), plus three free, keyless job-board aggregators whose
terms were read on 2026-10-17 and are recorded in the registry: Jobicy
(`jobicy.com/api/v2/remote-jobs`, cursor-paged, last 7 days, at most one pass an
hour, credit Jobicy and keep its URL), Arbeitnow (`www.arbeitnow.com/api/job-board-api`,
paged, newest first, link back requested) and Remote OK (`remoteok.com/api`,
link back to Remote OK required). Remotive is not used. We Work Remotely (terms
could not be read), Working Nomads (its terms bar building a competing service)
and Himalayas (no terms found) were evaluated and left out. Aggregators are
discovery sources only: their listings link to the aggregator's own page, their
dates are shown as the job board's publication date, and Kenya wording in them
is never treated as authoritative (it stays "not established"). Their feeds are
windows onto recent postings, so a job missing from one response is never
marked `missing_from_source`. Nothing about the candidate is sent to any
source. Requests are pinned to that host, including on
redirects, with a 20-second timeout, a 20 MB response limit and at most three
attempts with backoff for timeouts, HTTP 429 (honouring `Retry-After`, capped)
and 5xx. Board identifiers are validated. One failing source never stops
`discover-registry` from running the others. Entries a run cannot store are
counted with a reason (for example "no usable https application URL"), never
silently dropped.

The registry records, for every organisation, its official domain and careers
page, category (direct employer, staffing agency, recruitment or outsourcing
firm, aggregator), discovery method, and when and how it was verified. A source
is enabled only when its job board was found on the organisation's own careers
page; staffing agencies and employers without a documented public feed are
manual-only and are never fetched. Each run is recorded in
`job_discovery_runs` before fetching, so failures are kept with an error
category. A failed fetch leaves stored listings untouched; after a successful
run, listings the source no longer returns are marked `missing_from_source`,
never deleted; a listing that later reappears is marked `relisted_at` without a
new posting date. Listings store only what the source states: `posted_at` is
Greenhouse `first_published`, Lever `createdAt` or Ashby `publishedAt` when
present, and workplace type, countries, salary and deadline stay empty unless
the source provides them. Every description section is kept, so location and
eligibility wording anywhere in a posting is preserved for review. The public
vacancy page (`listing_url`) and the application link are stored separately.

`verify-links` checks a bounded number of listings (oldest-checked first, at
least one second apart). Links are requested only over HTTPS on the source's own
platform or official domain; redirects elsewhere are recorded as
`redirected_off_domain` and not followed. Outcomes are `reachable`, `expired`
(404/410, or Greenhouse's "posting not found" redirect), `auth_required`,
`rate_limited`, `broken`, `unreachable`, `insecure` and `unverified_domain`.
"Reachable" means the page answered; it does not prove the vacancy is open or
that the application form works. When the vacancy page also hosts the form, the
record says the form itself was not tested. No form is submitted.

The job-listing and discovery-run endpoints require an authenticated session
(anonymous requests receive HTTP 401). Discovered listings and runs are shared
application records: they have no owner or candidate-profile link, so any
signed-in user of this local app sees the same listings.

`GET /api/v1/job-listings` supports `source_status`, `limit`, `offset`,
`eligibility`, `eligible_scope` (`kenya_named`, `africa`, `emea`, `worldwide`),
`q` (title or employer; comma-separated keywords, any of which may match),
`role_family` (repeatable: `support_it`, `customer_support`,
`ecommerce_support`, `operations_support`), `exclude_role_family`
(repeatable), `source` (a registry id), `workplace` (`remote`, `hybrid`,
`onsite`, as stated by the source), `sort` (`posted`, the default, with undated
listings last; `discovered`; `relevance`), `kenya` (the strict state),
`source_category`, `verified_application_link`, `include_expired_links`
(default false), `collapse_duplicates` (default true) and `posted_within_hours`,
which matches only listings whose source-stated `posted_at` falls between the
cut-off and now; the UI offers 24 hours, 3, 7, 14 and 30 days, or all.
Role groups come from the title only (`app/services/role_relevance.py`):
technical and IT support; customer support and service; e-commerce and
marketplace support (seller, merchant, orders, returns and refunds, payments,
delivery, trust and safety); and related support operations (SaaS and product
support, implementation, onboarding, service operations). Leadership,
DevOps/SRE, customer-success management, sales and other business titles never
match. Role and Kenya filters are applied to every candidate row before totals
and paging. Each listing reports `role_match` (family, group and the matched
words) and `posted_at_source` (`employer_board`, `job_board` or null when the
source gave no date; the discovery time is never used as a posting date).
Each listing reports its registry source, its latest vacancy-page and
application-link checks, its vacancy status (`listed_by_source`,
`no_longer_listed`, `link_expired`) and how many other sources list the same
vacancy; `GET /api/v1/job-listings/{id}` lists those alternates.
`GET /api/v1/job-sources` returns the registry with each source's run health. Listings without
a posting date, or dated in the future, are excluded and never given a guessed
date.

Each listing reports its effective Kenya eligibility (`eligible_confirmed`,
`not_eligible` or `eligibility_unknown`) with its currency (`not_assessed`,
`current` or `stale`). Record a review with
`POST /api/v1/job-listings/{listing_id}/eligibility-assessments`; a definite
result requires an exact quotation from the listing's description or location
that concerns this role (or a company-wide hiring policy whose wording covers
it), and the server rejects a quotation that is not in the stored text. A
review also records what the wording establishes (Kenya named, any African or
EMEA country, worldwide, other countries only, restricted, conflicting, unclear
or awaiting employer confirmation), which must fit the outcome.
`GET .../eligibility-evidence` lists passages to review (Kenya named or
excluded, worldwide wording, regions, residency, work authorization,
sponsorship, time zones, employment model) and any conflicts; a listing that
excludes Kenya, or claims worldwide hiring while restricting locations, cannot
be recorded as accepting Kenya-based applicants.
Nothing is inferred from "remote", a location label or office locations.
Import a listing into a profile with
`POST /api/v1/candidate-profiles/{profile_id}/job-descriptions/from-listing/{listing_id}`;
the server copies the stored text verbatim and returns the existing job if it
was imported before. Track applications under
`/api/v1/candidate-profiles/{profile_id}/applications`, changing stages with
`POST .../applications/{application_id}/status`.

Use only boards verified from the organisation's official careers site, and add
them to the registry with their evidence. Discovery tests use fake sources,
mocked network calls and in-memory SQLite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_job_discovery.py tests\test_job_source_adapters.py tests\test_source_registry.py tests\test_link_verification.py
```

## Frontend

The React workspace restores the authenticated session before loading any
profile, document, extraction, evidence, job-description, draft, or export
data. From the repository root, run the backend locally in one terminal:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Then start Vite in another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

The Vite development and preview servers listen only on
`http://127.0.0.1:5173` (with `strictPort`) and proxy `/api` requests to
`http://127.0.0.1:8000`. Open the app at `http://127.0.0.1:5173`, not
`localhost`: the API accepts only that exact browser Origin
(`AUTH_ALLOWED_ORIGIN`), so another host name or port fails sign-in with HTTP
403. Set the non-secret `VITE_API_BASE_URL` variable at build/start time to override
the API base (include `/api/v1`), or set `VITE_CANDIDATE_PROFILE_ID` to
preselect a profile after sign-in. The selected profile is only a convenience;
the API authorizes every request. The frontend keeps session credentials in an
HttpOnly cookie and the CSRF token in memory, never browser storage. On logout
or an expired session it clears workspace state and the remembered profile ID.
After sign-in, the profile picker lists the profiles the server reports as owned
by the signed-in user. Restoring the session in another tab rotates the CSRF
token; the client then restores the session once and retries a rejected
mutation. No candidate record or successful API response is bundled into the
frontend.

The workspace supports profile updates and create, list, edit, and delete
operations for work experience, education, skills, and certifications.
Profile-history records are scoped to the selected profile; duplicate skills
and invalid date ranges are rejected. Deletion requires an explicit
confirmation. Documents can be uploaded as new immutable source files,
downloaded, and extracted; the API does not provide source-document deletion.
Evidence starts unreviewed, and only the candidate can explicitly confirm it.
Job descriptions can be pasted and saved, tailored CV drafts generated and
exported, and stored discovered jobs browsed (with an optional "posted in the
last 24 hours" view). While an action runs, other action buttons are disabled,
the pending action is named, and a second attempt shows a wait message.

Run frontend tests, a type check, and a production build with:

```powershell
npm test
npx tsc -b
npm run build
```

`npm run build` replaces the contents of `frontend/dist`. The frontend tests
mock `fetch`; they do not exercise a real browser session, the API, or
PostgreSQL. On 2026-10-17: backend 378 passed (`pytest -q`), frontend 59
passed (`npm test`), `npx tsc -b` clean.

The login flow requires the exact configured browser Origin, pre-login and
session-bound CSRF tokens, and same-origin API requests through the existing
Vite `/api` proxy. For local HTTP development, explicitly enable
`AUTH_LOCAL_HTTP=true` only while both services are bound to loopback; cookies
are Secure by default and Secure over HTTPS. Do not add permissive credentialed
CORS or expose health endpoints publicly. See
[docs/PROJECT_HANDOFF.md](./docs/PROJECT_HANDOFF.md) for the verified status,
remaining database/integration blockers, and the safe migration and owner
setup runbook.
