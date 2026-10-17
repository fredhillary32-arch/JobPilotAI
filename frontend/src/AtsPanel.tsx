import { useEffect, useState, type ReactNode } from "react";

import { api, ApiError } from "./api/client";
import type { AtsReport, AtsRequirement, EligibilityStatus, RequirementStatus, WorkExperience } from "./api/types";
import { RequirementAnswer } from "./RequirementAnswer";

type RunAction = (action: () => Promise<unknown>, success?: string, pending?: string) => Promise<boolean>;

const STATUS_LABELS: Record<RequirementStatus, string> = {
  matched: "Shown in your records",
  partial: "Partly shown",
  uncertain: "Needs your confirmation",
  missing: "Not shown",
  candidate_confirmed: "You confirmed this skill",
  not_possessed: "You do not have this",
  unverified: "Left unverified",
};
const STRENGTH_LABELS: Record<NonNullable<AtsRequirement["evidence_strength"]>, string> = {
  document_or_record: "Confirmed document evidence, certification or education",
  work_history: "Your recorded work history",
  candidate_statement: "Your own statement (confirmed here)",
  listed_only: "Listed skill only",
  none: "No support yet",
};
const BASIS_LABELS: Record<AtsRequirement["basis"], string> = {
  explicit: "Stated by the employer",
  inferred: "Inferred from the duties",
  ambiguous: "Wording is ambiguous",
};
const COMPONENT_LABELS: Record<string, string> = {
  essential: "Essential requirements",
  preferred: "Preferred requirements",
  responsibilities: "Duties shown in your experience",
  keywords: "Important terms",
};
const GEOGRAPHIC_LABELS: Record<EligibilityStatus, string> = {
  eligible_confirmed: "Kenya applicants accepted",
  not_eligible: "Kenya-based applicants excluded",
  eligibility_unknown: "Kenya eligibility not established",
};

function RequirementList({ title, items, empty, intro, answer }: {
  title: string;
  items: AtsRequirement[];
  empty: string;
  intro?: string;
  answer?: (item: AtsRequirement) => ReactNode;
}) {
  return <section aria-label={title} className="ats-list">
    <h3>{title} <span className="count-pill">{items.length}</span></h3>
    {intro && <p className="muted">{intro}</p>}
    {items.length === 0 ? <p className="muted">{empty}</p> : <ul>{items.map((item) => <li key={item.id}>
      <div className="ats-item-head">
        {item.status && <span className={`status-pill ats-${item.status}`}>{STATUS_LABELS[item.status]}</span>}
        <span className="ats-basis">{BASIS_LABELS[item.basis]}</span>
      </div>
      <strong>{item.text}</strong>
      {item.source_text !== item.text && <blockquote>{item.source_text}</blockquote>}
      {item.explanation && <p className="muted">{item.explanation}</p>}
      {item.evidence && item.evidence.length > 0 && <p className="fit-sources">From: {item.evidence.map((ref) => ref.label).join("; ")}</p>}
      {item.action && !item.confirmation && <p className="requirement-action"><strong>What you can do:</strong> {item.action}</p>}
      {answer && (item.status !== "matched" || item.confirmation) ? answer(item) : null}
    </li>)}</ul>}
  </section>;
}

