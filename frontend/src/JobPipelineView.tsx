import { useEffect, useState, type FormEvent } from "react";

import { api, ApiError } from "./api/client";
import type { JobPipeline, KenyaDecision, KenyaState, PipelineCard, PipelineQueue, PreparedApplication, RoleGroup, RoleMatch } from "./api/types";

// Posting-date windows count only listings whose source states a posting date.
export type Window = "all" | "24" | "72" | "168" | "336" | "720";
export const WINDOW_OPTIONS: Array<[Window, string]> = [
  ["all", "All stored listings (dated and undated)"],
  ["24", "Posted in the last 24 hours (source-dated only)"],
  ["72", "Posted in the last 3 days (source-dated only)"],
  ["168", "Posted in the last 7 days (source-dated only)"],
  ["336", "Posted in the last 14 days (source-dated only)"],
  ["720", "Posted in the last 30 days (source-dated only)"],
];
export const ROLE_GROUP_LABELS: Record<RoleGroup, string> = {
  support_it: "Technical and IT support",
  customer_support: "Customer support and service",
  ecommerce_support: "E-commerce and marketplace support",
  operations_support: "Related support operations",
};

// Several role groups at once; none selected means every role. Leadership, sales,
// software development and DevOps/SRE titles never match any group.
export function RoleGroupPicker({ selected, onChange }: { selected: RoleGroup[]; onChange: (groups: RoleGroup[]) => void }) {
  return <fieldset className="role-groups">
    <legend>Role groups</legend>
    {(Object.keys(ROLE_GROUP_LABELS) as RoleGroup[]).map((group) => <label className="confirm-check" key={group}>
      <input checked={selected.includes(group)} onChange={(event) => onChange(event.target.checked ? [...selected, group] : selected.filter((item) => item !== group))} type="checkbox" /> {ROLE_GROUP_LABELS[group]}
    </label>)}
  </fieldset>;
}

const QUEUE_LABELS: Record<PipelineQueue, string> = {
  auto_apply: "Auto-apply eligible",
  needs_action: "Needs your action",
  review_needed: "Review needed",
  not_eligible: "Not eligible",
};
const QUEUE_HELP: Record<PipelineQueue, string> = {
  auto_apply: "Kenya-qualified jobs JobPilot could submit through an official channel once you approve.",
  needs_action: "Kenya-qualified jobs that need you: JobPilot prepares the application, you submit it, or you confirm a fact it cannot assume.",
  review_needed: "Kenya eligibility is not established, the wording conflicts, or the source is unverified. These are not Kenya-qualified.",
  not_eligible: "Excluded jobs, kept only so you can see why: the employer rules out Kenya-based applicants, or the vacancy is expired, duplicated, already tracked or unsafe.",
};
const EMPTY: Record<Exclude<PipelineQueue, "auto_apply">, string> = {
  needs_action: "No Kenya-qualified jobs need your action right now.",
  review_needed: "Nothing is waiting for an eligibility review.",
  not_eligible: "No jobs were excluded.",
};
export const KENYA_STATE_LABELS: Record<KenyaState, string> = {
  eligible: "Kenya-qualified",
  ineligible: "Not open to Kenya",
  unverified: "Kenya not established",
  needs_candidate_input: "Needs your confirmation",
};
const STATE_CLASS: Record<KenyaState, string> = {
  eligible: "eligibility-confirmed", ineligible: "eligibility-excluded", unverified: "eligibility-unknown", needs_candidate_input: "eligibility-unknown",
};

function formatDay(value: string | null) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value)) : null;
}

