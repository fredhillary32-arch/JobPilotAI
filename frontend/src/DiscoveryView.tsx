import { useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import type { JobDiscoveryRun, JobListing, JobListingPage } from "./api/types";
import { EmptyState, PageHeading } from "./Views";

type Window = "all" | "24";

// Source text is untrusted: only render outbound links to https URLs.
function safeHttpsUrl(value: string): string | null {
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

export function DiscoveryView() {
  const [window, setWindow] = useState<Window>("all");
  const [page, setPage] = useState<JobListingPage | null>(null);
  const [runs, setRuns] = useState<JobDiscoveryRun[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    Promise.all([
      api.listJobListings(window === "24" ? { postedWithinHours: 24 } : {}),
      api.listDiscoveryRuns(),
    ])
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
  }, [window]);

  const failedRuns = runs.filter((run) => run.status === "failed");

  return <div className="view-stack">
    <PageHeading eyebrow="Job discovery" title="Discovered jobs" description="Listings stored from job sources you have run. Facts are shown as the source stated them; nothing is inferred." />
    <section className="panel trust-banner"><span aria-hidden="true">!</span><p><strong>Eligibility has not been checked.</strong> Every listing shows "Eligibility unknown" until Kenya eligibility checks are implemented. A listing that says "remote" is not evidence that Kenyan applicants are accepted.</p></section>
    {failedRuns.length > 0 && <section className="panel" aria-label="Failed discovery runs">
      <h2>Source problems</h2>
      <ul className="run-list">{failedRuns.slice(0, 5).map((run) => <li key={run.id} className="validation-error">{run.source_kind}:{run.source_key} failed ({run.error_category?.replaceAll("_", " ")}) on {formatDateTime(run.started_at)}. Stored listings from this source were not changed.</li>)}</ul>
    </section>}
    <section className="panel">
      <div className="section-title">
        <div><p className="eyebrow">Stored listings</p><h2>Active listings</h2></div>
        <label className="field discovery-window"><span>Show</span><select value={window} onChange={(event) => setWindow(event.target.value as Window)}><option value="all">All active listings</option><option value="24">Posted in the last 24 hours (source-dated only)</option></select></label>
      </div>
      {loading ? <p className="muted" role="status">Loading discovered jobs…</p>
        : error ? <p className="feedback-error setup-error" role="alert">{error}</p>
        : !page || page.items.length === 0 ? <EmptyState title="No discovered jobs" text={window === "24" ? "No stored listing has a source-stated posting date in the last 24 hours." : "Run a job source from the command line to store listings. No jobs are shown until a real source has been read."} />
        : <>
          <p className="muted">{page.total} listing{page.total === 1 ? "" : "s"}{page.total > page.items.length ? `, showing the first ${page.items.length}` : ""}.</p>
          <div className="job-list">{page.items.map((listing) => <ListingCard key={listing.id} listing={listing} />)}</div>
        </>}
    </section>
    {runs.length > 0 && <p className="inline-note">Last discovery run: {runs[0].source_kind}:{runs[0].source_key}, {runs[0].status} on {formatDateTime(runs[0].started_at)}.</p>}
  </div>;
}

function ListingCard({ listing }: { listing: JobListing }) {
  const applyUrl = safeHttpsUrl(listing.application_url);
  return <article className="job-card">
    <div className="job-card-title"><div><h3>{listing.title}</h3><p>{listing.employer_name} · {listing.location_text || "Location not stated by source"}</p></div><span className="status-pill eligibility-unknown" title={listing.eligibility.reason}>Eligibility unknown</span></div>
    <dl className="listing-facts">
      <div><dt>Posted</dt><dd>{listing.posted_at ? formatDateTime(listing.posted_at) : "Posting date not provided by source"}</dd></div>
      <div><dt>First seen by JobPilot</dt><dd>{formatDateTime(listing.first_seen_at)}</dd></div>
      <div><dt>Last verified at source</dt><dd>{formatDateTime(listing.last_verified_at)}</dd></div>
      <div><dt>Deadline</dt><dd>{listing.application_deadline || "Not stated"}</dd></div>
      <div><dt>Source</dt><dd>{listing.source_kind}:{listing.source_key}</dd></div>
    </dl>
    {applyUrl ? <a className="text-button" href={applyUrl} rel="noopener noreferrer" target="_blank">Open original listing <span aria-hidden="true">↗</span></a> : <p className="muted">The source did not provide a secure listing link.</p>}
  </article>;
}
