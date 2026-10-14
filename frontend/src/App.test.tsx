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
let requests: Array<{ path: string; method: string; body: string | null }> = [];
let failJobSave = false;

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
    method,
    body: body || (init.body instanceof FormData ? "[form-data]" : null),
  });

  if (path === `/api/v1/candidate-profiles/${profileId}`) {
    if (method === "PATCH") {
      currentProfile = { ...currentProfile, ...JSON.parse(body || "{}") };
      return jsonResponse(currentProfile);
    }
    if (method === "GET") return jsonResponse(currentProfile);
  }
  if (path.endsWith("/experiences")) return jsonResponse([]);
  if (path.endsWith("/education")) return jsonResponse([]);
  if (path.endsWith("/skills")) return jsonResponse([]);
  if (path.endsWith("/certifications")) return jsonResponse([]);
  if (path === `/api/v1/candidate-profiles/${profileId}/documents`) {
    if (method === "POST") return jsonResponse(document, 201);
    return jsonResponse([document]);
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
    requests = [];
    failJobSave = false;
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

    expect(await screen.findByText("Candidate profile saved.")).toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "PATCH" &&
      request.path === `/api/v1/candidate-profiles/${profileId}` &&
      JSON.parse(request.body || "{}").professional_headline === "Systems Engineer",
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
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(requests.some((request) => request.path.endsWith("/exports/export-123/download"))).toBe(true));
    expect(createObjectUrl).toHaveBeenCalled();
    expect(anchorClick).toHaveBeenCalled();
    expect(revokeObjectUrl).toHaveBeenCalled();
    createObjectUrl.mockRestore();
    revokeObjectUrl.mockRestore();
    anchorClick.mockRestore();
  });
});
