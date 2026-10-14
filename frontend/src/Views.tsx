import { useState, type FormEvent } from "react";
import type { ReactNode } from "react";

import type {
  CandidateProfileInput,
  EvidenceCategory,
  EvidenceStatus,
  ExportFormat,
  ExtractedText,
  JobDescription,
  RemoteWorkPreference,
  WorkspaceData,
} from "./api/types";

export type ViewName =
  | "Dashboard"
  | "Profile"
  | "Documents"
  | "Evidence review"
  | "Job descriptions"
  | "Tailored CVs"
  | "Exports";

type RunAction = (action: () => Promise<unknown>, success?: string) => void;

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
  const metrics = [
    ["Documents", data.documents.length, "Documents"],
    ["Saved roles", data.jobs.length, "Job descriptions"],
    ["CV drafts", data.drafts.length, "Tailored CVs"],
    ["Exports", data.exports.length, "Exports"],
  ] as const;

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
      </div>

      <section className="panel privacy-note">
        <span className="privacy-icon" aria-hidden="true">i</span>
        <p><strong>Local workspace</strong> — JobPilot AI does not yet have sign-in or authorization. Keep this application on your trusted local machine and do not expose its API publicly.</p>
      </section>
    </div>
  );
}

export function ProfileView({
  data,
  onSave,
  runAction,
}: {
  data: WorkspaceData;
  onSave: (payload: CandidateProfileInput) => Promise<unknown>;
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
    runAction(() => onSave(payload), "Candidate profile saved.");
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
        <div className="form-footer"><span className="muted">Changes update this profile only; saved CV drafts remain unchanged.</span><button className="button button-primary" type="submit">Save profile</button></div>
      </form>

      <section className="panel">
        <div className="section-title"><div><p className="eyebrow">Candidate history</p><h2>Work, education and skills</h2></div></div>
        <p className="inline-note">These records are loaded from your profile. The current API supports viewing them but does not yet provide create, edit or delete operations for these record types.</p>
        <div className="record-columns">
          <RecordGroup title="Work experience" count={data.experiences.length} empty="No work experience has been added.">
            {data.experiences.map((item) => <Record key={item.id} title={item.job_title} subtitle={`${item.employer} · ${item.start_date}${item.current_role ? " – Present" : item.end_date ? ` – ${item.end_date}` : ""}`} detail={item.description} />)}
          </RecordGroup>
          <RecordGroup title="Education" count={data.education.length} empty="No education has been added.">
            {data.education.map((item) => <Record key={item.id} title={item.qualification} subtitle={`${item.institution}${item.field_of_study ? ` · ${item.field_of_study}` : ""}`} detail={`${item.start_date}${item.end_date ? ` – ${item.end_date}` : ""}`} />)}
          </RecordGroup>
          <RecordGroup title="Skills" count={data.skills.length} empty="No skills have been added.">
            {data.skills.map((item) => <Record key={item.id} title={item.name} subtitle={item.proficiency_level || "Proficiency not specified"} />)}
          </RecordGroup>
          <RecordGroup title="Certifications" count={data.certifications.length} empty="No certifications have been added.">
            {data.certifications.map((item) => <Record key={item.id} title={item.name} subtitle={`${item.issuer} · ${item.issue_date}`} />)}
          </RecordGroup>
        </div>
      </section>
    </div>
  );
}

