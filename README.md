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
  experiences, education, skills, or certifications with their respective
  `/{profile_id}/experiences`, `/education`, `/skills`, and `/certifications`
  endpoints.
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

## Frontend

From `frontend`, install and run the React application:

```powershell
npm install
npm run dev
npm test
npm run build
```
