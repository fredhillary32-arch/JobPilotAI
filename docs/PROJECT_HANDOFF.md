# JobPilot AI Project Handoff

**Status:** Authentication Stages 1-7 were committed and pushed in
`c2985cb5b65fa813e04670e92437ad055f9596f1`. A full audit on 2026-10-15
(see "2026-10-15 audit" below) found that the configured database has not been
migrated to the authentication schema, so the authenticated app cannot yet run
against it. This handoff does not certify the configured PostgreSQL database
or a real browser/API workflow.

## 2026-10-15 audit

Findings and corrections (uncommitted at the time of writing):

- **Blocker: configured database not migrated.** A read-only query showed the
  configured `jobpilot` database at revision `7ce347caa873` with no `users`,
  `auth_sessions`, or `candidate_profiles.user_id`. The code requires
  `d4f7a19c2b86`. The database held zero candidate profiles, documents,
  evidence, job descriptions, drafts, and exports, so no legacy profile needs
  adoption. The configured private document directory held zero files.
- **Fixed: readiness reported ready on an outdated schema.** `/readyz` now
  also compares the Alembic revision with the repository head and returns a
  generic 503 if they differ. Verified read-only against the configured
  database: it now returns 503 "Database schema is not current".
- **Fixed: profiles were unreachable after logout.** Logout clears the
  remembered profile ID, the UI never displays profile UUIDs, and there was no
  endpoint to list owned profiles. Added `GET /api/v1/candidate-profiles`
  (owner-scoped) and a profile picker after sign-in.
- **Fixed: the default Vite address broke sign-in.** `npm run dev` served
  `http://localhost:5173`, but the API accepts only the Origin
  `http://127.0.0.1:5173`. Vite now binds to `127.0.0.1:5173` with
  `strictPort` (verified listener address).
- **Fixed: a CSRF token rotated in another tab broke mutations.** Session
  restoration rotates the CSRF token; the client now restores the session and
  retries once on a CSRF-verification 403 (never for login or Origin failures).
- **Fixed:** a stale dashboard notice saying sign-in did not exist;
  `.env.example` now documents `AUTH_ALLOWED_ORIGIN` and `AUTH_LOCAL_HTTP`.
- **Added:** a route-derived test that every API route except pre-auth CSRF
  and login rejects anonymous requests.

### Job discovery slice (2026-10-16, uncommitted, not applied to `jobpilot`)

- Migration `3b8e5f0c9a12` (parent `d4f7a19c2b86`) adds `job_listings` and
  `job_discovery_runs` only; no foreign keys to candidate data. Downgrade drops
  both tables and all discovered listings and run history.
- Rehearsed on the new disposable database
  `jobpilot_jobdisc_rehearsal_20261016_91c48d`, restored from
  `jobpilot-pre-job-discovery-20261016-135946-686b42.dump` (SHA-256
  `C1D887EA…627E77`): upgrade, `alembic check`, downgrade, re-upgrade and
  `check` passed; 7 PostgreSQL tests passed. Private documents were copied to
  `documents-pre-job-discovery-20261016-135946` and verified by hash.
- Source facts and JobPilot conclusions are separate: listings store only what
  a source states; eligibility is reported as `unknown` and will live in a
  separate per-profile assessment table.
- The Windows `uvicorn --reload` dev server was found stuck on its original
  worker after a file change; restart it after code changes and verify.

Known limitations recorded by the audit (not fixed):

- The login limiter keys on client IP. Behind the Vite proxy every request
  comes from `127.0.0.1`, so five failed attempts lock out all sign-ins for 15
  minutes; the limiter is process-local.
- Job descriptions cannot be edited or deleted; evidence descriptions and
  excerpts can be changed through the API but not in the UI; documents cannot
  be deleted.
- ~~Generated CV exports appear in the document list and can be extracted and
  used as evidence sources.~~ Fixed 2026-10-16: extraction and evidence
  creation accept only candidate-uploaded source documents (HTTP 409
  otherwise), and the UI lists source documents only (`?origin=source`).
- CV generation includes every work experience and fails the draft if any
  role lacks five substantive supported bullets.
- The backup archive's restore has not been re-verified in this audit.
- Uploads are bounded at 10 MB when stored, but the multipart body is spooled
  before that check; there is no request-size limit at the server.

## Application and authentication behavior

JobPilot AI uses a React/TypeScript/Vite frontend and a FastAPI, Pydantic,
SQLAlchemy, and PostgreSQL backend. PostgreSQL migrations are managed by
Alembic. Original and generated document bytes are kept in private local file
storage, not in PostgreSQL.

