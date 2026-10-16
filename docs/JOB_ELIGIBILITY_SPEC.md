# JobPilot AI Job Eligibility Specification (Kenya-based candidates)

Status: draft for review, revision 4 (2026-10-17). Nothing in this document is
implemented. Test cases live in
[JOB_ELIGIBILITY_TEST_CASES.md](JOB_ELIGIBILITY_TEST_CASES.md).

## Purpose and scope

JobPilot reports three independent results for a stored job listing. None of
them is a source fact, and none may be merged into a single "suitable" or
"ineligible" verdict.

| Result | Question it answers | Depends on |
|---|---|---|
| **Geographic hiring eligibility** | Does reliable, role-applicable evidence establish whether the employer permits applicants based in Kenya? | Employer evidence only. |
| **Candidate compatibility** | Which role requirements depend on the individual candidate, and is the candidate's position on each known? | Employer evidence plus candidate-confirmed facts and preferences. |
| **Posting recency** | Was the vacancy first posted recently? | The source's posting timestamp only. |

Separately, the listing has a **vacancy status** (`active` or
`missing_from_source`), and each eligibility assessment has an **evidence
currency**. Neither is part of any of the three results above.

**Evidence currency and posting recency are different questions:**

- **Evidence currency** (`current`, `stale`, `unverifiable`) answers whether
  the evidence an eligibility assessment relied on still corresponds to the
  listing's relevant text and remains usable under the evidence rules. It
  says nothing about when the vacancy was posted.
