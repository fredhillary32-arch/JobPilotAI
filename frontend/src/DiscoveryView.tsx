import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, ApiError, type JobListingFilters } from "./api/client";
import type {
  EligibilityAssessmentInput,
  EligibilityEvidence,
  EligibilityStatus,
  KenyaState,
  EvidenceField,
  GeographicScope,
  JobDescription,
  JobDiscoveryRun,
  JobListing,
  JobListingDetail,
  JobListingPage,
  JobSourceHealth,
  LinkCheck,
  DiscoveryRefresh,
  RoleApplicability,
  RoleGroup,
  SourceCategory,
  StatementScope,
} from "./api/types";
import { EmptyState, Field, PageHeading } from "./Views";
import { KenyaDecisionSummary, ROLE_GROUP_LABELS, RoleGroupPicker, RoleMatchNote, WINDOW_OPTIONS, type Window } from "./JobPipelineView";

const PAGE_SIZE = 50;
type Workplace = "" | "remote" | "hybrid" | "onsite";
type Sort = "posted" | "discovered" | "relevance";
// The strict decision: "eligible" returns only Kenya-qualified listings, never unverified ones.
type EligibilityFilter = "all" | KenyaState;

export type RecordEligibility = (listingId: string, payload: EligibilityAssessmentInput) => Promise<boolean>;

const ELIGIBILITY_LABELS: Record<EligibilityStatus, string> = {
  eligible_confirmed: "Kenya applicants accepted",
  not_eligible: "Kenya-based applicants excluded",
  eligibility_unknown: "Kenya eligibility not established",
};
const SCOPE_LABELS: Record<GeographicScope, string> = {
  kenya_named: "Kenya named as eligible",
  africa: "Any African country",
  emea: "Any EMEA country",
  worldwide: "Worldwide",
  other_countries: "Only other countries",
  restricted: "Restricted; Kenya excluded",
  conflicting: "Conflicting statements",
  unclear: "Unclear",
  awaiting_employer: "Awaiting employer confirmation",
};
const SCOPES_BY_OUTCOME: Record<EligibilityStatus, GeographicScope[]> = {
  eligible_confirmed: ["kenya_named", "africa", "emea", "worldwide"],
  not_eligible: ["restricted", "other_countries"],
  eligibility_unknown: ["unclear", "conflicting", "awaiting_employer"],
};
const STATEMENT_LABELS: Record<StatementScope, string> = {
  role: "This role",
  company: "The whole company",
  team: "The team or employees",
  market_or_customer: "Customers or markets",
  unclear: "Unclear",
};
const APPLICABILITY_LABELS: Record<RoleApplicability, string> = {
  direct: "It is about this role",
  established_by_wording: "A company policy whose wording covers this role",
  unclear: "Unclear whether it covers this role",
  not_applicable: "It does not govern hiring for this role",
};
const CATEGORY_LABELS: Record<SourceCategory, string> = {
  direct_employer: "Direct employer",
  staffing_agency: "Staffing agency",
  recruitment_outsourcing: "Recruitment or outsourcing firm",
  aggregator: "Aggregator",
};
const LINK_LABELS: Record<LinkCheck["outcome"], string> = {
  reachable: "Reachable on the source's own site",
  expired: "Expired or removed",
  auth_required: "Requires sign-in",
  redirected_off_domain: "Redirects to another site",
  unverified_domain: "Not on the source's verified domain",
  insecure: "Not secure (http)",
  rate_limited: "Not checked: site asked to slow down",
  broken: "Broken",
  unreachable: "Unreachable",
};
const PASSAGE_LABELS: Record<string, string> = {
  kenya_named: "Names Kenya",
  kenya_exclusion: "Excludes Kenya",
  worldwide_claim: "Worldwide wording",
  region: "Mentions a region",
  residency_restriction: "Residency restriction",
  work_authorization: "Work authorization",
  sponsorship: "Sponsorship",
  time_zone: "Time zone or hours",
  employment_model: "Employment model",
  location_label: "Location label",
};
const HEALTH_LABELS: Record<JobSourceHealth["health"], string> = {
  healthy: "Healthy",
  stale: "Stale",
  failing: "Failing",
  never_run: "Not run yet",
  manual_only: "Manual only",
  disabled: "Disabled",
};

