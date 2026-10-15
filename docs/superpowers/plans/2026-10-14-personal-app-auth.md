# Personal-App Authentication Implementation Plan

**Status:** For review. This plan does not authorize implementation.

JobPilot AI currently has no authentication, authorization, password hashing,
sessions, or CSRF controls. Candidate resources are scoped by profile UUID,
which is not authorization. Keep the app local and loopback-only. No public
registration, invitations, multi-user administration, or public deployment.

## Safety rules

- Use test-first development: add a focused failing test, implement the
  smallest safe change, run focused and regression tests, inspect the diff, and
  commit each verified implementation slice. Do not push.
- Preserve existing profiles, documents, extraction/evidence records, jobs,
  drafts, exports, IDs, foreign-key relationships, and private files. Never
  reset the user's database, run destructive SQL, downgrade its schema, or
  delete candidate files.
- Back up the database and private `var/documents` outside the repository
  before any migration. Verify the backup and restore only to a new,
  separately named disposable database/storage directory. Never stage backups.
- Keep `CandidateProfile.user_id` nullable until each legacy profile is
  explicitly adopted by supplied UUID. Never infer ownership from email or
  account order. Record each owner change durably without candidate content or
  secrets; unassigned profiles and their resources remain inaccessible.
- Never log or print `.env`, credentials, passwords/hashes, session or CSRF
  tokens, extracted text, or candidate content. Do not weaken evidence-backed
  CV claim rules.
- Bind backend to `127.0.0.1:8000` and Vite to `127.0.0.1:5173`, using the
  single browser origin `http://127.0.0.1:5173` through the existing `/api`
  proxy. Only pre-auth CSRF, login, `/healthz`, and
  `/readyz` are unauthenticated. Health responses are minimal and readiness
  errors generic; do not expose these endpoints publicly.

## Stage 1 — Verify environment, migration state, and backup

**Inspect:** `compose.yaml`, `backend/app/settings.py`,
`backend/app/db.py`, `backend/alembic/env.py`,
`backend/alembic/versions/`, and the configured private document directory.
The handoff records migration head `7ce347caa873`; the live revision is
unverified. Backend tests use in-memory SQLite and do not verify PostgreSQL
migrations.

**Commands (from `backend`; `current` and `check` connect read-only):**

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

Capture read-only aggregate row counts only. From repository root, provide
restricted external paths and allow PostgreSQL tools to prompt for the
password; never put it in a command or output:

```powershell
$dbUser = Read-Host "PostgreSQL user"
$dbName = Read-Host "PostgreSQL database"
$backupRoot = Read-Host "Restricted backup folder outside the repository"
pg_dump --format=custom --file "$backupRoot\jobpilot-pre-auth.dump" --host 127.0.0.1 --port 5433 --username $dbUser $dbName
pg_restore --list "$backupRoot\jobpilot-pre-auth.dump"

# Choose a unique name and verify it does not already exist before creating it.
$restoreDb = "jobpilot_auth_restore_<unique>"
createdb --host 127.0.0.1 --port 5433 --username $dbUser $restoreDb
pg_restore --no-owner --no-privileges --exit-on-error --dbname $restoreDb "$backupRoot\jobpilot-pre-auth.dump"

# Confirm var\documents is the configured private store before copying.
robocopy "var\documents" "$backupRoot\documents" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 /XJ
```

Verify the dump by restoring it only into a newly created, uniquely named
disposable database and point-in-time isolated storage directory. Never
overwrite the configured database. Do not print connection URLs or candidate
metadata.

**Expected / accept when:** Live revision and drift are understood; database
and file backups are readable and isolated-restore verification succeeds;
existing data was not changed. Stop if any state differs unexpectedly or
backup/recovery is not usable.

## Stage 2 — Add user/session models and additive migration

**Files:** `backend/app/models/user.py` (new),
`backend/app/models/auth_session.py` (new),
`backend/app/models/pre_auth_challenge.py` (new),
`backend/app/models/profile_ownership_adoption.py` (new),
`backend/app/models/__init__.py`,
`backend/app/models/candidate_profile.py`,
`backend/alembic/versions/<new_revision>.py` (new),
`backend/tests/test_auth_models.py` (new),
`backend/tests/test_auth_migration.py` (new).

Model a UUID `User` with normalized unique login email, password hash,
active-state and timestamps; an `AuthSession` with hashed opaque token,
creation/expiry/revocation metadata; and a short-lived, one-use pre-auth
challenge record to prevent replay. Add nullable profile owner and a minimal
adoption audit record (profile UUID, old/new owner, operator/action, time; no
candidate content). Use a one-to-many user-to-profile relationship. Do not add
a backfill or make existing owners non-null. Use the verified live revision as
the migration parent; never edit applied revisions.

**Test/commands (from `backend`, using only the disposable PostgreSQL database
for Alembic commands):**