- **Posting recency** answers how recently the vacancy was posted, using only
  posting-date evidence and the recency policy in
  [Posting recency](#posting-recency). It says nothing about whether
  eligibility evidence is still valid.
- A listing may have `current` eligibility evidence and have been posted long
  ago (outside the recency window).
- A listing may have been posted recently and have `stale` or `unverifiable`
  eligibility evidence.
- `stale` or `unverifiable` evidence is never presented as a currently
  verified geographic result. Until reassessment, the effective geographic
  result is `eligibility_unknown`, whatever the posting date.

Terminology: "recent" refers only to posting recency. "Current", "stale" and
"unverifiable" refer only to eligibility evidence currency. A removed vacancy
is "no longer listed", never "stale".

## Current state this specification builds on

- `job_listings` stores source facts only. `description_text` is the
  HTML-to-text conversion of the source's job content; `location_text` is the
  source's location label verbatim; `stated_workplace_type` and
  `stated_countries` exist but the Greenhouse adapter never populates them.
- `content_hash` (in `app/services/job_discovery.py`) is a SHA-256 over the
  application URL, employer, title, description, location, workplace type,
  countries, `posted_at`, `source_updated_at`, deadline and salary. It
  therefore changes when **any** of these change, including timestamp-only
  changes.
- `source_updated_at` is the source's own `updated_at`.
- `last_verified_at` is set to the **start time of a successful discovery
  run** for every listing that run saw, and also for listings that run newly
  marked `missing_from_source` (listings already missing are not touched). A
  failed run changes nothing.
- `first_seen_at` is the start time of the run that first stored the listing.
- `job_listings.updated_at` is bumped by the database on every row update,
  including runs that only refresh `last_seen_at`; it does not indicate a
  content change.
- No field records when a listing's description text last changed.
- The API returns `eligibility: {"status": "unknown", reason: ...}` for every
  listing (`Literal["unknown"]`). The UI shows "Eligibility unknown" and warns
  that "remote" is not evidence.
- `docs/PROJECT_HANDOFF.md` records that eligibility "will live in a separate
  per-profile assessment table". No such table exists.
- Nothing in the current implementation stores an assessment, an evidence
  item, a copy of examined text, or a hash of description or location text.
  Every such element in this specification is a design requirement only.
- `CandidateProfile.location` is optional free text. No candidate field records
  country of residence, citizenship, work authorization, willingness to
  relocate, or work preferences.

## A. Geographic hiring eligibility

### Outcomes

| Outcome | Meaning |
|---|---|
| `eligible_confirmed` | Explicit, reliable, role-applicable evidence permits applications from candidates based in Kenya, or explicitly includes Kenya within an eligible geographic scope, with no unresolved conflicting evidence. |
| `not_eligible` | Explicit, reliable, role-applicable evidence rules out applicants based in Kenya for this role. The excluding statement must be quoted. |
| `eligibility_unknown` | Evidence is missing, ambiguous, contradictory or insufficient. This is the default and the only safe fallback. |

`eligibility_unknown` is not a soft rejection. Listings in this state stay
visible, and the UI must say that Kenya eligibility was not established.

Missing **candidate** information never affects this result. A work
authorization requirement, a residency requirement for employment, or an
unknown willingness to relocate cannot produce `not_eligible`; those belong to
[candidate compatibility](#b-candidate-compatibility).

The existing API status `"unknown"` corresponds to `eligibility_unknown`.
Widening the API is a future contract change and is not specified here.

### Core rules

1. **Explicit evidence only.** An outcome other than `eligibility_unknown`
   requires at least one exact quotation that states the permission or
   exclusion, with role applicability `direct`, `established_by_wording` or
   `established_by_official_source` (see
   [company-wide statements](#company-wide-statements) and the evidence
   record).
2. **Never infer eligibility from:** the job title, the employer's
   headquarters or offices, the word "remote", "distributed", "global" or
   "async" on its own, the absence of a country restriction, a location label,
   or a list of the role's operating locations.
3. **Missing information is not worldwide eligibility.** "Remote" with no
   geography is `eligibility_unknown`.
4. **Absence of Kenya is not exclusion.** Listing other countries does not
   exclude Kenya unless the wording explicitly limits who may apply or be
   hired.
5. **Keywords are search aids, never proof.** A keyword match may locate a
   passage for review; the outcome rests on the passage's meaning, subject and
   scope. "Africa" as a sales territory, "hybrid" as software architecture and
   "global" as company reach are not eligibility statements.
6. **Ambiguity resolves to `eligibility_unknown`.** When two readings are
   plausible, record both and do not choose.

### Kinds of location statements

| Kind | Example | Geographic outcome | Reason |
|---|---|---|---|
| Explicit closed hiring list | "We can only hire in Canada and the United States." | `not_eligible` | States who can be hired; Kenya is outside the closed list. |
| Explicit applicant eligibility | "Applicants must reside in the United Kingdom." / "This position is open to US residents only." | `not_eligible` | States where applicants must be; a Kenya-based applicant is outside it. |
| Explicit whole-scope permission | "Open to candidates in any country." / "Open to candidates in any African country." | `eligible_confirmed` | Explicit permission whose scope contains Kenya (see region facts). |
| Kenya named as eligible | "We can hire in Kenya, Nigeria and Ghana." | `eligible_confirmed` | Direct naming. |
| Kenya named as excluded | "We are unable to hire in Kenya." | `not_eligible` | Direct exclusion. |
| Role location statement | "This position is based in the UK, Ireland, France, Spain, and the Netherlands." | `eligibility_unknown` | Describes where the role operates; does not state that applicants elsewhere cannot apply or be hired. |
| Location label | `Remote, Canada; Remote, United States` | `eligibility_unknown` | A source label about where the role is listed, not a hiring rule. |
| Employment residency | "You must reside in Germany for the duration of employment." | `eligibility_unknown` | About where the employee must live while employed, not where applicants may apply from; recorded as a candidate-compatibility requirement. |
| Descriptive team or employee locations | "Our team members live in Canada, Germany and Japan." | `eligibility_unknown` | Describes people, not hiring rules. |
| Ambiguous location statement | "Locations: UK, Ireland, Spain (remote)." | `eligibility_unknown` | Could be a hiring list or operating locations; cannot tell. |

### Region facts

Region membership only *applies* an explicit statement; it never creates one.
Fixed facts JobPilot may rely on:

- Kenya is in Africa, in Sub-Saharan and East Africa, and in EMEA.
- Kenya is not in Europe, North America, Latin America, APAC or the Americas.

| Statement | Outcome |
|---|---|
| "Open to candidates in any African country" / "any EMEA country" | `eligible_confirmed` (region fact recorded). |
| "Remote, Africa" or "Remote, EMEA" label, or the region named without "any", "all" or a country list | `eligibility_unknown` (employers often hire only in specific countries of a region). |
| "Candidates must be located in Europe." | `not_eligible` (explicit applicant restriction; Kenya ∉ Europe). |

### Company-wide statements

A company-level statement keeps its original scope (`statement_scope:
company`) in the evidence record. Whether it governs this role is a separate
judgement, recorded as **role applicability** and supported by the wording
itself. A company-scoped quotation is never relabelled as role-scoped.
Appearing in the listing's text does not by itself make a policy applicable.

**Not hiring policies** (applicability `not_applicable`, context only):
general company descriptions ("We are a global, all-remote company"),
international presence ("We have offices in London, Berlin and Nairobi"),
employee locations ("Our team members live in 40 countries") and marketing
language ("customers in 100 countries").

**Hiring policies.** A statement about where the company hires is assessed
for applicability:

| Applicability | When | Effect |
|---|---|---|
| `established_by_wording` | The wording itself establishes that the policy governs hiring for this role: it is categorical and covers all hiring or names this role or its category. Examples: "We can only hire in Canada and the United States." "This applies to all open positions: we are unable to hire in Kenya." | May decide the geographic outcome. |
| `established_by_official_source` | An official page outside the listing states the policy and explicitly states that it covers this role or all roles. | May decide the outcome only under the external evidence rules (age policy, approved fetching). |
| `unclear` | Hedged or partial wording ("Most of our hiring is focused on North America", "We generally hire where we have entities"), a policy limited to a category that may not include this role, or a policy elsewhere that does not say whom it covers. | Cannot decide the outcome. If nothing else decides it, the outcome is `eligibility_unknown`. |

**Role-specific exceptions.** When a role-level statement appears to conflict
with a company-wide policy, both are recorded with their own scopes, and the
conflict is resolved only from explicit evidence:

- The policy's own wording admits exceptions ("We usually hire only in the US")
  and the role statement is explicit ("This role is open to candidates in any
  country"): the role statement decides.
- The role statement explicitly presents itself as an exception ("Unlike most
  of our roles, which are US-only, this role is open to candidates in any
  country"): the role statement decides.
- A categorical policy ("We can only hire in the US") and a role statement
  ("This role is open to candidates in any country") with nothing explaining
  how they relate: unresolved conflict, `eligibility_unknown`.

### Conflicts

1. **Explicit Kenya exclusion over vague permission.** A role-applicable
   statement excluding Kenya produces `not_eligible` unless an equally
   explicit role-applicable statement permits Kenya.
2. **Genuine conflict produces `eligibility_unknown`.** Two explicit,
   role-applicable statements that cannot both be true (for example "Open to
   applicants worldwide" and "Applicants must currently reside in Canada")
   produce `eligibility_unknown`, with both quotations recorded. JobPilot must
   not pick a winner.
3. **Role restriction over company reach.** A general company description
   next to an explicit role restriction is not a conflict; the company
   statement is context.
4. **Location label vs description.** A label never overrides an explicit
   description statement. A description statement that is only a role
   location statement does not override a label either; both are recorded
   and the outcome is `eligibility_unknown` unless another rule applies.
5. **Listing vs official application page.** Consistent, clearer evidence
   from an official page may be used under the external evidence rules.
   Contradictory evidence between them is a genuine conflict.

## B. Candidate compatibility

Candidate compatibility is a separate list of items, one per requirement or
preference that depends on the individual. It never changes the geographic
outcome, and the geographic outcome never resolves a compatibility item.

### Item types

| Item | Source of the requirement | Candidate side |
|---|---|---|
| Work authorization | Quoted employer requirement (for example "must be authorized to work in the US"). | Candidate-confirmed authorization status; today always `unknown` because nothing is recorded. |
| Residency for employment | Quoted requirement to live in a place while employed. | Current base (Kenya, by the spec's assumption) plus relocation items below. |
| Relocation availability | Quoted employer offer, with its stated geographic coverage. | — (an employer fact, but recorded here because it only matters for an individual's move). |
| Willingness to relocate | — | Candidate-confirmed only. **Never assumed**, never inferred from applying or from the profile location. |
| Visa sponsorship | Quoted employer offer, with what it covers. | Whether it addresses the specific authorization requirement; `unclear` unless the text says so. |
| Time zone and schedule | Quoted requirement (for example "4 hours overlap with US Eastern"). | Candidate preference or acceptance; `unknown` until stated. |
| Remote, hybrid or on-site arrangement | Quoted arrangement. | Candidate preference. |
| Skills fit, seniority, salary expectations, other matching | Out of scope for this specification; listed so they are never folded into eligibility. | — |

### Item states

Each item records the quoted requirement (or `not stated`) and a candidate
state:

- `candidate_meets` — candidate-confirmed data shows the requirement is met.
- `candidate_does_not_meet` — candidate-confirmed data shows it is not met.
- `resolvable_by_relocation` — the requirement is not met where the candidate
  is based, but relocation is explicitly available from Kenya **and** the
  candidate has explicitly confirmed willingness to move.
- `unresolved` — any other case, including missing candidate data, unclear
  relocation coverage and unknown willingness.

Missing candidate data is always `unresolved`. It is never reported as the
employer excluding Kenya.

### Residency, relocation and sponsorship cases

| Case | Example | Geographic eligibility | Candidate compatibility |
|---|---|---|---|
| Role explicitly excludes Kenya-based applicants, no relocation path | "We cannot consider applicants based in Kenya." | `not_eligible` | Not assessed further; nothing to resolve. |
| Employment residency required, relocation not mentioned | "You must reside in Germany for the duration of employment." | `eligibility_unknown` (unless other evidence decides it) | Residency item `unresolved`: not met where the candidate is based; relocation not stated; willingness unknown. |
| Relocation offered, coverage unclear | "Must reside in Germany. Relocation support is available." | `eligibility_unknown` (unless other evidence decides it) | Residency item `unresolved`; relocation item records the offer with coverage `unclear`. |
| Relocation explicitly available from Kenya, willingness unknown | "We welcome applicants from Kenya and provide relocation to Berlin." | `eligible_confirmed` (Kenya named as welcome) | Residency item `unresolved` until the candidate confirms willingness. |
| Relocation available from Kenya, willingness confirmed | As above, plus a candidate-confirmed willingness record (does not exist today). | `eligible_confirmed` | Residency item `resolvable_by_relocation`. |
| Sponsorship offered, coverage of the requirement unclear | "Must be authorized to work in the US. Visa sponsorship may be available." | Unaffected; decided by other evidence | Work authorization item `unresolved`; sponsorship recorded with coverage `unclear`. |

Relocation eligibility and visa eligibility are never inferred: an offer
covers a Kenya-based candidate only when its text says so (by naming Kenya,
or by an explicit whole-scope statement such as "for candidates from any
country").

## Evidence record

Each assessment carries its geographic outcome, its compatibility items, and
the evidence behind both.

### Assessment fields

| Field | Requirement |
|---|---|
| `geographic_outcome` | One of the three outcomes. |
| `geographic_explanation` | Plain English naming what was found or missing. |
| `compatibility_items` | Zero or more items as defined above, each with its quotation(s) and candidate state. |
| `evidence` / `conflicting_evidence` | Evidence items supporting and opposing the geographic outcome. |
| `basis` | `directly_stated` when the quotation states the permission or exclusion; `interpretation` otherwise. Applying a fixed region fact to a directly stated whole-scope statement remains `directly_stated`. `eligible_confirmed` and `not_eligible` require `directly_stated`. |
| `outcome_reason` | Which rule produced the outcome. |
| `assessed_at` | When the assessment was made (UTC). |
| `listing_identity` | The listing's `id` and its source identity (`source_kind`, `source_key`, `source_listing_id`). |
| `examined_text` | The exact `description_text` and `location_text` (including nulls) the assessment evaluated, retained as a copy or as a reference to an immutable stored copy. A hash may be kept alongside for fast comparison, but the retained text (or a reference that can reproduce it) is the requirement, so quotations stay verifiable. |
| `listing_version_metadata` | The listing's `content_hash`, `source_updated_at` and `last_verified_at` at assessment time. Informational only; none of these identifies the text version on its own (see timestamp semantics). |
| `method` | How the assessment was produced. Open question. |

### Evidence item fields

| Field | Requirement |
|---|---|
| `quotation` | Exact characters from the evidence source; not paraphrased, corrected or re-cased. |
| `evidence_type` | `job_description`, `source_location_label`, `official_application_page` or `official_employer_page`. |
| `evidence_url` | For listing text, the listing's `application_url` (`source_url` is the board list endpoint shared by every listing). Otherwise the exact page URL. |
| `location_in_source` | Character offsets in the examined text, or the heading the quotation sits under. |
| `subject` | What the statement is about: `applicant_location`, `hiring_countries`, `employment_location`, `work_authorization`, `relocation`, `visa_sponsorship`, `schedule`, `work_arrangement`, `pay`, `context`. |
| `statement_scope` | The statement's own scope, as written: `role`, `company`, `team`, `market_or_customer`, or `unclear`. Never rewritten. |
| `role_applicability` | Whether the statement governs this role: `direct` (the statement is about this role), `established_by_wording`, `established_by_official_source`, `unclear`, or `not_applicable`. Recorded separately from `statement_scope`. |
| `stance` | For geographic evidence: `permits_kenya`, `excludes_kenya` or `context_only`. Compatibility evidence uses the item states instead. |
| `region_fact_used` | The fixed geographic fact applied, if any. |
| `text_timestamps` | For listing text: see timestamp semantics. For external pages: `retrieved_at` (when JobPilot fetched that page) and any update date the page states. |

## Evidence handling

1. **The source text stays intact.** Eligibility work never edits, annotates
   or truncates `job_listings` facts.
2. **Three separate layers.** Source facts, extracted evidence (quotations
   with provenance) and assessments (conclusions) are stored separately;
   nothing writes back into source facts.
3. **Quotations are verifiable.** A listing-text quotation must be an exact
   substring of the assessment's `examined_text`. A quotation that fails this
   check is invalid; an outcome depending on it
   falls back to `eligibility_unknown` (or `unresolved` for a compatibility
   item).
4. **No new source contact without approval.** Evidence from official
   application or employer pages requires fetching them. JobPilot does not do
   this today; adding it is a separate source decision.

### Timestamp semantics (current architecture)

| Timestamp | What it does mean | What it does not mean |
|---|---|---|
| `first_seen_at` | Start of the discovery run that first stored the listing. | Posting time; text retrieval time of later versions. |
| `last_verified_at` | Start of the most recent successful run that either saw the listing (and found the stored facts identical or updated them) or newly marked it `missing_from_source`. It is recorded at run start, before the fetch completes. | The moment the evidence text was retrieved, the time it last changed, or that the listing is still active (missing listings also receive it). |
| `source_updated_at` | The source's own `updated_at` as of the most recent successful run that saw the listing (any change to it updates the row, because it is part of `content_hash`). | That eligibility wording changed; Greenhouse may advance it for unrelated edits. |
| `content_hash` | Some stored fact changed, possibly only `posted_at` or `source_updated_at`. | That the description or location wording changed. |
| `job_listings.updated_at` | The row was written. | Anything about the source; it changes on every run that refreshes `last_seen_at`. |

Consequences:

- For listing text, JobPilot can state **when the assessment examined it**
  (`assessed_at`). The listing's `last_verified_at` shows when a discovery run
  last confirmed the listing as a whole; it is **not** the retrieval time of
  any individual piece of evidence text and is never recorded as one.
- JobPilot cannot state when the text was first retrieved in its current form
  or when it last changed; that would need a new field (see future
  requirements).

### Evidence currency

**Relevant text.** For listing evidence, the relevant text is the listing's
stored `description_text` and `location_text`. Eligibility wording is
considered **changed** when either differs, character for character, from the
assessment's `examined_text` (a value becoming null, or a null becoming text,
is a change). No normalization is applied: any difference in the retained
description or location text, including a whitespace-only difference, is a
change that makes the assessment `stale` and requires reassessment.

**The listing hash is a trigger, not a verdict.** The current `content_hash`
covers timestamps (`posted_at`, `source_updated_at`) as well as text fields.
A changed `content_hash` therefore requires verification (comparing the
relevant text with `examined_text`) but does not by itself make the
assessment stale.

Each assessment is in exactly one currency state:

| State | When | Effect |
|---|---|---|
| `current` | The assessment's listing identity matches the listing, its `examined_text` is available, the listing's current relevant text equals it, and no external evidence the outcome depends on is past its maximum age. | Outcome and items shown as current. If `source_updated_at` advanced since assessment, the UI notes "source updated since assessment; eligibility wording unchanged". |
| `stale` | The comparison ran and the relevant text differs (wording changed), or external evidence the outcome depends on is past its maximum age. | Reassessment required. The previous outcome is kept as history; the effective geographic outcome is `eligibility_unknown`, reason "eligibility evidence changed; reassessment needed". |
| `unverifiable` | JobPilot cannot verify that the evidence corresponds to the current relevant text: no `examined_text` was retained (or its reference no longer resolves), only a hash with an unrecorded method was kept, the listing identity does not match, or the listing's current text cannot be read. | Effective geographic outcome `eligibility_unknown` until reassessment, reason "cannot confirm eligibility evidence is current". The previous outcome is shown only as history. Never silently treated as current. |

Timestamp-only changes:

- **`source_updated_at` changes** (and therefore `content_hash` changes) while
  the relevant description and location text are identical to
  `examined_text`: the hash change triggers the text comparison, the text
  matches, and the evidence stays `current`.
- **`posted_at` changes** (and therefore `content_hash` changes) while the
  relevant text is identical: the evidence stays `current`. Posting recency is
  assessed separately under the posting recency rules; a changed posting date
  never affects evidence currency, and current evidence never affects
  recency.
- **`last_verified_at` changes alone** (no change to `content_hash`): this
  does not by itself require re-checking the assessed text and never makes
  the evidence `stale`.

External-page evidence:

- Carries its own `retrieved_at` (when JobPilot fetched that page).
- Cannot independently support `eligible_confirmed` or `not_eligible` until an
  explicit maximum-age policy exists, and only while within that age. Until
  then it may be recorded, and may be shown alongside listing evidence that
  decides the outcome on its own, but it cannot be the deciding evidence or
  resolve a compatibility item.

### Vacancy status is separate

A listing marked `missing_from_source` is **no longer listed**. This is
neither stale evidence nor a posting-recency result. Its last assessment is
kept unchanged as history, the UI shows "No longer listed by the source" first,
the listing is never presented as actionable, and it is not reassessed. If the
listing reappears in a later successful run, its currency is checked as
normal.

## Posting recency

Posting recency answers "was this vacancy first posted recently?" and nothing
else. It is independent of eligibility, compatibility, evidence currency and
vacancy status (see the distinction under
[Purpose and scope](#purpose-and-scope)).

The only recency policy defined here is the 24-hour window below. "Recent"
means within that window; "not recent" means outside it. No other age bands
(for example "old" or "this week") are defined; whether any are needed is an
open question.

- **Timestamp used:** `posted_at` only, which the Greenhouse adapter sets from
  `first_published` when present and timezone-qualified.
- **Timezone:** comparisons use UTC instants. Display may convert to Kenya time
  (UTC+3, no daylight saving).
- **"Posted within the last 24 hours":** `now_utc − 24h <= posted_at <=
  now_utc`. The lower bound matches the current `posted_within_hours` filter.
- **Recency unknown:** if `posted_at` is null, recency is unknown and the
  listing is excluded from the 24-hour view. No date is guessed.
- **Not posting dates:** `first_seen_at` (import), `last_verified_at`
  (verification) and `source_updated_at` (source edit) never stand in for
  `posted_at`. A newly imported listing is not necessarily newly posted; a
  recently updated listing is not necessarily a new vacancy.
- **Unreliable timestamps:** a `posted_at` later than `now_utc`, or later than
  `source_updated_at`, makes recency unknown. The current API filter does not
  exclude future timestamps; this is a known gap, not changed here.
- **Reliability caveat:** Greenhouse documents `updated_at` but not
  `first_published` for the list endpoint. Reposted vacancies may carry a new
  `first_published`; JobPilot cannot distinguish a repost from a new vacancy.

## Communicating results in the UI

The UI shows the results side by side and never combines them into an overall
"suitable", "match" or "ineligible" label.

| Result | Example wording |
|---|---|
| Geographic `eligible_confirmed` | "Employer states it accepts applicants from Kenya" with the quotation. |
| Geographic `not_eligible` | "Employer states it does not accept applicants based in Kenya" with the quotation. Never "You are not eligible". |
| Geographic `eligibility_unknown` | "Kenya eligibility not established" with what was missing or conflicting. Never "Not eligible". |
| Compatibility items `unresolved` | "Needs your input" or "Unclear in the posting", one line per item (for example "Requires US work authorization; your status is not recorded", "Relocation offered; not stated whether it covers applicants from Kenya"). |
| Compatibility, no items | "No candidate-specific requirements found in the posting", not "Compatible". |
| Evidence `stale` or `unverifiable` | "Eligibility evidence changed or could not be confirmed; reassessment needed". The geographic result shown is "Kenya eligibility not established"; the previous outcome appears only as labelled history, never as a current result, even when the posting is recent. |
| Posting recency | "Posted in the last 24 hours", the posting date, or "Posting date not stated by the source". |
| Vacancy status | "No longer listed by the source" shown before everything else. |

A geographically confirmed listing with unresolved compatibility items must
show both, so the candidate sees that Kenya is accepted **and** what still
needs their input.

## Potential future data-model requirements (not implemented)

No migration or schema change is proposed here. A future design would likely
need:

- an evidence table (quotation, provenance, subject, statement scope, role
  applicability), linked to a listing and independent of any assessment;
- a per-profile assessment table holding the geographic outcome, the
  compatibility items, the listing identity, the retained `examined_text` (or
  a reference to an immutable copy, optionally with a hash whose method is
  recorded) and the listing version metadata at assessment time;
- a per-listing field recording when the description or location wording last
  changed, if "text changed at" is ever needed;
- candidate-confirmed fields for country of residence, work authorizations,
  willingness to relocate (and to where), and work-arrangement and schedule
  preferences;
- a widened API eligibility contract carrying the separate results, replacing
  the current `Literal["unknown"]`.

## Open questions

1. **Assessment method.** Manual review, deterministic rules over
   operator-selected passages, or a model proposing passages for confirmation.
   Keyword hits may only propose passages.
2. **Candidate base.** The spec assumes a Kenya-based candidate.
   `CandidateProfile.location` is free text. Should the jurisdiction be a fixed
   setting or a confirmed profile field?
3. **Candidate-confirmed data.** How to record work authorizations, willingness
   to relocate and preferences, and how the candidate confirms them.
4. **Application-page and employer-page evidence.** Whether to fetch them at
   all, and under which terms.
5. **Maximum age for external evidence**, and whether reassessment is manual or
   scheduled.
6. **Examined-text set and storage.** Whether `examined_text` covers only
   `description_text` and `location_text` or also the title and other fields an
   assessment might cite, and whether to store full copies or references to
   immutable versions. (Comparison is settled: character for character, with
   any difference, including whitespace, making evidence `stale`.)
7. **Applicability judgements.** Who confirms that a hiring policy's wording
   is categorical enough for `established_by_wording`, and whether borderline
   wording (for example "at this time") needs operator review.
8. **Per-listing vs per-profile storage.** Geographic outcomes depend only on
   the listing; compatibility depends on the candidate. Whether to store the
   geographic layer once per listing or per profile.
9. **Further recency bands.** Whether any posting-age categories beyond the
   24-hour window are needed, and with which thresholds. None is defined.
