# JobPilot AI Project Handoff

**Status:** Authentication Stages 1-7 are implemented in the current
uncommitted worktree. This Stage 8 handoff records source review and automated
test results from 2026-10-15. It does not certify the configured PostgreSQL
database or a real browser/API workflow.

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

- Backend: `backend\.venv\Scripts\python.exe -m pytest -q` — **133 passed**.
  Tests use isolated in-memory SQLite databases and temporary private storage.
  The SQLite migration test verifies that the new auth schema is additive and
  leaves a synthetic legacy profile unassigned.
- Frontend: `npm test` from `frontend` — **19 passed**.
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

Repository migration history ends at `7ce347caa873` before the uncommitted
auth revision `d4f7a19c2b86`. The `d4f7a19c2b86` migration declares
`7ce347caa873` as its parent and is additive. The live configured database
revision was **not queried in this Stage 8 pass**; it must not be inferred from
the repository revision. No migration, bootstrap, password reset, or profile
adoption command was run. No database or private document directory was
modified.

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

At handoff, branch `main` is at `bd4080c27cd71ee18e2302573ae3a23ef1556246`.
The authentication implementation and plan, plus the Stage 8 documentation,
remain uncommitted and unstaged. Preserve existing modifications and untracked
files; do not stage or commit without explicit instruction.