```powershell
# Choose a unique DB name and verify it does not already exist.
$dbUser = Read-Host "PostgreSQL user"
createdb --host 127.0.0.1 --port 5433 --username $dbUser jobpilot_auth_test
# Override only for this PowerShell process; other settings remain local.
$env:POSTGRES_DB = "jobpilot_auth_test"
.\.venv\Scripts\python.exe -m pytest tests\test_auth_models.py tests\test_auth_migration.py -q
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

Verify existing IDs, counts, relationships, storage references, and files
remain unchanged in the restored test copy.

**Expected / accept when:** Focused tests pass and the additive migration
passes on disposable PostgreSQL with existing profiles still unassigned and
all existing data/file references preserved.

## Stage 3 — Implement one-time owner setup and password hashing

**Files:** `backend/app/services/auth.py` (new),
`backend/app/cli.py` or an inspected existing CLI entry point,
`backend/pyproject.toml`, `backend/tests/test_auth_cli.py` (new),
`backend/tests/test_auth_passwords.py` (new).

Choose a maintained Argon2id library compatible with Python `>=3.11` after
checking the actual backend environment; do not guess versions. Add a
loopback-local CLI bootstrap that prompts for email and hidden password and
refuses a second account. Normalize email before enforcing uniqueness. Enforce
password length 15–128 characters without composition rules; never implement
public registration.

**Test/commands (from `backend`):**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_auth_cli.py tests\test_auth_passwords.py -q
.\.venv\Scripts\python.exe -m pip check
```

Test first setup, repeat-setup refusal, normalized duplicate email, password
verification, length boundaries, and that output/storage reveal no password
or hash.

**Expected / accept when:** One local owner can be created once; tests and
dependency checks pass; no public account-creation route or secret output.

## Stage 4 — Implement login, sessions, CSRF, and local password reset

**Files:** `backend/app/api/v1/auth.py` (new),
`backend/app/api/v1/dependencies.py` (new or existing dependency location),
`backend/app/schemas/auth.py` (new), `backend/app/services/auth.py`,
`backend/app/cli.py`, `backend/app/settings.py`, `backend/app/main.py`,
`backend/pyproject.toml` only if an approved lightweight limiter requires it,
`backend/tests/test_auth_api.py` (new), `backend/tests/test_csrf.py` (new),
`backend/tests/test_password_reset.py` (new),
`backend/tests/test_health.py`, `backend/tests/test_readiness.py`.

Implement pre-auth CSRF retrieval as a same-origin response with a short-lived
cookie-bound token. Validate cookie, submitted header, exact allowed `Origin`,
expiry, and one-use/replay protection before password verification. Issue a
separate session-bound CSRF token after login; validate it and Origin on every
state-changing request. Keep tokens in memory only. Sessions use a 12-hour
idle expiry and 7-day absolute lifetime. Cookies are `HttpOnly`,
`SameSite=Strict`, `Path=/`, and omit `Domain`; allow non-`Secure` cookies only
in explicitly configured local HTTP mode, and require `Secure` over HTTPS.
Allow only the exact local frontend origin `http://127.0.0.1:5173` during
local HTTP development; reject other Origins.
Use a maintained lightweight single-instance login limiter; add no Redis or
service solely for throttling. Login errors must not reveal whether an email
exists. Disable default `/docs`, `/redoc`, and `/openapi.json` routes.

Add local operator password reset with explicit account confirmation and
revocation of all that account's sessions. Keep `/healthz` and `/readyz`
unauthenticated, loopback-only, and non-sensitive; readiness failures must
not return exception details or database credentials.

**Test/commands (from `backend`):**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_auth_api.py tests\test_csrf.py tests\test_health.py tests\test_readiness.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_password_reset.py -q
```

Cover pre-auth token expiry/replay/binding and Origin, login success/failure,
cookie flags, CSRF binding, session restoration/logout/expiry, password-reset
invalidation, throttling, generic health responses, and disabled docs routes.

**Expected / accept when:** Focused tests pass; no token is persisted in browser
storage or printed; all chosen settings are explicit and tested.

## Stage 5 — Enforce authentication and ownership on all resources

**Files:** `backend/app/api/v1/candidate_profiles.py`,
`backend/app/api/v1/candidate_documents.py`,
`backend/app/api/v1/document_extractions.py`,
`backend/app/api/v1/candidate_evidence.py`,
`backend/app/api/v1/cv_generation.py`,
`backend/app/api/v1/cv_exports.py`,
`backend/app/models/candidate_profile.py`,
`backend/app/cli.py`,
`backend/tests/conftest.py`,
`backend/tests/test_authorization.py` (new), and
`backend/app/services/documents.py` only if private-storage boundaries require
it.

Derive profile ownership from the authenticated user, never request payload.
Scope all resource lookups to both owner and existing parent relationships;
return the same not-found behavior for unknown and non-owned IDs. Explicitly
adopt only approved profile UUIDs and persist an audit entry for each change.
Authorize before resolving or streaming private files. Cover every route:
profile and experience/education/skill/certification CRUD; document upload,
list/read/download; extraction status/run/text; evidence CRUD; job
description list/create/read; CV draft create/list/read; export create/list
and PDF/DOCX download. Retain the health/auth exceptions, relationship
integrity, and evidence trust rules.

**Test/command (from `backend`):**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_authorization.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_profile_adoption.py -q
```

