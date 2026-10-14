# JobPilot AI

JobPilot AI is a React/TypeScript frontend and FastAPI backend backed by
PostgreSQL. The backend database integration uses SQLAlchemy 2.x, Psycopg 3,
Pydantic Settings, and Alembic.

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
- `GET http://127.0.0.1:8000/readyz` executes `SELECT 1` and returns HTTP 503 if
  the database connection is unavailable.
- Candidate profiles are available under `/api/v1/candidate-profiles`: create
  with `POST`, retrieve by ID with `GET`, partially update with `PATCH`, and list
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
  never replaces a prior source file.
- Original CVs and supporting documents can be uploaded under
  `/api/v1/candidate-profiles/{profile_id}/documents`, listed with `GET` on that
  path, and retrieved by document ID. Download the original bytes from the
  document's `/download` endpoint. Uploads accept PDF, DOCX, or UTF-8 TXT files
  up to 10 MB. Original uploads are immutable; new files create new records.
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
  `/api/v1/candidate-profiles/{profile_id}/job-descriptions`. Create a tailored
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

Authentication and authorization are not implemented yet. Profile IDs scope
requests but do not authenticate the caller; do not expose these endpoints on a
public or shared multi-user deployment.

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

The extraction and evidence tests use synthetic documents and in-memory
SQLite; they do not require PostgreSQL. From `backend`, run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_document_extraction_and_evidence.py
.\.venv\Scripts\python.exe -m pytest
```

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
shrink text to force one page. The frontend does not yet render/export the CV
draft; use the API `generated_content` and `structured_content` response for
review. Export a successfully validated draft as PDF or DOCX through
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

These endpoints are local-only until authentication and authorization exist.
Profile-scoped IDs do not authenticate callers. Do not expose them publicly or
use them as a shared multi-user service.

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

## Frontend

The React workspace calls the existing profile, document, extraction, evidence,
job-description, draft, and export endpoints. From the repository root, run
the backend locally in one terminal:

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

The Vite development and preview servers proxy `/api` requests to
`http://127.0.0.1:8000`. Set the non-secret `VITE_API_BASE_URL` variable at
build/start time to override the API base (include `/api/v1`), or set
`VITE_CANDIDATE_PROFILE_ID` to preselect an existing profile ID. Without that
setting, the workspace asks for an existing profile ID or creates a profile
through the API; it remembers the selected ID in browser local storage. No
candidate record or successful API response is bundled into the frontend.

The workspace supports profile updates and create, list, edit, and delete
operations for work experience, education, skills, and certifications.
Profile-history records are scoped to the selected profile; duplicate skills
and invalid date ranges are rejected. Deletion requires an explicit
confirmation. Documents can be uploaded as new immutable source files,
downloaded, and extracted; the API does not provide source-document deletion.
Evidence starts unreviewed, and only the candidate can explicitly confirm it.

Run frontend tests and a production build with:

```powershell
npm test
npm run build
```

The API currently has no authentication or authorization. Keep both frontend
and backend on a trusted local machine; do not expose the API or serve this as
a shared public application. A production frontend on a different origin
requires an explicitly configured same-origin API proxy or appropriately
restricted backend CORS configuration, which is not added in this local-only
milestone.