export function DocumentsView({
  data,
  onUpload,
  onExtract,
  onDownload,
  onGetText,
  runAction,
}: {
  data: WorkspaceData;
  onUpload: (file: File) => Promise<unknown>;
  onExtract: (documentId: string) => Promise<unknown>;
  onDownload: (documentId: string, filename: string) => Promise<unknown>;
  onGetText: (documentId: string) => Promise<ExtractedText>;
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
    }, "Document uploaded as a new, separate source file.");
  }

  return (
    <div className="view-stack">
      <PageHeading eyebrow="Source documents" title="Documents" description="Upload original documents, extract their text locally and keep every source file intact." />
      <form className="panel upload-panel" onSubmit={submit}>
        <div><h2>Upload a document</h2><p className="muted">PDF, DOCX or UTF-8 TXT · up to 10 MB. Existing files are never replaced.</p></div>
        <div className="upload-controls"><input aria-label="Choose a document" accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" onChange={(event) => setFile(event.target.files?.[0] || null)} required type="file" /><button className="button button-primary" disabled={!file} type="submit">Upload new document</button></div>
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
                <div className="row-actions"><button className="button button-secondary" onClick={() => runAction(() => onDownload(document.id, document.original_filename), "Source document downloaded.")} type="button">Download</button><button className="button button-secondary" onClick={() => runAction(() => onExtract(document.id), "Text extraction completed.")} type="button">{extraction ? "Retry extraction" : "Extract text"}</button>{extraction?.status === "succeeded" && <button className="text-button" onClick={() => runAction(async () => setSelectedText(await onGetText(document.id)))} type="button">View extracted text</button>}</div>
              </article>;
            })}
          </div>
        )}
        <p className="inline-note">Source uploads are immutable and the API has no document deletion endpoint. Extracted text is unverified source content, not proof of a claim. Scanned PDFs do not receive OCR.</p>
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
  runAction,
}: {
  data: WorkspaceData;
  onGetText: (documentId: string) => Promise<ExtractedText>;
  onCreate: (payload: { source_document_id: string; category: string; description: string; source_excerpt: string; source_section?: string }) => Promise<unknown>;
  onSetStatus: (id: string, status: EvidenceStatus) => Promise<unknown>;
  runAction: RunAction;
}) {
  const [sourceId, setSourceId] = useState("");
  const [category, setCategory] = useState<EvidenceCategory>("achievement");
  const [description, setDescription] = useState("");
  const [sourceSection, setSourceSection] = useState("");
  const [excerpt, setExcerpt] = useState("");
  const [textByDocument, setTextByDocument] = useState<Record<string, ExtractedText>>({});

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
    }, "Evidence saved as unreviewed. It has not been confirmed.");
  }

  const eligibleDocuments = data.documents.filter((document) => data.extractions[document.id]?.status === "succeeded");
  return (
    <div className="view-stack">
      <PageHeading eyebrow="Review before use" title="Evidence review" description="Extracted text is unverified. Only information you explicitly confirm can support tailored CV claims." />
      <section className="panel trust-banner"><span aria-hidden="true">!</span><p><strong>Nothing is confirmed automatically.</strong> Review the source and evidence description before marking a claim candidate-confirmed. Rejected or unreviewed evidence is excluded from CV generation.</p></section>
      <section className="panel">
        <div className="section-title"><div><p className="eyebrow">Source references</p><h2>Candidate evidence</h2></div><span className="count-pill">{data.evidence.length}</span></div>
        {data.evidence.length === 0 ? <EmptyState title="No evidence records yet" text="Create a record from text extracted from one of your source documents." /> : <div className="evidence-list">{data.evidence.map((item) => {
          const source = data.documents.find((document) => document.id === item.source_document_id);
          const text = textByDocument[item.source_document_id];
          return <article className="evidence-card" key={item.id}>
            <div className="evidence-card-head"><div><span className={`status-pill evidence-${item.confirmation_status}`}>{statusLabel(item.confirmation_status)}</span><span className="category-label">{categoryLabels[item.category]}</span></div><small>{formatDate(item.created_at)}</small></div>
            <h3>{item.description}</h3>
            <p className="source-reference">Source: {source?.original_filename || "Source document unavailable"}{item.source_section ? ` · ${item.source_section}` : ""}</p>
            {item.source_excerpt && <blockquote>{item.source_excerpt}</blockquote>}
            <div className="evidence-actions">
              {item.confirmation_status !== "candidate_confirmed" && <button className="button button-primary" onClick={() => runAction(() => onSetStatus(item.id, "candidate_confirmed"), "Evidence marked candidate-confirmed.")} type="button">Confirm evidence</button>}
              {item.confirmation_status !== "rejected" && <button className="button button-danger-quiet" onClick={() => runAction(() => onSetStatus(item.id, "rejected"), "Evidence rejected and excluded from CV generation.")} type="button">Reject</button>}
              {source && <button className="text-button" onClick={() => runAction(async () => setTextByDocument({ ...textByDocument, [source.id]: await onGetText(source.id) }))} type="button">{text ? "Refresh source text" : "Review source text"}</button>}
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
          {sourceId && <div className="full-span"><button className="text-button" onClick={() => runAction(async () => { const text = await onGetText(sourceId); setTextByDocument({ ...textByDocument, [sourceId]: text }); })} type="button">Load source text for reference</button>{textByDocument[sourceId] && <pre className="source-text source-text-compact">{textByDocument[sourceId].text}</pre>}</div>}
        </div>}
        <div className="form-footer"><span className="muted">Confirmation requires a separate review action.</span><button className="button button-primary" disabled={eligibleDocuments.length === 0} type="submit">Save unreviewed evidence</button></div>
      </form>
    </div>
  );
}

export function JobsView({
  jobs,
  onCreate,
  runAction,
}: {
  jobs: JobDescription[];
  onCreate: (payload: { job_title: string; company?: string; source_url?: string; description: string }) => Promise<unknown>;
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
    }, "Job description saved.");
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
      <div className="form-footer"><span className="muted">Saved roles are retained independently from CV drafts.</span><button className="button button-primary" type="submit">Save job description</button></div>
    </form>
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Saved locally</p><h2>Saved roles</h2></div><span className="count-pill">{jobs.length}</span></div>
      {jobs.length === 0 ? <EmptyState title="No job descriptions saved" text="Paste a role above to start a job-specific CV workflow." /> : <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}><div className="job-card-title"><div><h3>{job.job_title}</h3><p>{job.company || "Company not provided"} · Added {formatDate(job.created_at)}</p></div>{job.source_url && <a className="text-button" href={job.source_url} rel="noreferrer" target="_blank">Open source <span aria-hidden="true">↗</span></a>}</div><details><summary>View full description</summary><p className="job-description">{job.description}</p></details></article>)}</div>}
    </section>
  </div>;
}

