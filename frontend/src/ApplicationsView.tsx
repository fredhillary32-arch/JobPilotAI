import { type FormEvent, useState } from "react";

import type {
  ApplicationStatus,
  CvDraft,
  JobApplication,
  JobApplicationDetails,
  JobDescription,
  WorkspaceData,
} from "./api/types";
import { APPLICATION_STATUS_LABELS, localToday } from "./applicationStatus";
import { EmptyState, Field, PageHeading } from "./Views";

const STATUS_ORDER = Object.keys(APPLICATION_STATUS_LABELS) as ApplicationStatus[];
const STARTING_STATUSES: ApplicationStatus[] = ["saved", "eligibility_review", "preparing", "ready_for_review", "applied"];

export type CreateApplication = (payload: { job_description_id: string; status: ApplicationStatus; applied_on?: string }) => Promise<boolean>;
export type UpdateApplication = (applicationId: string, payload: JobApplicationDetails) => Promise<boolean>;
export type ChangeApplicationStatus = (applicationId: string, payload: { status: ApplicationStatus; applied_on?: string; note?: string }) => Promise<boolean>;

function formatDay(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
}

function formatMoment(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function ApplicationsView({
  data,
  busy,
  onCreate,
  onUpdate,
  onChangeStatus,
}: {
  data: WorkspaceData;
  busy: boolean;
  onCreate: CreateApplication;
  onUpdate: UpdateApplication;
  onChangeStatus: ChangeApplicationStatus;
}) {
  const [filter, setFilter] = useState<"all" | ApplicationStatus>("all");
  const [jobId, setJobId] = useState("");
  const [startStatus, setStartStatus] = useState<ApplicationStatus>("saved");
  const [appliedOn, setAppliedOn] = useState(localToday);
  const tracked = new Set(data.applications.map((application) => application.job_description_id));
  const untrackedJobs = data.jobs.filter((job) => !tracked.has(job.id));
  const jobs = new Map(data.jobs.map((job) => [job.id, job]));
  const visible = filter === "all" ? data.applications : data.applications.filter((application) => application.status === filter);

  async function startTracking(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const created = await onCreate({
      job_description_id: jobId,
      status: startStatus,
      ...(startStatus === "applied" && { applied_on: appliedOn }),
    });
    if (created) {
      setJobId("");
      setStartStatus("saved");
    }
  }

  return <div className="view-stack">
    <PageHeading eyebrow="Job search" title="Applications" description="Track each saved role from first interest to outcome. An application is only marked applied when you record that you submitted it." />
    <form className="panel" onSubmit={startTracking}>
      <div className="section-title"><div><p className="eyebrow">Start tracking</p><h2>Track a saved job</h2></div></div>
      {untrackedJobs.length === 0 ? <p className="muted">{data.jobs.length === 0 ? "Save a job description or import a discovered listing first." : "Every saved job is already being tracked."}</p> : <div className="form-grid">
        <Field label="Saved job" required><select required value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Choose a saved job</option>{untrackedJobs.map((job) => <option key={job.id} value={job.id}>{job.job_title}{job.company ? ` · ${job.company}` : ""}</option>)}</select></Field>
        <Field label="Starting stage"><select value={startStatus} onChange={(event) => setStartStatus(event.target.value as ApplicationStatus)}>{STARTING_STATUSES.map((value) => <option key={value} value={value}>{APPLICATION_STATUS_LABELS[value]}</option>)}</select></Field>
        {startStatus === "applied" && <Field label="Date you submitted it" required hint="Only choose Applied if you have already submitted this application."><input max={localToday()} required type="date" value={appliedOn} onChange={(event) => setAppliedOn(event.target.value)} /></Field>}
      </div>}
      {untrackedJobs.length > 0 && <div className="form-footer"><span className="muted">Each saved job can be tracked once.</span><button className="button button-primary" disabled={!jobId || busy} type="submit">Start tracking</button></div>}
    </form>
    <section className="panel">
      <div className="section-title">
        <div><p className="eyebrow">Your pipeline</p><h2>Tracked applications</h2></div>
        <label className="field discovery-window"><span>Stage</span><select value={filter} onChange={(event) => setFilter(event.target.value as "all" | ApplicationStatus)}><option value="all">All stages</option>{STATUS_ORDER.map((value) => <option key={value} value={value}>{APPLICATION_STATUS_LABELS[value]}</option>)}</select></label>
      </div>
      {visible.length === 0
        ? <EmptyState title={data.applications.length === 0 ? "No applications tracked yet" : "No applications at this stage"} text={data.applications.length === 0 ? "Track a saved job above to follow it through to an outcome." : "Choose another stage to see more applications."} />
        : <div className="job-list">{visible.map((application) => <ApplicationCard application={application} busy={busy} drafts={data.drafts} job={jobs.get(application.job_description_id)} key={application.id} onChangeStatus={onChangeStatus} onUpdate={onUpdate} />)}</div>}
    </section>
  </div>;
}

function ApplicationCard({
  application,
  job,
  drafts,
  busy,
  onUpdate,
  onChangeStatus,
}: {
  application: JobApplication;
  job: JobDescription | undefined;
  drafts: CvDraft[];
  busy: boolean;
  onUpdate: UpdateApplication;
  onChangeStatus: ChangeApplicationStatus;
}) {
  const title = job?.job_title || "Saved job";
  const [nextStatus, setNextStatus] = useState<ApplicationStatus | "">("");
  const [appliedOn, setAppliedOn] = useState(localToday);
  const [note, setNote] = useState("");
  const [details, setDetails] = useState({
    cv_draft_id: application.cv_draft_id || "",
    deadline_on: application.deadline_on || "",
    follow_up_on: application.follow_up_on || "",
    contact_name: application.contact_name || "",
    contact_email: application.contact_email || "",
    notes: application.notes || "",
  });
  const usableDrafts = drafts.filter((draft) => draft.job_description_id === application.job_description_id && draft.status !== "failed");

  async function changeStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!nextStatus) return;
    const changed = await onChangeStatus(application.id, {
      status: nextStatus,
      ...(nextStatus === "applied" && { applied_on: appliedOn }),
      ...(note.trim() && { note: note.trim() }),
    });
    if (changed) {
      setNextStatus("");
      setNote("");
    }
  }

  function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Empty inputs clear the stored value rather than sending empty text.
    const payload = Object.fromEntries(
      Object.entries(details).map(([key, value]) => [key, value.trim() ? value.trim() : null]),
    ) as JobApplicationDetails;
    void onUpdate(application.id, payload);
  }

  return <article aria-label={title} className="job-card">
    <div className="job-card-title">
      <div><h3>{title}</h3><p>{job?.company || "Company not provided"}{application.applied_on ? ` · Applied ${formatDay(application.applied_on)}` : ""}</p></div>
      <span className="status-pill">{APPLICATION_STATUS_LABELS[application.status]}</span>
    </div>
    <dl className="listing-facts">
      <div><dt>Deadline</dt><dd>{application.deadline_on ? formatDay(application.deadline_on) : "Not recorded"}</dd></div>
      <div><dt>Follow up</dt><dd>{application.follow_up_on ? formatDay(application.follow_up_on) : "Not scheduled"}</dd></div>
      <div><dt>Contact</dt><dd>{application.contact_name || application.contact_email || "Not recorded"}</dd></div>
      <div><dt>Tailored CV</dt><dd>{application.cv_draft_id ? "Linked" : "Not linked"}</dd></div>
    </dl>
    {job?.source_url && <a className="text-button" href={job.source_url} rel="noopener noreferrer" target="_blank">Open job source <span aria-hidden="true">↗</span></a>}
    {application.allowed_next_statuses.length > 0
      ? <form className="form-grid application-status-form" onSubmit={changeStatus}>
        <Field label="Move to"><select value={nextStatus} onChange={(event) => setNextStatus(event.target.value as ApplicationStatus | "")}><option value="">Choose the next stage</option>{application.allowed_next_statuses.map((value) => <option key={value} value={value}>{APPLICATION_STATUS_LABELS[value]}</option>)}</select></Field>
        {nextStatus === "applied" && <Field label="Date you submitted it" required hint="Record this only after you have submitted the application."><input max={localToday()} required type="date" value={appliedOn} onChange={(event) => setAppliedOn(event.target.value)} /></Field>}
        <Field label="Note (optional)"><input maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} /></Field>
        <div className="form-footer full-span"><span className="muted">The change is added to this application's history.</span><button className="button button-primary" disabled={!nextStatus || busy} type="submit">Update stage</button></div>
      </form>
      : <p className="inline-note">This application is closed. Its history is kept below.</p>}
    <details>
      <summary>Edit details</summary>
      <form className="form-grid" onSubmit={saveDetails}>
        <Field label="Deadline"><input type="date" value={details.deadline_on} onChange={(event) => setDetails({ ...details, deadline_on: event.target.value })} /></Field>
        <Field label="Follow-up date"><input type="date" value={details.follow_up_on} onChange={(event) => setDetails({ ...details, follow_up_on: event.target.value })} /></Field>
        <Field label="Contact name"><input maxLength={200} value={details.contact_name} onChange={(event) => setDetails({ ...details, contact_name: event.target.value })} /></Field>
        <Field label="Contact email"><input type="email" value={details.contact_email} onChange={(event) => setDetails({ ...details, contact_email: event.target.value })} /></Field>
        <Field label="Tailored CV used"><select value={details.cv_draft_id} onChange={(event) => setDetails({ ...details, cv_draft_id: event.target.value })}><option value="">None linked</option>{usableDrafts.map((draft) => <option key={draft.id} value={draft.id}>Draft from {formatMoment(draft.created_at)}{draft.structured_content?.review?.approval_status === "approved" ? " (approved)" : " (not approved yet)"}{draft.status === "needs_review" ? ", incomplete" : ""}</option>)}</select></Field>
        <Field className="full-span" label="Notes"><textarea maxLength={10000} rows={3} value={details.notes} onChange={(event) => setDetails({ ...details, notes: event.target.value })} /></Field>
        <div className="form-footer full-span"><span className="muted">Empty fields are cleared.</span><button className="button button-secondary" disabled={busy} type="submit">Save details</button></div>
      </form>
    </details>
    <details>
      <summary>Stage history ({application.events.length})</summary>
      <ol className="run-list">{application.events.map((event) => <li key={event.id}>{event.from_status ? `${APPLICATION_STATUS_LABELS[event.from_status]} → ` : "Started as "}{APPLICATION_STATUS_LABELS[event.to_status]} · {formatMoment(event.occurred_at)}{event.note ? ` · ${event.note}` : ""}</li>)}</ol>
    </details>
  </article>;
}
