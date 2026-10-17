import { useRef, useState, type FormEvent } from "react";
import type { ReactNode } from "react";

import type {
  CandidateEvidence,
  CandidateProfileInput,
  Certification,
  CertificationInput,
  CvDraft,
  Education,
  EducationInput,
  EvidenceCategory,
  EvidenceStatus,
  ExportFormat,
  ExtractedText,
  JobApplication,
  JobDescription,
  RemoteWorkPreference,
  Skill,
  SkillInput,
  WorkspaceData,
  WorkExperience,
  WorkExperienceInput,
} from "./api/types";
import { APPLICATION_STATUS_LABELS, FINISHED_STATUSES, localToday } from "./applicationStatus";
import { AtsPanel } from "./AtsPanel";
import { DraftReview } from "./DraftReview";
import { JobFitPanel } from "./JobFitPanel";

export type ViewName =
  | "Dashboard"
  | "Profile"
  | "Documents"
  | "Evidence review"
  | "Job pipeline"
  | "Job discovery"
  | "Job descriptions"
  | "Tailored CVs"
  | "Applications"
  | "Exports";

type RunAction = (
  action: () => Promise<unknown>,
  success?: string | ((result: unknown) => string),
  pending?: string,
) => Promise<boolean>;

const categories: EvidenceCategory[] = [
  "employment_responsibility",
  "technical_skill",
  "project",
  "achievement",
  "qualification",
  "metric",
];

const categoryLabels: Record<EvidenceCategory, string> = {
  employment_responsibility: "Employment responsibility",
  technical_skill: "Technical skill",
  project: "Project",
  achievement: "Achievement",
  qualification: "Qualification",
  metric: "Metric",
};