export function DraftsView({
  data,
  onGenerate,
  onCreateExport,
  onDownloadExport,
  runAction,
}: {
  data: WorkspaceData;
  onGenerate: (jobId: string) => Promise<unknown>;
  onCreateExport: (jobId: string, draftId: string, format: ExportFormat) => Promise<unknown>;
  onDownloadExport: (jobId: string, draftId: string, exportId: string, filename: string) => Promise<unknown>;
  runAction: RunAction;
}) {
  const [jobId, setJobId] = useState("");
  return <div className="view-stack">
    <PageHeading eyebrow="Evidence-backed applications" title="Tailored CVs" description="Generate and review a separate CV draft for a saved role. Unsupported requirements remain gaps, not candidate claims." />
    <section className="panel generation-panel"><div><p className="eyebrow">Create a new draft</p><h2>Select a saved job</h2><p className="muted">Generation uses candidate profile data and candidate-confirmed evidence only.</p></div><div className="generation-controls"><select aria-label="Saved job description" value={jobId} onChange={(event) => setJobId(event.target.value)}><option value="">Choose a job description</option>{data.jobs.map((job) => <option key={job.id} value={job.id}>{job.job_title}{job.company ? ` · ${job.company}` : ""}</option>)}</select><button className="button button-primary" disabled={!jobId} onClick={() => runAction(() => onGenerate(jobId), "CV draft generated and saved.")} type="button">Generate CV draft</button></div>{data.jobs.length === 0 && <p className="inline-note">Save a job description before generating a draft.</p>}</section>
    <section className="panel"><div className="section-title"><div><p className="eyebrow">Saved versions</p><h2>CV drafts</h2></div><span className="count-pill">{data.drafts.length}</span></div>
      {data.drafts.length === 0 ? <EmptyState title="No CV drafts yet" text="Generated and failed attempts will appear here. Each attempt is saved separately." /> : <div className="draft-list">{data.drafts.map((draft) => {
        const job = data.jobs.find((item) => item.id === draft.job_description_id);
        const draftExports = data.exports.filter((item) => item.cv_draft_id === draft.id);
        return <article className="draft-card" key={draft.id}>
          <div className="draft-header"><div><span className={`status-pill ${draft.status}`}>{draft.status === "generated" ? "Validated draft" : "Needs more evidence"}</span><h3>{job?.job_title || "Saved job"}{job?.company ? ` · ${job.company}` : ""}</h3><p>Created {formatDate(draft.created_at)}</p></div></div>
          {draft.status === "generated" && draft.generated_content ? <details className="draft-content"><summary>Review generated CV text</summary><pre>{draft.generated_content}</pre></details> : <p className="validation-error">This draft failed validation. It is preserved for review, but cannot be exported.</p>}
          {(draft.validation_results.errors.length > 0 || draft.validation_results.gaps.length > 0 || draft.validation_results.warnings.length > 0) && <div className="validation-results">
            {draft.validation_results.errors.length > 0 && <ResultList title="Validation issues" items={draft.validation_results.errors} kind="error" />}
            {draft.validation_results.gaps.length > 0 && <ResultList title="Evidence and skill gaps" items={draft.validation_results.gaps} kind="gap" />}
            {draft.validation_results.warnings.length > 0 && <ResultList title="Notes" items={draft.validation_results.warnings} kind="warning" />}
          </div>}
          {draft.status === "generated" && job && <div className="draft-export-actions"><span className="muted">Export validated version:</span>{(["pdf", "docx"] as const).map((format) => <button className="button button-secondary" key={format} onClick={() => runAction(() => onCreateExport(job.id, draft.id, format), `${format.toUpperCase()} export created.`)} type="button">Export {format.toUpperCase()}</button>)}</div>}
          {draftExports.length > 0 && job && <div className="draft-export-list"><strong>Exports</strong>{draftExports.map((item) => <div className="export-row" key={item.id}><span>{item.export_format.toUpperCase()} · {formatDate(item.created_at)}{item.page_count ? ` · ${item.page_count} page${item.page_count === 1 ? "" : "s"}` : ""}</span><button className="text-button" onClick={() => runAction(() => onDownloadExport(job.id, draft.id, item.id, item.filename), "Export downloaded.")} type="button">Download</button></div>)}</div>}
        </article>;
      })}</div>}
    </section>
  </div>;
}