The new tests must cover anonymous access, two-user isolation on every
resource family including downloads, valid foreign IDs, mismatched
parent/child IDs, unassigned legacy profiles, and explicit audited adoption.

**Expected / accept when:** No candidate-owned route or file download relies
on UUID secrecy; owner behavior and existing API contracts remain correct.

## Stage 6 — Add backend security and regression tests

**Files:** `backend/tests/conftest.py`, `backend/tests/test_auth_*.py`,
`backend/tests/test_authorization.py`, `backend/tests/test_auth_migration.py`,
`backend/tests/test_profile_adoption.py`, and existing
`backend/tests/test_candidate_profile_api.py`,
`backend/tests/test_candidate_profile_crud.py`,
`backend/tests/test_candidate_documents.py`,
`backend/tests/test_document_extraction_and_evidence.py`,
`backend/tests/test_cv_generation.py`, `backend/tests/test_cv_exports.py`,
`backend/tests/test_health.py`, and `backend/tests/test_readiness.py`.

Keep fast SQLite fixtures isolated; use the separate disposable PostgreSQL
database for migrations/persistence. Adapt fixtures to create authenticated
owner, second user, and unassigned legacy profile; do not bypass production
auth dependencies. Preserve regression coverage for profile CRUD, documents,
extraction, evidence review, job descriptions, CV generation, and exports.

**Commands (from `backend`; Alembic settings must point to disposable DB):**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# Run again with POSTGRES_DB set to the disposable migration-test database.
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

**Expected / accept when:** Full backend suite passes; cross-resource,
anonymous, CSRF/session, migration, data-preservation and existing-feature
regressions pass; test commands cannot modify the user's database.

## Stage 7 — Add frontend login and session handling

**Files:** `frontend/src/api/client.ts`, `frontend/src/api/types.ts`,
`frontend/src/App.tsx`, `frontend/src/Views.tsx`,
`frontend/src/styles.css`, `frontend/src/App.test.tsx`, and a focused API
client test file if needed.

Restore the session before loading or rendering candidate workspace data.
Implement pre-auth challenge, login, logout, session restoration, and
in-memory CSRF header handling in the central client. On logout/session
expiry, clear workspace state and `jobpilot.profileId` from local storage.
Keep only the selected profile ID as a convenience; never store passwords,
session or CSRF tokens. Use the existing Vite proxy and `http://127.0.0.1:5173` browser origin.

**Commands (from `frontend`):**

```powershell
npm test -- --run
npm run build
```

Test challenge-before-login, session restoration before workspace API calls,
no anonymous workspace loads, mutation CSRF headers, login errors, expiry,
logout clearing, and existing profile/document/evidence/CV/export UI behavior.

**Expected / accept when:** Frontend tests and production build pass; no
candidate data is requested/rendered before authentication and no token enters
local storage.

## Stage 8 — Verify, update documentation, and hand off

**Files:** `README.md`, `docs/PROJECT_HANDOFF.md`, and the design document only
if an implementation requires an approved design change.

Run the full backend suite, frontend tests/build, Alembic checks on the
disposable PostgreSQL database, `git diff --check`, and a real local
browser/API/PostgreSQL workflow only if safely exercised. Use synthetic data
and a temporary storage directory; never clean up or overwrite pre-existing
records/files. A browser-to-database result may be claimed only when the real
browser, frontend, API, and PostgreSQL were all exercised together.

**Commands:**

```powershell
# Repository root; use only the documented local service and isolated test DB.
docker compose up -d postgres

# Backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend
npm test -- --run
npm run build
npm run dev -- --host 127.0.0.1 --port 5173

# Repository root
git diff --check
```

Update README/handoff with only verified behavior, actual migration revision,
test/build and integration results, backup/setup/reset instructions, security
limitations, and remaining decisions. Keep local-only/no-public-registration
restrictions explicit.

**Expected / accept when:** All achievable checks pass or blockers are stated;
existing data and files remain intact; docs distinguish mocked tests from
real integration and current migration head from live DB state.

## Review gates

Pause before migration if backup/restore is not verified, live migration state
differs unexpectedly, or any proposed step would alter existing ownership or
files. Resolve cookie/Origin policy, one-use pre-auth challenge storage,
rate-limit threshold, and adoption procedure before implementing their
respective stages. Keep the plan and any future work uncommitted until
reviewed; never push.
