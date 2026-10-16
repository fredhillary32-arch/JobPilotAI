import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  api,
  ApiError,
  clearSessionCsrfToken,
  loadWorkspace,
  saveBlob,
  setUnauthorizedHandler,
} from "./api/client";
import type {
  CandidateProfile,
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
import { DiscoveryView } from "./DiscoveryView";

const navigation: { name: ViewName; label: string; icon: string }[] = [
  { name: "Dashboard", label: "Overview", icon: "⌂" },
  { name: "Profile", label: "Candidate profile", icon: "◎" },
  { name: "Documents", label: "Documents", icon: "▤" },
  { name: "Evidence review", label: "Evidence review", icon: "✓" },
  { name: "Job discovery", label: "Discovered jobs", icon: "⌕" },
  { name: "Job descriptions", label: "Job descriptions", icon: "▱" },
  { name: "Tailored CVs", label: "Tailored CVs", icon: "▧" },
  { name: "Exports", label: "Exports", icon: "⇩" },
];

const configuredProfileId = import.meta.env.VITE_CANDIDATE_PROFILE_ID?.trim();

export default function App() {
  const [profileId, setProfileId] = useState(
    "",
  );
  const [authStatus, setAuthStatus] = useState<"restoring" | "authenticated" | "anonymous" | "error">("restoring");
  const [authEmail, setAuthEmail] = useState("");
  const [authError, setAuthError] = useState("");
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [activeView, setActiveView] = useState<ViewName>("Dashboard");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pendingLabel, setPendingLabel] = useState("");
  const [blockedAttempt, setBlockedAttempt] = useState(false);
  const actionLock = useRef(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const handleUnauthorized = () => {
      clearSessionCsrfToken();
      window.localStorage.removeItem("jobpilot.profileId");
      setProfileId("");
      setData(null);
      setLoadError("");
      setAuthEmail("");
      setAuthStatus("anonymous");
      setAuthError("");
    };
    setUnauthorizedHandler(handleUnauthorized);
    api.restoreSession()
      .then((session) => {
        setAuthEmail(session.user.email);
        setProfileId(configuredProfileId || window.localStorage.getItem("jobpilot.profileId") || "");
        setAuthStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          handleUnauthorized();
        } else {
          setData(null);
          setProfileId("");
          setAuthStatus("error");
          setAuthError(errorMessage(error));
        }
      });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated") {
      setData(null);
      setLoading(authStatus === "restoring");
      return;
    }
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
  }, [authStatus, profileId]);

  async function restoreSession() {
    setAuthStatus("restoring");
    setAuthError("");
    try {
      const session = await api.restoreSession();
      setAuthEmail(session.user.email);
      setProfileId(configuredProfileId || window.localStorage.getItem("jobpilot.profileId") || "");
      setAuthStatus("authenticated");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuthStatus("anonymous");
      } else {
        setAuthStatus("error");
        setAuthError(errorMessage(error));
      }
    }
  }

  async function login(email: string, password: string) {
    setAuthError("");
    try {
      const session = await api.login(email, password);
      setAuthEmail(session.user.email);
      setProfileId(configuredProfileId || window.localStorage.getItem("jobpilot.profileId") || "");
      setAuthStatus("authenticated");
    } catch (error) {
      setAuthError(errorMessage(error));
      throw error;
    }
  }

  async function logout() {
    setAuthError("");
    try {
      await api.logout();
      setAuthStatus("anonymous");
    } catch (error) {
      setAuthError(`You have been signed out of this workspace, but the server did not confirm session revocation: ${errorMessage(error)}`);
      setAuthStatus("anonymous");
    } finally {
      clearSessionCsrfToken();
      window.localStorage.removeItem("jobpilot.profileId");
      setProfileId("");
      setData(null);
      setAuthEmail("");
    }
  }

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

  // Actions run one at a time because each one reloads the shared workspace;
  // a second action is refused with visible feedback rather than dropped.
  async function runAction(
    action: () => Promise<unknown>,
    success?: string,
    pending = "Saving your changes…",
  ): Promise<boolean> {
    if (actionLock.current) {
      setBlockedAttempt(true);
      return false;
    }
    actionLock.current = true;
    setBusy(true);
    setPendingLabel(pending);
    setActionError("");
    setNotice("");
    try {
      await action();
      if (success) setNotice(success);
      if (profileId) setData(await loadWorkspace(profileId));
      return true;
    } catch (error) {
      setActionError(errorMessage(error));
      if (profileId && !(error instanceof ApiError && error.status === 401)) {
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
      setPendingLabel("");
      setBlockedAttempt(false);
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

  if (authStatus === "restoring") {
    return <main className="loading-screen"><div className="spinner" aria-hidden="true" /><p role="status">Restoring your secure session…</p></main>;
  }
  if (authStatus === "error") {
    return <main className="loading-screen"><section className="auth-error panel"><h1>Could not restore your session</h1><p role="alert">{authError}</p><button className="button button-primary" onClick={() => void restoreSession()}>Try again</button></section></main>;
  }
  if (authStatus === "anonymous") {
    return <LoginScreen onLogin={login} error={authError} />;
  }
  if (loading) {
    return <main className="loading-screen"><div className="spinner" aria-hidden="true" /><p role="status">Connecting to your local JobPilot workspace…</p></main>;
  }
  if (!profileId || !data) {
    return <ProfileStart onSelect={selectProfile} error={loadError} onLogout={() => void logout()} />;
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
        return <DocumentsView data={data} onUpload={uploadDocument} onExtract={extractDocument} onDownload={downloadDocument} onGetText={(id) => api.getExtractedText(profileId, id)} busy={busy} runAction={runAction} />;
      case "Evidence review":
        return <EvidenceView data={data} onGetText={(id) => api.getExtractedText(profileId, id)} onCreate={createEvidence} onSetStatus={setEvidenceStatus} busy={busy} runAction={runAction} />;
      case "Job discovery":
        return <DiscoveryView />;
      case "Job descriptions":
        return <JobsView jobs={data.jobs} onCreate={createJob} busy={busy} runAction={runAction} />;
      case "Tailored CVs":
        return <DraftsView data={data} onGenerate={generateDraft} onCreateExport={createExport} onDownloadExport={downloadExport} busy={busy} runAction={runAction} />;
      case "Exports":
        return <ExportsView data={data} onDownload={downloadExport} busy={busy} runAction={runAction} />;
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
          <p className="local-label"><span /> Signed in as {authEmail}</p>
          <button className="switch-profile" onClick={() => void logout()}>Sign out</button>
        </div>
      </aside>
      <main className="main-content">
        <header className="topbar"><div><span className="topbar-label">Candidate workspace</span><span className="topbar-divider">/</span><span>{activeView}</span></div><span className="local-chip"><span /> Stored locally</span></header>
        <div aria-busy={busy} className="content-area">
          {(actionError || notice || busy) && <div className="feedback-region" data-testid="feedback-region">
            {actionError && <div className="feedback feedback-error" role="alert"><strong>Could not complete that action</strong><span>{actionError}</span><button aria-label="Dismiss error" onClick={() => setActionError("")}>×</button></div>}
            {notice && <div className="feedback feedback-success" role="status"><span>{notice}</span><button aria-label="Dismiss message" onClick={() => setNotice("")}>×</button></div>}
            {busy && <div className="inline-loading" role="status"><span className="spinner small" /> {pendingLabel}</div>}
            {busy && blockedAttempt && <div className="feedback feedback-wait" role="status"><span>Please wait for the current action to finish before starting another.</span></div>}
          </div>}
          {view}
        </div>
        <footer className="app-footer">JobPilot AI <span>·</span> Evidence first, applications with care <span className="footer-security">Your workspace is protected by your secure session.</span></footer>
      </main>
    </div>
  );
}

function LoginScreen({ onLogin, error }: {
  onLogin: (email: string, password: string) => Promise<void>;
  error: string;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      await onLogin(email, password);
      setPassword("");
    } catch {
      setFormError("Sign-in was unsuccessful. Check your credentials and try again.");
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  return <main className="setup-shell">
    <section className="setup-card login-card">
      <a className="brand setup-brand" href="#" onClick={(event) => event.preventDefault()}>
        <span className="brand-mark">J</span><span>jobpilot<span className="brand-ai">.ai</span><small>CAREER WORKSPACE</small></span>
      </a>
      <p className="eyebrow">Private candidate workspace</p>
      <h1>Sign in to JobPilot</h1>
      <p className="setup-intro">Use your local owner account to access your candidate workspace.</p>
      {(formError || error) && <p className="feedback-error setup-error" role="alert">{formError || error}</p>}
      <form onSubmit={(event) => void submit(event)} className="setup-form">
        <Field label="Email address" required>
          <input autoComplete="username" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        </Field>
        <Field label="Password" required>
          <input autoComplete="current-password" type="password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        </Field>
        <button className="button button-primary button-wide" disabled={submitting} type="submit">
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="setup-warning">Session credentials are held in a secure, HttpOnly cookie. This application does not offer public registration.</p>
    </section>
  </main>;
}

function ProfileStart({ onSelect, error, onLogout }: {
  onSelect: (id: string) => void;
  error: string;
  onLogout: () => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [existingId, setExistingId] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");
  const [ownedProfiles, setOwnedProfiles] = useState<CandidateProfile[] | null>(null);
  const [listError, setListError] = useState("");

  useEffect(() => {
    let current = true;
    api.listProfiles()
      .then((profiles) => {
        if (current) setOwnedProfiles(profiles);
      })
      .catch((caught: unknown) => {
        if (!current) return;
        setOwnedProfiles([]);
        setListError(errorMessage(caught));
      });
    return () => {
      current = false;
    };
  }, []);

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
      <p className="setup-intro">{error ? `The saved profile could not be loaded: ${error}` : "Create a candidate profile or open one you own to begin."}</p>
      {formError && <p className="feedback-error setup-error" role="alert">{formError}</p>}
      {listError && <p className="feedback-error setup-error" role="alert">Your profiles could not be listed: {listError}</p>}
      {ownedProfiles === null ? <p className="muted">Loading your profiles…</p> : ownedProfiles.length > 0 && <section aria-label="Your candidate profiles" className="owned-profiles">
        <h2>Your profiles</h2>
        <ul>{ownedProfiles.map((owned) => <li key={owned.id}><button className="button button-secondary button-wide" onClick={() => onSelect(owned.id)} type="button">Open {owned.name}</button></li>)}</ul>
        <div className="setup-divider"><span>or create another profile</span></div>
      </section>}
      <form onSubmit={create} className="setup-form">
        <Field label="Your name" required><input autoComplete="name" maxLength={200} required value={name} onChange={(event) => setName(event.target.value)} /></Field>
        <Field label="Email (optional)"><input autoComplete="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></Field>
        <button className="button button-primary button-wide" disabled={creating} type="submit">{creating ? "Creating profile…" : "Create candidate profile"}</button>
      </form>
      <div className="setup-divider"><span>or open a profile you own</span></div>
      <form className="existing-profile-form" onSubmit={(event) => { event.preventDefault(); if (existingId.trim()) onSelect(existingId); }}>
        <Field label="Candidate profile ID"><input autoComplete="off" placeholder="Paste profile UUID" value={existingId} onChange={(event) => setExistingId(event.target.value)} /></Field>
        <button className="button button-secondary button-wide" disabled={!existingId.trim()} type="submit">Open profile</button>
      </form>
      <p className="setup-warning">Profile selection is only a convenience; the server verifies ownership for every request.</p>
      <button className="button button-secondary button-wide" onClick={onLogout}>Sign out</button>
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
