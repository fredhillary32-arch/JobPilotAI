import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const profileId = "profile-123";
const documentId = "document-123";
const evidenceId = "evidence-123";
const jobId = "job-123";
const draftId = "draft-123";
const now = "2026-10-14T12:00:00Z";

const profile = {
  id: profileId,
  name: "Taylor Candidate",
  contact_email: "taylor@example.test",
  contact_phone: null,
  professional_headline: "Platform Engineer",
  summary: "I build reliable systems.",
  location: "Nairobi, Kenya",
  remote_work_preference: "remote",
  target_job_categories: ["Engineering"],
  created_at: now,
  updated_at: now,
};
let currentProfile = profile;
const document = {
  id: documentId,
  candidate_profile_id: profileId,
  source_document_id: null,
  document_kind: "source_cv",
  provenance: "candidate_uploaded",
  original_filename: "candidate-cv.txt",
  media_type: "text/plain",
  size_bytes: 512,
  sha256: "synthetic-test-digest",
  target_job_title: null,
  target_company: null,
  created_at: now,
};
const evidenceBase = {
  id: evidenceId,
  candidate_profile_id: profileId,
  source_document_id: documentId,
  category: "achievement",
  description: "Automated deployment checks.",
  source_excerpt: "Automated deployment checks.",
  source_start: 20,
  source_end: 49,
  source_section: null,
  confirmation_status: "unreviewed",
  created_at: now,
  updated_at: now,
};
const job = {
  id: jobId,
  candidate_profile_id: profileId,
  job_title: "Platform Engineer",
  company: "Example Org",
  description: "Build reliable systems with Python.",
  source_url: null,
  created_at: now,
};
const draft = {
  id: draftId,
  candidate_profile_id: profileId,
  job_description_id: jobId,
  status: "generated",
  generated_content: "Taylor Candidate\nProfessional Summary\nExperienced engineer.",
  structured_content: {},
  validation_results: { is_valid: true, errors: [], gaps: [], warnings: [] },
  source_references: [],
  created_at: now,
};

let evidenceStatus = "unreviewed";
let exports: Array<Record<string, unknown>>;
let profileRecords: Record<string, Array<Record<string, unknown>>>;
let requests: Array<{
  path: string;
  search: string;
  method: string;
  body: string | null;
  headers: Headers;
  credentials: RequestCredentials | undefined;
  mode: RequestMode | undefined;
}> = [];
let failJobSave = false;
let failProfileRecordSave = false;
let sessionValid = true;
let failSessionRestore = false;
let expireNextPrivateRequest = false;
let sessionCsrf = "session-csrf-test";
let jobListings: Array<Record<string, unknown>> = [];
let discoveryRuns: Array<Record<string, unknown>> = [];
let failJobListings = false;
let enforceSessionCsrf = false;

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeExport(id = "export-123") {
  return {
    id,
    candidate_profile_id: profileId,
    cv_draft_id: draftId,
    document_id: `document-${id}`,
    export_format: "pdf",
    page_count: 1,
    filename: `jobpilot-cv-${id}.pdf`,
    media_type: "application/pdf",
    size_bytes: 2048,
    created_at: now,
  };
}

