# JobPilot AI Job Eligibility Test Cases

Status: draft for review, revision 4 (2026-10-17). These are test designs
only; no executable tests exist for them yet. Rules are defined in
[JOB_ELIGIBILITY_SPEC.md](JOB_ELIGIBILITY_SPEC.md).

## Conventions

- All input text is synthetic. Where a case mirrors a pattern seen in the
  2026-10-16 GitLab rehearsal run, the "Why" column says so; no real posting
  is quoted.
- "Location" means `job_listings.location_text`; "Description" means
  `job_listings.description_text`.
- Unless stated otherwise: the listing is `active`; the assessment's evidence
  currency is `current`; the candidate is based in Kenya; and no
  candidate-confirmed work authorization, relocation willingness or
  preference exists (matching today's data model).
- "Geo" is the geographic hiring eligibility outcome. "Compat" is the
  candidate compatibility record. They are asserted separately.
- Every case also implies the [universal assertions](#universal-assertions).

## Revision 4 changes

| ID | Change |
|---|---|
| EV-13 | Removed the reference to an open question; whitespace-only differences are settled as a change (`stale`). |
| EV-02, EV-03, EV-09 | Restated so each covers exactly one timestamp: `source_updated_at`, `last_verified_at` (with `content_hash` unchanged, no re-check required), and `posted_at` (recency assessed separately under FR rules). |
| EV-14, EV-15 | Added: a posting-date change that moves the listing into the 24-hour window, and a realistic run changing `source_updated_at` and `last_verified_at` together. |
| IND-04, FR-10 | Wording changed from "old posting" to "posted outside the 24-hour window" (no age band beyond the window is defined); expectations unchanged. |
| IND-05, IND-06 | Added: recent posting with `stale` evidence, and recent posting with `unverifiable` evidence. |
| Universal assertion 8 | Added: evidence currency and posting recency are evaluated independently, and stale or unverifiable evidence is never shown as a current Geo result. |

## Revision 3 changes

| ID | Change |
|---|---|
| EL-17 | Input made explicitly company-wide; applicability `established_by_wording` (was `company_policy_in_listing`). |
| EL-21 | Applicability `established_by_wording`. |
| EL-36 | Policy recorded with applicability `unclear` (hedged wording); outcome unchanged. |
| EL-14a, EL-35 | Wording aligned with "external evidence cannot independently support an outcome before the age policy". |
| EL-38 to EL-42 | Added: unresolved policy-vs-exception conflict, hedged in-listing policy, explicitly acknowledged exception, international presence, category-limited policy. |
| EV-01, EV-02, EV-04, EV-05 | Restated in terms of retained `examined_text` and external-evidence independence. |
| EV-09 to EV-13 | Added: posting-date-only change, identity mismatch, text removed, unrecorded hash method, whitespace-only change. |
| Universal assertions 2, 3 | Updated for `examined_text` and the new applicability values. |

## Revision 2 changes

| ID | Change |
|---|---|
| EL-08 | Geo unchanged (`eligibility_unknown`); the work authorization requirement now asserted as a compat item, not geographic evidence. |
| EL-09 | Geo changed from `not_eligible` to `eligibility_unknown`: employment residency is a compat item, not an applicant exclusion. |
| EL-10 | Input reworded so both statements concern applicants, keeping it a genuine conflict. |
| EL-13 | Moved to EV-01 (evidence currency). |
| EL-15, EL-17, EL-21 | Evidence now asserts original `statement_scope` and separate `role_applicability`. |
| EL-16 | Moved to EV-06 (vacancy status is not evidence staleness). |
| EL-23 | Geo changed from `not_eligible` to `eligibility_unknown`: a role location statement is not a hiring restriction. |
| EL-24 | Geo changed to `eligibility_unknown`, following EL-23. |
| EL-25 | Schedule requirement now asserted as a compat item. |
| EL-26 | Replaced by the CC residency and relocation cases. |
| EL-31 to EL-37 | Added: applicant-residency and closed-list contrasts, ambiguous location list, company-policy applicability, marketing language. |
| CC-01 to CC-10 | Added: candidate compatibility. |
| EV-01 to EV-08 | Added: evidence currency and timestamp semantics. |
| FR-01 to FR-10 | Terminology changed from "freshness" to "posting recency"; FR-10 updated. |
| IND-01 to IND-04 | Added: independence of the three results. |

## Geographic hiring eligibility cases

| ID | Scenario | Input evidence | Expected Geo outcome | Expected explanation / evidence requirements | Why it matters |
|---|---|---|---|---|---|
| EL-01 | Explicit worldwide permission | Location: `Remote`. Description: "This role is fully remote and open to candidates in any country." | `eligible_confirmed` | Quote; subject `applicant_location`; scope `role`; applicability `direct`; stance `permits_kenya`; basis `directly_stated`; region fact "Kenya ⊂ world". | Main positive path. |
| EL-02 | Kenya explicitly listed | Description: "We can hire in the following countries: Kenya, Nigeria, South Africa." | `eligible_confirmed` | Quote; subject `hiring_countries`; no region fact needed. | Direct naming is the strongest evidence. |
| EL-03 | Applicant restriction: US only | Description: "This position is open to US residents only." | `not_eligible` | Quote; subject `applicant_location`; stance `excludes_kenya`. | Explicit applicant exclusion. |
| EL-04 | Applicant restriction: Europe | Description: "Candidates must be located in Europe." | `not_eligible` | Region fact "Kenya ∉ Europe"; basis `directly_stated`. | Region exclusion records the region fact. |
| EL-05 | Remote, Africa, no clarification | Location: `Remote, Africa`. No eligibility statement. | `eligibility_unknown` | Label recorded with scope `unclear`, stance `context_only`; explanation: not stated as open to every African country. | A region label is not whole-region permission. |
| EL-06 | Remote, EMEA, no country list | Location: `Remote, EMEA`. No eligibility statement. | `eligibility_unknown` | As EL-05. | Common label that must not become a confirmation. |
| EL-07 | Remote, no geography | Location: `Remote`. Description mentions remote work only. | `eligibility_unknown` | No geographic evidence; explanation: "remote" without geography does not establish eligibility. | Missing information is not worldwide eligibility. Pattern seen in 9 GitLab rows. |
| EL-08 | Work authorization in another country | Description: "Must be authorized to work in the United States without sponsorship." | `eligibility_unknown` | No geographic evidence from this sentence. Compat: work authorization item `unresolved` (candidate status not recorded). | Missing candidate data must not become an employer exclusion. |
| EL-09 | Employment residency | Description: "You must reside in Germany for the duration of employment." | `eligibility_unknown` | Subject `employment_location`. Compat: residency item `unresolved`; relocation `not stated`; willingness unknown. | Where an employee must live is not where applicants may apply from. |
| EL-10 | Conflicting applicant statements | Description intro: "Open to applicants worldwide." Later: "Applicants must currently reside in Canada." | `eligibility_unknown` | Both quoted, one in `evidence`, one in `conflicting_evidence`; explanation names the conflict. | JobPilot must not pick a winner. |
| EL-11 | "Africa" as customer or coverage area | Location: `Bangalore, India`. Description: "Our team supports customers across Europe, the Middle East, Africa, and the United States." | `eligibility_unknown` | If recorded: scope `market_or_customer`, applicability `not_applicable`, stance `context_only`. | Keyword trap. Mirrors 8 GitLab rows. |
| EL-12 | "Hybrid" as software architecture | Description: "Experience with cloud and hybrid architecture deployments." | `eligibility_unknown` | No evidence or work-arrangement item derived from "hybrid"; `stated_workplace_type` stays null. | Keyword trap. Mirrors a GitLab row. |
| EL-13 | (Moved) | See EV-01. | — | — | — |
| EL-14a | Official application page clearer than listing | Listing: `Remote`. Official application page: "Applicants from any country, including Kenya, are welcome." | `eligibility_unknown` until page fetching is approved and a maximum-age policy exists (the page would be the only deciding evidence); `eligible_confirmed` afterwards, while within age | Evidence type `official_application_page`, exact URL, own `retrieved_at`. | Clearer official evidence, gated on open questions 4 and 5. |
| EL-14b | Official application page contradicts listing | Listing: "Open to candidates worldwide." Application page: "Are you located in the United States? (Required: Yes)". | `eligibility_unknown` | Both recorded; application-page item in `conflicting_evidence`. | Cross-source contradiction is a genuine conflict. |
| EL-15 | Company description + role restriction | Description: "We are a global, all-remote company." Later: "This role is open to candidates in the United Kingdom only." | `not_eligible` | Company sentence: scope `company`, applicability `not_applicable`, `context_only`. Role sentence: scope `role`, applicability `direct`. | Marketing language is not a hiring policy. |
| EL-15b | Role-level global + role-level restriction | Description: "This role can be performed from anywhere in the world." Later: "Candidates for this role must be based in Mexico." | `eligibility_unknown` | Genuine conflict; both quoted. | Contrast with EL-15. |
| EL-16 | (Moved) | See EV-06. | — | — | — |
| EL-17 | Explicit company-wide restriction that clearly applies | Description: "This applies to all of our open positions: we are unable to hire anyone based in Kenya." | `not_eligible` | Scope `company` (as written, never relabelled); applicability `established_by_wording` (covers all positions); stance `excludes_kenya`. | A policy decides the role only because its wording covers it. |
| EL-18 | Explicit exclusion vs explicit inclusion | Description: "Open to candidates in Kenya." Elsewhere: "We cannot hire in Kenya." | `eligibility_unknown` | Both recorded as conflicting. | Exclusion wins only over vague permission. |
| EL-19 | Explicit whole-region permission | Description: "Open to candidates in any African country." | `eligible_confirmed` | Region fact "Kenya ∈ Africa"; basis `directly_stated`. | Contrast with EL-05. |
| EL-20 | Location label lists other countries | Location: `Remote, Canada; Remote, United States`. No eligibility statement. | `eligibility_unknown` | Label recorded as `source_location_label`, scope `unclear`; explanation: a location label is not a hiring rule. | Most common GitLab label shape (45 rows). |
| EL-21 | Explicit closed hiring list | Description: "We can only hire in: Canada, United States." | `not_eligible` | Subject `hiring_countries`; scope `company`; applicability `established_by_wording` (categorical: "only", all hiring); reason: closed list excludes Kenya. | Contrast with EL-20 and EL-23. |
| EL-22 | Descriptive team locations | Description: "Our team members live in Canada, Germany and Japan." | `eligibility_unknown` | Scope `team`, applicability `not_applicable`, `context_only`. | Where employees live is not a hiring rule. |
| EL-23 | Role location statement | Location: `Remote`. Description: "This position is 100% remote and will be based in the UK, Ireland, France, Spain, and the Netherlands." | `eligibility_unknown` | Subject `employment_location`; explanation: states where the role operates, not that applicants elsewhere cannot apply. | Mirrors a GitLab multi-location row; must not become an exclusion. |
| EL-24 | Role location statement + unrelated time-zone wording | As EL-23, plus: "The team works across multiple U.S. time zones." | `eligibility_unknown` | Time-zone sentence `context_only`, not a conflict. | The GitLab row behind EL-23 contained both. |
| EL-25 | Time-zone overlap only | Location: `Remote`. Description: "Must overlap at least 4 hours with US Eastern time." | `eligibility_unknown` | Compat: schedule item `unresolved`. | Working hours are not geographic eligibility. |
| EL-26 | (Replaced) | See CC-02 to CC-06. | — | — | — |
| EL-27 | Pay text scoped to one country | Description: "The base salary range is for residents of the United States only." | `eligibility_unknown` | Subject `pay`; scope `unclear`; `context_only`. | Keyword trap: "residents ... only" in a pay sentence. Mirrors GitLab rows. |
| EL-28 | Non-substring quotation | Quotation differs from the examined text by one character. | Invalid evidence; Geo `eligibility_unknown` | Validation names the failed check. | Enforces verbatim quotation. |
| EL-29 | Confirmation resting on interpretation | Description: "We embrace a distributed, async culture." Proposed `eligible_confirmed` with basis `interpretation`. | Rejected; `eligibility_unknown` | Confirmation requires `directly_stated`. | Culture wording is not permission. |
| EL-30 | No description, no location | Both null. | `eligibility_unknown` | No evidence; explanation says nothing was stated. | Missing-evidence floor. |
| EL-31 | Explicit applicant residency | Description: "Applicants must reside in the United Kingdom." | `not_eligible` | Subject `applicant_location`; applicability `direct`. | Contrast with EL-09 and EL-23: applicant rule vs employment or operating location. |
| EL-32 | Explicit closed list of role locations | Description: "Only candidates located in the UK, Ireland, France, Spain or the Netherlands will be considered." | `not_eligible` | Subject `applicant_location`. | Same countries as EL-23, but explicit restrictive wording. |
| EL-33 | Ambiguous location list | Description: "Locations: UK, Ireland, Spain (remote)." | `eligibility_unknown` | Scope `unclear`; explanation: cannot tell hiring list from operating locations. | Ambiguity resolves to unknown. |
| EL-34 | Company policy elsewhere, applicability unclear | Listing: `Remote`, no geography. Official careers FAQ (approved fetch assumed): "We currently hire in 20 countries: …" (Kenya absent), with no statement that it covers all roles. | `eligibility_unknown` | Policy recorded with scope `company`, applicability `unclear`. | A company policy decides a role only when applicability is explicit or reliably established. |
| EL-35 | Company policy elsewhere, explicitly covering all roles | As EL-34, but the FAQ says "This applies to all open roles." | `eligibility_unknown` until page fetching is approved and a maximum-age policy exists; `not_eligible` afterwards, while within age | Applicability `established_by_official_source`; own `retrieved_at`. | Contrast with EL-34; external evidence cannot decide on its own before the age policy. |
| EL-36 | Hedged policy with role exception | Description: "We usually hire only in the US. This role is open to candidates in any country." | `eligible_confirmed` | Both recorded. Policy: scope `company`, applicability `unclear` ("usually"). Role sentence: scope `role`, applicability `direct`, decides. | The policy's own wording admits exceptions, so the conflict is resolved from explicit evidence. |
| EL-37 | Marketing language only | Description: "We are a global company with customers in 100 countries." | `eligibility_unknown` | Scope `company`, applicability `not_applicable`. | "Global" is not a hiring policy. |
| EL-38 | Categorical policy vs unexplained role statement | Description: "We can only hire in the United States." Later: "This role is open to candidates in any country." | `eligibility_unknown` | Both recorded with their own scopes; conflict unresolved; explanation names both. | Nothing explicit says how the two relate, so JobPilot must not pick one. |
| EL-39 | Company-wide restriction with unclear applicability (in the listing) | Location: `Remote`. Description: "Most of our hiring is focused on North America." | `eligibility_unknown` | Scope `company`, applicability `unclear` (hedged, not categorical). | Printing a policy in the listing does not make it applicable. |
| EL-40 | Role statement explicitly presented as an exception | Description: "Unlike most of our roles, which are US-only, this role is open to candidates in any country." | `eligible_confirmed` | Role sentence `direct`; the embedded policy reference recorded as context. | The exception is stated explicitly, so it resolves the apparent conflict. |
| EL-41 | International presence and offices | Description: "We have offices in London, Berlin and Nairobi and employees in 40 countries." | `eligibility_unknown` | Scope `company`, applicability `not_applicable`, `context_only`. | Presence, offices (even in Nairobi) and employee locations are not hiring policies. |
| EL-42 | Category-limited policy, category of this role unclear | Title: "Account Executive". Description: "For engineering roles, we can only hire in the United States." | `eligibility_unknown` | Applicability `unclear`; the role's category is not inferred from its title. | A category-limited policy applies only when the listing states the role is in that category. |

## Candidate compatibility cases

| ID | Scenario | Input evidence | Expected Geo outcome | Expected Compat record | Why it matters |
|---|---|---|---|---|---|
| CC-01 | Geo confirmed, work authorization unknown | Description: "Open to applicants in any EMEA country. You must have the right to work in the country you are based in." | `eligible_confirmed` | Work authorization item `unresolved` (candidate's right to work in Kenya not recorded). | Geographic confirmation and an open candidate requirement coexist. |
| CC-02 | Employment residency, relocation not mentioned | Description: "You must reside in Germany for the duration of employment." | `eligibility_unknown` | Residency `unresolved`; relocation `not stated`; willingness unknown. | No exclusion manufactured from a residency requirement. |
| CC-03 | Relocation offered, coverage unclear | Description: "Must reside in Germany. Relocation support is available." | `eligibility_unknown` | Residency `unresolved`; relocation offer recorded, coverage `unclear`. | An offer does not show it covers Kenya. |
| CC-04 | Relocation explicitly available from Kenya, willingness unknown | Description: "We welcome applicants from Kenya and provide relocation to Berlin." | `eligible_confirmed` | Residency `unresolved`; relocation coverage includes Kenya; willingness unknown. | Willingness is never assumed. |
| CC-05 | Relocation from Kenya, willingness confirmed | As CC-04, plus a synthetic candidate-confirmed record "willing to relocate to Germany" (no such field exists today). | `eligible_confirmed` | Residency `resolvable_by_relocation`. | Only candidate-confirmed willingness resolves the item. |
| CC-06 | Sponsorship offered, coverage unclear | Description: "Must be authorized to work in the US. Visa sponsorship may be available." | `eligibility_unknown` | Work authorization `unresolved`; sponsorship recorded, coverage `unclear`. | Sponsorship is not assumed to address the requirement. |
| CC-07 | Explicit Kenya exclusion, no relocation path | Description: "We cannot consider applicants based in Kenya." | `not_eligible` | No items to resolve. | Exclusion is geographic, not a compatibility gap. |
| CC-08 | Missing candidate data never becomes exclusion | CC-01 with no candidate data at all. | `eligible_confirmed` | Items `unresolved`; UI says "needs your input", never "not eligible". | Guards the core separation. |
| CC-09 | Work-arrangement preference | Description: "This is a hybrid role, 3 days per week in our Nairobi office." Candidate preference not recorded. | `eligibility_unknown` (no applicant rule stated) | Work-arrangement item `unresolved`; no preference assumed. | Preferences never alter Geo, and even a Kenyan office location is a role location statement, not a confirmation. |
| CC-10 | No candidate-specific requirements | Description: "Open to candidates in any country." Nothing else relevant. | `eligible_confirmed` | No items; UI: "No candidate-specific requirements found in the posting", not "Compatible". | Absence of requirements is not a suitability claim. |

## Evidence currency and timestamp cases

| ID | Scenario | Input | Expected currency | Expected effect | Why it matters |
|---|---|---|---|---|---|
| EV-01 | Relevant text changed | EL-01 assessment exists; the eligibility sentence in the description is edited, so `description_text` differs from `examined_text`. | `stale` | Effective Geo `eligibility_unknown`, reason "eligibility evidence changed; reassessment needed"; previous outcome kept as history. | Changed evidence must not stay authoritative. |
| EV-02 | Only `source_updated_at` changes | `source_updated_at` advances; `posted_at` and `last_verified_at` unchanged; description and location identical to `examined_text`. The listing `content_hash` **does** change because it includes `source_updated_at`. | `current` (after verification) | The hash change triggers a text comparison; text matches; outcome kept; UI note "source updated since assessment; eligibility wording unchanged". Posting recency unaffected (see FR-06). | A source-edit timestamp is not a wording change. |
| EV-03 | Only `last_verified_at` changes | A new successful run updates `last_verified_at`; `content_hash`, `source_updated_at`, `posted_at`, description and location all unchanged. | `current` | No re-check of the assessed text is required, and the evidence is not made `stale`; `last_verified_at` is never recorded as an evidence retrieval time. | A run's verification time is not an evidence retrieval or change time. |
| EV-04 | No examined text retained | Assessment record has an outcome but no `examined_text` (and no resolvable reference). | `unverifiable` | Effective Geo `eligibility_unknown` until reassessment, reason "cannot confirm eligibility evidence is current"; previous outcome as history. | Uncertainty is surfaced, never silently treated as current. |
| EV-05 | External evidence, age policy undecided | EL-14a evidence with `retrieved_at` recorded. | Not usable as deciding evidence | Recorded and shown; cannot independently support `eligible_confirmed` or `not_eligible`; Geo stays `eligibility_unknown` unless listing evidence decides it. | External evidence needs its own timestamp and an agreed age policy. |
| EV-06 | Vacancy no longer listed | Listing with a `current` `eligible_confirmed` assessment is marked `missing_from_source`. | Unchanged (not `stale`) | UI shows "No longer listed by the source" first; listing not actionable; no reassessment; assessment kept as history. | Vacancy status is distinct from stale evidence. |
| EV-07 | Location wording changed, description unchanged | Assessment cited `location_text`; label changes. | `stale` | As EV-01. | The examined text includes the location label. |
| EV-08 | Removed listing reappears | EV-06 listing seen again in a later successful run with identical text. | Re-checked: `current` | Shown as listed again with its outcome. | Reappearance re-enters the normal currency check. |
| EV-09 | Only `posted_at` changes | `posted_at` changes from now − 30d to now − 20d (so `content_hash` changes); `source_updated_at` and `last_verified_at` unchanged; description and location identical. | `current` (after verification) | Geo outcome kept. Posting recency assessed separately under the FR rules: not recent (outside the 24-hour window). | A posting date is not eligibility wording, and evidence currency does not decide recency. |
| EV-10 | Listing identity mismatch | Assessment's recorded `source_listing_id` differs from the listing it is attached to. | `unverifiable` | Effective Geo `eligibility_unknown`; reason names the identity mismatch. | Evidence must correspond to the listing it describes. |
| EV-11 | Relevant text removed | Assessment examined a description; the listing's `description_text` is now null. | `stale` | Effective Geo `eligibility_unknown`, "eligibility evidence changed; reassessment needed". | Text becoming null is a change, not an absence of change. |
| EV-12 | Hash kept without method or text | Assessment retained only a hash whose algorithm and input fields were not recorded. | `unverifiable` | As EV-04. | A comparison that cannot be reproduced cannot confirm currency. |
| EV-13 | Whitespace-only change | Description differs from `examined_text` only by a trailing newline. | `stale` | As EV-01: no normalization is applied, so any difference, including whitespace only, requires reassessment. | Pins the character-for-character comparison rule. |
| EV-14 | `posted_at` moves into the recency window | `posted_at` changes from now − 30d to now − 2h (for example a repost); description and location identical. | `current` (after verification) | Geo outcome kept. Posting recency, assessed separately: recent (FR-01 rule). Repost caveat applies: JobPilot cannot tell a repost from a new vacancy. | A posting-date change can change recency without touching evidence currency. |
| EV-15 | Typical run: `source_updated_at` and `last_verified_at` change together | One successful run advances both; `posted_at`, description and location unchanged. | `current` (after verification) | The `content_hash` change (from `source_updated_at`) triggers the text comparison; text matches. The `last_verified_at` change contributes nothing to the decision. | The most common real-world combination. |

## Posting recency cases

Posting recency is independent of all other results. `now` is a fixed UTC
instant in every case.

| ID | Scenario | Input evidence | Expected recency | Expected explanation | Why it matters |
|---|---|---|---|---|---|
| FR-01 | Inside the window | `posted_at` = now − 3h | Recent (within 24h) | Uses `posted_at` in UTC. | Normal path. |
| FR-02 | Exactly at the boundary | `posted_at` = now − 24h | Recent | Inclusive boundary, matching the current API filter. | Pins the boundary. |
| FR-03 | Just outside | `posted_at` = now − 24h − 1s | Not recent | — | Boundary. |
| FR-04 | Missing posting date | `posted_at` null; `first_seen_at` = now − 1h | Unknown; excluded from 24h view | "Posting date not stated by the source." | Import time never stands in. |
| FR-05 | Old vacancy, newly imported | `posted_at` = now − 30d; `first_seen_at` = now − 5min | Not recent | — | Newly imported is not newly posted. |
| FR-06 | Old vacancy, recently updated | `posted_at` = now − 30d; `source_updated_at` = now − 1h | Not recent | — | Recently updated is not a new vacancy. |
| FR-07 | Future posting date | `posted_at` = now + 2h | Unknown | Timestamp flagged unreliable. | Documents the current filter's gap. |
| FR-08 | Posting later than update | `posted_at` = now − 1h; `source_updated_at` = now − 5h | Unknown | — | Internal inconsistency is not trusted. |
| FR-09 | Timezone handling | `first_published` = "2026-10-16T06:00:00+03:00"; now = 2026-10-17T02:30:00Z | Recent | UTC instants: 03:00Z vs 02:30Z next day (23.5h). | Local-time comparison would mis-classify. |
| FR-10 | Recent verification, posting outside the window | `posted_at` = now − 10d; `last_verified_at` = now − 1h | Not recent | — | A verification timestamp is not a posting date. |

## Independence cases

| ID | Input | Expected Geo | Expected Compat | Expected recency | Why it matters |
|---|---|---|---|---|---|
| IND-01 | CC-01 text; `posted_at` = now − 2h | `eligible_confirmed` | Work authorization `unresolved` | Recent | Three different results shown side by side; no overall "suitable" label. |
| IND-02 | EL-03 text; `posted_at` = now − 2h | `not_eligible` | No items | Recent | A recent posting is not more eligible. |
| IND-03 | EL-07 text; `posted_at` null | `eligibility_unknown` | No items | Unknown | Unknown in two results independently. |
| IND-04 | CC-04 text; `posted_at` = now − 40d; evidence `current` | `eligible_confirmed` | Residency `unresolved` (willingness unknown) | Not recent | Current evidence for a listing posted outside the 24-hour window keeps its confirmed Geo outcome. |
| IND-05 | EL-01 assessment; description since edited (evidence `stale`); `posted_at` = now − 2h | Effective `eligibility_unknown` (previous `eligible_confirmed` shown only as history) | Unchanged items, shown as needing reassessment | Recent | A recent posting does not keep stale evidence authoritative. |
| IND-06 | EL-01 assessment with no retained `examined_text` (evidence `unverifiable`); `posted_at` = now − 2h | Effective `eligibility_unknown` (previous outcome only as history) | As IND-05 | Recent | Recency never substitutes for verifiable evidence. |

## Universal assertions

Every case should also verify that:

1. `job_listings` facts are unchanged by any assessment.
2. Every listing-text quotation is an exact substring of the assessment's
   retained `examined_text`.
3. Every `eligible_confirmed` or `not_eligible` outcome has at least one
   deciding evidence item with applicability `direct`,
   `established_by_wording` or `established_by_official_source` (the last
   only within an agreed external-evidence age policy), and basis
   `directly_stated`.
4. `statement_scope` is recorded as written; it is never rewritten to `role`
   to make a company statement count.
5. No compatibility item, and no missing candidate data, changes the Geo
   outcome.
6. No overall "suitable", "match" or "ineligible" label is produced.
7. No outcome is derived from the title, the employer's location, a location
   label, a role location list, or a keyword match alone.
8. Evidence currency and posting recency are evaluated independently: a
   change to `posted_at` can at most trigger the text comparison and never by
   itself changes evidence currency, and no currency state changes recency. A `stale` or
   `unverifiable` assessment is never shown as a current Geo result; the
   effective Geo result is `eligibility_unknown` until reassessment.

## Where these tests could eventually live

No executable tests are added by this task.

| Area | Candidate module | Notes |
|---|---|---|
| Geographic rules (EL), compatibility (CC), independence (IND), universal assertions | New module, for example `backend/tests/test_job_eligibility.py` | No eligibility code exists. |
| Evidence currency against listing changes (EV) | New module, with fixtures built like those in `backend/tests/test_job_discovery.py` | Existing tests already exercise `content_hash`, `last_verified_at` and `missing_from_source`. |
| Posting recency filter (FR-01 to FR-10) | `backend/tests/test_job_discovery.py` | Extends `test_api_posted_within_filter_excludes_undated_and_old_listings`. |
| Adapter guarantees (EL-12: no inferred workplace type or countries) | `backend/tests/test_job_discovery.py` | Extends `test_greenhouse_maps_documented_fields_without_inventing_values`. |
| UI wording for separate results, stale and no-longer-listed states | `frontend/src/App.test.tsx` | Extends "shows stored listings as source facts with eligibility unknown". |
