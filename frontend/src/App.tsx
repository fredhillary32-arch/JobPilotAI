import { useEffect, useRef, useState, type FormEvent } from "react";

import { api, ApiError, loadWorkspace, saveBlob } from "./api/client";
import type {
  CandidateProfileInput,
  CertificationInput,
  EducationInput,
  EvidenceStatus,
  ExportFormat,
  SkillInput,
  WorkExperienceInput,
  WorkspaceData,
} from "./api/types";
import {
  DashboardView,
  DocumentsView,
  DraftsView,
  EvidenceView,
  ExportsView,
  Field,
  JobsView,
  ProfileView,
  type ViewName,
} from "./Views";

const navigation: { name: ViewName; label: string; icon: string }[] = [
  { name: "Dashboard", label: "Overview", icon: "⌂" },
  { name: "Profile", label: "Candidate profile", icon: "◎" },
  { name: "Documents", label: "Documents", icon: "▤" },
  { name: "Evidence review", label: "Evidence review", icon: "✓" },
  { name: "Job descriptions", label: "Job descriptions", icon: "▱" },
  { name: "Tailored CVs", label: "Tailored CVs", icon: "▧" },
  { name: "Exports", label: "Exports", icon: "⇩" },
];

const configuredProfileId = import.meta.env.VITE_CANDIDATE_PROFILE_ID?.trim();