export function DashboardView({
  data,
  navigate,
}: {
  data: WorkspaceData;
  navigate: (view: ViewName) => void;
}) {
  const completeFields = [
    data.profile.name,
    data.profile.contact_email,
    data.profile.contact_phone,
    data.profile.professional_headline,
    data.profile.summary,
    data.profile.location,
    data.profile.remote_work_preference,
  ].filter(Boolean).length;
  const completion = Math.round((completeFields / 7) * 100);
  const activeApplications = data.applications.filter((application) => !FINISHED_STATUSES.includes(application.status));
  const metrics = [
    ["Documents", data.documents.length, "Documents"],
    ["Saved roles", data.jobs.length, "Job descriptions"],
    ["CV drafts", data.drafts.length, "Tailored CVs"],
    ["Active applications", activeApplications.length, "Applications"],
  ] as const;
  // Deadlines and follow-ups due within two weeks, including overdue ones.
  const today = localToday();
  const horizon = new Date(`${today}T00:00:00Z`);
  horizon.setUTCDate(horizon.getUTCDate() + 14);
  const horizonDay = horizon.toISOString().slice(0, 10);
  const upcoming = activeApplications
    .flatMap((application) => [
      application.deadline_on ? { application, kind: "Deadline", day: application.deadline_on } : null,
      application.follow_up_on ? { application, kind: "Follow up", day: application.follow_up_on } : null,
    ])
    .filter((item): item is { application: JobApplication; kind: string; day: string } => item !== null && item.day <= horizonDay)
    .sort((left, right) => left.day.localeCompare(right.day))
    .slice(0, 5);

  return (
    <div className="view-stack">
      <section className="welcome-panel">
        <div>
          <p className="eyebrow">Your job search workspace</p>
          <h1>Good to see you, {data.profile.name.split(" ")[0]}</h1>
          <p>Keep your candidate information current and build every application from reviewed evidence.</p>
        </div>
        <button className="button button-light" onClick={() => navigate("Profile")}>
          Complete your profile
        </button>
      </section>

      <section className="metric-grid" aria-label="Workspace totals">
        {metrics.map(([label, count, view]) => (
          <button className="metric-card" key={label} onClick={() => navigate(view)}>
            <span>{label}</span>
            <strong>{count}</strong>
            <small>From your saved records</small>
          </button>
        ))}
      </section>

      <div className="dashboard-grid">
        <section className="panel completion-panel">
          <div className="section-title">
            <div>
              <p className="eyebrow">Candidate profile</p>
              <h2>Profile completeness</h2>
            </div>
            <strong className="completion-number">{completion}%</strong>
          </div>
          <div
            aria-label={`Profile details completed: ${completion}%`}
            className="progress-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={completion}
          >
            <span style={{ width: `${completion}%` }} />
          </div>
          <p>{completeFields} of 7 key profile details are present. A complete profile helps keep tailored drafts grounded in your information.</p>
          <button className="text-button" onClick={() => navigate("Profile")}>Review profile details <span aria-hidden="true">→</span></button>
        </section>

        <section className="panel">
          <div className="section-title">
            <div>
              <p className="eyebrow">Recent activity</p>
              <h2>Continue where you left off</h2>
            </div>
          </div>
          {data.drafts.length ? (
            <ul className="activity-list">
              {data.drafts.slice(0, 3).map((draft) => (
                <li key={draft.id}>
                  <span className={`status-dot ${draft.status}`} />
                  <div>
                    <strong>{jobTitle(data.jobs, draft.job_description_id)}</strong>
                    <small>{draft.status === "generated" ? "Validated draft saved" : "Draft needs more evidence"}</small>
                  </div>
                  <span className="muted">{formatDate(draft.created_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No CV drafts yet" text="Save a job description and generate a draft when you are ready." />
          )}
          <button className="text-button" onClick={() => navigate("Tailored CVs")}>Open tailored CVs <span aria-hidden="true">→</span></button>
        </section>

        <section className="panel" aria-label="Upcoming application dates">
          <div className="section-title">
            <div>
              <p className="eyebrow">Applications</p>
              <h2>Upcoming dates</h2>
            </div>
          </div>
          {upcoming.length ? (
            <ul className="activity-list">
              {upcoming.map(({ application, kind, day }) => (
                <li key={`${application.id}-${kind}`}>
                  <span className={`status-dot ${day < today ? "overdue" : "generated"}`} />
                  <div>
                    <strong>{jobTitle(data.jobs, application.job_description_id)}</strong>
                    <small>{kind}{day < today ? " (overdue)" : ""} · {APPLICATION_STATUS_LABELS[application.status]}</small>
                  </div>
                  <span className="muted">{day}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nothing due in the next two weeks" text="Record deadlines and follow-up dates on your tracked applications." />
          )}
          <button className="text-button" onClick={() => navigate("Applications")}>Open applications <span aria-hidden="true">→</span></button>
        </section>
      </div>

      <section className="panel privacy-note">
        <span className="privacy-icon" aria-hidden="true">i</span>
        <p><strong>Local workspace</strong> — Sign-in protects this workspace, but JobPilot AI is built for a single trusted machine. Keep the application bound to this computer and do not expose its API publicly.</p>
      </section>
    </div>
  );
}

export function ProfileView({
  data,
  onSave,
  onCreateExperience,
  onUpdateExperience,
  onDeleteExperience,
  onCreateEducation,
  onUpdateEducation,
  onDeleteEducation,
  onCreateSkill,
  onUpdateSkill,
  onDeleteSkill,
  onCreateCertification,
  onUpdateCertification,
  onDeleteCertification,
  busy,
  runAction,
}: {
  data: WorkspaceData;
  onSave: (payload: CandidateProfileInput) => Promise<unknown>;
  onCreateExperience: (payload: WorkExperienceInput) => Promise<unknown>;
  onUpdateExperience: (id: string, payload: WorkExperienceInput) => Promise<unknown>;
  onDeleteExperience: (id: string) => Promise<unknown>;
  onCreateEducation: (payload: EducationInput) => Promise<unknown>;
  onUpdateEducation: (id: string, payload: EducationInput) => Promise<unknown>;
  onDeleteEducation: (id: string) => Promise<unknown>;
  onCreateSkill: (payload: SkillInput) => Promise<unknown>;
  onUpdateSkill: (id: string, payload: SkillInput) => Promise<unknown>;
  onDeleteSkill: (id: string) => Promise<unknown>;
  onCreateCertification: (payload: CertificationInput) => Promise<unknown>;
  onUpdateCertification: (id: string, payload: CertificationInput) => Promise<unknown>;
  onDeleteCertification: (id: string) => Promise<unknown>;
  busy: boolean;
  runAction: RunAction;
}) {
  const [form, setForm] = useState<ProfileFormState>(() => profileForm(data));
  const [categoriesText, setCategoriesText] = useState(data.profile.target_job_categories.join(", "));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload: CandidateProfileInput = {
      name: form.name.trim(),
      contact_email: form.contact_email.trim() || null,
      contact_phone: form.contact_phone.trim() || null,
      professional_headline: form.professional_headline.trim() || null,
      summary: form.summary.trim() || null,
      location: form.location.trim() || null,
      remote_work_preference: form.remote_work_preference || null,
      target_job_categories: categoriesText.split(",").map((value) => value.trim()).filter(Boolean),
    };
    runAction(() => onSave(payload), "Candidate profile saved.", "Saving candidate profile…");
  }

  return (
    <div className="view-stack">
      <PageHeading eyebrow="Your information" title="Candidate profile" description="Keep your contact details, work preferences and professional summary accurate." />
      <form className="panel form-panel" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Full name" required><input autoComplete="name" maxLength={200} required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Field>
          <Field label="Professional headline"><input maxLength={240} value={form.professional_headline} onChange={(event) => setForm({ ...form, professional_headline: event.target.value })} placeholder="For example, Platform Engineer" /></Field>
          <Field label="Email address"><input autoComplete="email" maxLength={320} type="email" value={form.contact_email} onChange={(event) => setForm({ ...form, contact_email: event.target.value })} /></Field>
          <Field label="Phone number"><input autoComplete="tel" maxLength={32} type="tel" value={form.contact_phone} onChange={(event) => setForm({ ...form, contact_phone: event.target.value })} /></Field>
          <Field label="Location"><input autoComplete="address-level2" maxLength={200} value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} placeholder="City, country" /></Field>
          <Field label="Remote-work preference"><select value={form.remote_work_preference} onChange={(event) => setForm({ ...form, remote_work_preference: event.target.value as RemoteWorkPreference | "" })}><option value="">Not specified</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="onsite">On-site</option><option value="flexible">Flexible</option></select></Field>
          <Field className="full-span" label="Professional summary"><textarea maxLength={5000} rows={5} value={form.summary} onChange={(event) => setForm({ ...form, summary: event.target.value })} /></Field>
          <Field className="full-span" label="Target job categories" hint="Separate categories with commas."><input maxLength={3000} value={categoriesText} onChange={(event) => setCategoriesText(event.target.value)} /></Field>
        </div>
        <div className="form-footer"><span className="muted">Changes update this profile only; saved CV drafts remain unchanged.</span><button className="button button-primary" disabled={busy} type="submit">Save profile</button></div>
      </form>

      <section className="panel">
        <div className="section-title"><div><p className="eyebrow">Candidate history</p><h2>Work, education and skills</h2></div></div>
        <p className="inline-note">Only add facts you confirm as accurate. Work achievements entered here are candidate-provided profile information; text extracted from uploaded documents remains unverified until you review it in Evidence review.</p>
        <div className="record-columns">
          <RecordManager<WorkExperience, WorkExperienceInput>
            title="Work experience"
            records={data.experiences}
            empty="No work experience has been added."
            busy={busy}
            createLabel="Add work experience"
            onCreate={(input) => runAction(() => onCreateExperience(input), "Work experience added.")}
            onUpdate={(id, input) => runAction(() => onUpdateExperience(id, input), "Work experience updated.")}
            onDelete={(id) => runAction(() => onDeleteExperience(id), "Work experience deleted.")}
            renderEditor={(record, onSubmit, onCancel) => <WorkExperienceEditor record={record} onSubmit={onSubmit} onCancel={onCancel} />}
            renderRecord={(item) => <Record title={item.job_title} subtitle={`${item.employer} · ${item.start_date}${item.current_role ? " – Present" : item.end_date ? ` – ${item.end_date}` : ""}`} detail={item.description} extra={item.achievements.length ? <ul>{item.achievements.map((achievement) => <li key={achievement}>{achievement}</li>)}</ul> : null} />}
          />
          <RecordManager<Education, EducationInput>
            title="Education"
            records={data.education}
            empty="No education has been added."
            busy={busy}
            createLabel="Add education"
            onCreate={(input) => runAction(() => onCreateEducation(input), "Education added.")}
            onUpdate={(id, input) => runAction(() => onUpdateEducation(id, input), "Education updated.")}
            onDelete={(id) => runAction(() => onDeleteEducation(id), "Education deleted.")}
            renderEditor={(record, onSubmit, onCancel) => <EducationEditor record={record} onSubmit={onSubmit} onCancel={onCancel} />}
            renderRecord={(item) => <Record title={item.qualification} subtitle={`${item.institution}${item.field_of_study ? ` · ${item.field_of_study}` : ""}`} detail={`${item.start_date}${item.end_date ? ` – ${item.end_date}` : ""}`} />}
          />
          <RecordManager<Skill, SkillInput>
            title="Skills"
            records={data.skills}
            empty="No skills have been added."
            busy={busy}
            createLabel="Add skill"
            onCreate={(input) => runAction(() => onCreateSkill(input), "Skill added.")}
            onUpdate={(id, input) => runAction(() => onUpdateSkill(id, input), "Skill updated.")}
            onDelete={(id) => runAction(() => onDeleteSkill(id), "Skill deleted.")}
            renderEditor={(record, onSubmit, onCancel) => <SkillEditor record={record} onSubmit={onSubmit} onCancel={onCancel} />}
            renderRecord={(item) => <Record title={item.name} subtitle={item.proficiency_level || "Proficiency not specified"} />}
          />
          <RecordManager<Certification, CertificationInput>
            title="Certifications"
            records={data.certifications}
            empty="No certifications have been added."
            busy={busy}
            createLabel="Add certification"
            onCreate={(input) => runAction(() => onCreateCertification(input), "Certification added.")}
            onUpdate={(id, input) => runAction(() => onUpdateCertification(id, input), "Certification updated.")}
            onDelete={(id) => runAction(() => onDeleteCertification(id), "Certification deleted.")}
            renderEditor={(record, onSubmit, onCancel) => <CertificationEditor record={record} onSubmit={onSubmit} onCancel={onCancel} />}
            renderRecord={(item) => <Record title={item.name} subtitle={`${item.issuer} · ${item.issue_date}`} detail={item.expires_on ? `Expires ${item.expires_on}` : null} />}
          />
        </div>
      </section>
    </div>
  );
}

export function DocumentsView({
  data,
  onUpload,
  onExtract,
  onSuggest,
  onDownload,
  onGetText,
  busy,
  runAction,
}: {
  data: WorkspaceData;
  onUpload: (file: File) => Promise<unknown>;
  onExtract: (documentId: string) => Promise<string>;
  onSuggest: (documentId: string) => Promise<string>;
  onDownload: (documentId: string, filename: string) => Promise<unknown>;
  onGetText: (documentId: string) => Promise<ExtractedText>;
  busy: boolean;
  runAction: RunAction;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [selectedText, setSelectedText] = useState<ExtractedText | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    const formElement = event.currentTarget;
    runAction(async () => {
      await onUpload(file);
      setFile(null);
      formElement.reset();
    }, "Document uploaded as a new, separate source file.", "Uploading document…");
  }

  return (
    <div className="view-stack">
      <PageHeading eyebrow="Source documents" title="Documents" description="Upload original documents, extract their text locally and keep every source file intact." />
      <form className="panel upload-panel" onSubmit={submit}>
        <div><h2>Upload a document</h2><p className="muted">PDF, DOCX or UTF-8 TXT · up to 10 MB. Existing files are never replaced.</p></div>
        <div className="upload-controls"><input aria-label="Choose a document" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" onChange={(event) => setFile(event.target.files?.[0] || null)} required type="file" /><button className="button button-primary" disabled={!file || busy} type="submit">Upload new document</button></div>
      </form>
      <section className="panel">
        <div className="section-title"><div><p className="eyebrow">Private source files</p><h2>Your documents</h2></div><span className="count-pill">{data.documents.length}</span></div>
        {data.documents.length === 0 ? <EmptyState title="No documents uploaded" text="Upload your CV or a supporting document to begin reviewing its extracted text." /> : (
          <div className="document-list">
            {data.documents.map((document) => {
              const extraction = data.extractions[document.id];
              return <article className="document-row" key={document.id}>
                <div className="file-mark" aria-hidden="true">{document.original_filename.split(".").pop()?.toUpperCase().slice(0, 4) || "FILE"}</div>
                <div className="document-details"><strong>{document.original_filename}</strong><span>{formatBytes(document.size_bytes)} · Uploaded {formatDate(document.created_at)}</span><div className="document-meta"><span className="status-pill">{document.document_kind === "source_cv" ? "Source CV" : "Supporting document"}</span><span className={`status-pill ${extraction?.status || "pending"}`}>{extraction ? extraction.status.replace("_", " ") : "Not extracted"}</span>{extraction?.error_category && <span className="muted">· {extraction.error_category.replaceAll("_", " ")}</span>}</div></div>
                <div className="row-actions"><button className="button button-secondary" disabled={busy} onClick={() => runAction(() => onDownload(document.id, document.original_filename), "Source document downloaded.", "Downloading document…")} type="button">Download</button><button className="button button-secondary" disabled={busy} onClick={() => runAction(() => onExtract(document.id), (message) => String(message), "Extracting text and suggesting evidence…")} type="button">{extraction ? "Retry extraction" : "Extract text"}</button>{extraction?.status === "succeeded" && <button className="button button-secondary" disabled={busy} onClick={() => runAction(() => onSuggest(document.id), (message) => String(message), "Suggesting evidence from this document…")} type="button">Suggest evidence</button>}{extraction?.status === "succeeded" && <button className="text-button" disabled={busy} onClick={() => runAction(async () => setSelectedText(await onGetText(document.id)), undefined, "Loading extracted text…")} type="button">View extracted text</button>}</div>
              </article>;
            })}
          </div>
        )}
        <p className="inline-note">Source uploads are immutable and the API has no document deletion endpoint. Extracted text is unverified source content, not proof of a claim. Scanned PDFs do not receive OCR. After extraction, JobPilot suggests evidence on this computer using fixed rules; every suggestion stays unreviewed until you confirm it, and contact details are never suggested.</p>
      </section>
      {selectedText && <section className="panel extracted-panel"><div className="section-title"><div><p className="eyebrow">Unverified source content</p><h2>Extracted text</h2></div><button aria-label="Close extracted text" className="icon-button" onClick={() => setSelectedText(null)}>×</button></div><p className="inline-note">{selectedText.note}</p><pre className="source-text">{selectedText.text || "No readable embedded text was found."}</pre></section>}
    </div>
  );
}

export function EvidenceView({
  data,
  onGetText,
  onCreate,
  onSetStatus,
  onRelink,
  busy,
  runAction,
}: {
  data: WorkspaceData;
  onGetText: (documentId: string) => Promise<ExtractedText>;
  onCreate: (payload: { source_document_id: string; category: string; description: string; source_excerpt: string; source_section?: string }) => Promise<unknown>;
  onSetStatus: (id: string, status: EvidenceStatus) => Promise<unknown>;
  onRelink: (id: string, sourceExcerpt: string) => Promise<unknown>;
  busy: boolean;
  runAction: RunAction;
}) {
  const [sourceId, setSourceId] = useState("");
  const [category, setCategory] = useState<EvidenceCategory>("achievement");
  const [description, setDescription] = useState("");
  const [sourceSection, setSourceSection] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [textByDocument, setTextByDocument] = useState<Record<string, ExtractedText>>({});
  const cardRefs = useRef(new Map<string, HTMLElement>());

  // The clicked button disappears once a decision is saved; keep keyboard focus on
  // the same card without moving the page, so review continues from where it was.
  async function review(id: string, status: EvidenceStatus, success: string, pending: string) {
    if (await runAction(() => onSetStatus(id, status), success, pending)) {
      cardRefs.current.get(id)?.focus({ preventScroll: true });
    }
  }

  function createEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sourceId || !description.trim() || !excerpt.trim()) return;
    runAction(async () => {
      await onCreate({
        source_document_id: sourceId,
        category,
        description: description.trim(),
        source_excerpt: excerpt,
        ...(sourceSection.trim() && { source_section: sourceSection.trim() }),
      });
      setDescription("");
      setSourceSection("");
      setExcerpt("");
    }, "Evidence saved as unreviewed. It has not been confirmed.", "Saving evidence…");
  }

  const eligibleDocuments = data.documents.filter((document) => data.extractions[document.id]?.status === "succeeded");
  return (
    <div className="view-stack">
      <PageHeading eyebrow="Review before use" title="Evidence review" description="Extracted text is unverified. Only information you explicitly confirm can support tailored CV claims." />
      <section className="panel trust-banner"><span aria-hidden="true">!</span><p><strong>Nothing is confirmed automatically.</strong> Suggestions found in your extracted documents start unreviewed. Review the source and evidence description before marking a claim candidate-confirmed. Rejected or unreviewed evidence is excluded from CV generation.</p></section>
      <section className="panel">
        <div className="section-title"><div><p className="eyebrow">Source references</p><h2>Candidate evidence</h2></div><span className="count-pill">{data.evidence.length}</span></div>
        {data.evidence.length === 0 ? <EmptyState title="No evidence records yet" text="Create a record from text extracted from one of your source documents." /> : <div className="evidence-list">{[...data.evidence].sort(compareEvidence).map((item) => {
          const source = data.documents.find((document) => document.id === item.source_document_id);
          const text = textByDocument[item.source_document_id];
          const stale = item.source_current === false;
          return <article aria-label={`Evidence: ${item.description}`} className="evidence-card" key={item.id} ref={(element) => { if (element) cardRefs.current.set(item.id, element); else cardRefs.current.delete(item.id); }} tabIndex={-1}>
            <div className="evidence-card-head"><div><span className={`status-pill evidence-${item.confirmation_status}`}>{statusLabel(item.confirmation_status)}</span><span className="category-label">{categoryLabels[item.category]}</span>{stale && <span className="status-pill failed">Source text changed</span>}</div><small>{formatDate(item.created_at)}</small></div>
            <h3>{item.description}</h3>
            <p className="source-reference">Source: {source?.original_filename || "Source document unavailable"}{item.source_section ? ` · Section: ${item.source_section}` : ""}</p>
            {item.source_excerpt && <blockquote>{item.source_excerpt}</blockquote>}
            {stale && <p className="validation-error" role="note">This excerpt is no longer in the document's current extracted text, so it is not used for CVs or matching. Re-link it if the same words are still in the document, or reject it.</p>}
            <div className="evidence-actions">
              {stale && item.source_excerpt && <button className="button button-secondary" disabled={busy} onClick={() => runAction(() => onRelink(item.id, item.source_excerpt as string), "Evidence re-linked to the current extracted text. Your review decision is unchanged.", "Re-linking evidence…")} type="button">Re-link to current text</button>}
              {item.confirmation_status !== "candidate_confirmed" && <button className="button button-primary" disabled={busy || stale} onClick={() => void review(item.id, "candidate_confirmed", "Evidence marked candidate-confirmed.", "Confirming evidence…")} type="button">Confirm evidence</button>}
              {item.confirmation_status !== "rejected" && <button className="button button-danger-quiet" disabled={busy} onClick={() => void review(item.id, "rejected", "Evidence rejected and excluded from CV generation.", "Rejecting evidence…")} type="button">Reject</button>}
              {source && <button className="text-button" disabled={busy} onClick={() => runAction(async () => setTextByDocument({ ...textByDocument, [source.id]: await onGetText(source.id) }), undefined, "Loading source text…")} type="button">{text ? "Refresh source text" : "Review source text"}</button>}
            </div>
            {text && <details className="source-review"><summary>Extracted source text <span>Unverified content</span></summary><pre className="source-text">{text.text || "No readable text."}</pre></details>}
          </article>;
        })}</div>}
      </section>
      <form className="panel form-panel" onSubmit={createEvidence}>
        <div className="section-title"><div><p className="eyebrow">Add a review item</p><h2>Record evidence from a source</h2></div></div>
        <p className="muted">The source excerpt must exactly match text from a successful extraction. New evidence always starts unreviewed.</p>
        {eligibleDocuments.length === 0 ? <EmptyState title="No extracted documents available" text="Extract readable text from a PDF, DOCX or TXT document first." /> : <div className="form-grid">
          <Field className="full-span" label="Source document"><select required value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Choose a document</option>{eligibleDocuments.map((document) => <option key={document.id} value={document.id}>{document.original_filename}</option>)}</select></Field>
          <Field label="Evidence category"><select value={category} onChange={(event) => setCategory(event.target.value as EvidenceCategory)}>{categories.map((value) => <option key={value} value={value}>{categoryLabels[value]}</option>)}</select></Field>
          <Field label="Short source section (optional)"><input maxLength={200} placeholder="For example, Platform Engineer" value={sourceSection} onChange={(event) => setSourceSection(event.target.value)} /></Field>
          <Field className="full-span" label="Evidence description" hint="Describe what this source says; do not add unverified details."><input maxLength={2000} required value={description} onChange={(event) => setDescription(event.target.value)} /></Field>
          <Field className="full-span" label="Exact source excerpt"><textarea maxLength={5000} required rows={3} value={excerpt} onChange={(event) => setExcerpt(event.target.value)} /></Field>
          {sourceId && <div className="full-span"><button className="text-button" disabled={busy} onClick={() => runAction(async () => { const text = await onGetText(sourceId); setTextByDocument({ ...textByDocument, [sourceId]: text }); }, undefined, "Loading source text…")} type="button">Load source text for reference</button>{textByDocument[sourceId] && <pre className="source-text source-text-compact">{textByDocument[sourceId].text}</pre>}</div>}
        </div>}
        <div className="form-footer"><span className="muted">Confirmation requires a separate review action.</span><button className="button button-primary" disabled={eligibleDocuments.length === 0 || busy} type="submit">Save unreviewed evidence</button></div>
      </form>
    </div>
  );
}

export function JobsView({
  jobs,
  onCreate,
  busy,
  runAction,
}: {
  jobs: JobDescription[];
  onCreate: (payload: { job_title: string; company?: string; source_url?: string; description: string }) => Promise<unknown>;
  busy: boolean;
  runAction: RunAction;
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const jobTitle = String(form.get("job_title") || "").trim();
    const description = String(form.get("description") || "").trim();
    const company = String(form.get("company") || "").trim();
    const sourceUrl = String(form.get("source_url") || "").trim();
    if (!jobTitle || !description) return;
    runAction(async () => {
      await onCreate({ job_title: jobTitle, description, ...(company && { company }), ...(sourceUrl && { source_url: sourceUrl }) });
      formElement.reset();
    }, "Job description saved.", "Saving job description…");
  }

  return <div className="view-stack">
    <PageHeading eyebrow="Application targets" title="Job descriptions" description="Save a role's complete description first. Job text is treated as untrusted input, never as candidate evidence." />
    <form className="panel form-panel" onSubmit={submit}>
      <div className="section-title"><div><p className="eyebrow">New opportunity</p><h2>Save a job description</h2></div></div>
      <div className="form-grid">
        <Field label="Job title" required><input maxLength={240} name="job_title" required /></Field>
        <Field label="Company"><input maxLength={200} name="company" /></Field>
        <Field className="full-span" label="Source URL"><input name="source_url" placeholder="https://" type="url" /></Field>
        <Field className="full-span" label="Full job description" hint="Include responsibilities and requirements so matching has enough context." required><textarea maxLength={50000} minLength={1} name="description" required rows={9} /></Field>
      </div>
      <div className="form-footer"><span className="muted">Saved roles are retained independently from CV drafts.</span><button className="button button-primary" disabled={busy} type="submit">Save job description</button></div>
    </form>
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Saved locally</p><h2>Saved roles</h2></div><span className="count-pill">{jobs.length}</span></div>
      {jobs.length === 0 ? <EmptyState title="No job descriptions saved" text="Paste a role above to start a job-specific CV workflow." /> : <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}><div className="job-card-title"><div><h3>{job.job_title}</h3><p>{job.company || "Company not provided"} · Added {formatDate(job.created_at)}{job.source_job_listing_id ? " · Imported from discovered jobs" : ""}</p></div>{job.source_url && <a className="text-button" href={job.source_url} rel="noreferrer" target="_blank">Open source <span aria-hidden="true">↗</span></a>}</div><details><summary>View full description</summary><p className="job-description">{job.description}</p></details></article>)}</div>}
    </section>
  </div>;
}

export function DraftsView({
  data,
  initialJobId = "",
  onGenerate,
  onCreateExport,
  onDownloadExport,
  busy,
  runAction,
}: {
  data: WorkspaceData;
  initialJobId?: string;
  onGenerate: (jobId: string, sourceDocumentId?: string) => Promise<unknown>;
  onCreateExport: (jobId: string, draftId: string, format: ExportFormat) => Promise<unknown>;
  onDownloadExport: (jobId: string, draftId: string, exportId: string, filename: string) => Promise<unknown>;
  busy: boolean;
  runAction: RunAction;
}) {
  const [jobId, setJobId] = useState(initialJobId);
  const [sourceDocumentId, setSourceDocumentId] = useState("");
  const selectedJob = data.jobs.find((job) => job.id === jobId);
  const sourceCvs = data.documents.filter((document) => data.extractions[document.id]?.status === "succeeded");
  return <div className="view-stack">
    <PageHeading eyebrow="Evidence-backed applications" title="Tailored CVs" description="Check how your records match a saved role, then write, review and approve a tailored CV. Unsupported requirements remain gaps, not candidate claims." />
    <section className="panel generation-panel"><div><p className="eyebrow">Create a new draft</p><h2>Select a saved job</h2><p className="muted">Analysis and writing run locally on this computer and use your profile and candidate-confirmed evidence only.</p></div><div className="generation-controls"><select aria-label="Saved job description" value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Choose a job description</option>{data.jobs.map((job) => <option key={job.id} value={job.id}>{job.job_title}{job.company ? ` · ${job.company}` : ""}</option>)}</select><select aria-label="Uploaded CV to check" value={sourceDocumentId} onChange={(event) => setSourceDocumentId(event.target.value)}><option value="">No uploaded CV selected</option>{sourceCvs.map((document) => <option key={document.id} value={document.id}>{document.original_filename}</option>)}</select><button className="button button-primary" disabled={!jobId || busy} onClick={() => runAction(() => onGenerate(jobId, sourceDocumentId || undefined), generationMessage, "Writing CV draft…")} type="button">{busy ? "Working…" : "Generate CV draft"}</button></div>{data.jobs.length === 0 && <p className="inline-note">Save a job description before generating a draft.</p>}{selectedJob?.source_job_listing_id && <p className="inline-note">Imported from a discovered listing. Check its Kenya eligibility below before applying.</p>}<p className="inline-note">Your uploaded CV is only read to check its layout and point out statements to confirm. It is never changed or replaced.</p></section>
    {selectedJob && <JobFitPanel jobId={selectedJob.id} profileId={data.profile.id} refreshKey={data} />}
    {selectedJob && <AtsPanel busy={busy} experiences={data.experiences} jobId={selectedJob.id} profileId={data.profile.id} refreshKey={data} runAction={runAction} sourceDocumentId={sourceDocumentId} />}
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Saved versions</p><h2>CV drafts</h2></div><span className="count-pill">{data.drafts.length}</span></div>
      {data.drafts.length === 0 ? <EmptyState title="No CV drafts yet" text="Generated and failed attempts will appear here. Each attempt is saved separately." /> : <div className="draft-list">{data.drafts.map((draft) => {
        const job = data.jobs.find((item) => item.id === draft.job_description_id);
        const draftExports = data.exports.filter((item) => item.cv_draft_id === draft.id);
        const review = draft.structured_content?.review;
        const awaitingApproval = Boolean(review && review.approval_status !== "approved");
        const hasContent = draft.status !== "failed" && Boolean(draft.generated_content);
        const issues = draft.validation_results.issues ?? [];
        return <article className="draft-card" key={draft.id}>
          <div className="draft-header"><div><span className={`status-pill ${draft.status}`}>{DRAFT_STATUS_LABELS[draft.status]}</span>{review && <span className="ats-basis">{review.parent_draft_id ? "Edited version" : "Reviewed writer"}</span>}<h3>{job?.job_title || "Saved job"}{job?.company ? ` · ${job.company}` : ""}</h3><p>Created {formatDate(draft.created_at)}</p></div></div>
          {draft.status === "needs_review" && <p className="inline-note">This draft is saved but incomplete: your records do not yet support every part of the CV layout. Nothing was invented to fill the gaps. Add the missing evidence and generate again, or approve it as incomplete to export it.</p>}
          {hasContent && review && <DraftReview busy={busy} draft={draft} profileId={data.profile.id} runAction={runAction} />}
          {hasContent ? <details className="draft-content"><summary>Preview CV text</summary><pre>{draft.generated_content}</pre></details> : <p className="validation-error">This draft failed validation. It is preserved for review, but cannot be exported.</p>}
          {(draft.validation_results.errors.length > 0 || issues.length > 0 || draft.validation_results.gaps.length > 0 || draft.validation_results.warnings.length > 0) && <div className="validation-results">
            {draft.validation_results.errors.length > 0 && <ResultList title="Validation errors" items={draft.validation_results.errors} kind="error" />}
            {(["experience_evidence", "profile_evidence"] as const).map((group) => {
              const grouped = issues.filter((issue) => issue.group === group);
              return grouped.length > 0 && <section className="result-list gap" key={group}><h4>{ISSUE_GROUP_LABELS[group]}</h4><ul>{grouped.map((issue, index) => <li key={index}><strong>{issue.message}</strong> {issue.action}</li>)}</ul></section>;
            })}
            {draft.validation_results.gaps.length > 0 && <details className="result-list gap"><summary>Job requirements not shown on this CV ({draft.validation_results.gaps.length})</summary><ul>{draft.validation_results.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul><p className="muted">Answer them in the requirement review above if any are genuinely true for you.</p></details>}
            {draft.validation_results.warnings.length > 0 && <ResultList title="Notes" items={draft.validation_results.warnings} kind="warning" />}
          </div>}
          {hasContent && job && <div className="draft-export-actions"><span className="muted">{awaitingApproval ? "Approve this draft to export it:" : "Export validated version:"}</span>{(["pdf", "docx"] as const).map((format) => <button className="button button-secondary" disabled={busy || awaitingApproval} key={format} onClick={() => runAction(() => onCreateExport(job.id, draft.id, format), `${format.toUpperCase()} export created.`, `Creating ${format.toUpperCase()} export…`)} type="button">Export {format.toUpperCase()}</button>)}</div>}
          {draftExports.length > 0 && job && <div className="draft-export-list"><strong>Exports</strong>{draftExports.map((item) => <div className="export-row" key={item.id}><span>{item.export_format.toUpperCase()} · {formatDate(item.created_at)}{item.page_count ? ` · ${item.page_count} page${item.page_count === 1 ? "" : "s"}` : ""}</span><button className="text-button" disabled={busy} onClick={() => runAction(() => onDownloadExport(job.id, draft.id, item.id, item.filename), "Export downloaded.", "Downloading export…")} type="button">Download</button></div>)}</div>}
        </article>;
      })}</div>}
    </section>
  </div>;
}

const DRAFT_STATUS_LABELS: Record<CvDraft["status"], string> = {
  generated: "Validated draft",
  needs_review: "Incomplete: needs your review",
  failed: "Failed validation",
};
const ISSUE_GROUP_LABELS = {
  experience_evidence: "Work experience evidence",
  profile_evidence: "Profile details",
} as const;

function generationMessage(result: unknown): string {
  const draft = result as CvDraft | undefined;
  if (draft?.status === "needs_review") {
    const count = draft.validation_results.issues?.length ?? 0;
    return `Draft saved, but incomplete (${count} item${count === 1 ? "" : "s"} to address). See the draft below; nothing was invented to fill the gaps.`;
  }
  return "CV draft written and saved. Review the changes, then approve it for export.";
}

export function ExportsView({
  data,
  onDownload,
  busy,
  runAction,
}: {
  data: WorkspaceData;
  onDownload: (jobId: string, draftId: string, exportId: string, filename: string) => Promise<unknown>;
  busy: boolean;
  runAction: RunAction;
}) {
  const drafts = new Map(data.drafts.map((draft) => [draft.id, draft]));
  const jobs = new Map(data.jobs.map((job) => [job.id, job]));
  return <div className="view-stack">
    <PageHeading eyebrow="Download center" title="CV exports" description="Download private PDF and DOCX files generated from validated saved drafts." />
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Private files</p><h2>Generated exports</h2></div><span className="count-pill">{data.exports.length}</span></div>
      {data.exports.length === 0 ? <EmptyState title="No exports generated" text="Open a validated CV draft and create a PDF or DOCX export." /> : <div className="table-scroll"><table><thead><tr><th>File</th><th>Job</th><th>Created</th><th>Size</th><th>Pages</th><th><span className="sr-only">Download action</span></th></tr></thead><tbody>{data.exports.map((item) => {
        const draft = drafts.get(item.cv_draft_id);
        const job = draft ? jobs.get(draft.job_description_id) : undefined;
        return <tr key={item.id}><td><span className="file-type">{item.export_format.toUpperCase()}</span>{item.filename}</td><td>{job?.job_title || "Job unavailable"}</td><td>{formatDate(item.created_at)}</td><td>{formatBytes(item.size_bytes)}</td><td>{item.page_count ?? "Word layout"}</td><td>{job && draft && <button className="button button-secondary" disabled={busy} onClick={() => runAction(() => onDownload(job.id, draft.id, item.id, item.filename), "Export downloaded.", "Downloading export…")} type="button">Download</button>}</td></tr>;
      })}</tbody></table></div>}
    </section>
    <p className="inline-note">DOCX page count varies by word processor and installed fonts. Export files are stored in the backend's private local document storage.</p>
  </div>;
}

export function PageHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <header className="page-heading"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></header>;
}

export function Field({ label, required, hint, className = "", children }: { label: string; required?: boolean; hint?: string; className?: string; children: ReactNode }) {
  return <label className={`field ${className}`}><span>{label}{required && <span className="required-mark" aria-hidden="true"> *</span>}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function EmptyState({ title, text }: { title: string; text: string }) {
  return <div className="empty-state"><span aria-hidden="true">○</span><h3>{title}</h3><p>{text}</p></div>;
}

type FormValue = string | boolean;
type FormValues = Record<string, FormValue>;
type ProfileRecord = { id: string };

interface RecordField {
  name: string;
  label: string;
  type?: "text" | "date" | "email" | "textarea" | "select" | "checkbox";
  required?: boolean;
  maxLength?: number;
  rows?: number;
  hint?: string;
  options?: { label: string; value: string }[];
  showWhen?: (values: FormValues) => boolean;
}

interface RecordManagerProps<T extends ProfileRecord, Input> {
  title: string;
  records: T[];
  empty: string;
  busy: boolean;
  createLabel: string;
  onCreate: (input: Input) => Promise<boolean>;
  onUpdate: (id: string, input: Input) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
  renderEditor: (
    record: T | null,
    onSubmit: (input: Input) => Promise<boolean>,
    onCancel: () => void,
  ) => ReactNode;
  renderRecord: (record: T) => ReactNode;
}

function RecordManager<T extends ProfileRecord, Input>({
  title,
  records,
  empty,
  busy,
  createLabel,
  onCreate,
  onUpdate,
  onDelete,
  renderEditor,
  renderRecord,
}: RecordManagerProps<T, Input>) {
  const [editing, setEditing] = useState<T | null | undefined>(undefined);
  const [deleteId, setDeleteId] = useState<string | null>(null);

  async function submit(input: Input) {
    const succeeded = editing
      ? await onUpdate(editing.id, input)
      : await onCreate(input);
    if (succeeded) setEditing(undefined);
    return succeeded;
  }

  async function confirmDelete(id: string) {
    if (await onDelete(id)) setDeleteId(null);
  }

  return (
    <section className="record-group">
      <div className="record-group-heading">
        <h3>{title}</h3>
        <span className="count-pill">{records.length}</span>
      </div>
      {records.length ? (
        <div className="record-list">
          {records.map((record) => (
            <div className="managed-record" key={record.id}>
              {renderRecord(record)}
              <div className="record-actions">
                <button className="text-button" disabled={busy} onClick={() => setEditing(record)}>Edit</button>
                {deleteId === record.id ? (
                  <span className="delete-confirmation">
                    <span>Delete this record?</span>
                    <button className="text-button" disabled={busy} onClick={() => void confirmDelete(record.id)}>Confirm delete</button>
                    <button className="text-button" disabled={busy} onClick={() => setDeleteId(null)}>Cancel</button>
                  </span>
                ) : (
                  <button className="text-button danger-text-button" disabled={busy} onClick={() => { setEditing(undefined); setDeleteId(record.id); }}>Delete</button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted record-empty">{empty}</p>
      )}
      {editing !== undefined ? (
        renderEditor(editing, submit, () => setEditing(undefined))
      ) : (
        <button className="button button-secondary record-add" disabled={busy} onClick={() => { setDeleteId(null); setEditing(null); }}>{createLabel}</button>
      )}
    </section>
  );
}

function Record({
  title,
  subtitle,
  detail,
  extra,
}: {
  title: string;
  subtitle: string;
  detail?: string | null;
  extra?: ReactNode;
}) {
  return <article className="record"><strong>{title}</strong><span>{subtitle}</span>{detail && <small>{detail}</small>}{extra}</article>;
}

function RecordForm<Input>({
  fields,
  values: initialValues,
  submitLabel,
  toPayload,
  onSubmit,
  onCancel,
}: {
  fields: RecordField[];
  values: FormValues;
  submitLabel: string;
  toPayload: (values: FormValues) => Input;
  onSubmit: (payload: Input) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [values, setValues] = useState(initialValues);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSubmit(toPayload(values));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="record-editor" onSubmit={(event) => void submit(event)}>
      <div className="record-editor-grid">
        {fields.filter((field) => !field.showWhen || field.showWhen(values)).map((field) => (
          <Field key={field.name} label={field.label} required={field.required} hint={field.hint}>
            {field.type === "textarea" ? (
              <textarea
                maxLength={field.maxLength}
                required={field.required}
                rows={field.rows || 3}
                value={String(values[field.name] || "")}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
              />
            ) : field.type === "checkbox" ? (
              <input
                checked={Boolean(values[field.name])}
                type="checkbox"
                onChange={(event) => setValues({ ...values, [field.name]: event.target.checked })}
              />
            ) : field.type === "select" ? (
              <select
                value={String(values[field.name] || "")}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
              >
                <option value="">Not specified</option>
                {(field.options || []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            ) : (
              <input
                maxLength={field.maxLength}
                required={field.required}
                type={field.type || "text"}
                value={String(values[field.name] || "")}
                onChange={(event) => setValues({ ...values, [field.name]: event.target.value })}
              />
            )}
          </Field>
        ))}
      </div>
      <div className="record-editor-actions">
        <button className="button button-primary" disabled={saving} type="submit">{saving ? "Saving…" : submitLabel}</button>
        <button className="button button-secondary" disabled={saving} onClick={onCancel} type="button">Cancel</button>
      </div>
    </form>
  );
}

function WorkExperienceEditor({
  record,
  onSubmit,
  onCancel,
}: {
  record: WorkExperience | null;
  onSubmit: (payload: WorkExperienceInput) => Promise<boolean>;
  onCancel: () => void;
}) {
  const fields: RecordField[] = [
    { name: "job_title", label: "Job title", required: true, maxLength: 200 },
    { name: "employer", label: "Employer", required: true, maxLength: 200 },
    { name: "location", label: "Location", maxLength: 200 },
    { name: "work_arrangement", label: "Work arrangement", type: "select", options: [
      { label: "Remote", value: "remote" }, { label: "Hybrid", value: "hybrid" }, { label: "On-site", value: "onsite" },
    ] },
    { name: "start_date", label: "Start date", type: "date", required: true },
    { name: "current_role", label: "Current role", type: "checkbox" },
    { name: "end_date", label: "End date", type: "date", showWhen: (values) => !values.current_role },
    { name: "description", label: "Role description", type: "textarea", rows: 3, maxLength: 5000 },
    { name: "achievements", label: "Achievements", type: "textarea", rows: 4, maxLength: 2000, hint: "One candidate-confirmed achievement per line. Do not add unverified metrics or claims." },
  ];
  return <RecordForm
    fields={fields}
    values={{
      job_title: record?.job_title || "",
      employer: record?.employer || "",
      location: record?.location || "",
      work_arrangement: record?.work_arrangement || "",
      start_date: record?.start_date || "",
      end_date: record?.end_date || "",
      current_role: record?.current_role || false,
      description: record?.description || "",
      achievements: record?.achievements.join("\n") || "",
    }}
    submitLabel={record ? "Save work experience" : "Save new work experience"}
    onSubmit={onSubmit}
    onCancel={onCancel}
    toPayload={(values) => ({
      job_title: textValue(values, "job_title"),
      employer: textValue(values, "employer"),
      location: optionalText(values, "location"),
      work_arrangement: optionalText(values, "work_arrangement") as WorkExperienceInput["work_arrangement"],
      start_date: textValue(values, "start_date"),
      end_date: Boolean(values.current_role) ? null : optionalText(values, "end_date"),
      current_role: Boolean(values.current_role),
      description: optionalText(values, "description"),
      achievements: textValue(values, "achievements").split("\n").map((item) => item.trim()).filter(Boolean),
    })}
  />;
}

function EducationEditor({
  record,
  onSubmit,
  onCancel,
}: {
  record: Education | null;
  onSubmit: (payload: EducationInput) => Promise<boolean>;
  onCancel: () => void;
}) {
  return <RecordForm
    fields={[
      { name: "qualification", label: "Qualification", required: true, maxLength: 200 },
      { name: "institution", label: "Institution", required: true, maxLength: 200 },
      { name: "field_of_study", label: "Field of study", maxLength: 200 },
      { name: "start_date", label: "Start date", type: "date", required: true },
      { name: "end_date", label: "End date", type: "date" },
    ]}
    values={{
      qualification: record?.qualification || "",
      institution: record?.institution || "",
      field_of_study: record?.field_of_study || "",
      start_date: record?.start_date || "",
      end_date: record?.end_date || "",
    }}
    submitLabel={record ? "Save education" : "Save new education"}
    onSubmit={onSubmit}
    onCancel={onCancel}
    toPayload={(values) => ({
      qualification: textValue(values, "qualification"),
      institution: textValue(values, "institution"),
      field_of_study: optionalText(values, "field_of_study"),
      start_date: textValue(values, "start_date"),
      end_date: optionalText(values, "end_date"),
    })}
  />;
}

function SkillEditor({
  record,
  onSubmit,
  onCancel,
}: {
  record: Skill | null;
  onSubmit: (payload: SkillInput) => Promise<boolean>;
  onCancel: () => void;
}) {
  return <RecordForm
    fields={[
      { name: "name", label: "Skill", required: true, maxLength: 100 },
      { name: "proficiency_level", label: "Proficiency level", type: "select", options: [
        { label: "Beginner", value: "beginner" }, { label: "Intermediate", value: "intermediate" },
        { label: "Advanced", value: "advanced" }, { label: "Expert", value: "expert" },
      ] },
    ]}
    values={{ name: record?.name || "", proficiency_level: record?.proficiency_level || "" }}
    submitLabel={record ? "Save skill" : "Save new skill"}
    onSubmit={onSubmit}
    onCancel={onCancel}
    toPayload={(values) => ({
      name: textValue(values, "name"),
      proficiency_level: optionalText(values, "proficiency_level") as SkillInput["proficiency_level"],
    })}
  />;
}

function CertificationEditor({
  record,
  onSubmit,
  onCancel,
}: {
  record: Certification | null;
  onSubmit: (payload: CertificationInput) => Promise<boolean>;
  onCancel: () => void;
}) {
  return <RecordForm
    fields={[
      { name: "name", label: "Certification", required: true, maxLength: 200 },
      { name: "issuer", label: "Issuing organization", required: true, maxLength: 200 },
      { name: "issue_date", label: "Issue date", type: "date", required: true },
      { name: "expires_on", label: "Expiry date", type: "date" },
    ]}
    values={{
      name: record?.name || "",
      issuer: record?.issuer || "",
      issue_date: record?.issue_date || "",
      expires_on: record?.expires_on || "",
    }}
    submitLabel={record ? "Save certification" : "Save new certification"}
    onSubmit={onSubmit}
    onCancel={onCancel}
    toPayload={(values) => ({
      name: textValue(values, "name"),
      issuer: textValue(values, "issuer"),
      issue_date: textValue(values, "issue_date"),
      expires_on: optionalText(values, "expires_on"),
    })}
  />;
}

function textValue(values: FormValues, name: string): string {
  return typeof values[name] === "string" ? values[name].trim() : "";
}

function optionalText(values: FormValues, name: string): string | null {
  return textValue(values, name) || null;
}

function ResultList({ title, items, kind }: { title: string; items: string[]; kind: string }) {
  return <section className={`result-list ${kind}`}><h4>{title}</h4><ul>{items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul></section>;
}

interface ProfileFormState {
  name: string;
  contact_email: string;
  contact_phone: string;
  professional_headline: string;
  summary: string;
  location: string;
  remote_work_preference: RemoteWorkPreference | "";
}

function profileForm(data: WorkspaceData): ProfileFormState {
  return {
    name: data.profile.name,
    contact_email: data.profile.contact_email || "",
    contact_phone: data.profile.contact_phone || "",
    professional_headline: data.profile.professional_headline || "",
    summary: data.profile.summary || "",
    location: data.profile.location || "",
    remote_work_preference: data.profile.remote_work_preference || "",
  };
}

function jobTitle(jobs: JobDescription[], jobId: string) {
  return jobs.find((job) => job.id === jobId)?.job_title || "Saved job description";
}

// Same order as the API: newest first, then document, then position in the
// document. Records created together share a timestamp, and the tie-breakers
// keep a card where it is after its status changes.
function compareEvidence(left: CandidateEvidence, right: CandidateEvidence): number {
  return right.created_at.localeCompare(left.created_at)
    || left.source_document_id.localeCompare(right.source_document_id)
    || (left.source_start ?? Number.MAX_SAFE_INTEGER) - (right.source_start ?? Number.MAX_SAFE_INTEGER)
    || left.id.localeCompare(right.id);
}

function statusLabel(status: EvidenceStatus) {
  if (status === "candidate_confirmed") return "Candidate-confirmed";
  if (status === "rejected") return "Rejected";
  return "Unreviewed";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
