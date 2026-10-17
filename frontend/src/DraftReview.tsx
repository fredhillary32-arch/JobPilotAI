import { useEffect, useState } from "react";

import { api, ApiError } from "./api/client";
import type { CvDraft, CvDraftReview } from "./api/types";

type RunAction = (action: () => Promise<unknown>, success?: string, pending?: string) => Promise<boolean>;

const ORIGIN_LABELS = {
  source: "Your wording, unchanged",
  rewritten: "Restated from your records",
  composed: "Assembled from your records",
  candidate_edited: "Edited by you",
} as const;

export function DraftReview({ profileId, draft, busy, runAction }: {
  profileId: string;
  draft: CvDraft;
  busy: boolean;
  runAction: RunAction;
}) {
  const [result, setResult] = useState<{ key: string; review: CvDraftReview } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [attest, setAttest] = useState(false);
  const [acknowledgeIncomplete, setAcknowledgeIncomplete] = useState(false);
  const key = JSON.stringify([profileId, draft.id, draft.status, draft.structured_content]);
  const review = result?.key === key ? result.review : null;
  const error = failure?.key === key ? failure.message : "";

  useEffect(() => {
    let current = true;
    api.getDraftReview(profileId, draft.id)
      .then((value) => { if (current) setResult({ key, review: value }); })
      .catch((caught: unknown) => {
        if (current) {
          setFailure({
            key,
            message: caught instanceof ApiError || caught instanceof Error
              ? caught.message
              : "The review could not be loaded.",
          });
        }
      });
    return () => { current = false; };
  }, [profileId, draft, key]);

  if (error) return <p className="feedback-error setup-error" role="alert">{error}</p>;
  if (!review) return <p className="muted" role="status">Loading the review…</p>;
  const reworded = review.change_log.filter((entry) => entry.significance === "wording");
  const minor = review.change_log.filter((entry) => entry.significance === "minor");
  const approved = review.approval?.approval_status === "approved";
  const incomplete = review.status === "needs_review";

  function saveEdits() {
    const payload = Object.entries(edits)
      .filter(([key, text]) => text.trim() && text.trim() !== review?.change_log.find((entry) => entry.key === key)?.proposed)
      .map(([key, text]) => ({ key, text: text.trim() }));
    if (!payload.length) {
      setEditing(false);
      return;
    }
    void runAction(async () => {
      await api.reviseDraft(profileId, draft.id, payload);
      setEditing(false);
      setEdits({});
    }, "Your edits were saved as a new draft version. The earlier version is unchanged.", "Saving your edits…");
  }

  return <section aria-label="Review before export" className="draft-review">
    <div className="draft-review-head">
      <span className={`status-pill ${approved ? "generated" : "pending"}`}>{approved ? (review.acknowledged_incomplete ? "Approved as incomplete" : "Approved for export") : "Awaiting your review"}</span>
      {review.ats_score !== null && <span className="muted">ATS match score when written: {review.ats_score} / 100</span>}
    </div>

    <details className="draft-content" open={!approved}>
      <summary>Changes and their sources ({reworded.length} reworded, {minor.length} punctuation only, of {review.change_log.length})</summary>
      <ul className="change-log">{review.change_log.map((entry, index) => <li className={entry.needs_confirmation ? "needs-confirmation" : ""} key={entry.key || index}>
        <p className="change-meta"><span className="ats-basis">{ORIGIN_LABELS[entry.origin]}</span> {entry.role || entry.section}</p>
        {entry.changed && entry.original && entry.original !== entry.proposed && <p><span className="change-label">Original</span> {entry.original}</p>}
        {editing && entry.key ? <label className="field"><span>Statement</span><textarea aria-label={`Edit statement ${index + 1}`} maxLength={600} rows={2} value={edits[entry.key] ?? entry.proposed} onChange={(event) => setEdits({ ...edits, [entry.key as string]: event.target.value })} /></label>
          : <p><span className="change-label">{entry.changed ? "Proposed" : "Statement"}</span> {entry.proposed}</p>}
        {entry.reasons.length > 0 && <p className="muted">Why: {entry.reasons.join(" ")}</p>}
        <p className="fit-sources">Evidence: {entry.evidence.map((ref) => `${ref.source_type.replace("_", " ")} (${ref.source_field})${ref.confirmed ? "" : " — unconfirmed"}: “${ref.text}”`).join("; ")}</p>
        {entry.needs_confirmation && <p className="validation-error">Needs your confirmation. {entry.confirmation_note}</p>}
      </li>)}</ul>
      <div className="draft-review-actions">
        {editing ? <>
          <button className="button button-primary" disabled={busy} onClick={saveEdits} type="button">Save edits as a new version</button>
          <button className="button button-secondary" disabled={busy} onClick={() => { setEditing(false); setEdits({}); }} type="button">Cancel</button>
        </> : <button className="button button-secondary" disabled={busy} onClick={() => setEditing(true)} type="button">Edit statements</button>}
      </div>
    </details>

    {(review.from_confirmations?.length ?? 0) > 0 && <section aria-label="Added from your answers" className="ats-list">
      <h4>Added because of your answers</h4>
      <ul>{review.from_confirmations!.map((item, index) => <li key={index}><span className="ats-basis">{item.section}</span> {item.proposed}</li>)}</ul>
      <p className="muted">These come from skills you confirmed or examples you gave. They are your own statements; check they are accurate before approving.</p>
    </section>}

    {review.suggestions.length > 0 && <section aria-label="Writing suggestions" className="ats-list">
      <h4>Suggestions not applied automatically</h4>
      <ul>{review.suggestions.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>}

    <section aria-label="Pre-export checks" className="ats-list">
      <h4>Pre-export checks</h4>
      <ul>{review.checks.checks.map((check) => <li key={check.name}><span className={`ats-check ats-check-${check.status}`}>{check.status}</span> <strong>{check.name}</strong> {check.detail}</li>)}</ul>
      <p className="muted">These checks confirm the draft reads back as intended. Screening systems differ, so no layout is guaranteed to parse identically everywhere.</p>
    </section>

    <details className="draft-content">
      <summary>Plain-text preview ({review.checks.word_count} words)</summary>
      <pre>{review.checks.plain_text}</pre>
    </details>

    <details className="draft-content">
      <summary>Where this draft came from</summary>
      <ul>
        {review.trace.job_description && <li>Job: {review.trace.job_description.job_title}{review.trace.job_description.company ? ` at ${review.trace.job_description.company}` : ""}{review.trace.job_description.source_job_listing_id ? " (imported from a discovered listing)" : ""}</li>}
        <li>Source CV checked: {review.trace.source_document ? review.trace.source_document.filename : "none selected"}</li>
        <li>Confirmed evidence used: {review.trace.evidence_used.length ? review.trace.evidence_used.map((item) => item.description).join("; ") : "none"}</li>
        {review.trace.parent_draft_id && <li>Edited from an earlier version of this draft.</li>}
      </ul>
    </details>

    {review.requires_approval && !approved && <div className="approval-box">
      {review.needs_confirmation > 0 && <label className="checkbox-field"><input checked={attest} onChange={(event) => setAttest(event.target.checked)} type="checkbox" /> I confirm the {review.needs_confirmation} statement{review.needs_confirmation === 1 ? "" : "s"} marked as needing confirmation {review.needs_confirmation === 1 ? "is" : "are"} accurate.</label>}
      {incomplete && <label className="checkbox-field"><input checked={acknowledgeIncomplete} onChange={(event) => setAcknowledgeIncomplete(event.target.checked)} type="checkbox" /> I understand this CV is incomplete ({(review.issues ?? []).map((issue) => issue.message).join(" ")}) and want to approve it as it is.</label>}
      <button className="button button-primary" disabled={busy || (review.needs_confirmation > 0 && !attest) || (incomplete && !acknowledgeIncomplete)} onClick={() => void runAction(() => api.approveDraft(profileId, draft.id, attest, incomplete && acknowledgeIncomplete), incomplete ? "Draft approved as incomplete. You can now export it." : "Draft approved. You can now export it.", "Approving draft…")} type="button">{incomplete ? "Approve as incomplete" : "Approve for export"}</button>
    </div>}
    {!review.export_ready && review.export_blockers.length > 0 && <ul className="muted">{review.export_blockers.map((item) => <li key={item}>{item}</li>)}</ul>}
  </section>;
}