export default function App() {
  const [profileId, setProfileId] = useState(
    () => configuredProfileId || window.localStorage.getItem("jobpilot.profileId") || "",
  );
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [activeView, setActiveView] = useState<ViewName>("Dashboard");
  const [loading, setLoading] = useState(
    Boolean(configuredProfileId || window.localStorage.getItem("jobpilot.profileId")),
  );
  const [busy, setBusy] = useState(false);
  const actionLock = useRef(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    if (!profileId) {
      setData(null);
      setLoading(false);
      setLoadError("");
      return;
    }
    let current = true;
    setLoading(true);
    setLoadError("");
    loadWorkspace(profileId)
      .then((workspace) => {
        if (current) {
          setData(workspace);
          setLoading(false);
        }
      })
      .catch((error: unknown) => {
        if (!current) return;
        setData(null);
        setLoadError(errorMessage(error));
        setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [profileId]);

  function selectProfile(id: string) {
    const normalizedId = id.trim();
    window.localStorage.setItem("jobpilot.profileId", normalizedId);
    setProfileId(normalizedId);
    setActiveView("Dashboard");
    setActionError("");
    setNotice("");
  }

  function switchProfile() {
    window.localStorage.removeItem("jobpilot.profileId");
    setProfileId("");
    setData(null);
    setLoadError("");
    setActionError("");
    setNotice("");
  }

  async function runAction(action: () => Promise<unknown>, success?: string): Promise<boolean> {
    if (actionLock.current) return false;
    actionLock.current = true;
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await action();
      if (success) setNotice(success);
      if (profileId) setData(await loadWorkspace(profileId));
      return true;
    } catch (error) {
      setActionError(errorMessage(error));
      if (profileId) {
        try {
          setData(await loadWorkspace(profileId));
        } catch (refreshError) {
          setActionError(
            `${errorMessage(error)} Workspace refresh also failed: ${errorMessage(refreshError)}`,
          );
        }
      }
      return false;
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function saveProfile(payload: CandidateProfileInput) {
    await api.updateProfile(profileId, payload);
  }

  async function uploadDocument(file: File) {
    await api.uploadDocument(profileId, file);
  }

  async function extractDocument(documentId: string) {
    await api.extractDocument(profileId, documentId);
  }

  async function downloadDocument(documentId: string, filename: string) {
    saveBlob(await api.downloadDocument(profileId, documentId), filename);
  }

  async function createEvidence(payload: {
    source_document_id: string;
    category: string;
    description: string;
    source_excerpt: string;
    source_section?: string;
  }) {
    await api.createEvidence(profileId, payload);
  }

  async function setEvidenceStatus(id: string, status: EvidenceStatus) {
    await api.updateEvidenceStatus(profileId, id, status);
  }

  async function createJob(payload: {
    job_title: string;
    company?: string;
    source_url?: string;
    description: string;
  }) {
    await api.createJob(profileId, payload);
  }

  async function generateDraft(jobId: string) {
    await api.generateDraft(profileId, jobId);
  }

  async function createExport(jobId: string, draftId: string, format: ExportFormat) {
    await api.createExport(profileId, jobId, draftId, format);
  }

  async function downloadExport(jobId: string, draftId: string, exportId: string, filename: string) {
    saveBlob(await api.downloadExport(profileId, jobId, draftId, exportId), filename);
  }

  if (loading) {
    return <main className="loading-screen"><div className="spinner" aria-hidden="true" /><p role="status">Connecting to your local JobPilot workspace…</p></main>;
  }
  if (!profileId || !data) {
    return <ProfileStart onSelect={selectProfile} error={loadError} />;
  }

  const view = (() => {
    switch (activeView) {
      case "Profile":
        return <ProfileView
          data={data}
          onSave={saveProfile}
          onCreateExperience={(payload: WorkExperienceInput) => api.createExperience(profileId, payload)}
          onUpdateExperience={(id: string, payload: WorkExperienceInput) => api.updateExperience(profileId, id, payload)}
          onDeleteExperience={(id: string) => api.deleteExperience(profileId, id)}
          onCreateEducation={(payload: EducationInput) => api.createEducation(profileId, payload)}
          onUpdateEducation={(id: string, payload: EducationInput) => api.updateEducation(profileId, id, payload)}
          onDeleteEducation={(id: string) => api.deleteEducation(profileId, id)}
          onCreateSkill={(payload: SkillInput) => api.createSkill(profileId, payload)}
          onUpdateSkill={(id: string, payload: SkillInput) => api.updateSkill(profileId, id, payload)}
          onDeleteSkill={(id: string) => api.deleteSkill(profileId, id)}
          onCreateCertification={(payload: CertificationInput) => api.createCertification(profileId, payload)}
          onUpdateCertification={(id: string, payload: CertificationInput) => api.updateCertification(profileId, id, payload)}
          onDeleteCertification={(id: string) => api.deleteCertification(profileId, id)}
          busy={busy}
          runAction={runAction}
        />;
      case "Documents":
        return <DocumentsView data={data} onUpload={uploadDocument} onExtract={extractDocument} onDownload={downloadDocument} onGetText={(id) => api.getExtractedText(profileId, id)} runAction={runAction} />;
      case "Evidence review":
        return <EvidenceView data={data} onGetText={(id) => api.getExtractedText(profileId, id)} onCreate={createEvidence} onSetStatus={setEvidenceStatus} runAction={runAction} />;
      case "Job descriptions":
        return <JobsView jobs={data.jobs} onCreate={createJob} runAction={runAction} />;
      case "Tailored CVs":
        return <DraftsView data={data} onGenerate={generateDraft} onCreateExport={createExport} onDownloadExport={downloadExport} runAction={runAction} />;
      case "Exports":
        return <ExportsView data={data} onDownload={downloadExport} runAction={runAction} />;
      default:
        return <DashboardView data={data} navigate={setActiveView} />;
    }
  })();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setActiveView("Dashboard"); }} aria-label="JobPilot AI overview">
          <span className="brand-mark">J</span><span>jobpilot<span className="brand-ai">.ai</span><small>CAREER WORKSPACE</small></span>
        </a>
        <p className="nav-caption">Workspace</p>
        <nav aria-label="Main navigation">
          {navigation.map((item) => <button aria-current={activeView === item.name ? "page" : undefined} className={`nav-item${activeView === item.name ? " active" : ""}`} key={item.name} onClick={() => { setActiveView(item.name); setActionError(""); setNotice(""); }}><span className="nav-icon" aria-hidden="true">{item.icon}</span>{item.label}{item.name === "Evidence review" && data.evidence.some((entry) => entry.confirmation_status === "unreviewed") && <span className="nav-count" aria-label="Unreviewed evidence">{data.evidence.filter((entry) => entry.confirmation_status === "unreviewed").length}</span>}</button>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="profile-mini"><span className="avatar">{data.profile.name.trim().charAt(0).toUpperCase()}</span><span><strong>{data.profile.name}</strong><small>{data.profile.professional_headline || "Candidate"}</small></span></div>
          <button className="switch-profile" onClick={switchProfile}>Switch profile</button>
          <p className="local-label"><span /> Local-only · no sign-in</p>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div><span className="topbar-label">Candidate workspace</span><span className="topbar-divider">/</span><span>{activeView}</span></div><span className="local-chip"><span /> Stored locally</span></header>
        <div aria-busy={busy} className="content-area">
          {actionError && <div className="feedback feedback-error" role="alert"><strong>Could not complete that action</strong><span>{actionError}</span><button aria-label="Dismiss error" onClick={() => setActionError("")}>×</button></div>}
          {notice && <div className="feedback feedback-success" role="status"><span>{notice}</span><button aria-label="Dismiss message" onClick={() => setNotice("")}>×</button></div>}
          {busy && <div className="inline-loading" role="status"><span className="spinner small" /> Saving your changes…</div>}
          {view}
        </div>
        <footer className="app-footer">JobPilot AI <span>·</span> Evidence first, applications with care <span className="footer-security">Keep this local workspace private. Authentication is not yet available.</span></footer>
      </main>
    </div>
  );
}

function ProfileStart({ onSelect, error }: { onSelect: (id: string) => void; error: string }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [existingId, setExistingId] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setFormError("");
    try {
      const profile = await api.createProfile({
        name: name.trim(),
        ...(email.trim() ? { contact_email: email.trim() } : {}),
      });
      onSelect(profile.id);
    } catch (caught) {
      setFormError(errorMessage(caught));
    } finally {
      setCreating(false);
    }
  }

  return <main className="setup-shell">
    <section className="setup-card">
      <a className="brand setup-brand" href="#"><span className="brand-mark">J</span><span>jobpilot<span className="brand-ai">.ai</span><small>CAREER WORKSPACE</small></span></a>
      <p className="eyebrow">Welcome to your local workspace</p>
      <h1>{error ? "Connect a candidate profile" : "Start with your profile"}</h1>
      <p className="setup-intro">{error ? `The saved profile could not be loaded: ${error}` : "Use an existing profile ID from your local API, or create a new candidate profile to begin."}</p>
      {formError && <p className="feedback-error setup-error" role="alert">{formError}</p>}
      <form onSubmit={create} className="setup-form">
        <Field label="Your name" required><input autoComplete="name" maxLength={200} required value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="Email (optional)"><input autoComplete="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
        <button className="button button-primary button-wide" disabled={creating} type="submit">{creating ? "Creating profile…" : "Create candidate profile"}</button>
      </form>
      <div className="setup-divider"><span>or connect an existing one</span></div>
      <form className="existing-profile-form" onSubmit={(event) => { event.preventDefault(); if (existingId.trim()) onSelect(existingId); }}>
        <Field label="Candidate profile ID"><input autoComplete="off" placeholder="Paste profile UUID" value={existingId} onChange={(event) => setExistingId(event.target.value)} /></Field>
        <button className="button button-secondary button-wide" disabled={!existingId.trim()} type="submit">Open profile</button>
      </form>
      <p className="setup-warning"><strong>Local-only access.</strong> The API does not yet implement authentication. Do not expose this workspace publicly or share it with other users.</p>
    </section>
  </main>;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail && typeof error.detail === "object") {
      const body = error.detail as { detail?: unknown };
      if (body.detail && typeof body.detail === "object") {
        const detail = body.detail as { validation_results?: { errors?: string[]; gaps?: string[] } };
        const messages = [...(detail.validation_results?.errors || []), ...(detail.validation_results?.gaps || [])];
        if (messages.length) return `${error.message} ${messages.join(" ")}`;
      }
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}
