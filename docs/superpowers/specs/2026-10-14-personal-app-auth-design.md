# JobPilot AI Personal-App Authentication Design

**Status:** Approved design for review; authentication is not implemented.
**Decision:** Keep JobPilot AI local and personal, with one initial owner
account. Do not expose it publicly.

## 1. Scope

Implement secure login and logout and require authentication and server-side
authorization for every application API endpoint and private resource. The
initial account is created locally; there is no public registration. The data
model should allow multiple users and profiles later, but this milestone does
not include invitations, public registration, multi-user administration, or
public deployment.

Do not change existing candidate records, uploaded files, evidence trust rules,
or CV-generation behavior as a side effect of authentication. Candidate-entered
profile data and explicitly candidate-confirmed evidence remain subject to the
existing CV-generation rules in `docs/CV_GENERATION_SPEC.md`.

## 2. Authentication and sessions

Use an opaque, high-entropy session cookie backed by a PostgreSQL session
record. Generate the token with a cryptographically secure random source; store
only its hash in the database. Resolve each request to an active user and
unexpired, non-revoked session. This fits the existing FastAPI, SQLAlchemy, and
PostgreSQL stack, supports immediate logout/revocation, and avoids putting
bearer credentials in browser storage.

Use an established Argon2id password-hashing library. The backend currently has
no password hashing or authentication dependency; select and validate the
library against the project's Python `>=3.11` environment during
implementation. Never store plaintext passwords or third-party credentials.

For browser requests, set an `HttpOnly` cookie with `SameSite=Strict`, `Path=/`,
and no `Domain`. Require HTTPS and `Secure` cookies if HTTPS is used. Local
development must bind services to loopback; any HTTP-only local cookie
exception must be limited to that explicitly local mode. The current Vite
configuration proxies `/api` to `127.0.0.1:8000`, allowing the normal browser
flow to remain same-origin.

Cookies are sent automatically, so protect login and all state-changing
requests with same-origin/`Origin` validation and a CSRF token sent in a
request header. Before login, the browser obtains a short-lived
pre-authentication CSRF token from a minimal endpoint. Bind it to a short-lived
`HttpOnly`, `SameSite=Strict` pre-authentication cookie, for example by signing
the token together with the cookie nonce using a server secret. The login
request sends the token in a header and the cookie automatically; the server
validates the token, its expiry and cookie binding, and the exact allowed
`Origin` before checking credentials. Reject missing, invalid, expired, or
replayed pre-authentication challenges; clear the challenge cookie after
success or expiry. Keep the token in frontend memory only.

After login, issue a separate CSRF token bound to the authenticated session;
the server returns it only during login/session restoration and validates it
alongside the session cookie for every state-changing request. Revoke or expire
it with its session. Keep it in frontend memory, not local storage. Do not
treat `SameSite` alone as the CSRF defense. The current API has no CORS
middleware; do not add permissive credentialed CORS. If a separate origin is
introduced later, allow only explicitly configured origins with credentials
and retain CSRF checks.

## 3. Initial account and recovery

Provide a local, one-time bootstrap command that prompts for the owner email
and password without echoing the password. Normalize the login email before
enforcing a database uniqueness constraint. The command must refuse to create
another initial account once one exists; there must be no public registration
endpoint or setup secret exposed through the API.

For recovery, provide a local operator-only password-reset command. It must
verify the target account explicitly, replace only its password hash, and
revoke that account's existing sessions. Do not rely on email reset links or a
third-party email service in this local-only milestone. Document a secure
backup and recovery procedure for the database and private document directory;
do not put recovery secrets in source control.

## 4. Data model and existing-data migration

Add a `User` model with a UUID key, normalized unique login email, password
hash, active state, and timestamps. Keep `CandidateProfile.contact_email` as
candidate contact information, separate from the login identity. Add a
user-to-profile relationship that can support multiple profiles per user in
the future. Add an `AuthSession` model with user foreign key, unique session
token hash, creation/expiry/revocation metadata, and only the minimum
additional fields needed for session and CSRF validation.

Use an additive migration: create the identity/session tables and add a
nullable owner foreign key to existing profiles. Do not rewrite profile IDs,
delete records, or alter private files. Existing profiles remain unassigned
until the owner explicitly maps selected profile UUIDs to the initial account
through a local, auditable procedure. Do not infer ownership from contact
email, profile UUID possession, or the fact that an account is the first one.
Until assigned, a legacy profile and its related resources must be inaccessible
through authenticated application requests. New profiles are assigned to the
authenticated user at creation.

Back up the existing database and private `var/documents` storage before
applying the migration. Verify the actual applied Alembic revision and data
state before writing the migration. Enforce non-null profile ownership only
after every existing profile has been explicitly mapped and that condition has
been verified. The handoff records `7ce347caa873` as the repository's migration
head; the live database revision was not checked for this design.

## 5. Authorization coverage

Every application endpoint must require a valid session, except the minimal
pre-authentication CSRF, login, and health-check endpoints. Logout requires a
valid session; session restoration reveals only the current account's minimal
identity. Keep `/healthz` and `/readyz` unauthenticated for minimal local
health checks: `/healthz` reports only process liveness, while `/readyz`
reports generic readiness and may return a generic unavailable response.
Neither endpoint may reveal credentials, connection strings, internal
exception details, or other sensitive configuration. Bind both services and
these endpoints to loopback; do not expose either endpoint publicly.