function responseFor(url: string, init: RequestInit = {}): Response {
  const path = new URL(url, "http://localhost").pathname;
  const method = init.method || "GET";
  const body = typeof init.body === "string" ? init.body : null;
  requests.push({
    path,
    search: new URL(url, "http://localhost").search,
    method,
    body: body || (init.body instanceof FormData ? "[form-data]" : null),
    headers: new Headers(init.headers),
    credentials: init.credentials,
    mode: init.mode,
  });

  if (path === "/api/v1/auth/session" && method === "GET") {
    if (failSessionRestore) return jsonResponse({ detail: "Session service unavailable." }, 503);
    if (!sessionValid) return jsonResponse({ detail: "Not authenticated." }, 401);
    return jsonResponse({ user: { id: "user-123", email: "owner@example.test" }, csrf_token: sessionCsrf });
  }
  if (path === "/api/v1/auth/pre-auth-csrf" && method === "GET") {
    return jsonResponse({ csrf_token: "pre-auth-csrf-test" });
  }
  if (path === "/api/v1/auth/login" && method === "POST") {
    if (JSON.parse(body || "{}").password !== "correct horse") {
      return jsonResponse({ detail: "Invalid credentials." }, 401);
    }
    sessionValid = true;
    return jsonResponse({ user: { id: "user-123", email: "owner@example.test" }, csrf_token: "session-csrf-test" });
  }
  if (path === "/api/v1/auth/logout" && method === "POST") {
    sessionValid = false;
    return new Response(null, { status: 204 });
  }
  if (expireNextPrivateRequest && path.includes("/candidate-profiles/")) {
    expireNextPrivateRequest = false;
    sessionValid = false;
    return jsonResponse({ detail: "Not authenticated." }, 401);
  }
  if (
    enforceSessionCsrf &&
    method !== "GET" &&
    path.startsWith("/api/v1/candidate-profiles") &&
    new Headers(init.headers).get("X-CSRF-Token") !== sessionCsrf
  ) {
    return jsonResponse({ detail: "Request verification failed." }, 403);
  }
  if (path === "/api/v1/candidate-profiles" && method === "GET") {
    return jsonResponse([currentProfile]);
  }

  if (path === `/api/v1/candidate-profiles/${profileId}`) {
    if (method === "PATCH") {
      currentProfile = { ...currentProfile, ...JSON.parse(body || "{}") };
      return jsonResponse(currentProfile);
    }
    if (method === "GET") return jsonResponse(currentProfile);
  }
  for (const section of Object.keys(profileRecords)) {
    const collectionPath = `/api/v1/candidate-profiles/${profileId}/${section}`;
    if (path === collectionPath) {
      if (method === "POST") {
        if (failProfileRecordSave) return jsonResponse({ detail: "Profile record could not be saved." }, 422);
        const created = {
          ...JSON.parse(body || "{}"),
          id: `${section}-created`,
          candidate_profile_id: profileId,
        };
        profileRecords[section].push(created);
        return jsonResponse(created, 201);
      }
      return jsonResponse(profileRecords[section]);
    }
    if (path.startsWith(`${collectionPath}/`)) {
      const recordId = path.slice(collectionPath.length + 1);
      const index = profileRecords[section].findIndex((item) => item.id === recordId);
      if (index < 0) return jsonResponse({ detail: "Profile record not found." }, 404);
      if (method === "PATCH") {
        const updated = { ...profileRecords[section][index], ...JSON.parse(body || "{}") };
        profileRecords[section][index] = updated;
        return jsonResponse(updated);
      }
      if (method === "DELETE") {
        profileRecords[section].splice(index, 1);
        return new Response(null, { status: 204 });
      }
    }
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/documents`) {
    if (method === "POST") return jsonResponse(document, 201);
    const origin = new URL(url, "http://localhost").searchParams.get("origin") || "all";
    if (origin === "source") return jsonResponse([document]);
    return jsonResponse([
      document,
      ...exports.map((entry) => ({
        ...document,
        id: entry.document_id,
        document_kind: "tailored_cv",
        provenance: "system_generated",
        original_filename: entry.filename,
        media_type: entry.media_type,
        size_bytes: entry.size_bytes,
      })),
    ]);
  }
  if (path.endsWith(`/documents/${documentId}/extraction`) && method === "GET") {
    return jsonResponse({
      id: "extraction-123",
      source_document_id: documentId,
      status: "succeeded",
      character_count: 29,
      extractor_version: "local-extractor/1",
      error_category: null,
      extracted_at: now,
      trust_status: "unverified_source_text",
    });
  }
  if (path.endsWith(`/documents/${documentId}/extraction/text`)) {
    return jsonResponse({
      source_document_id: documentId,
      status: "succeeded",
      text: "Experience\nAutomated deployment checks.",
      character_count: 41,
      trust_status: "unverified_source_text",
      note: "Unverified text.",
    });
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/evidence`) {
    return jsonResponse([{ ...evidenceBase, confirmation_status: evidenceStatus }]);
  }
  if (path.endsWith(`/evidence/${evidenceId}`) && method === "PATCH") {
    evidenceStatus = JSON.parse(body || "{}").confirmation_status;
    return jsonResponse({ ...evidenceBase, confirmation_status: evidenceStatus });
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/job-descriptions`) {
    if (method === "POST") {
      if (failJobSave) return jsonResponse({ detail: "Job description is invalid." }, 422);
      return jsonResponse(job, 201);
    }
    return jsonResponse([job]);
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/cv-drafts`) {
    if (method === "GET") return jsonResponse([draft]);
  }
  if (path.endsWith(`/job-descriptions/${jobId}/cv-drafts/${draftId}/exports`)) {
    if (method === "POST") {
      const nextExport = makeExport();
      exports = [nextExport];
      return jsonResponse(nextExport, 201);
    }
    return jsonResponse(exports);
  }
  if (path.endsWith(`/exports/export-123/download`)) {
    return new Response(new Blob(["synthetic PDF bytes"]), {
      status: 200,
      headers: { "Content-Type": "application/pdf" },
    });
  }
  if (path.endsWith(`/documents/${documentId}/download`)) {
    return new Response(new Blob(["synthetic source bytes"]), {
      status: 200,
      headers: { "Content-Type": "text/plain" },
    });
  }
  if (path === "/api/v1/job-listings" && method === "GET") {
    if (failJobListings) return jsonResponse({ detail: "Job listings are unavailable." }, 503);
    const within = new URL(url, "http://localhost").searchParams.get("posted_within_hours");
    const items = within ? jobListings.filter((item) => item.posted_at) : jobListings;
    return jsonResponse({ items, total: items.length, limit: 50, offset: 0 });
  }
  if (path === "/api/v1/job-discovery/runs" && method === "GET") return jsonResponse(discoveryRuns);
  return jsonResponse({ detail: `Unexpected test request: ${method} ${path}` }, 404);
}