// Source text is untrusted: only render outbound links to https URLs.
function safeHttpsUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

const window_ = globalThis.window;

export function DiscoveryView({
  busy,
  importedJobs,
  onOpenCv,
  onPrepareCv,
  onRecordEligibility,
}: {
  busy: boolean;
  importedJobs: JobDescription[];
  onOpenCv: (jobId: string) => void;
  onPrepareCv: (listingId: string) => Promise<boolean>;
  onRecordEligibility: RecordEligibility;
}) {
  // Show all active listings by default; users can narrow to recently posted jobs.
  const [window, setWindow] = useState<Window>("all");
  const [eligibilityFilter, setEligibilityFilter] = useState<EligibilityFilter>("all");
  const [scope, setScope] = useState<"" | "kenya_named" | "africa" | "emea" | "worldwide">("");
  const [category, setCategory] = useState<"" | SourceCategory>("");
  const [roleGroups, setRoleGroups] = useState<RoleGroup[]>([]);
  const [excludeGroup, setExcludeGroup] = useState<"" | RoleGroup>("");
  const [sourceId, setSourceId] = useState("");
  const [workplace, setWorkplace] = useState<Workplace>("");
  const [sort, setSort] = useState<Sort>("posted");
  const [paging, setPaging] = useState({ key: "", offset: 0 });
  const [refresh, setRefresh] = useState<DiscoveryRefresh | null>(null);
  const [refreshError, setRefreshError] = useState("");
  const polling = useRef<number | null>(null);
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [page, setPage] = useState<JobListingPage | null>(null);
  const [runs, setRuns] = useState<JobDiscoveryRun[]>([]);
  const [sources, setSources] = useState<JobSourceHealth[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const importedByListing = new Map(
    importedJobs.flatMap((job) => (job.source_job_listing_id ? [[job.source_job_listing_id, job.id] as const] : [])),
  );

  // Any filter change returns to the first page, without an extra request.
  const filterKey = JSON.stringify([window, eligibilityFilter, scope, category, roleGroups, excludeGroup, sourceId, workplace, sort, verifiedOnly, appliedSearch]);
  const offset = paging.key === filterKey ? paging.offset : 0;

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    const filters: JobListingFilters = {
      ...(window !== "all" && { postedWithinHours: Number(window) }),
      ...(eligibilityFilter !== "all" && { kenya: eligibilityFilter }),
      ...(scope && { eligibleScope: scope }),
      ...(category && { sourceCategory: category }),
      ...(roleGroups.length > 0 && { roleGroups }),
      ...(verifiedOnly && { verifiedLinksOnly: true }),
      ...(appliedSearch && { search: appliedSearch }),
      ...(excludeGroup && { excludeRoleGroups: [excludeGroup] }),
      ...(sourceId && { source: sourceId }),
      ...(workplace && { workplace }),
      ...(sort !== "posted" && { sort }),
      ...(offset > 0 && { offset }),
    };
    Promise.all([api.listJobListings(filters), api.listDiscoveryRuns()])
      .then(([listings, discoveryRuns]) => {
        if (!current) return;
        setPage(listings);
        setRuns(discoveryRuns);
      })
      .catch((caught: unknown) => {
        if (!current) return;
        setPage(null);
        setError(caught instanceof ApiError || caught instanceof Error ? caught.message : "Discovered jobs could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
    // filterKey covers every filter value used above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey, offset, reloadToken]);

  useEffect(() => {
    let current = true;
    api.listJobSources().then((list) => { if (current) setSources(list); }).catch(() => undefined);
    return () => { current = false; };
  }, [reloadToken]);

  // Follow a pass that is running (started here or elsewhere), then reload the results.
  function follow(state: DiscoveryRefresh) {
    setRefresh(state);
    if (polling.current !== null) window_.clearTimeout(polling.current);
    if (state.state !== "running") return;
    polling.current = window_.setTimeout(() => {
      api.getDiscoveryRefresh()
        .then((next) => {
          follow(next);
          if (next.state === "finished") setReloadToken((value) => value + 1);
        })
        .catch(() => setRefreshError("Lost track of the discovery pass; reload the page to see its results."));
    }, 2000);
  }

  useEffect(() => {
    api.getDiscoveryRefresh().then((state) => { if (state?.state === "running") follow(state); }).catch(() => undefined);
    return () => { if (polling.current !== null) window_.clearTimeout(polling.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startRefresh() {
    setRefreshError("");
    try {
      follow(await api.startDiscoveryRefresh());
    } catch (caught) {
      setRefreshError(caught instanceof ApiError && caught.status === 409 ? "A discovery pass is already running." : caught instanceof Error ? caught.message : "The refresh could not be started.");
    }
  }

  async function recordEligibility(listingId: string, payload: EligibilityAssessmentInput) {
    const recorded = await onRecordEligibility(listingId, payload);
    if (recorded) setReloadToken((value) => value + 1);
    return recorded;
  }

  const failedRuns = runs.filter((run) => run.status === "failed" || run.display_status === "interrupted");
  const automatic = sources.filter((source) => source.enabled).length;
  const enabledSources = sources.filter((source) => source.enabled);
  const running = refresh?.state === "running";
  const narrowed = roleGroups.length > 0 || Boolean(appliedSearch || sourceId || workplace || scope || category || excludeGroup) || verifiedOnly || eligibilityFilter !== "all";

  return <div className="view-stack">
    <PageHeading eyebrow="Job discovery" title="Discovered jobs" description="Listings stored from verified job sources. Facts are shown as the source stated them; nothing is inferred." />
    <section className="panel trust-banner"><span aria-hidden="true">!</span><p><strong>Kenya eligibility comes only from quoted evidence.</strong> A listing is Kenya-qualified only when the employer's own listing names Kenya or says the role can be done from anywhere, with no conflicting restriction, or when you recorded the exact sentence yourself. "Remote", regions such as EMEA, and company marketing are never treated as evidence.</p></section>
    {failedRuns.length > 0 && <section className="panel" aria-label="Failed discovery runs">
      <h2>Source problems</h2>
      <ul className="run-list">{failedRuns.slice(0, 5).map((run) => <li key={run.id} className="validation-error">{run.source_name || `${run.source_kind}:${run.source_key}`} {run.display_status === "interrupted" ? "was interrupted" : `failed (${run.error_category?.replaceAll("_", " ")})`} on {formatDateTime(run.started_at)}. Stored listings from this source were not changed.</li>)}</ul>
    </section>}
    <section className="panel" aria-label="Refresh job sources">
      <div className="section-title">
        <div><p className="eyebrow">Discovery</p><h2>Refresh job sources</h2></div>
        <button className="button button-primary" disabled={running} onClick={() => { void startRefresh(); }} type="button">{running ? "Refreshing…" : "Refresh all sources"}</button>
      </div>
      <p className="muted">Reads every enabled source's public feed in the background; you can keep browsing. Only public job data is fetched: nothing about you is sent to any source. Sources that ask for a gap between reads are skipped until it has passed.</p>
      {refreshError && <p className="feedback-error setup-error" role="alert">{refreshError}</p>}
      {refresh && refresh.state !== "idle" && <div role="status">
        <p>{running ? `Reading ${refresh.current ?? "sources"}… ${refresh.outcomes.length} of ${refresh.requested.length} done.` : `Finished: ${refresh.outcomes.filter((item) => item.status === "succeeded").length} of ${refresh.requested.length} sources read.`}</p>
        {refresh.outcomes.length > 0 && <ul className="run-list">{refresh.outcomes.map((outcome) => <li className={outcome.status === "failed" || outcome.status === "error" ? "validation-error" : undefined} key={outcome.source_id}><strong>{outcome.source_id}</strong>: {outcome.status === "skipped" ? `skipped, ${outcome.message}` : outcome.message}</li>)}</ul>}
      </div>}
    </section>
    <section className="panel">
      <div className="section-title">
        <div><p className="eyebrow">Stored listings</p><h2>Active listings</h2></div>
      </div>
      <div className="filter-row">
        <label className="field discovery-window"><span>Show</span><select value={window} onChange={(event) => setWindow(event.target.value as Window)}>{WINDOW_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="field discovery-window"><span>Kenya eligibility</span><select value={eligibilityFilter} onChange={(event) => setEligibilityFilter(event.target.value as EligibilityFilter)}><option value="all">Any (each listing is labelled)</option><option value="eligible">Kenya-qualified only</option><option value="needs_candidate_input">Needs your confirmation</option><option value="unverified">Not established (review queue)</option><option value="ineligible">Not open to Kenya</option></select></label>
        <label className="field discovery-window"><span>Accepted scope</span><select value={scope} onChange={(event) => setScope(event.target.value as typeof scope)}><option value="">Any reviewed scope</option><option value="kenya_named">Kenya named</option><option value="africa">Any African country</option><option value="emea">Any EMEA country</option><option value="worldwide">Worldwide</option></select></label>
        <label className="field discovery-window"><span>Source type</span><select value={category} onChange={(event) => setCategory(event.target.value as "" | SourceCategory)}><option value="">All source types</option>{(Object.keys(CATEGORY_LABELS) as SourceCategory[]).map((value) => <option key={value} value={value}>{CATEGORY_LABELS[value]}</option>)}</select></label>
        <label className="field discovery-window"><span>Source</span><select value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">All sources</option>{enabledSources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label>
        <label className="field discovery-window"><span>Work arrangement</span><select value={workplace} onChange={(event) => setWorkplace(event.target.value as Workplace)}><option value="">Any (as stated by source)</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option></select></label>
        <label className="field discovery-window"><span>Sort by</span><select value={sort} onChange={(event) => setSort(event.target.value as Sort)}><option value="posted">Posting date (undated last)</option><option value="discovered">Date found by JobPilot</option><option value="relevance">Role relevance</option></select></label>
      </div>
      <div className="filter-row">
        <RoleGroupPicker selected={roleGroups} onChange={setRoleGroups} />
        <label className="field discovery-window"><span>Hide role group</span><select value={excludeGroup} onChange={(event) => setExcludeGroup(event.target.value as "" | RoleGroup)}><option value="">None</option>{(Object.keys(ROLE_GROUP_LABELS) as RoleGroup[]).map((value) => <option key={value} value={value}>{ROLE_GROUP_LABELS[value]}</option>)}</select></label>
      </div>
      <form className="filter-row" onSubmit={(event) => { event.preventDefault(); setAppliedSearch(search); }} role="search">
        <label className="field discovery-window"><span>Search title or employer</span><input aria-describedby="keyword-hint" maxLength={200} value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <button className="button button-secondary" type="submit">Search</button>
        <span className="muted" id="keyword-hint">Separate keywords with commas; any one may match.</span>
        <label className="confirm-check"><input checked={verifiedOnly} onChange={(event) => setVerifiedOnly(event.target.checked)} type="checkbox" /> Verified application links only</label>
      </form>
      {loading ? <p className="muted" role="status">Loading discovered jobs…</p>
        : error ? <p className="feedback-error setup-error" role="alert">{error}</p>
        : !page || page.items.length === 0 ? <EmptyState title="No discovered jobs" text={window === "24" ? "No stored listing has a source-stated posting date in the last 24 hours. Listings without a posting date, or dated in the future, are never counted as fresh; choose \"All stored active listings\" to see them." : narrowed ? "No stored listing matches every filter you chose. Clear a filter to widen the search." : "No listings are stored yet. Use \"Refresh all sources\" to read the enabled job sources; no jobs are shown until a real source has been read."} />
        : <>
          <p className="muted">{page.total} listing{page.total === 1 ? "" : "s"}{page.total > page.items.length ? `, showing ${page.offset + 1}–${page.offset + page.items.length}` : ""}. Expired links and copies of the same vacancy from other sources are hidden.</p>
          <div className="job-list">{page.items.map((listing) => <ListingCard busy={busy} importedJobId={importedByListing.get(listing.id)} key={listing.id} listing={listing} onOpenCv={onOpenCv} onPrepareCv={onPrepareCv} onRecordEligibility={recordEligibility} showRoleMatch={roleGroups.length > 0 || sort === "relevance"} />)}</div>
          {page.total > PAGE_SIZE && <nav aria-label="Listing pages" className="row-actions">
            <button className="button button-secondary" disabled={offset === 0} onClick={() => setPaging({ key: filterKey, offset: Math.max(0, offset - PAGE_SIZE) })} type="button">Previous</button>
            <span className="muted">Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.ceil(page.total / PAGE_SIZE)}</span>
            <button className="button button-secondary" disabled={offset + PAGE_SIZE >= page.total} onClick={() => setPaging({ key: filterKey, offset: offset + PAGE_SIZE })} type="button">Next</button>
          </nav>}
        </>}
    </section>
    {sources.length > 0 && <details className="panel" aria-label="Job sources">
      <summary>Job sources: {automatic} automatic, {sources.length - automatic} manual or disabled</summary>
      <p className="muted">Employer sources run automatically only when their job board was found on the organisation's own careers page. Aggregators (job boards that collect listings from many employers) run on their documented public API terms; they help find jobs but never count as evidence of Kenya eligibility. Manual sources are never fetched; open their careers page yourself.</p>
      <ul className="source-list">{sources.map((source) => <li key={source.id}>
        <strong>{source.name}</strong> <span className="muted">{CATEGORY_LABELS[source.category]}</span> <span className={`status-pill health-${source.health}`}>{HEALTH_LABELS[source.health]}</span>
        {source.enabled && <span className="muted"> · {source.active_listings} active · last success {source.last_success_at ? formatDateTime(source.last_success_at) : "never"}{source.consecutive_failures ? ` · ${source.consecutive_failures} failure(s) in a row` : ""}</span>}
        <p className="fit-sources">{source.verification.evidence}</p>
        {safeHttpsUrl(source.careers_url) && <a className="text-button" href={safeHttpsUrl(source.careers_url)!} rel="noopener noreferrer" target="_blank">Official careers page <span aria-hidden="true">↗</span></a>}
      </li>)}</ul>
    </details>}
    {runs.length > 0 && <p className="inline-note">Last discovery run: {runs[0].source_name || `${runs[0].source_kind}:${runs[0].source_key}`}, {runs[0].display_status || runs[0].status} on {formatDateTime(runs[0].started_at)}.</p>}
  </div>;
}

function EligibilitySummary({ listing }: { listing: JobListing }) {
  const eligibility = listing.eligibility;
  if (eligibility.currency === "stale") {
    return <p className="eligibility-detail"><strong>Evidence changed: reassessment needed.</strong> The listing's wording changed after it was reviewed{eligibility.previous_status ? `; the earlier result (${ELIGIBILITY_LABELS[eligibility.previous_status]}) is no longer current` : ""}.</p>;
  }
  if (eligibility.currency === "not_assessed") return null;
  return <div className="eligibility-detail">
    {eligibility.geographic_scope && <p><strong>{SCOPE_LABELS[eligibility.geographic_scope]}</strong></p>}
    <p>{eligibility.explanation}</p>
    {eligibility.quotation && <blockquote>{eligibility.quotation}</blockquote>}
    {eligibility.assessed_at && <p className="muted">Reviewed {formatDateTime(eligibility.assessed_at)}{eligibility.statement_scope ? ` · About: ${STATEMENT_LABELS[eligibility.statement_scope].toLowerCase()}` : ""}</p>}
  </div>;
}

function LinkStatus({ label, check }: { label: string; check: LinkCheck | null }) {
  return <div><dt>{label}</dt><dd>{check ? `${LINK_LABELS[check.outcome]} (checked ${formatDateTime(check.checked_at)})` : "Not checked yet"}</dd></div>;
}

function ListingCard({
  busy,
  importedJobId,
  listing,
  onOpenCv,
  onPrepareCv,
  onRecordEligibility,
  showRoleMatch = false,
}: {
  busy: boolean;
  importedJobId: string | undefined;
  listing: JobListing;
  showRoleMatch?: boolean;
  onOpenCv: (jobId: string) => void;
  onPrepareCv: (listingId: string) => Promise<boolean>;
  onRecordEligibility: RecordEligibility;
}) {
  const pageUrl = safeHttpsUrl(listing.listing_url) || safeHttpsUrl(listing.application_url);
  const applyUrl = safeHttpsUrl(listing.application_url);
  const [reviewing, setReviewing] = useState(false);
  const status = listing.eligibility.status;
  const source = listing.source;
  return <article aria-label={listing.title} className="job-card">
    <div className="job-card-title"><div><h3>{listing.title}</h3><p>{listing.employer_name} · {listing.location_text || "Location not stated by source"}</p></div>{!listing.kenya_eligibility && <span className={`status-pill eligibility-${status === "eligibility_unknown" ? "unknown" : status === "eligible_confirmed" ? "confirmed" : "excluded"}`} title={listing.eligibility.reason}>{ELIGIBILITY_LABELS[status]}</span>}</div>
    {!listing.posted_at && <p><span className="status-pill eligibility-unknown">Undated</span> <span className="muted">The source gives no posting date, so this listing is never shown as fresh.</span></p>}
    <p className="muted">Source: {source.registered ? `${source.name} (${source.category ? CATEGORY_LABELS[source.category] : "category not recorded"}; ${source.category === "aggregator" ? "job-board aggregator, not the employer" : "registry-verified board"})` : `${listing.source_kind}:${listing.source_key} (not in the verified source registry)`}{listing.vacancy_status === "link_expired" ? " · Link expired at the source" : listing.vacancy_status === "no_longer_listed" ? " · No longer listed by the source" : ""}</p>
    {showRoleMatch && listing.role_match && <RoleMatchNote match={listing.role_match} />}
    {listing.kenya_eligibility && <KenyaDecisionSummary decision={listing.kenya_eligibility} />}
    <EligibilitySummary listing={listing} />
    <dl className="listing-facts">
      <div><dt>{listing.posted_at_source === "job_board" ? "Published on job board" : "Posted"}</dt><dd>{listing.posted_at ? `${formatDateTime(listing.posted_at)}${listing.posted_at_source === "job_board" ? " (the job board's date, not necessarily the employer's)" : ""}` : "Posting date not provided by source"}</dd></div>
      <div><dt>First seen by JobPilot</dt><dd>{formatDateTime(listing.first_seen_at)}</dd></div>
      {listing.relisted_at && <div><dt>Relisted</dt><dd>{formatDateTime(listing.relisted_at)} (the source had dropped it; not a new posting date)</dd></div>}
      <div><dt>Last verified at source</dt><dd>{formatDateTime(listing.last_verified_at)}</dd></div>
      <div><dt>Work arrangement</dt><dd>{listing.stated_workplace_type ? `${listing.stated_workplace_type} (stated by source)` : "Not stated"}</dd></div>
      <div><dt>Deadline</dt><dd>{listing.application_deadline || "Not stated"}</dd></div>
      <LinkStatus check={listing.links.listing} label="Vacancy page" />
      <LinkStatus check={listing.links.application} label="Application link" />
    </dl>
    {listing.duplicate_group_size > 1 && <p className="inline-note">Also listed by {listing.duplicate_group_size - 1} other source{listing.duplicate_group_size > 2 ? "s" : ""}; this is the preferred original.</p>}
    <div className="row-actions">
      {importedJobId
        ? <button className="button button-secondary" disabled={busy} onClick={() => onOpenCv(importedJobId)} type="button">Open in Tailored CVs</button>
        : listing.source_status === "active" && <button className="button button-primary" disabled={busy} onClick={() => { void onPrepareCv(listing.id); }} type="button">Prepare tailored CV</button>}
      {listing.source_status === "active" && <button aria-expanded={reviewing} className="button button-secondary" onClick={() => setReviewing((value) => !value)} type="button">{reviewing ? "Close eligibility review" : "Review Kenya eligibility"}</button>}
      {pageUrl ? <a className="text-button" href={pageUrl} rel="noopener noreferrer" target="_blank">Open original listing <span aria-hidden="true">↗</span></a> : <p className="muted">The source did not provide a secure listing link.</p>}
      {applyUrl && listing.listing_url && applyUrl !== pageUrl && <a className="text-button" href={applyUrl} rel="noopener noreferrer" target="_blank">Application page <span aria-hidden="true">↗</span></a>}
    </div>
    {reviewing && <EligibilityReviewForm busy={busy} listing={listing} onDone={() => setReviewing(false)} onRecord={onRecordEligibility} />}
  </article>;
}

function EligibilityReviewForm({
  busy,
  listing,
  onDone,
  onRecord,
}: {
  busy: boolean;
  listing: JobListing;
  onDone: () => void;
  onRecord: RecordEligibility;
}) {
  const [detail, setDetail] = useState<JobListingDetail | null>(null);
  const [evidence, setEvidence] = useState<EligibilityEvidence | null>(null);
  const [loadError, setLoadError] = useState("");
  const [outcome, setOutcome] = useState<EligibilityStatus>("eligibility_unknown");
  const [geographicScope, setGeographicScope] = useState<GeographicScope>("unclear");
  const [quotation, setQuotation] = useState("");
  const [evidenceField, setEvidenceField] = useState<EvidenceField>("description");
  const [scope, setScope] = useState<StatementScope>("role");
  const [applicability, setApplicability] = useState<RoleApplicability>("direct");
  const [explanation, setExplanation] = useState("");
  const definite = outcome !== "eligibility_unknown";

  useEffect(() => {
    let current = true;
    Promise.all([api.getJobListing(listing.id), api.getEligibilityEvidence(listing.id)])
      .then(([value, passages]) => { if (current) { setDetail(value); setEvidence(passages); } })
      .catch((caught: unknown) => { if (current) setLoadError(caught instanceof Error ? caught.message : "The listing text could not be loaded."); });
    return () => { current = false; };
  }, [listing.id]);

  function chooseOutcome(value: EligibilityStatus) {
    setOutcome(value);
    setGeographicScope(SCOPES_BY_OUTCOME[value][0]);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // The quotation is sent exactly as typed or pasted; the server checks it
    // against the stored listing text character for character.
    const payload: EligibilityAssessmentInput = {
      outcome,
      explanation,
      geographic_scope: geographicScope,
      ...(quotation && { quotation, evidence_field: evidenceField }),
      ...(definite && { statement_scope: scope, role_applicability: applicability }),
    };
    if (await onRecord(listing.id, payload)) onDone();
  }

  return <form aria-label={`Kenya eligibility review for ${listing.title}`} className="eligibility-review" onSubmit={submit}>
    <p className="inline-note">Copy the exact sentence that states whether applicants based in Kenya can apply. Do not rely on "remote", a location label, office locations or a list of where the role is based; choose "not established" when the listing does not say.</p>
    {evidence?.conflicts.map((conflict) => <p className="feedback-error setup-error" key={conflict} role="alert">{conflict} It cannot be recorded as accepting Kenya-based applicants.</p>)}
    {evidence && evidence.passages.filter((passage) => passage.kind !== "location_label").length > 0 && <section aria-label="Passages to review" className="fit-list">
      <h3>Passages to review</h3>
      <p className="muted">Found by wording only; read each in context. This is not a decision.</p>
      <ul>{evidence.passages.filter((passage) => passage.kind !== "location_label").map((passage, index) => <li key={`${passage.kind}-${index}`}><strong>{PASSAGE_LABELS[passage.kind] || passage.kind}</strong><blockquote>{passage.sentence}</blockquote></li>)}</ul>
    </section>}
    {loadError ? <p className="feedback-error setup-error" role="alert">{loadError}</p>
      : !detail ? <p className="muted" role="status">Loading the listing text…</p>
      : <details open><summary>Listing text as stored</summary><p className="muted">Location: {detail.location_text || "Not stated"}</p><pre className="source-text source-text-compact">{detail.description_text || "The source provided no description."}</pre></details>}
    <div className="form-grid">
      <Field label="Result"><select value={outcome} onChange={(event) => chooseOutcome(event.target.value as EligibilityStatus)}><option value="eligibility_unknown">{ELIGIBILITY_LABELS.eligibility_unknown}</option><option value="eligible_confirmed">{ELIGIBILITY_LABELS.eligible_confirmed}</option><option value="not_eligible">{ELIGIBILITY_LABELS.not_eligible}</option></select></Field>
      <Field label="What the wording establishes"><select value={geographicScope} onChange={(event) => setGeographicScope(event.target.value as GeographicScope)}>{SCOPES_BY_OUTCOME[outcome].map((value) => <option key={value} value={value}>{SCOPE_LABELS[value]}</option>)}</select></Field>
      <Field label="Quotation comes from"><select value={evidenceField} onChange={(event) => setEvidenceField(event.target.value as EvidenceField)}><option value="description">The description</option><option value="location">The location label</option></select></Field>
      <Field className="full-span" label="Exact quotation" required={definite} hint={definite ? "Required: paste the sentence exactly as it appears." : "Optional when the result is not established."}><textarea maxLength={5000} required={definite} rows={2} value={quotation} onChange={(event) => setQuotation(event.target.value)} /></Field>
      {definite && <>
        <Field label="The statement is about"><select value={scope} onChange={(event) => setScope(event.target.value as StatementScope)}>{(Object.keys(STATEMENT_LABELS) as StatementScope[]).map((value) => <option key={value} value={value}>{STATEMENT_LABELS[value]}</option>)}</select></Field>
        <Field label="Does it govern hiring for this role?"><select value={applicability} onChange={(event) => setApplicability(event.target.value as RoleApplicability)}>{(Object.keys(APPLICABILITY_LABELS) as RoleApplicability[]).map((value) => <option key={value} value={value}>{APPLICABILITY_LABELS[value]}</option>)}</select></Field>
      </>}
      <Field className="full-span" label="Explanation" required><textarea maxLength={2000} required rows={2} value={explanation} onChange={(event) => setExplanation(event.target.value)} /></Field>
    </div>
    <div className="form-footer"><span className="muted">Each review is kept; if the listing's wording changes later, this result stops counting.</span><button className="button button-primary" disabled={busy || !explanation.trim()} type="submit">Record review</button></div>
  </form>;
}