export function KenyaDecisionSummary({ decision }: { decision: KenyaDecision }) {
  const quote = decision.evidence[0];
  return <div className="kenya-decision">
    <p><span className={`status-pill ${STATE_CLASS[decision.state]}`}>{KENYA_STATE_LABELS[decision.state]}</span> {decision.explanation}</p>
    {quote && <blockquote>{quote.quotation}<span className="muted"> (from the listing's {quote.field})</span></blockquote>}
    {decision.conflicts.length > 0 && <p className="muted">Conflicting wording: {decision.conflicts.map((item) => `“${item.quotation.slice(0, 160)}”`).join("; ")}</p>}
    <p className="fit-sources">Source: {decision.source_url ? <a href={decision.source_url} rel="noopener noreferrer" target="_blank">{decision.source_type}</a> : decision.source_type}{decision.checked_at ? ` · text checked ${formatDay(decision.checked_at)}` : ""}</p>
  </div>;
}

// Why a job counts as a support role; separate from Kenya eligibility.
export function RoleMatchNote({ match }: { match: RoleMatch }) {
  return <p className="role-match"><span className="ats-basis">Role: {match.label}</span>{match.group_label && <span className="muted"> · {match.group_label}</span>} {match.reason}</p>;
}

function Card({ card, prepared, busy, onPrepare, onOpenCv, showRoleMatch = false }: {
  showRoleMatch?: boolean;
  card: PipelineCard;
  prepared: PreparedApplication | undefined;
  busy: boolean;
  onPrepare: (listingId: string) => void;
  onOpenCv: (jobId: string) => void;
}) {
  const canPrepare = (card.queue === "needs_action" || card.queue === "auto_apply") && card.eligibility.state === "eligible" && !card.application;
  return <article aria-label={`${card.title} at ${card.employer}`} className="job-card pipeline-card">
    <div className="job-card-title"><div><h3>{card.title}</h3><p>{card.employer} · {card.location || "Location not stated by source"}{card.workplace_type ? ` · ${card.workplace_type}` : ""}</p></div></div>
    <p className="muted">{card.posted_at ? `${card.source.category === "aggregator" ? "Published on a job board" : "Posted by the employer"} ${formatDay(card.posted_at)}` : "Undated: the source gives no posting date"} · Found by JobPilot {formatDay(card.first_seen_at)}{card.application_deadline ? ` · Deadline ${formatDay(card.application_deadline)}` : ""}</p>
    {showRoleMatch && card.role_match && <RoleMatchNote match={card.role_match} />}
    <KenyaDecisionSummary decision={card.eligibility} />
    {card.reasons.length > 0 && <ul className="pipeline-reasons">{card.reasons.map((reason) => <li key={reason.code}>{reason.message}</li>)}</ul>}
    <p className="pipeline-next"><strong>Next step:</strong> {card.next_step}</p>
    {card.fit && <div className="pipeline-fit">
      <p><strong>Match {card.fit.score ?? "–"} / 100</strong> · {card.fit.essential_met} of {card.fit.essential_total} essential requirements shown in your records. <span className="muted">{card.fit.headline}</span></p>
      {card.fit.missing_essential.length > 0 && <p className="muted">Not shown yet: {card.fit.missing_essential.join("; ")}</p>}
      {card.fit.missing_preferred.length > 0 && <p className="muted">Preferred, not shown: {card.fit.missing_preferred.join("; ")}</p>}
    </div>}
    {card.application && <p className="muted">Tracked in Applications · stage: {card.application.status.replace("_", " ")}</p>}
    {(card.queue === "needs_action" || card.queue === "auto_apply") && <details className="pipeline-method">
      <summary>How this application works</summary>
      <p>{card.application_method.reason}</p>
      <div className="ats-keywords">
        <div><h4>JobPilot prepares</h4><ul>{card.application_method.jobpilot_prepares.map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div><h4>You do</h4><ol>{card.application_method.candidate_steps.map((item) => <li key={item}>{item}</li>)}</ol></div>
      </div>
    </details>}
    <div className="listing-actions">
      {canPrepare && <button className="button button-primary" disabled={busy} onClick={() => onPrepare(card.listing_id)} type="button">Prepare application</button>}
      {(card.queue === "needs_action" || card.queue === "auto_apply") && card.application_url.startsWith("https://") && <a className="text-button" href={card.application_url} rel="noopener noreferrer" target="_blank">Official application page <span aria-hidden="true">↗</span></a>}
    </div>
    {prepared && <section aria-label="Prepared application" className="prepared-pack">
      <h4>Prepared, not submitted</h4>
      <ol>{prepared.steps.map((step) => <li key={step.step}><span className={`ats-check ats-check-${step.status === "done" ? "pass" : step.status === "blocked" ? "fail" : "warn"}`}>{step.status === "handed_to_you" ? "your turn" : step.status}</span> <strong>{step.step}.</strong> {step.detail}</li>)}</ol>
      <label className="field"><span>Cover letter draft (edit before use)</span><textarea readOnly rows={10} value={prepared.cover_letter.text} /></label>
      {prepared.cover_letter.notes.map((note) => <p className="muted" key={note}>{note}</p>)}
      <div className="listing-actions">
        <button className="button button-secondary" onClick={() => onOpenCv(prepared.job_description_id)} type="button">Review the tailored CV</button>
        <a className="button button-secondary" href={prepared.handoff.application_url} rel="noopener noreferrer" target="_blank">Open official application page</a>
      </div>
    </section>}
  </article>;
}

export function JobPipelineView({ profileId, busy, onPrepare, onOpenCv }: {
  profileId: string;
  busy: boolean;
  onPrepare: (listingId: string) => Promise<PreparedApplication | null>;
  onOpenCv: (jobId: string) => void;
}) {
  // All stored listings by default, like Discovered jobs; the 24-hour window is an explicit choice.
  const [window, setWindow] = useState<Window>("all");
  const [roleGroups, setRoleGroups] = useState<RoleGroup[]>([]);
  const [search, setSearch] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [pipeline, setPipeline] = useState<JobPipeline | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<PipelineQueue | null>(null);
  const [prepared, setPrepared] = useState<Record<string, PreparedApplication>>({});
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    setPipeline(null);
    setError("");
    api.getJobPipeline(profileId, { postedWithinHours: window === "all" ? undefined : Number(window), roleGroups, search: appliedSearch })
      .then((value) => {
        if (!current) return;
        setPipeline(value);
        setTab((selected) => selected ?? (["auto_apply", "needs_action", "review_needed", "not_eligible"] as PipelineQueue[]).find((name) => value.counts[name] > 0) ?? "needs_action");
      })
      .catch((caught: unknown) => { if (current) setError(caught instanceof ApiError || caught instanceof Error ? caught.message : "The job pipeline could not be loaded."); });
    return () => { current = false; };
    // roleGroups is compared by value through its joined form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, window, roleGroups.join(","), appliedSearch, reload]);

  async function prepare(listingId: string) {
    const pack = await onPrepare(listingId);
    if (pack) {
      setPrepared((existing) => ({ ...existing, [listingId]: pack }));
      setReload((value) => value + 1);
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAppliedSearch(search);
  }

  const selected = tab ?? "needs_action";
  return <div className="view-stack">
    <header className="page-heading"><p className="eyebrow">From discovery to application</p><h1>Job pipeline</h1><p>Every stored listing sorted for you: Kenya eligibility is decided from quoted evidence only, unsuitable jobs are set aside with the reason, and eligible jobs can be prepared in one step.</p></header>
    <section className="panel discovery-filters">
      <label className="field discovery-window"><span>Show</span><select value={window} onChange={(event) => setWindow(event.target.value as Window)}>{WINDOW_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <RoleGroupPicker selected={roleGroups} onChange={setRoleGroups} />
      <form className="discovery-search" onSubmit={submitSearch}><label className="field"><span>Search title or employer</span><input maxLength={200} placeholder="Comma-separated keywords" value={search} onChange={(event) => setSearch(event.target.value)} /></label><button className="button button-secondary" type="submit">Search</button></form>
    </section>
    {error ? <p className="feedback-error setup-error" role="alert">The job pipeline could not be loaded: {error}</p>
      : !pipeline ? <p className="muted" role="status">Sorting listings…</p>
        : <section className="panel">
          <div aria-label="Job pipeline queues" className="pipeline-tabs" role="tablist">
            {(Object.keys(QUEUE_LABELS) as PipelineQueue[]).map((name) => <button aria-controls={`queue-${name}`} aria-selected={selected === name} className={`pipeline-tab${selected === name ? " active" : ""}`} id={`tab-${name}`} key={name} onClick={() => setTab(name)} role="tab" type="button">{QUEUE_LABELS[name]} <span className="count-pill">{pipeline.counts[name]}</span></button>)}
          </div>
          <div aria-labelledby={`tab-${selected}`} id={`queue-${selected}`} role="tabpanel">
            <p className="inline-note">{QUEUE_HELP[selected]}</p>
            {pipeline.queues[selected].length === 0
              ? <div className="empty-state"><h3>{selected === "auto_apply" ? "No job can be submitted automatically" : "Nothing here"}</h3><p>{selected === "auto_apply" ? pipeline.automation.explanation : EMPTY[selected]}</p></div>
              : <div className="job-list">{pipeline.queues[selected].map((card) => <Card busy={busy} card={card} key={card.listing_id} onOpenCv={onOpenCv} onPrepare={(id) => void prepare(id)} prepared={prepared[card.listing_id]} showRoleMatch={roleGroups.length > 0} />)}</div>}
            {pipeline.counts[selected] > pipeline.queues[selected].length && <p className="muted">Showing the first {pipeline.queues[selected].length} of {pipeline.counts[selected]}.</p>}
          </div>
        </section>}
  </div>;
}
