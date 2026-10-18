# Browser authentication smoke tests

The Playwright suite uses project-local Chromium and connects to the already
running app. From `backend`, start the API with
`.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
From `frontend`, start Vite with
`npm run dev -- --host 127.0.0.1 --port 5173`. Do not start or recreate a
database as part of this browser test.

Run from `frontend`:

```powershell
npm ci
npx playwright install chromium
npm run test:e2e
```

The default frontend URL is `http://127.0.0.1:5173`; override it with
`$env:PLAYWRIGHT_BASE_URL` when needed. The tests without credentials render
the login page on desktop and mobile, exercise one intentionally invalid login
against the local backend, verify candidate profiles return 401, and cover
delayed session restoration and duplicate-submit handling.

## One dedicated account

The valid-login journey requires a dedicated account and a profile owned by
that account. Enter its password without echoing it, then remove the local
environment values after the run:

```powershell
$env:JOBPILOT_TEST_EMAIL = Read-Host 'Dedicated test account email'
$securePassword = Read-Host 'Dedicated test password' -AsSecureString
$env:JOBPILOT_TEST_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
$env:JOBPILOT_TEST_PROFILE_ID = Read-Host 'UUID of that account test profile'
npm run test:e2e
Remove-Item Env:JOBPILOT_TEST_EMAIL, Env:JOBPILOT_TEST_PASSWORD, Env:JOBPILOT_TEST_PROFILE_ID -ErrorAction SilentlyContinue
```

## Two-account ownership isolation

To test that two accounts can each access their own profile but receive 403 or
404 for the other account’s profile, set both accounts and profile IDs locally:

```powershell
$env:JOBPILOT_TEST_EMAIL = Read-Host 'First dedicated test account email'
$securePassword = Read-Host 'First dedicated test password' -AsSecureString
$env:JOBPILOT_TEST_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
$env:JOBPILOT_TEST_PROFILE_ID = Read-Host 'UUID of first account test profile'
$env:JOBPILOT_OTHER_TEST_EMAIL = Read-Host 'Second dedicated test account email'
$otherSecurePassword = Read-Host 'Second dedicated test password' -AsSecureString
$env:JOBPILOT_OTHER_TEST_PASSWORD = [System.Net.NetworkCredential]::new('', $otherSecurePassword).Password
$env:JOBPILOT_OTHER_TEST_PROFILE_ID = Read-Host 'UUID of second account test profile'
npm run test:e2e
Remove-Item Env:JOBPILOT_TEST_EMAIL, Env:JOBPILOT_TEST_PASSWORD, Env:JOBPILOT_TEST_PROFILE_ID, Env:JOBPILOT_OTHER_TEST_EMAIL, Env:JOBPILOT_OTHER_TEST_PASSWORD, Env:JOBPILOT_OTHER_TEST_PROFILE_ID -ErrorAction SilentlyContinue
```

The suite does not create accounts or profiles. This repository only has a
one-time `bootstrap-owner` CLI, which refuses to create another account once
an owner exists; there is no invite or admin provisioning endpoint. Provision
dedicated test accounts through an authorized admin workflow before using the
credentialed tests. Do not run `bootstrap-owner` against the current
installation to make a test account.

Screenshots, video, and traces are disabled so credentials and profile data are
not written into browser artifacts. Sanitized browser console and failed
request diagnostics are attached to the local test result only when present.
