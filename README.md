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

Run backend tests from `backend` with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

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