export function AtsPanel({ profileId, jobId, sourceDocumentId, refreshKey, experiences = [], busy = false, runAction }: {
  profileId: string;
  jobId: string;
  sourceDocumentId: string;
  refreshKey: unknown;
  experiences?: WorkExperience[];
  busy?: boolean;
  runAction?: RunAction;
}) {
  const [loaded, setLoaded] = useState<{ target: string; refreshKey: unknown; report: AtsReport } | null>(null);
  const [failure, setFailure] = useState<{ target: string; refreshKey: unknown; message: string } | null>(null);
  const target = `${profileId}|${jobId}|${sourceDocumentId}`;
  const report = loaded?.target === target ? loaded.report : null;
  const error = failure?.target === target && Object.is(failure.refreshKey, refreshKey)
    ? failure.message
    : "";
  const refreshing = report !== null && !Object.is(loaded?.refreshKey, refreshKey);

  useEffect(() => {
    let current = true;
    api.getAtsAnalysis(profileId, jobId, sourceDocumentId || undefined)
      .then((value) => { if (current) setLoaded({ target, refreshKey, report: value }); })
      .catch((caught: unknown) => {
        if (current) {
          setFailure({
            target,
            refreshKey,
            message: caught instanceof ApiError || caught instanceof Error
              ? caught.message
              : "The ATS analysis could not be loaded.",
          });
        }
      });
    return () => { current = false; };
  }, [profileId, jobId, sourceDocumentId, refreshKey, target]);

  const answer = runAction ? (item: AtsRequirement) => <RequirementAnswer busy={busy} experiences={experiences} jobId={jobId} key={`${item.key}-${item.confirmation?.id ?? "new"}-${item.confirmation?.confirmed_at ?? ""}`} profileId={profileId} requirement={item} runAction={runAction} /> : undefined;
  if (error) return <p className="feedback-error setup-error" role="alert">ATS analysis: {error}</p>;
  if (!report) return <p className="muted" role="status">Analysing the job description against your records…</p>;
  const geo = report.eligibility.geographic;
  const present = report.keywords.filter((k) => k.status === "shown" || k.status === "listed_only");
  const absent = report.keywords.filter((k) => k.status === "absent" || k.status === "unconfirmed_only");
  const cv = report.cv_document;
  return <section aria-label="ATS match report" className="panel ats-panel">
    <div className="section-title"><div><p className="eyebrow">Before you generate</p><h2>ATS match report</h2></div>{refreshing && <span className="inline-loading" role="status"><span className="spinner small" /> Updating the report with your latest answers…</span>}</div>
    <p className={`fit-headline ats-verdict-${report.verdict}`}>{report.headline}</p>

    <div className="fit-columns">
      <section aria-label="Match score" className="fit-block">
        <h3>Skills match score</h3>
        {report.score === null ? <p className="muted">Not measurable for this job description.</p> : <>
          <p className="fit-coverage">{report.score} / 100</p>
          {report.eligibility_overrides_score && <p className="validation-error">Eligibility comes first: this score does not outweigh the location or authorization issue.</p>}
          {report.potential_score !== null && report.potential_score > report.score && <p className="muted">Could reach {report.potential_score} if the uncertain items are accurate and you confirm them.</p>}
        </>}
        <details className="ats-method">
          <summary>How this score is calculated</summary>
          <p>{report.score_explanation.method}</p>
          <table>
            <thead><tr><th>Part</th><th>Items</th><th>Weight</th><th>Credited</th><th>Points</th></tr></thead>
            <tbody>{report.score_explanation.components.map((part) => <tr key={part.name}>
              <td>{COMPONENT_LABELS[part.name] || part.name}</td><td>{part.items}</td><td>{part.effective_weight}</td>
              <td>{part.fraction_credited === null ? "—" : `${Math.round(part.fraction_credited * 100)}%`}</td><td>{part.points}</td>
            </tr>)}</tbody>
          </table>
          <p className="muted">{report.score_explanation.potential_note}</p>
          <ul>{report.score_explanation.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      </section>
      <section aria-label="Eligibility, assessed separately" className="fit-block">
        <h3>Eligibility (assessed separately)</h3>
        <span className={`status-pill eligibility-${geo.status === "eligible_confirmed" ? "confirmed" : geo.status === "not_eligible" ? "excluded" : "unknown"}`}>{GEOGRAPHIC_LABELS[geo.status]}</span>
        <p className="muted">{geo.reason}</p>
        {geo.quotation && <blockquote>{geo.quotation}</blockquote>}
        {report.eligibility.disqualifiers.map((item, index) => <p className="validation-error" key={`d-${index}`}>{item.explanation}</p>)}
        {report.eligibility.location_items.map((item, index) => <p className="muted" key={`l-${index}`}>{item.explanation}{item.quotation ? ` "${item.quotation}"` : ""}</p>)}
        {report.requirements.eligibility.map((item) => <p className="fit-sources" key={item.id}>{item.text}: “{item.source_text}”</p>)}
      </section>
    </div>

    {report.recommendations.length > 0 && <section aria-label="Recommended improvements" className="ats-list">
      <h3>Recommended improvements</h3>
      <ol>{report.recommendations.map((item) => <li key={item.rank}><span className="ats-basis">{item.category}</span> {item.text}</li>)}</ol>
    </section>}

    {report.evidence_strength && <section aria-label="Evidence strength" className="ats-list">
      <h3>Evidence strength (separate from the score)</h3>
      <ul>{(Object.keys(STRENGTH_LABELS) as (keyof typeof STRENGTH_LABELS)[]).filter((level) => report.evidence_strength!.essential[level]).map((level) => <li key={level}>{STRENGTH_LABELS[level]}: {report.evidence_strength!.essential[level]} essential requirement{report.evidence_strength!.essential[level] === 1 ? "" : "s"}</li>)}</ul>
      <p className="muted">{report.evidence_strength.method}</p>
    </section>}

    <section aria-label="Review missing requirements" className="requirement-review">
      <h3>Review missing requirements and add skills you genuinely have</h3>
      <p className="muted">Answer only what is true. A skill you confirm can appear in your skills list; an example you give from a recorded role can become a bullet for that role. "I do not have this" and "Not sure" never appear on your CV. Your answers are your own statements and are never shown as independently verified.</p>
      {report.candidate_answers && <p className="muted">Answered so far: {report.candidate_answers.confirmed} confirmed, {report.candidate_answers.not_possessed} not possessed, {report.candidate_answers.unverified} left unverified.</p>}
    </section>
    <RequirementList answer={answer} empty="No essential requirements were found." items={report.requirements.essential} title="Essential requirements" />
    <RequirementList answer={answer} empty="No preferred requirements were found." items={report.requirements.preferred} title="Preferred requirements" />
    {(report.requirements.work_style?.length ?? 0) > 0 && <RequirementList answer={answer} empty="" intro="Personal qualities and ways of working the employer asks for. A CV cannot prove these, so they are not scored or listed as CV gaps; prepare a real example of each for the interview." items={report.requirements.work_style ?? []} title="Work style and personal qualities (for interview preparation)" />}
    {(report.requirements.context?.length ?? 0) > 0 && <details className="ats-details">
      <summary>About the team and how they work ({report.requirements.context!.length}, not requirements)</summary>
      <ul>{report.requirements.context!.map((item, index) => <li key={index}>{item.text}</li>)}</ul>
    </details>}
    <details className="ats-details">
      <summary>Duties in the job and your experience ({report.requirements.responsibilities.length})</summary>
      <RequirementList empty="No listed duties were found." items={report.requirements.responsibilities} title="Duties" />
    </details>

    <section aria-label="Important terms" className="ats-list">
      <h3>Important terms</h3>
      <p className="muted">A term on your CV is not proof of skill; only terms backed by your records count fully.</p>
      <div className="ats-keywords">
        <div><h4>Present in your records</h4>{present.length ? <ul>{present.map((k) => <li key={k.term}>{k.term}{k.status === "listed_only" ? " (listed only)" : ""}</li>)}</ul> : <p className="muted">None yet.</p>}</div>
        <div><h4>Not shown in your confirmed records</h4>{absent.length ? <ul>{absent.map((k) => <li key={k.term}>{k.term}{k.status === "unconfirmed_only" ? " (only in unconfirmed sources)" : ""}{k.importance === "high" ? " · important" : ""}</li>)}</ul> : <p className="muted">None.</p>}</div>
      </div>
    </section>

    {report.screening_concerns.length > 0 && <section aria-label="Screening concerns" className="ats-list">
      <h3>Possible screening concerns</h3>
      <ul>{report.screening_concerns.map((item, index) => <li key={index}><span className={`ats-severity ats-severity-${item.severity}`}>{item.severity}</span> {item.text}</li>)}</ul>
    </section>}

    <section aria-label="Formatting and parsing" className="ats-list">
      <h3>Formatting and parsing risks</h3>
      {!cv ? <p className="muted">Choose your uploaded CV above to check its layout. The CV that JobPilot exports uses a single-column layout with standard headings.</p>
        : cv.status === "unavailable" ? <p className="muted">{cv.error}</p>
          : cv.formatting_risks.length === 0 ? <p className="muted">No layout risks were found in {cv.filename}.</p>
            : <ul>{cv.formatting_risks.map((risk) => <li key={risk.code}><span className={`ats-severity ats-severity-${risk.severity}`}>{risk.severity}</span> <strong>{risk.title}</strong> {risk.detail}</li>)}</ul>}
      {cv && cv.unconfirmed_statements.length > 0 && <>
        <h4>Statements in your CV that are not confirmed</h4>
        <ul>{cv.unconfirmed_statements.map((item) => <li key={item.text}><q>{item.text}</q> <span className="muted">{item.reason}</span></li>)}</ul>
      </>}
      {cv && cv.contradictions.length > 0 && <>
        <h4>Differences from your profile</h4>
        <ul>{cv.contradictions.map((item) => <li key={item.record}>{item.explanation}</li>)}</ul>
      </>}
    </section>
  </section>;
}
