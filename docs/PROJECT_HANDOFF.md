# JobPilot AI Project Handoff

**Status (updated 2026-10-17):** Authentication Stages 1-7 are in
`c2985cb5b65fa813e04670e92437ad055f9596f1` on `main`, which matches
`origin/main` as last recorded locally. The 2026-10-15 audit fixes,
document-provenance protection, the job-discovery first slice, action-feedback
UX changes and the eligibility design documents are committed **locally only**
on `feature/jobpilot-discovery-eligibility` (`1ac77ea`, `1342fb2`). That
branch has not been pushed, and no push or deployment is authorized.

The configured `jobpilot` database is at the repository head, `d8b4f6a2c9e1`.
With the user's explicit approval it was migrated twice on 2026-10-17, each time
after a verified backup and restore rehearsal: `d4f7a19c2b86` → `a17c3e5b9d24`,
then `a17c3e5b9d24` → `c3e9a2d7f1b5` → `d8b4f6a2c9e1` (see "2026-10-17
approved migration to head, browser verification and ATS CV writer"). Existing
rows and private documents were unchanged both times and `/readyz` returns HTTP
200. A 28-step walkthrough in Google Chrome passed against a restored, migrated
copy; the real account was not signed in to. All work since `1342fb2` is
uncommitted on the feature branch.

## 2026-10-18 CV workflow repair and skill confirmations (uncommitted; migration pending approval)

Root cause of the "stuck" Tailored CVs screen: a failed generation joined every
validation error and requirement gap into one notification in a fixed,
bottom-right box with no height limit; at 1366x768 it was 832 px tall, started
80 px above the screen and its close button could not be reached (reproduced in
Chrome with the real 422 body). The failure itself came from a hard rule that
every role must have exactly five bullets; the real Tourism Fund role supports
one. Fixed: notifications are capped and scroll, messages are short with details
on the page, every request times out after 90 s, the success message appears
only after the saved result is on screen, and completeness gaps give a
`needs_review` draft instead of a failure.

Added: `candidate_skill_confirmations` (migration `e7c4a9d2b6f3`), the
skill-confirmation API, per-requirement answers in the ATS report, work-style
and context separation, stable requirement keys, filler-word keyword filter,
confirmed skills and role examples in the reviewed writer, explicit approval of
incomplete drafts, and linking incomplete drafts to applications.

Migration status: tested on a disposable restored copy
(`jobpilot_cvflow_rehearsal_20261018`): upgrade, downgrade and re-upgrade;
existing rows and drafts/evidence digests unchanged. **Not applied to
`jobpilot`** (still `d8b4f6a2c9e1`); backup taken first:
`C:\Users\Fred\JobPilot-Private-Backup\jobpilot_pre_cvflow_20261017T214747Z.dump`.
The running backend needs this migration before the new code can serve the real
database.

## 2026-10-17 multi-source discovery (uncommitted)

No migration was needed (still `d8b4f6a2c9e1`). Backup taken first:
`C:\Users\Fred\JobPilot-Private-Backup\jobpilot_pre_multisource_20261017T185128Z.dump`
(custom format, 24 table-data entries, checksum matched the in-container copy).

- Aggregator adapters `app/services/job_sources/aggregators.py`: Jobicy,
  Arbeitnow and Remote OK (free, keyless, terms read 2026-10-17 and recorded in
  the registry with outcome `public_api_documented`, category `aggregator`).
  Feeds are windows, so absent jobs are never marked missing. Remotive is not
  used; We Work Remotely, Working Nomads and Himalayas were left out (terms
  unreadable, competitive-use ban, no terms found).
- `app/services/discovery_runner.py`: one pass at a time (process lock plus
  PostgreSQL advisory lock), per-source isolation, per-source minimum interval
  (Jobicy one hour), incremental windows (`--full` to override), interrupted
  runs reported, in-memory progress for the UI.
- `POST/GET /api/v1/job-discovery/refresh` (background thread; CSRF-checked);
  the listings router stays GET-only and never contacts a source.
- CLI: `validate-sources`, `discovery-status`, `discover-registry --force/--full`,
  exit code 3 when another pass holds the lock.
- Role taxonomy: four groups (technical and IT; customer support and service;
  e-commerce and marketplace; related support operations); listing and
  pipeline filters take several groups, exclusions, comma-separated keywords,
  `source`, `workplace` and `sort`; `posted_at_source` labels job-board dates.
- UI: refresh button with progress, date windows (24 h, 3/7/14/30 days, all),
  role-group checkboxes, hide-group, source, work arrangement, sort, paging,
  "Undated" and "Published on job board" labels.

Real run against `jobpilot` (CLI, 2026-10-17 UTC):

| Source | Run | Fetched | New | Updated | Unchanged | Skipped |
|---|---|---|---|---|---|---|
| arbeitnow (first) | 18:51 | 1414 | 1000 | 0 | 0 | 414 (URL host) |
| arbeitnow (after host fix, incremental) | 18:55 | 300 | 100 | 0 | 200 | 0 |
| arbeitnow (repeat: dedup proof) | 18:56 | 300 | 0 | 0 | 300 | 0 |
| arbeitnow `--full` | 18:57 | 1414 | 314 | 0 | 1100 | 0 |
| all 11 sources | 18:58-19:01 | 2009 | 1669 | 0 | 340 | 0 |

The all-source pass: GitLab 232, Canonical 309, Sourcegraph 9, Andela 16,
Kraken 89, 1Password 74, Oyster 22, Jobicy 819, Remote OK 99 new; M-KOPA 40 and
Arbeitnow 300 unchanged; 11 of 11 succeeded. An immediate Jobicy re-run was
skipped for pacing. Read-only checks afterwards: 3,122 active listings after
duplicate collapsing; 2,332 posted within 7 days; 75 match a support role
group; of those, 4 are Kenya-qualified (Canonical, "Home based - Worldwide"),
the rest are mostly excluded by location labels; no aggregator listing is
Kenya-qualified. The 414 first-run skips were Arbeitnow country sites (.fr,
.ch) not yet in the trusted host list; fixed and recovered with `--full`.

## 2026-10-17 approved migration to head, browser verification and ATS CV writer (uncommitted)

**Migration of `jobpilot` (approved).** Target confirmed read-only as
`jobpilot` on `127.0.0.1:5433` at `a17c3e5b9d24`. The database had changed since
the 02:02 backup (one tracked application with its history event, one more
session), so a fresh backup was taken:
`jobpilot-pre-sources-20261017-043943-2465b4.dump` (75,710 bytes, 127 entries,
SHA-256 `db97adb5…66d28e9`) plus `documents-pre-sources-20261017-043943` (3
files, hashes verified) and a state file of per-table row fingerprints (md5 of
every row's original columns). The dump was restored into
`jobpilot_presrc_restore_20261017_043943_2465b4`; all 21 tables matched row for
row, and both migrations were rehearsed there with `alembic check` clean and no
existing row changed. The migration script then re-checked target, revision,
fingerprints and backup hashes, ran `alembic upgrade head` on `jobpilot`
(`a17c3e5b9d24` → `c3e9a2d7f1b5` → `d8b4f6a2c9e1`), and verified: revision
`d8b4f6a2c9e1`; all pre-existing tables row-identical; three new tables present
and empty; expected foreign keys; no unvalidated constraints; `alembic check`
clean; three private documents byte-identical. A later read-only check found
the data still identical, and `/readyz` returned 200. The configured profile is
a synthetic smoke-test profile, not real candidate history.

**Browser verification (real Chrome 155, headless, via Playwright 1.64 in a
scratch environment; not part of the project).** Target: the same dump restored
again into `jobpilot_browser_20261017_054600` (all tables matched the backup
fingerprints) and migrated to head, with a scratch copy of the documents. The
copy's owner was given a random one-off password; a second synthetic user was
added; 273 public listings (GitLab, M-KOPA) were fetched into the copy and 6
links checked (all reachable). The real `jobpilot` account was **not** signed in
to and its password was not changed. Final run 28 of 28 passed: sign-in (wrong
password refused generically), session survives reload, profile, documents
(download), 5 evidence records, discovered-jobs filters and search, link-status
display, source health, eligibility review form, listing import, job-fit and
ATS panels, score method, uploaded-CV layout check, reviewed draft generation,
export blocked before approval, plain-text preview and trace, approval, PDF and
DOCX export and download (both read back 13 of 13 lines), candidate edit saved
as a new version flagged for confirmation, application tracking through a
valid stage, invalid transition refused (409), eligibility details saved only
after the confirmation box, missing/forged CSRF refused (403), sign-out (reload
stays signed out, API 401), a second user gets 404 for the first user's profile,
documents, drafts and applications, and a clear error for an incomplete
profile. Against the real `jobpilot` database only `/readyz` (200) and the
sign-in page in Chrome were checked. Earlier runs failed on script locators
and on an `example.test` address the login validator rejects; those were
script errors, fixed before the final run. No job application was submitted
and nothing was sent to an external service apart from the public job-board
API and listing-page requests.

**ATS analysis and reviewed CV writer.** New services `job_requirements`,
`cv_document_analysis`, `ats_match`, `cv_writer`, `cv_export_checks` and
`ats_vocabulary`; router `api/v1/cv_review.py`; frontend `AtsPanel.tsx` and
`DraftReview.tsx`. Behaviour is described in the README section "ATS match
report and reviewed CV writer". Testing on real listings exposed two extraction
faults that were fixed and covered by tests: headings written with a curly
apostrophe ("What you’ll bring") were missed, and duty sentences containing
"required" were counted as essential requirements. The CV validator's
action-verb list was extended to present-tense and further verbs so current
roles are not rejected; the five-bullet, no-filler and source rules are
unchanged. No migration was added.

Tests: backend **378 passed** (36 new), frontend **59 passed** (6 new),
`npx tsc -b` clean, single head `d8b4f6a2c9e1`, `git diff --check` clean.

Known limitations: matching is literal word and phrase matching with a small
alias list, so skills described differently are reported missing; requirement
extraction depends on headings and wording and can over- or under-count on
unusual layouts (on 120 stored listings most yield 5-20 essentials); the writer
only restates and reorders, so weak source wording stays weak apart from the
listed fixes; column detection in PDFs is heuristic; reviewed drafts still need
five substantive bullets per role; no OCR for scanned CVs; the score is not a
prediction of any employer's system.

## 2026-10-17 source expansion and direct-link verification (uncommitted)

Implemented:

- Shared host-pinned fetcher (`app/services/job_sources/http.py`): redirects
  must stay on the API host, 20 s timeout, 20 MB cap, three attempts with
  backoff for timeouts, 429 (`Retry-After` capped at 30 s) and 5xx.
- Lever (`api.lever.co`, EU `api.eu.lever.co`) and Ashby
  (`api.ashbyhq.com/posting-api`) public adapters beside Greenhouse. Workable
  was **not** implemented: its API terms were not verified.
- Source registry `app/data/source_registry.json`, validated on load: 38
  organisations, 8 enabled (Greenhouse `gitlab`, `canonical`, `sourcegraph91`;
  Ashby `andela`, `kraken.com`, `1password`, `M-KOPA`, `oyster`). Boards were
  taken only from links on each organisation's own careers page (one GET per
  page, 2026-10-16 23:56-23:59Z). Toggl's Ashby link returned 404 from the
  API (2026-10-17 00:14Z) and is disabled; Kelly (Workday, no adapter) and
  Robert Walters (HTTP 403) are recorded but not fetched. The 12 staffing
  agencies and the remaining employers are manual-only. `regions_served` is
  left empty because it was not verified.
- Migration `d8b4f6a2c9e1`: `listing_url`, `source_category`, `relisted_at`,
  run `skip_reasons`, assessment `geographic_scope`, and the
  `job_listing_link_checks` table.
- `verify-links` records vacancy-page and application-link outcomes
  separately; "reachable" never claims the vacancy is open or the form works.
- Cross-source duplicate collapsing (only across different sources; the
  employer's own posting is preferred), vacancy status, source health
  (`GET /job-sources`), eligibility evidence passages with a conflict guard,
  geographic scope on reviews, and new listing filters; the Discovered jobs
  page shows all of these.

Controlled run, disposable rehearsal database only (never `jobpilot`):

- `discover-registry`, 2026-10-17 00:14:52-00:15:11Z: 8 of 9 sources
  succeeded, Toggl failed `not_found`, nothing skipped. Listings: GitLab 229,
  Canonical 309, Sourcegraph 9, Andela 16, Kraken 89, 1Password 74, M-KOPA 41,
  Oyster 22 — 789 active, all with a vacancy page and posting date; no
  cross-source duplicates among them.
- `verify-links` (28 listings over three runs, 00:15-00:17Z): 25 reachable on
  both links (GitLab 17, M-KOPA 5, Canonical 3); 3 expired (HTTP 404), all
  synthetic leftovers from earlier test boards.
- Read-only queries: 42 listings name Kenya; 5 have eligibility conflicts;
  303 contain worldwide wording (still requiring human review); 42 match the
  support/IT filter.

Tests: backend **342 passed**, frontend **53 passed**, `npx tsc -b` clean,
`git diff --check` clean, single Alembic head `d8b4f6a2c9e1`; the migration was
upgraded, checked, downgraded and re-upgraded on PostgreSQL.

Known gaps: no Lever board was found on a verified careers page, so the Lever
adapter is tested only against mocked responses; staffing agencies have no
public feeds; several employers render boards with JavaScript only; the older
`discover-greenhouse` path does not retry; duplicates posted under a different
employer name are not matched; link checks are manual (no scheduler). Coverage
is a small verified set, not worldwide.

## 2026-10-17 build, migration and workflow verification

Implemented (uncommitted, on top of `1342fb2`):

- Discovered listing → job description import (server copies the stored text
  verbatim; one import per profile and listing; migration `5c2d9e7a1f40`).
- Discovery hardening: the 24-hour window excludes future-dated listings and is
  the default view; the Greenhouse fetch refuses redirects away from HTTPS
  `boards-api.greenhouse.io`.
- Application tracker with ten stages, server-enforced transitions, an
  append-only status history, and a required recorded date for "Applied"
  (migration `8d4b6f2e9c17`); dashboard shows active applications and dates
  due within two weeks.
- Candidate-reviewed Kenya eligibility per listing with exact, server-verified
  quotations, examined-text snapshots, stale detection on any wording change,
  and an eligibility filter (migration `a17c3e5b9d24`). The API's eligibility
  status changed from `unknown` to `eligibility_unknown`, as the spec defines.
- Added after the migration below (applied to `jobpilot` later that day): candidate-
  confirmed work eligibility details (`PUT/GET .../eligibility-details`,
  explicit `confirmed: true`, ISO country codes, per-country work
  authorization, unknown kept unknown; migration `c3e9a2d7f1b5`) and a
  read-only deterministic job-fit check (`GET .../job-descriptions/{id}/fit`)
  that separates met, missing, uncertain and potentially disqualifying
  requirements with sources, keeps Kenya eligibility separate from skills
  coverage, and never lets coverage outweigh a stated exclusion. Keyword
  detection only proposes passages: a potential disqualifier needs a strict
  restriction naming a country that conflicts with a confirmed detail.
  Request-size limits and per-account login limiting were also added.

Migration of the configured database (approved): target confirmed as
`jobpilot` on `127.0.0.1:5433` at `d4f7a19c2b86` with counts equal to the
backup state; backup `jobpilot-pre-applications-20261017-020223-bef63d.dump`
(SHA-256 `ba5b4c33…feb97`) restored into
`jobpilot_premig_restore_20261017_020223_bef63d` with matching counts; the
four pending migrations rehearsed there first. After `alembic upgrade head` on
`jobpilot`: revision `a17c3e5b9d24`, all 15 pre-existing data tables
unchanged, the five new tables present and empty, `alembic check` clean, and
the three private documents byte-identical to their backup copy
(`documents-pre-applications-20261017-020223`).

Workflow verification: 40 of 40 checks passed over real HTTP through the Vite
dev server and `/api` proxy, FastAPI and PostgreSQL, with real cookies and
CSRF. This ran against the migrated **restored copy** (same data as
`jobpilot`), whose owner was given a one-off password; the configured
database's password was not reset and no sign-in to it was performed. Covered:
sign-in and session restore (including CSRF rotation), the existing profile,
three documents and five evidence records, a discovery run (227 GitLab
listings, 11 posted within 24 hours), eligibility review with quotation
validation, listing import without duplicates, CV draft generation, PDF and
DOCX export, application tracking with refused invalid transitions, and
refusal of anonymous, forged-CSRF and wrong-origin requests. No job
application was submitted. The configured `jobpilot` database holds no
discovered listings yet.

## 2026-10-15 audit

Findings and corrections (since committed locally in `1342fb2`). The database
observations in this section are historical; see "Database, migration, and
backup status" for later observations.

- **Blocker at the time: configured database not migrated.** A read-only
  query showed the configured `jobpilot` database at revision `7ce347caa873`
  with no `users`, `auth_sessions`, or `candidate_profiles.user_id`. The code
  requires `d4f7a19c2b86`. The database held zero candidate profiles,
  documents, evidence, job descriptions, drafts, and exports, so no legacy
  profile needs adoption. The configured private document directory held zero
  files.
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

### Job discovery slice (2026-10-16, committed locally in `1342fb2`; no recorded application to `jobpilot`)

- Migration `3b8e5f0c9a12` (parent `d4f7a19c2b86`) adds `job_listings` and
  `job_discovery_runs` only; no foreign keys to candidate data. Downgrade drops
  both tables and all discovered listings and run history.
- Rehearsed on the new disposable database
  `jobpilot_jobdisc_rehearsal_20261016_91c48d`, restored from
  `jobpilot-pre-job-discovery-20261016-135946-686b42.dump` (SHA-256
  `C1D887EA…627E77`): upgrade, `alembic check`, downgrade, re-upgrade and
  `check` passed; 7 PostgreSQL tests passed. Private documents were copied to
  `documents-pre-job-discovery-20261016-135946` and verified by hash.
- First live source test (2026-10-16), against the disposable rehearsal
  database only: the Greenhouse board token `gitlab` was verified from GitLab's
  official careers-page asset (`https://about.gitlab.com/_nuxt/4xV37onP.js`,
  which references `boards-api.greenhouse.io/v1/boards/gitlab/...`). One
  `discover-greenhouse --board gitlab --employer "GitLab"` run, with
  `POSTGRES_DB` overridden for that process only, exited 0: 226 fetched, 226
  new, 0 updated, 0 missing, 0 skipped. A read-only spot check of five stored
  listings checked them for internal consistency with the adapter's mapping:
  titles, locations, posting dates, apply URLs and readable descriptions were
  consistent, and workplace type, countries, salary and deadline were empty as
  designed. The listings were not compared with the original Greenhouse
  response, because the raw response was not retained. Read-only checks
  before and after showed the configured `jobpilot` database's revision and
  table counts unchanged and the discovery tables absent there. This does not
  verify the configured database, a browser workflow, or any other board.
- Source facts and JobPilot conclusions are separate: listings store only what
  a source states; eligibility is reported as `unknown`. A draft design for
  Kenya eligibility, candidate compatibility and posting recency is in
  `docs/JOB_ELIGIBILITY_SPEC.md` and `docs/JOB_ELIGIBILITY_TEST_CASES.md`
  (revision 4, awaiting sign-off; nothing in it is implemented).
- `dedupe_key` is computed and stored but not yet used to group cross-source
  duplicates; the `posted_within_hours` filter does not reject future-dated
  `posted_at` values.
- The Windows `uvicorn --reload` dev server was found stuck on its original
  worker after a file change; restart it after code changes and verify.

Known limitations recorded by the audit (not fixed):

- ~~The login limiter keys on client IP. Behind the Vite proxy every request
  comes from `127.0.0.1`, so five failed attempts lock out all sign-ins for 15
  minutes.~~ Fixed 2026-10-17 (uncommitted): failures are counted per client
  and account (5 per 15 minutes) with a per-client cap across accounts (50 per
  15 minutes), and a successful sign-in clears that account's count. The
  limiter is still process-local.
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
- ~~Uploads are bounded at 10 MB when stored, but the multipart body is spooled
  before that check; there is no request-size limit at the server.~~ Fixed
  2026-10-17 (uncommitted): a server middleware refuses request bodies above
  10.5 MiB for document uploads and 1 MiB elsewhere with HTTP 413, using the
  declared length or by counting streamed bytes before parsing.

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

Latest results, 2026-10-17, after the ATS and CV-review work: backend **378
passed**, frontend **59 passed**, `npx tsc -b` clean; plus the 28-step Chrome
walkthrough described above. After the source expansion the tree gave 342
backend and 53 frontend. Before that change the same tree gave 280 backend and 48 frontend. Earlier the
same day at commit `1342fb2`:

- Backend: `backend\.venv\Scripts\python.exe -m pytest -q` — **203 passed**,
  with one third-party deprecation warning (Starlette `TestClient` and
  `httpx`). Tests use isolated in-memory or temporary-file SQLite databases,
  temporary private storage, injected CLI session factories, and fake job
  sources; none contacts PostgreSQL or the network. The SQLite migration test
  verifies that the auth schema is additive and leaves a synthetic legacy
  profile unassigned.
- Frontend: `npm test` from `frontend` — **32 passed** (`fetch` is mocked).
- Frontend type check: `npx tsc -b` from `frontend` — **clean**.

Earlier results, kept for history: 141 backend and 22 frontend tests passed
after the 2026-10-15 audit (133 and 19 before it).

- An earlier frontend run concurrent with the production build hit the
  default five-second timeout in two UI tests; the complete suite passed when
  run separately.
- Frontend: `npm run build` from `frontend` — **passed** on 2026-10-15. It
  was not re-run afterwards because it replaces `frontend/dist`.

The following results come from the 2026-10-15 audit and were not re-run for
the 2026-10-17 documentation update:

- Backend dependencies: `python -m pip check` in `backend\.venv` — **passed**
  (2026-10-15 audit).
- `git diff --check` — **passed** (2026-10-15 audit).
- Pylance workspace diagnostics (2026-10-15 audit): no errors; two
  low-severity unused-parameter warnings are reported in
  `backend/tests/test_authorization.py`.
- Source review (2026-10-15 audit) found the authentication migration parent is
  `7ce347caa873`; the new revision is `d4f7a19c2b86`. It creates identity,
  session, pre-auth challenge, and adoption-audit tables, then adds nullable
  `candidate_profiles.user_id`. It contains no profile-owner backfill.
- The focused security review (2026-10-15 audit) reported no vulnerabilities
  in the changes it reviewed. It could not establish runtime
  listener/configuration state, live-database revision, or private-storage
  permissions.

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

Repository migration history is linear with a single head, confirmed from the
migration files on 2026-10-17: `f9a82b168b1b` → `8fb8c7fc5e68` →
`fa273b191a93` → `167049a09299` → `6ae71f371562` → `7ce347caa873` →
`d4f7a19c2b86` (auth, additive) → `3b8e5f0c9a12` (job discovery, additive;
its downgrade drops both discovery tables and their data) → `5c2d9e7a1f40`
(job-description listing link) → `8d4b6f2e9c17` (job applications) →
`a17c3e5b9d24` (listing eligibility assessments) → `c3e9a2d7f1b5` (candidate
eligibility details and work authorizations) → `d8b4f6a2c9e1` (source
verification and link checks). All are applied to `jobpilot` (2026-10-17).
Each new migration was upgraded, downgraded, re-upgraded and `alembic check`ed
on a disposable database before use.

Configured-database history:

- 2026-10-15: revision `7ce347caa873` (PostgreSQL 17.11), read-only check.
- 2026-10-16: revision `d4f7a19c2b86`, with no discovery tables, read-only
  check.
- 2026-10-17: migrated to `a17c3e5b9d24` with approval; verified as recorded in
  "2026-10-17 build, migration and workflow verification".
- 2026-10-17: migrated to `d8b4f6a2c9e1` with approval after a fresh backup
  (`jobpilot-pre-sources-20261017-043943-2465b4.dump`); verified row for row as
  recorded in "2026-10-17 approved migration to head, browser verification and
  ATS CV writer".

Always confirm the revision read-only before any future migration. Apart from
that approved migration, no bootstrap, password reset, or profile adoption
command was run against the configured database during the sessions recorded
here. The disposable copy `jobpilot_premig_restore_20261017_020223_bef63d` now
holds test data from the workflow verification; do not treat it as a backup
(use the dump file). Four earlier disposable databases
named `jobpilot_auth_*_20261015*` exist on the same server; one may
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

The runbook was written for the auth migration and was followed on 2026-10-17
to migrate `jobpilot` from `d4f7a19c2b86` to `a17c3e5b9d24`. For any future
migration, substitute the then-current revision and target, and in step 4
verify that new tables exist and all pre-existing table counts are unchanged.
Steps 6 and 7 apply only if no owner or adoption has been set up yet.

1. **Confirm target and current revision.** From `backend`, run `alembic
   current` only after verifying through the local operator configuration
   (without displaying secrets) which database the process will contact.
   Stop if the target or revision is unexpected. The repository shows the
   expected parent of the pending migration, but this does not establish the
   live revision.

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
contains the authentication implementation and matches `origin/main` as last
recorded locally (no fetch was made to re-check the remote).

Branch `feature/jobpilot-discovery-eligibility` adds two local commits on top
of `main`:

- `1ac77ea` — Kenya job eligibility specification and test-case design
  (documentation only).
- `1342fb2` — the 2026-10-15 audit fixes, document-provenance protection, the
  job-discovery first slice, and action-feedback UX, combined in one commit
  because they are interleaved in shared files.

The 2026-10-17 work (listing import, discovery hardening, application tracker,
reviewed eligibility, three migrations and their tests) is uncommitted in the
working tree on that branch.

This branch is local only: it has not been pushed, and no push or deployment
is authorized. Preserve any modifications and untracked files; do not stage,
commit, or push without explicit instruction.