export function ExportsView({
  data,
  onDownload,
  runAction,
}: {
  data: WorkspaceData;
  onDownload: (jobId: string, draftId: string, exportId: string, filename: string) => Promise<unknown>;
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
        return <tr key={item.id}><td><span className="file-type">{item.export_format.toUpperCase()}</span>{item.filename}</td><td>{job?.job_title || "Job unavailable"}</td><td>{formatDate(item.created_at)}</td><td>{formatBytes(item.size_bytes)}</td><td>{item.page_count ?? "Word layout"}</td><td>{job && draft && <button className="button button-secondary" onClick={() => runAction(() => onDownload(job.id, draft.id, item.id, item.filename), "Export downloaded.")} type="button">Download</button>}</td></tr>;
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

function RecordGroup({ title, count, empty, children }: { title: string; count: number; empty: string; children: ReactNode }) {
  return <section className="record-group"><div><h3>{title}</h3><span className="count-pill">{count}</span></div>{count ? <div className="record-list">{children}</div> : <p className="muted">{empty}</p>}</section>;
}

function Record({ title, subtitle, detail }: { title: string; subtitle: string; detail?: string | null }) {
  return <article className="record"><strong>{title}</strong><span>{subtitle}</span>{detail && <small>{detail}</small>}</article>;
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
