# JobPilot AI Project Handoff

## Purpose and technology

JobPilot AI is a local candidate job-search and application workspace. The
frontend is React, TypeScript, and Vite. The API is FastAPI with Pydantic and
SQLAlchemy 2.x, PostgreSQL, and Alembic. Backend tests use pytest; frontend
tests use Vitest and React Testing Library.

## Implemented functionality

- Candidate profile creation, retrieval, and partial updates.
- Profile-owned work experience, education, skills, and certification
  collection and individual-record CRUD. Updates validate merged date ranges,
  duplicate skills return HTTP 409, and profile/record mismatches return 404.
- Local PDF, DOCX, and TXT document upload, private storage, download, and
  local text extraction.
- Evidence creation from extracted source text and explicit unreviewed,
  candidate-confirmed, or rejected review states.
- Saved job descriptions, deterministic evidence-backed CV drafts, validation
  and unsupported-skill gaps, and validated PDF/DOCX exports.
- React dashboard and editors connected to the local API, with loading,
  success, error, empty, and delete-confirmation states.

Candidate profile records are profile-scoped, but there is no authentication
or authorization. A profile ID is not proof of ownership. Keep the app on a
trusted local machine and do not expose it publicly or share it between users.
Document extraction is local and does not perform OCR or malware scanning.
Generated CV claims use candidate profile information and explicitly
candidate-confirmed evidence; unreviewed or rejected extracted evidence is
excluded.

## API and database

Main routes:

- `/healthz` and `/readyz`
- `/api/v1/candidate-profiles` and `/{profile_id}`
- `/{profile_id}/experiences`, `/education`, `/skills`, and `/certifications`;
  each supports collection GET/POST and item GET/PATCH/DELETE.
- `/{profile_id}/documents` and document extraction/download routes.
- `/{profile_id}/evidence`
- `/{profile_id}/job-descriptions` and `/{job_id}/cv-drafts`
- `/{profile_id}/job-descriptions/{job_id}/cv-drafts/{draft_id}/exports`

PostgreSQL stores candidate profiles and their experience, education, skill,
certification, document, evidence, job-description, CV-draft, and export
records. Original and generated document bytes are in private local storage
under `var/documents` by default. The current migration is
`7ce347caa873 (head)`. Candidate history CRUD did not require a schema
migration; Alembic reported no schema drift.

## Local development commands

From the repository root, configure `.env` using `.env.example` without
committing credentials. The documented database start command is
`docker compose up -d postgres`. This session's Docker CLI was unavailable;
the already-running local PostgreSQL service accepted connections on the
configured port.

Start the backend from `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start the frontend from `frontend`:

```powershell
npm install
npm run dev -- --host 127.0.0.1
```

Run backend tests from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest
```

Run frontend tests and the production build from `frontend`:

```powershell
npm test -- --run
npm run build
```

Check migration revision and drift from `backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

## Verification recorded for this handoff

- Backend suite: 63 tests passed.
- Frontend suite: 12 tests passed when run without concurrent build/test
  processes. Running the suites concurrently exceeded Vitest's 5-second
  per-test timeout on this machine.
- Frontend TypeScript production build: passed.
- PostgreSQL readiness: `/readyz` returned HTTP 200; Alembic reported
  `7ce347caa873 (head)` and no new upgrade operations.
- Live API/PostgreSQL smoke check: synthetic records exercised all four CRUD
  collections, ownership scoping, missing IDs, invalid merged dates, duplicate
  skills, and persistence from a separate database session. The synthetic
  profiles were removed using an exact-ID/name guard.
- Browser-to-API/PostgreSQL check: created a synthetic profile through the
  frontend, created and edited a skill, confirmed the deletion prompt, deleted
  the skill, and verified its API GET returned 404. The synthetic profile and
  dependent records were removed.
- `git diff --check` and cached diff checks passed before final consolidation.
- No full browser-based document/evidence/CV-generation/export workflow was
  performed in this verification.

## Git state

The working branch is `main`. At handoff preparation, the base commit was
`c9f25e8` (`Build JobPilot candidate workspace frontend`). The candidate
profile CRUD checkpoint commit has not yet been created.

## Next milestone and sequence

Implement secure authentication and authorization before any public
deployment:

1. Define the user/account and user-to-profile relationship, including
   migration and account lifecycle rules.
2. Implement registration and login with a maintained password-hashing
   algorithm and safe password policy; never store third-party credentials.
3. Add secure session management and CSRF protections appropriate to the
   chosen browser session mechanism.
4. Authorize every profile-owned endpoint and every associated document,
   evidence, job, draft, and export by the authenticated user.
5. Add cross-user isolation tests for all resource types, unauthenticated
   access, session handling, and profile ownership; verify existing local
   workflows and migrations.

After authentication, continue with approved job discovery, evidence-based
verification that vacancies accept applicants in Kenya, job tracking,
tailored applications, permitted application workflows, and interview
preparation. Do not add scraping or bypass access controls.