The backend provides local owner bootstrap, Argon2id password hashing, login,
session restoration/logout, and operator-only password reset and profile
adoption commands. There is no public registration. Session credentials are
opaque, high-entropy HttpOnly cookies; token hashes are stored server-side.
Session policy is a 12-hour idle timeout and a 7-day absolute lifetime. The
browser keeps CSRF tokens in memory and sends them in request headers for
mutations. Login and mutations require the configured exact Origin; the
frontend uses same-origin requests via Vite's `/api` proxy. Cookies use
SameSite=Strict, Path=/, and HttpOnly; Secure is on except for the explicitly
enabled local HTTP mode.

All candidate-profile resource routers use a shared authenticated ownership
guard. This covers profiles and child records, documents and downloads,
extraction, evidence, jobs, CV drafts, exports, and generated downloads.
Non-owned and unassigned legacy profiles are not accessible; profile UUIDs
remain selectors, not authorization. Adoption is explicit, requires
confirmation, and writes an audit record. Health/readiness and the pre-login
CSRF/login endpoints are the documented unauthenticated exceptions. Health
responses are minimal; OpenAPI/docs endpoints are disabled.

The React app restores the session before requesting workspace data. An
unauthenticated/expired session clears in-memory workspace state and the
remembered profile ID. Logout calls the API and clears that selection. The Vite
development proxy targets `127.0.0.1:8000`; run both API and frontend bound to
loopback. This is not a public or shared multi-user deployment.

## Verification status

### Verified by automated tests/checks

- Backend: `backend\.venv\Scripts\python.exe -m pytest -q` — **141 passed**
  after the 2026-10-15 audit (133 before it). Tests use isolated in-memory
  SQLite databases and temporary private storage. The SQLite migration test
  verifies that the new auth schema is additive and leaves a synthetic legacy
  profile unassigned.
- Frontend: `npm test` from `frontend` — **22 passed** after the audit (19
  before it).
- An earlier frontend run concurrent with the production build hit the
  default five-second timeout in two UI tests; the complete suite passed when
  run separately.
- Frontend: `npm run build` from `frontend` — **passed**, including
  `tsc -b`.
- Backend dependencies: `python -m pip check` in `backend\.venv` — **passed**.
- `git diff --check` — **passed**.
- Pylance workspace diagnostics: no errors; two low-severity unused-parameter
  warnings are reported in `backend/tests/test_authorization.py`.
- Source review found the authentication migration parent is
  `7ce347caa873`; the new revision is `d4f7a19c2b86`. It creates identity,
  session, pre-auth challenge, and adoption-audit tables, then adds nullable
  `candidate_profiles.user_id`. It contains no profile-owner backfill.
- The focused security review reported no vulnerabilities in the reviewed
  changes. It could not establish runtime listener/configuration state,
  live-database revision, or private-storage permissions.

### Reviewed from source, not exercised end to end

- Auth API paths and response fields match the frontend: pre-auth challenge,
  login, session restoration, and logout use `/api/v1/auth/...`; responses
  return the user identity and CSRF token as documented.
- The frontend sends same-origin credentials/mode, uses the pre-auth token for
  login, retains the returned session CSRF token only in memory, and attaches
  it to mutations. Browser-controlled `Origin` is not manually overridden.
- Authentication/ownership dependencies and child-parent checks are applied
  to candidate resource routers. Private file access is authorized before
  resolution; traversal/inaccessible-legacy cases have regression tests.
- Logout, session expiry/revocation, CSRF, exact-Origin rejection, inactive
  users, login limiting, cross-user isolation, profile adoption, and migration
  behavior have automated backend coverage.
- Vite's proxy remains `/api` to `http://127.0.0.1:8000`. No permissive
  credentialed CORS configuration was added.

### Not yet verified end to end

- Frontend tests mock `fetch`; they do **not** prove real browser cookie,
  browser-generated Origin, API, or PostgreSQL integration.
- No live login/logout or private document workflow was run against the API.
- No production deployment, HTTPS reverse proxy, or multi-worker setup was
  tested. Keep the application loopback-only.
- Login throttling is process-local and is not a distributed/multi-worker
  limiter; do not scale the service across workers without revisiting it.
- The backend test suite uses SQLite. PostgreSQL locking, migration execution,
  and persistence behavior remain unverified for this authentication rollout.

## Database, migration, and backup status