function mountApp() {
  window.localStorage.setItem("jobpilot.profileId", profileId);
  render(<App />);
}

describe("JobPilot frontend", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    evidenceStatus = "unreviewed";
    currentProfile = profile;
    exports = [];
    profileRecords = {
      experiences: [{
        id: "experience-123",
        candidate_profile_id: profileId,
        employer: "Northstar Systems",
        job_title: "Platform Engineer",
        location: null,
        work_arrangement: null,
        start_date: "2022-01-01",
        end_date: null,
        current_role: true,
        description: "Maintained deployment systems.",
        achievements: ["Improved release checks."],
      }],
      education: [{
        id: "education-123",
        candidate_profile_id: profileId,
        institution: "Example Institute",
        qualification: "Bachelor of Science",
        field_of_study: "Computer Science",
        start_date: "2018-01-01",
        end_date: "2022-01-01",
      }],
      skills: [{
        id: "skill-123",
        candidate_profile_id: profileId,
        name: "Python",
        proficiency_level: "advanced",
      }],
      certifications: [{
        id: "certification-123",
        candidate_profile_id: profileId,
        name: "Cloud Practitioner",
        issuer: "Example Board",
        issue_date: "2024-01-01",
        expires_on: null,
      }],
    };
    requests = [];
    failJobSave = false;
    failProfileRecordSave = false;
    sessionValid = true;
    failSessionRestore = false;
    expireNextPrivateRequest = false;
    sessionCsrf = "session-csrf-test";
    enforceSessionCsrf = false;
    jobListings = [];
    discoveryRuns = [];
    failJobListings = false;
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn((url: string | URL, init?: RequestInit) =>
      Promise.resolve(responseFor(String(url), init)),
    ));
  });

  it("shows a real-data dashboard after the workspace loads", async () => {
    mountApp();

    expect(await screen.findByRole("heading", { name: "Good to see you, Taylor" })).toBeInTheDocument();
    const totals = within(screen.getByRole("region", { name: "Workspace totals" }));
    expect(totals.getByText("Documents")).toBeInTheDocument();
    expect(totals.getByText("Saved roles")).toBeInTheDocument();
    expect(screen.getByText("Local workspace")).toBeInTheDocument();
    expect(requests.some((request) => request.path.endsWith("/candidate-profiles/profile-123"))).toBe(true);
  });

  it("restores the session before requesting private workspace data", async () => {
    let releaseSession: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((url: string | URL, init?: RequestInit) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path === "/api/v1/auth/session" && !releaseSession) {
        return new Promise<Response>((resolve) => { releaseSession = resolve; });
      }
      return Promise.resolve(responseFor(String(url), init));
    }));
    window.localStorage.setItem("jobpilot.profileId", profileId);
    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Restoring your secure session");
    expect(requests.some((request) => request.path.includes("/candidate-profiles/"))).toBe(false);
    releaseSession?.(jsonResponse({ user: { id: "user-123", email: "owner@example.test" }, csrf_token: "session-csrf-test" }));
    expect(await screen.findByRole("heading", { name: "Good to see you, Taylor" })).toBeInTheDocument();
  });

  it("logs in through a pre-auth challenge and uses same-origin requests", async () => {
    sessionValid = false;
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByRole("textbox", { name: "Email address" }), "owner@example.test");
    await user.type(screen.getByLabelText(/Password/), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Start with your profile" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Candidate profile ID" }), profileId);
    await user.click(screen.getByRole("button", { name: "Open profile" }));
    expect(await screen.findByRole("heading", { name: "Good to see you, Taylor" })).toBeInTheDocument();
    const challengeIndex = requests.findIndex((request) => request.path.endsWith("/auth/pre-auth-csrf"));
    const loginIndex = requests.findIndex((request) => request.path.endsWith("/auth/login"));
    expect(challengeIndex).toBeGreaterThan(-1);
    expect(loginIndex).toBeGreaterThan(challengeIndex);
    expect(requests[loginIndex].headers.get("X-CSRF-Token")).toBe("pre-auth-csrf-test");
    expect(requests[loginIndex].credentials).toBe("same-origin");
    expect(requests[loginIndex].mode).toBe("same-origin");
    expect(requests.some((request) => request.path.endsWith("/candidate-profiles/profile-123"))).toBe(true);
    expect(window.localStorage.getItem("jobpilot.profileId")).toBe(profileId);
  });

  it("lists owned profiles after sign-in so a profile can be reopened without its ID", async () => {
    sessionValid = false;
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByRole("textbox", { name: "Email address" }), "owner@example.test");
    await user.type(screen.getByLabelText(/Password/), "correct horse");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const owned = within(await screen.findByRole("region", { name: "Your candidate profiles" }));
    await user.click(owned.getByRole("button", { name: "Open Taylor Candidate" }));

    expect(await screen.findByRole("heading", { name: "Good to see you, Taylor" })).toBeInTheDocument();
    expect(requests.some((request) => request.path === "/api/v1/candidate-profiles" && request.method === "GET")).toBe(true);
    expect(window.localStorage.getItem("jobpilot.profileId")).toBe(profileId);
  });

  it("recovers once from a CSRF token rotated by another tab and retries the mutation", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    enforceSessionCsrf = true;
    sessionCsrf = "session-csrf-rotated";

    await user.click(screen.getByRole("button", { name: "Candidate profile" }));
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    expect(await screen.findByText("Candidate profile saved.")).toBeInTheDocument();
    const patches = requests.filter((request) => request.method === "PATCH" && request.path.endsWith(`/candidate-profiles/${profileId}`));
    expect(patches.map((request) => request.headers.get("X-CSRF-Token"))).toEqual(["session-csrf-test", "session-csrf-rotated"]);
  });

  it("does not retry a mutation more than once when CSRF verification keeps failing", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    enforceSessionCsrf = true;
    sessionCsrf = "session-csrf-rotated-elsewhere";
    vi.mocked(fetch).mockImplementation((url: RequestInfo | URL, init?: RequestInit) => {
      const response = responseFor(String(url), init);
      if (new URL(String(url), "http://localhost").pathname === "/api/v1/auth/session") {
        sessionCsrf = `session-csrf-${requests.length}`;
      }
      return Promise.resolve(response);
    });

    await user.click(screen.getByRole("button", { name: "Candidate profile" }));
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    expect(await screen.findByText("Request verification failed.")).toBeInTheDocument();
    const patches = requests.filter((request) => request.method === "PATCH");
    expect(patches).toHaveLength(2);
  });

  it("shows a generic error for failed login and does not load private data", async () => {
    sessionValid = false;
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByRole("textbox", { name: "Email address" }), "owner@example.test");
    await user.type(screen.getByLabelText(/Password/), "incorrect");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in was unsuccessful.");
    expect(screen.getByRole("heading", { name: "Sign in to JobPilot" })).toBeInTheDocument();
    expect(requests.some((request) => request.path.includes("/candidate-profiles/"))).toBe(false);
  });

  it("shows the login screen for expired sessions without retaining selected profile data", async () => {
    sessionValid = false;
    window.localStorage.setItem("jobpilot.profileId", profileId);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sign in to JobPilot" })).toBeInTheDocument();
    expect(requests.some((request) => request.path.includes("/candidate-profiles/"))).toBe(false);
    expect(window.localStorage.getItem("jobpilot.profileId")).toBeNull();
  });

  it("clears workspace selection and posts the session CSRF token on logout", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in to JobPilot" })).toBeInTheDocument();
    const logoutRequest = requests.find((request) => request.path.endsWith("/auth/logout"));
    expect(logoutRequest?.headers.get("X-CSRF-Token")).toBe("session-csrf-test");
    expect(logoutRequest?.credentials).toBe("same-origin");
    expect(window.localStorage.getItem("jobpilot.profileId")).toBeNull();
    expect(requests.some((request) => request.path.includes("/candidate-profiles/"))).toBe(true);
  });

  it("returns to login and clears selected profile when an active session expires", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    expireNextPrivateRequest = true;
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));
    await user.clear(screen.getByRole("textbox", { name: /Professional headline/ }));
    await user.type(screen.getByRole("textbox", { name: /Professional headline/ }), "Systems Engineer");
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    expect(await screen.findByRole("heading", { name: "Sign in to JobPilot" })).toBeInTheDocument();
    expect(window.localStorage.getItem("jobpilot.profileId")).toBeNull();
  });

  it("does not load private data when session restoration fails", async () => {
    failSessionRestore = true;
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Could not restore your session" })).toBeInTheDocument();
    expect(requests.some((request) => request.path.includes("/candidate-profiles/"))).toBe(false);
  });

  it("shows a loading state while the API responds", async () => {
    window.localStorage.setItem("jobpilot.profileId", profileId);
    let releaseProfile: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn((url: string | URL, init?: RequestInit) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path === `/api/v1/candidate-profiles/${profileId}` && !releaseProfile) {
        return new Promise<Response>((resolve) => {
          releaseProfile = resolve;
        });
      }
      return Promise.resolve(responseFor(String(url), init));
    }));
    render(<App />);

    expect(screen.getByRole("status")).toHaveTextContent("Restoring your secure session");
    await waitFor(() => expect(releaseProfile).toBeDefined());
    expect(screen.getByRole("status")).toHaveTextContent("Connecting to your local JobPilot workspace");
    releaseProfile?.(jsonResponse(profile));
    expect(await screen.findByRole("heading", { name: "Good to see you, Taylor" })).toBeInTheDocument();
  });

  it("surfaces recoverable API validation errors from forms", async () => {
    const user = userEvent.setup();
    failJobSave = true;
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Job descriptions" }));
    await screen.findByRole("heading", { name: "Save a job description" });
    await user.type(screen.getByRole("textbox", { name: /Job title/ }), "Backend Engineer");
    await user.type(screen.getByRole("textbox", { name: /Full job description/ }), "Build useful services.");
    await user.click(screen.getByRole("button", { name: "Save job description" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Job description is invalid.");
    expect(requests.some((request) => request.method === "POST" && request.path.endsWith("/job-descriptions"))).toBe(true);
  });

  it("saves profile changes through the profile update endpoint", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));
    await user.clear(screen.getByRole("textbox", { name: /Professional headline/ }));
    await user.type(screen.getByRole("textbox", { name: /Professional headline/ }), "Systems Engineer");
    await user.click(screen.getByRole("button", { name: "Save profile" }));

    const saved = await screen.findByText("Candidate profile saved.");
    expect(within(screen.getByTestId("feedback-region")).getByText("Candidate profile saved.")).toBe(saved);
    expect(requests.some((request) =>
      request.method === "PATCH" &&
      request.path === `/api/v1/candidate-profiles/${profileId}` &&
      JSON.parse(request.body || "{}").professional_headline === "Systems Engineer",
    )).toBe(true);
  });

  it("adds, edits, and explicitly confirms deletion of a skill", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));

    const skillGroup = screen.getByRole("heading", { name: "Skills" }).closest("section");
    expect(skillGroup).not.toBeNull();
    const skills = within(skillGroup as HTMLElement);
    await user.click(skills.getByRole("button", { name: "Add skill" }));
    await user.type(skills.getByRole("textbox", { name: "Skill" }), "React");
    await user.selectOptions(skills.getByLabelText("Proficiency level"), "intermediate");
    await user.click(skills.getByRole("button", { name: "Save new skill" }));

    expect(await screen.findByText("Skill added.")).toBeInTheDocument();
    expect(skills.getByText("React")).toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "POST" &&
      request.path === `/api/v1/candidate-profiles/${profileId}/skills` &&
      JSON.parse(request.body || "{}").name === "React",
    )).toBe(true);

    const reactRecord = skills.getByText("React").closest(".managed-record");
    expect(reactRecord).not.toBeNull();
    await user.click(within(reactRecord as HTMLElement).getByRole("button", { name: "Edit" }));
    await user.clear(skills.getByRole("textbox", { name: "Skill" }));
    await user.type(skills.getByRole("textbox", { name: "Skill" }), "TypeScript");
    await user.click(skills.getByRole("button", { name: "Save skill" }));
    expect(await screen.findByText("Skill updated.")).toBeInTheDocument();
    expect(skills.getByText("TypeScript")).toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "PATCH" &&
      request.path.endsWith("/skills/skills-created") &&
      JSON.parse(request.body || "{}").name === "TypeScript",
    )).toBe(true);

    const editedRecord = skills.getByText("TypeScript").closest(".managed-record");
    expect(editedRecord).not.toBeNull();
    await user.click(within(editedRecord as HTMLElement).getByRole("button", { name: "Delete" }));
    expect(skills.getByText("Delete this record?")).toBeInTheDocument();
    expect(requests.some((request) => request.method === "DELETE")).toBe(false);
    await user.click(skills.getByRole("button", { name: "Confirm delete" }));
    expect(await screen.findByText("Skill deleted.")).toBeInTheDocument();
    expect(skills.queryByText("TypeScript")).not.toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "DELETE" &&
      request.path.endsWith("/skills/skills-created"),
    )).toBe(true);
  });

  it("surfaces server validation errors when saving profile records", async () => {
    const user = userEvent.setup();
    failProfileRecordSave = true;
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));
    const skills = within(screen.getByRole("heading", { name: "Skills" }).closest("section") as HTMLElement);
    await user.click(skills.getByRole("button", { name: "Add skill" }));
    await user.type(skills.getByRole("textbox", { name: "Skill" }), "React");
    await user.click(skills.getByRole("button", { name: "Save new skill" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Profile record could not be saved.");
  });

  it("labels work achievements as candidate-provided and sends them as explicit profile input", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));
    const experienceGroup = within(screen.getByRole("heading", { name: "Work experience" }).closest("section") as HTMLElement);
    await user.click(experienceGroup.getByRole("button", { name: "Add work experience" }));
    expect(experienceGroup.getByText(/One candidate-confirmed achievement per line/)).toBeInTheDocument();
    await user.type(experienceGroup.getByRole("textbox", { name: "Job title" }), "Engineer");
    await user.type(experienceGroup.getByRole("textbox", { name: "Employer" }), "Synthetic Systems");
    await user.type(experienceGroup.getByLabelText(/Start date/), "2024-01-01");
    await user.type(experienceGroup.getByLabelText(/Achievements/), "Improved synthetic deployment checks.");
    await user.click(experienceGroup.getByRole("button", { name: "Save new work experience" }));
    expect(await screen.findByText("Work experience added.")).toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "POST" &&
      request.path.endsWith("/experiences") &&
      JSON.parse(request.body || "{}").achievements[0] === "Improved synthetic deployment checks.",
    )).toBe(true);
  });

  it("clears a previous end date when an experience is changed to a current role", async () => {
    const user = userEvent.setup();
    profileRecords.experiences[0] = {
      ...profileRecords.experiences[0],
      current_role: false,
      end_date: "2025-01-01",
    };
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));

    const experienceGroup = within(
      screen.getByRole("heading", { name: "Work experience" }).closest("section") as HTMLElement,
    );
    const record = experienceGroup.getByText("Platform Engineer").closest(".managed-record");
    expect(record).not.toBeNull();
    await user.click(within(record as HTMLElement).getByRole("button", { name: "Edit" }));
    await user.click(experienceGroup.getByRole("checkbox", { name: "Current role" }));
    await user.click(experienceGroup.getByRole("button", { name: "Save work experience" }));

    expect(await screen.findByText("Work experience updated.")).toBeInTheDocument();
    const update = requests.find((request) =>
      request.method === "PATCH" && request.path.endsWith("/experiences/experience-123"),
    );
    expect(JSON.parse(update?.body || "{}")).toMatchObject({
      current_role: true,
      end_date: null,
    });
  });

  it("creates education and certification records through their profile endpoints", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Candidate profile" }));

    const education = within(screen.getByRole("heading", { name: "Education" }).closest("section") as HTMLElement);
    await user.click(education.getByRole("button", { name: "Add education" }));
    await user.type(education.getByRole("textbox", { name: "Qualification" }), "BSc Computing");
    await user.type(education.getByRole("textbox", { name: "Institution" }), "Synthetic Institute");
    fireEvent.change(education.getByLabelText(/Start date/), { target: { value: "2020-01-01" } });
    await user.click(education.getByRole("button", { name: "Save new education" }));
    expect(await screen.findByText("Education added.")).toBeInTheDocument();

    const certifications = within(screen.getByRole("heading", { name: "Certifications" }).closest("section") as HTMLElement);
    await user.click(certifications.getByRole("button", { name: "Add certification" }));
    await user.type(certifications.getByRole("textbox", { name: "Certification" }), "Synthetic Cloud Credential");
    await user.type(certifications.getByRole("textbox", { name: "Issuing organization" }), "Synthetic Board");
    fireEvent.change(certifications.getByLabelText(/Issue date/), { target: { value: "2025-02-01" } });
    await user.click(certifications.getByRole("button", { name: "Save new certification" }));
    expect(await screen.findByText("Certification added.")).toBeInTheDocument();

    expect(requests.some((request) =>
      request.method === "POST" &&
      request.path.endsWith("/education") &&
      JSON.parse(request.body || "{}").institution === "Synthetic Institute",
    )).toBe(true);
    expect(requests.some((request) =>
      request.method === "POST" &&
      request.path.endsWith("/certifications") &&
      JSON.parse(request.body || "{}").name === "Synthetic Cloud Credential",
    )).toBe(true);
  });

  it("uploads a new source document without treating it as an overwrite", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Documents" }));
    const file = new File(["candidate provided content"], "source.txt", { type: "text/plain" });
    await user.upload(screen.getByLabelText("Choose a document"), file);
    expect((screen.getByLabelText("Choose a document") as HTMLInputElement).files).toHaveLength(1);
    const uploadForm = screen.getByRole("button", { name: "Upload new document" }).closest("form");
    expect(uploadForm).not.toBeNull();
    fireEvent.submit(uploadForm!);

    await waitFor(() => expect(requests.some((request) =>
      request.method === "POST" &&
      request.path === `/api/v1/candidate-profiles/${profileId}/documents`,
    ), JSON.stringify(requests)).toBe(true));
    expect(await screen.findByText("Document uploaded as a new, separate source file.")).toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "POST" &&
      request.path === `/api/v1/candidate-profiles/${profileId}/documents` &&
      request.body === "[form-data]",
    )).toBe(true);
  });

  it("requires an explicit evidence review action to confirm a claim", async () => {
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: /^Evidence review/ }));

    expect(screen.getByText("Unreviewed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Confirm evidence" }));

    expect(await screen.findByText("Candidate-confirmed")).toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "PATCH" &&
      request.path.endsWith(`/evidence/${evidenceId}`) &&
      JSON.parse(request.body || "{}").confirmation_status === "candidate_confirmed",
    )).toBe(true);
  });

  it("keeps generated CV exports out of the source documents list", async () => {
    exports = [makeExport()];
    const user = userEvent.setup();
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Documents" }));

    expect(await screen.findByText("candidate-cv.txt")).toBeInTheDocument();
    expect(screen.queryByText("jobpilot-cv-export-123.pdf")).not.toBeInTheDocument();
    const documentRequests = requests.filter((request) => request.path.endsWith(`/candidate-profiles/${profileId}/documents`));
    expect(documentRequests.length).toBeGreaterThan(0);
    expect(documentRequests.every((request) => request.search === "?origin=source")).toBe(true);
    expect(requests.some((request) => request.path.endsWith("/documents/document-export-123/extraction"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Exports" }));
    expect(await screen.findByText("jobpilot-cv-export-123.pdf")).toBeInTheDocument();
  });

  it("creates and downloads exports only from a generated draft", async () => {
    const user = userEvent.setup();
    const createObjectUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    const revokeObjectUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    mountApp();
    await screen.findByRole("heading", { name: "Good to see you, Taylor" });
    await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
    expect(await screen.findByRole("heading", { name: "CV drafts" })).toBeInTheDocument();
    expect(screen.getByText("Validated draft")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Export PDF" }));

    expect(await screen.findByText(/PDF ·/)).toBeInTheDocument();
    const generatedDocumentIds = exports.map((entry) => entry.document_id);
    expect(requests.some((request) =>
      generatedDocumentIds.some((id) =>
        request.path === `/api/v1/candidate-profiles/${profileId}/documents/${id}/extraction`,
      ),
    )).toBe(false);
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(requests.some((request) => request.path.endsWith("/exports/export-123/download"))).toBe(true));
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(revokeObjectUrl).toHaveBeenCalled();
    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
    anchorClick.mockRestore();
  });

  describe("actions in progress", () => {
    // Holds the first request matching `predicate` open until release() is called.
    function holdRequest(predicate: (path: string, method: string) => boolean) {
      let release: (response?: Response) => void = () => {};
      let held = false;
      vi.mocked(fetch).mockImplementation((url: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(url), "http://localhost").pathname;
        const method = init?.method || "GET";
        if (!held && predicate(path, method)) {
          held = true;
          // Record the request when it is sent, not when it is answered.
          requests.push({ path, search: "", method, body: null, headers: new Headers(init?.headers), credentials: init?.credentials, mode: init?.mode });
          return new Promise<Response>((resolve) => {
            release = (response) => {
              if (response) return resolve(response);
              const real = responseFor(String(url), init);
              requests.pop(); // responseFor logged this request a second time
              resolve(real);
            };
          });
        }
        return Promise.resolve(responseFor(String(url), init));
      });
      return { release: (response?: Response) => release(response) };
    }

    const isExportCreate = (path: string, method: string) => method === "POST" && path.endsWith(`/cv-drafts/${draftId}/exports`);

    async function openDrafts(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
      await screen.findByRole("heading", { name: "CV drafts" });
    }

    it("disables export buttons and ignores repeated clicks while an export is running", async () => {
      const user = userEvent.setup();
      await openDrafts(user);
      const held = holdRequest(isExportCreate);

      await user.click(screen.getByRole("button", { name: "Export PDF" }));
      expect(await screen.findByText("Creating PDF export…")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Export PDF" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Export DOCX" })).toBeDisabled();
      fireEvent.click(screen.getByRole("button", { name: "Export PDF" }));
      fireEvent.click(screen.getByRole("button", { name: "Export DOCX" }));
      expect(requests.filter((request) => isExportCreate(request.path, request.method))).toHaveLength(1);

      held.release();
      expect(await screen.findByText("PDF export created.")).toBeInTheDocument();
      expect(screen.queryByText("Creating PDF export…")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Export PDF" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Export DOCX" })).toBeEnabled();
      expect(requests.filter((request) => isExportCreate(request.path, request.method))).toHaveLength(1);
    });

    it("restores buttons and shows the error when the running action fails", async () => {
      const user = userEvent.setup();
      await openDrafts(user);
      const held = holdRequest(isExportCreate);

      await user.click(screen.getByRole("button", { name: "Export DOCX" }));
      expect(await screen.findByText("Creating DOCX export…")).toBeInTheDocument();
      held.release(jsonResponse({ detail: "CV export storage is unavailable" }, 503));

      expect(await screen.findByText("CV export storage is unavailable")).toBeInTheDocument();
      expect(screen.queryByText("Creating DOCX export…")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Export PDF" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "Export DOCX" })).toBeEnabled();
      await user.click(screen.getByRole("button", { name: "Export PDF" }));
      expect(await screen.findByText("PDF export created.")).toBeInTheDocument();
    });

    it("restores buttons when a download fails at the network level", async () => {
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Documents" }));
      await screen.findByText("candidate-cv.txt");
      vi.mocked(fetch).mockImplementation((url: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(url), "http://localhost").pathname;
        if (path.endsWith(`/documents/${documentId}/download`)) return Promise.reject(new TypeError("Failed to fetch"));
        return Promise.resolve(responseFor(String(url), init));
      });

      await user.click(screen.getByRole("button", { name: "Download" }));

      expect(await screen.findByText("The download could not reach the local API.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
      expect(screen.queryByText("Downloading document…")).not.toBeInTheDocument();
    });

    it("tells the user to wait instead of silently dropping a second action", async () => {
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Job descriptions" }));
      await user.type(screen.getByRole("textbox", { name: /Job title/ }), "Support Engineer");
      await user.type(screen.getByRole("textbox", { name: /Full job description/ }), "Help customers.");
      const isJobCreate = (path: string, method: string) => method === "POST" && path.endsWith("/job-descriptions");
      const held = holdRequest(isJobCreate);

      await user.click(screen.getByRole("button", { name: "Save job description" }));
      expect(await screen.findByText("Saving job description…")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Save job description" })).toBeDisabled();
      fireEvent.submit(screen.getByRole("button", { name: "Save job description" }).closest("form")!);

      expect(await screen.findByText("Please wait for the current action to finish before starting another.")).toBeInTheDocument();
      expect(requests.filter((request) => isJobCreate(request.path, request.method))).toHaveLength(1);

      held.release();
      expect(await screen.findByText("Job description saved.")).toBeInTheDocument();
      expect(screen.queryByText("Please wait for the current action to finish before starting another.")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Save job description" })).toBeEnabled();
    });

    it("keeps navigation available while an action is running", async () => {
      const user = userEvent.setup();
      await openDrafts(user);
      const held = holdRequest(isExportCreate);

      await user.click(screen.getByRole("button", { name: "Export PDF" }));
      await screen.findByText("Creating PDF export…");
      await user.click(screen.getByRole("button", { name: "Documents" }));
      expect(await screen.findByRole("heading", { name: "Documents" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();

      held.release();
      expect(await screen.findByText("PDF export created.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Download" })).toBeEnabled();
    });
  });
  describe("job discovery", () => {
    function makeListing(overrides: Record<string, unknown> = {}) {
      return {
        id: "listing-1", source_kind: "greenhouse", source_key: "syntheticco", source_listing_id: "101",
        source_url: "https://boards-api.greenhouse.io/v1/boards/syntheticco/jobs?content=true",
        application_url: "https://boards.greenhouse.io/syntheticco/jobs/101",
        employer_name: "Synthetic Co", title: "Technical Support Specialist", location_text: "Remote - EMEA",
        stated_workplace_type: null, stated_countries: [], posted_at: null, source_updated_at: null,
        application_deadline: null, salary_min: null, salary_max: null, salary_currency: null, salary_period: null,
        source_status: "active", first_seen_at: now, last_seen_at: now, last_verified_at: now, dedupe_key: "a".repeat(64),
        eligibility: { status: "unknown", reason: "Eligibility for Kenya-based applicants has not been assessed." },
        ...overrides,
      };
    }

    async function openDiscovery(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Discovered jobs" }));
    }

    it("shows stored listings as source facts with eligibility unknown", async () => {
      jobListings = [makeListing(), makeListing({ id: "listing-2", title: "IT Support L2", application_url: "javascript:alert(1)", posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);

      expect(await screen.findByText("Technical Support Specialist")).toBeInTheDocument();
      expect(screen.getAllByText("Eligibility unknown")).toHaveLength(2);
      expect(screen.getByText("Posting date not provided by source")).toBeInTheDocument();
      const link = screen.getByRole("link", { name: /Open original listing/ });
      expect(link).toHaveAttribute("href", "https://boards.greenhouse.io/syntheticco/jobs/101");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(screen.getAllByRole("link", { name: /Open original listing/ })).toHaveLength(1);
      expect(screen.getByText("The source did not provide a secure listing link.")).toBeInTheDocument();
    });

    it("requests only source-dated listings for the 24-hour window", async () => {
      jobListings = [makeListing(), makeListing({ id: "listing-2", title: "Dated role", posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);
      await screen.findByText("Technical Support Specialist");

      await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "24");

      expect(await screen.findByText("Dated role")).toBeInTheDocument();
      expect(screen.queryByText("Technical Support Specialist")).not.toBeInTheDocument();
      expect(requests.some((request) => request.path === "/api/v1/job-listings" && request.search === "?posted_within_hours=24")).toBe(true);
    });

    it("shows an honest empty state and reports failed source runs", async () => {
      discoveryRuns = [{
        id: "run-1", source_kind: "greenhouse", source_key: "syntheticco", status: "failed", error_category: "rate_limited",
        started_at: now, finished_at: now, fetched_count: 0, created_count: 0, updated_count: 0, unchanged_count: 0, missing_count: 0, skipped_count: 0,
      }];
      const user = userEvent.setup();
      await openDiscovery(user);

      expect(await screen.findByText("No discovered jobs")).toBeInTheDocument();
      expect(screen.getByText(/greenhouse:syntheticco failed \(rate limited\)/)).toBeInTheDocument();
    });

    it("surfaces API errors instead of an empty list", async () => {
      failJobListings = true;
      const user = userEvent.setup();
      await openDiscovery(user);

      expect(await screen.findByText("Job listings are unavailable.")).toBeInTheDocument();
      expect(screen.queryByText("No discovered jobs")).not.toBeInTheDocument();
    });
  });
});