For every resource request, scope the query to the authenticated user's
profile ownership on the server. Continue validating parent/child
relationships; client-supplied UUIDs are selectors, never proof of ownership.
Return a consistent not-found response for unknown and non-owned resources to
avoid disclosing whether another user's record exists.

Coverage must include:

- Profiles and all work-experience, education, skill, and certification
  collection and item operations.
- Source documents: list, upload, metadata retrieval, and private download.
- Extraction start/status and extracted-text retrieval.
- Evidence list/create/read/update/delete, including source-document
  association checks.
- Job-description list/create/read.
- CV-draft creation/list/read, including failed drafts and validation details.
- CV-export create/list and private PDF/DOCX download, with ownership checked
  across profile, job, draft, export, and generated document.
- Files in private local storage: no static/public serving; authorize before
  resolving or streaming a source or generated file.

The reviewed route implementations currently validate profile/record
associations but do not authenticate a caller or check user ownership. UUIDs
do not replace these authorization checks.

## 6. Frontend behavior

Add login UI and restore the session from the API when the app loads. Until
restoration succeeds, do not load or display candidate workspace data. On
unauthenticated responses, clear in-memory candidate data and show login;
logout calls the API to revoke the session, then clears workspace state and
the locally remembered profile selection. Do not store passwords, session
tokens, or CSRF secrets in local storage. Send the CSRF header for mutations.
Treat the selected profile ID in local storage as a convenience only; every
request remains server-authorized.

## 7. Essential controls and tests

- Keep the API and Vite server loopback-only. Do not publish port bindings or
  deployment configuration. Protect every application API route by default,
  with only the minimal pre-authentication CSRF, login, `/healthz`, and
  `/readyz` endpoints unauthenticated. Test anonymous access explicitly.
- Keep health responses minimal and non-sensitive; ensure readiness failures
  do not expose database credentials, connection strings, or internal
  exception details. Do not expose health endpoints publicly.
- Validate and normalize login email; use Argon2id, generic login errors,
  bounded request sizes, and rate limiting for login attempts. Choose the
  limiter implementation without adding an external service unless a measured
  need justifies it.
- Use CSRF token and `Origin` checks for login and state-changing operations;
  test invalid/missing tokens and origins.
- Expire and revoke sessions server-side; test logout, expired/revoked
  sessions, password reset invalidation, and cookie flags in HTTPS mode.
- Add cross-user isolation tests for every resource family and direct download,
  including requests with valid IDs belonging to another profile. Test
  mismatched parent/child IDs, unassigned legacy profiles, and anonymous
  requests.
- Test one-time bootstrap refusal, email normalization/uniqueness, password
  hashing (no plaintext persistence), explicit profile adoption, and
  preservation of existing record/file references across migration.
- Retain regression coverage for profile CRUD, document upload/extraction,
  evidence review, job descriptions, evidence-backed CV generation, and
  exports. Use synthetic data and isolated databases; never reset the user's
  existing database as a test shortcut.
- Frontend tests cover login, restored/expired sessions, protected workspace,
  logout, errors, and cookie/CSRF request behavior. Distinguish mocked tests
  from real local API/PostgreSQL/browser verification.

## 8. Stages and acceptance criteria

1. **Identity and additive schema:** User/session models and migration are
   reviewed; existing rows/files are unchanged and legacy ownership remains
   explicitly unassigned.
2. **Bootstrap and session API:** One local owner can be created once, log in,
   restore a session, log out, and reset a password locally; session expiry and
   revocation work.
3. **Server authorization:** Every candidate-owned endpoint and file download
   requires authentication and ownership; only the documented
   pre-authentication and minimal health endpoints are unauthenticated.
   Cross-user, anonymous-access, and health-response tests pass without
   weakening existing association or evidence checks.
4. **Frontend session flow:** Login gates workspace loading; refresh restores
   only a valid session; logout clears candidate state and remembered profile
   selection; no bearer credentials are browser-stored.
5. **Local verification and handoff:** Backend/frontend suites and production
   build pass; migration checks run against a safe local test database;
   cross-user tests pass; a real local workflow is reported only if actually
   exercised. The app remains loopback-only and is not publicly deployed.

## 9. Risks and unresolved decisions

- Confirm session idle and absolute lifetime values and whether the UI needs
  an explicit “log out all sessions” action.
- Decide whether all existing profiles are to be mapped to the initial owner
  or some should remain unassigned. No automatic mapping is allowed.
- Confirm how the one-time local adoption procedure records operator approval
  without exposing candidate details in logs.
- Verify a maintained Argon2id library and any rate-limiting approach against
  the current Python environment before adding dependencies.
- The frontend currently uses a selected profile ID in local storage; this
  must not be mistaken for authorization and should be cleared on logout.
- No authentication, authorization, session, CSRF, or rate-limiting control is
  implemented today. Until the milestone is implemented and verified, retain
  the existing local-only restriction and do not expose the API or private
  document storage to another machine.