Repository migration history is linear and ends at the auth revision
`d4f7a19c2b86`, whose parent is `7ce347caa873`; it is additive. A read-only
query on 2026-10-15 showed the configured database at `7ce347caa873`
(PostgreSQL 17.11), so the auth migration has **not** been applied. No
migration, bootstrap, password reset, or profile adoption command was run. No
database or private document directory was modified. Four earlier disposable
databases named `jobpilot_auth_*_20261015*` exist on the same server; one may
hold a partial restore. Do not reuse, overwrite, or delete them, and choose a
new unique name for any future restore.

Earlier project context reported Stage 1 backup/restore verification complete.
That backup was not re-opened or re-restored during this handoff. Before any
future migration, the operator must confirm the current target, produce fresh
database and private-file backups outside the repository, and verify a restore
into a new, uniquely named disposable database and separate storage copy.
Never overwrite an existing restore database or target the configured
application database during restore verification.

## Safe ordered runbook for later migration and owner setup

This runbook is documentation only; none of these commands was executed for
this handoff. Perform the steps only after confirming the exact target database
and obtaining approval to migrate it. Do not print `.env`, credentials,
connection URLs, candidate content, or private document contents.

1. **Confirm target and current revision.** From `backend`, run `alembic
   current` only after verifying through the local operator configuration
   (without displaying secrets) which database the process will contact.
   Stop if the target or revision is unexpected. The expected repository
   parent is `7ce347caa873`, but this does not establish the live revision.

2. **Back up both stores outside the repository.** Use an access-restricted
   backup directory and operator-supplied host, port, user, and database
   values. Let PostgreSQL prompt for its password; do not place passwords in
   commands or environment history. Create a custom-format dump with
   `pg_dump`, confirm its exit code and `pg_restore --list` output, and record
   a file hash in the restricted backup location. Copy the actual configured
   private document directory to a separate backup path. Verify the copied
   file count and hashes without displaying file contents or sensitive names.

3. **Verify restore only into a fresh disposable target.** Choose a unique
   disposable database name, query the local PostgreSQL instance to confirm
   that exact name is absent, then create it. Restore with `pg_restore
   --no-owner --no-privileges --exit-on-error` into that new database and an
   isolated storage copy. Capture the exit code. Verify its Alembic revision,
   required objects, and aggregate table counts against the source. On any
   error or discrepancy, stop; do not reuse or overwrite a partial restore.

4. **Test the auth migration on a separate disposable PostgreSQL database.**
   Ensure the environment for the Alembic process explicitly targets the
   disposable database, verify `alembic current` there, then run
   `alembic upgrade head` and `alembic check`. Verify the resulting revision
   is `d4f7a19c2b86`, existing profiles and relationships are preserved, and
   every legacy `user_id` remains null. The current automated migration test
   is SQLite-only and does not replace this step.

5. **Apply to the intended application database only after approval.** Take a
   fresh verified database-and-storage backup, explicitly confirm the
   migration target and current revision again, then run `alembic upgrade
   head`. Verify the live revision and aggregate preservation checks. The
   migration does not assign owners; do not add an automatic backfill.

6. **Create the initial owner after the migration is verified.** Confirm the
   CLI's configured database target before invoking it. From `backend`, run
   `.\.venv\Scripts\python.exe -m app.cli bootstrap-owner`. Enter the password
   only at the hidden prompt. The command is one-time and refuses an existing
   owner; there is no public registration.

7. **Adopt only explicitly approved legacy profiles.** Leave profiles
   unassigned unless the operator has confirmed the exact profile IDs and
   owner. For selected IDs, run
   `.\.venv\Scripts\python.exe -m app.cli adopt-profiles --profile-id
   <profile-uuid>` (repeat the option for each approved profile). Confirm the
   owner email and adoption phrase in the prompts, then verify audit records
   and ownership changes without printing candidate data.

8. **Start and smoke-test locally.** Run Uvicorn with
   `--host 127.0.0.1 --port 8000`; run Vite with
   `npm run dev -- --host 127.0.0.1 --strictPort`. For HTTP development,
   explicitly configure `AUTH_LOCAL_HTTP=true` and retain the approved exact
   origin `http://127.0.0.1:5173`. Exercise login, session restoration,
   ownership denial for a synthetic unowned profile, logout, and a private
   download using synthetic data and isolated storage. Do not describe this
   workflow as verified until it is actually performed.

## Current repository state

Branch `main` is at `c2985cb5b65fa813e04670e92437ad055f9596f1`, which
contains the authentication implementation and was pushed to the private
GitHub repository. The 2026-10-15 audit corrections are uncommitted and
unstaged. Preserve existing modifications and untracked files; do not stage or
commit without explicit instruction.
