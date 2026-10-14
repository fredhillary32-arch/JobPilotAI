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

Run backend tests from `backend` with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Document file bytes are stored outside PostgreSQL in a private local directory,
`var/documents` by default. Set `DOCUMENT_STORAGE_PATH` in `.env` to use another
location. The file-store interface allows replacement with a protected object
storage implementation later. Restrict access to the storage directory and
include it in access-controlled backups. Upload checks format, declared MIME
type, and maximum size but does not perform malware scanning. Keep the API
private until authentication and authorization are implemented.

Document files are stored outside PostgreSQL under `var/documents` by default.
Set `DOCUMENT_STORAGE_PATH` to an absolute private directory in `.env` to choose
another location. The local storage implementation is behind a storage
interface so a protected object-storage implementation can replace it later.
Restrict filesystem access to the application process and include this storage
location in access-controlled backups. File upload is not malware scanning or
content sanitization; keep the API private until authentication and
authorization are in place.

## Database migrations

Candidate profile models are registered with Alembic metadata. After inspecting
and editing the generated migration, create and apply future schema changes
from `backend` with:

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe schema change"
.\.venv\Scripts\alembic.exe upgrade head
```

Review every generated migration before applying it. Alembic autogeneration
compares `Base.metadata` with the configured database; it does not replace
manual migration review.

## Frontend

From `frontend`, install and run the React application:

```powershell
npm install
npm run dev
npm test
npm run build
```
