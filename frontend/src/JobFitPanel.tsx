import { useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import type { EligibilityStatus, FitItem, JobFit } from "./api/types";

const GEOGRAPHIC_LABELS: Record<EligibilityStatus, string> = {
  eligible_confirmed: "Kenya applicants accepted",
  not_eligible: "Kenya-based applicants excluded",
  eligibility_unknown: "Kenya eligibility not established",
};

function FitList({ title, items, empty }: { title: string; items: FitItem[]; empty?: string }) {
  if (items.length === 0 && !empty) return null;
  return <section aria-label={title} className="fit-list">
    <h3>{title} <span className="count-pill">{items.length}</span></h3>
    {items.length === 0 ? <p className="muted">{empty}</p> : <ul>{items.map((item, index) => <li key={`${item.requirement}-${index}`}>
      <strong>{item.requirement}</strong> <span className="muted">{item.explanation}</span>
      {item.quotation && <blockquote>{item.quotation}</blockquote>}
      {item.sources.length > 0 && <p className="fit-sources">From: {item.sources.map((source) => source.label).join("; ")}</p>}
    </li>)}</ul>}
  </section>;
}

export function JobFitPanel({ profileId, jobId, refreshKey }: { profileId: string; jobId: string; refreshKey: unknown }) {
  const [fit, setFit] = useState<JobFit | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    setFit(null);
    setError("");
    api.getJobFit(profileId, jobId)
      .then((value) => { if (current) setFit(value); })
      .catch((caught: unknown) => { if (current) setError(caught instanceof ApiError || caught instanceof Error ? caught.message : "Job fit could not be checked."); });
    return () => { current = false; };
  }, [profileId, jobId, refreshKey]);

  if (error) return <p className="feedback-error setup-error" role="alert">{error}</p>;
  if (!fit) return <p className="muted" role="status">Checking job fit…</p>;
  const geo = fit.geographic_eligibility;
  return <section aria-label="Job fit" className="panel job-fit">
    <div className="section-title"><div><p className="eyebrow">Before you apply</p><h2>Eligibility and fit</h2></div></div>
    <p className={`fit-headline fit-${fit.verdict}`}>{fit.headline}</p>
    <div className="fit-columns">
      <section aria-label="Kenya eligibility" className="fit-block">
        <h3>Kenya eligibility</h3>
        <span className={`status-pill eligibility-${geo.status === "eligible_confirmed" ? "confirmed" : geo.status === "not_eligible" ? "excluded" : "unknown"}`}>{GEOGRAPHIC_LABELS[geo.status]}</span>
        <p className="muted">{geo.reason}{geo.currency === "stale" ? " Review the listing again on the Discovered jobs page." : ""}</p>
        {geo.quotation && <blockquote>{geo.quotation}</blockquote>}
        {geo.assessed_at && <p className="fit-sources">From your eligibility review of {new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(geo.assessed_at))}</p>}
      </section>
      <section aria-label="Skills coverage" className="fit-block">
        <h3>Skills coverage</h3>
        {fit.coverage.total > 0 && <p className="fit-coverage">{fit.coverage.met} of {fit.coverage.total}</p>}
        <p className="muted">{fit.coverage.summary}</p>
      </section>
    </div>
    {!fit.candidate_details_confirmed && <p className="inline-note">You have not confirmed your work eligibility details on your profile, so location and authorization requirements cannot be compared.</p>}
    <FitList items={fit.disqualifiers} title="Potential disqualifiers" />
    <FitList empty="None of the stated requirements are supported yet." items={[...fit.matched, ...fit.location_requirements_met]} title="Requirements you meet" />
    <FitList items={fit.missing} title="Not found in your information" />
    <FitList items={fit.uncertain} title="Uncertain: check these yourself" />
    <FitList items={fit.preferences} title="Your preferences" />
  </section>;
}
