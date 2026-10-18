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
let importedJobs: Array<Record<string, unknown>> = [];
let jobSources: Array<Record<string, unknown>> = [];
let confirmations: Array<Record<string, unknown>> = [];
// Discovery refresh: the state POST returns, then what each later GET returns.
let refreshStates: Array<Record<string, unknown>> = [];
let listingTotal: number | null = null;
let eligibilityEvidence: Record<string, unknown> = { passages: [], conflicts: [] };
let applications: Array<Record<string, unknown>> = [];
const notConfirmed = {
  confirmation_status: "not_confirmed", confirmed_at: null, country_of_residence: null, country_of_residence_name: null,
  relocation_willingness: null, relocation_countries: [], accepted_work_arrangements: [], work_authorizations: [],
};
let eligibilityDetails: Record<string, unknown> = notConfirmed;
const countryNames: Record<string, string> = { KE: "Kenya", DE: "Germany", US: "United States" };
let jobFit: Record<string, unknown> | null = null;
let atsReport: Record<string, unknown> | null = null;
let suggestedEvidence: Array<Record<string, unknown>> = [];
let extractionPostStatus = "succeeded";
let evidenceSourceCurrent = true;
let batchEvidence: Array<Record<string, unknown>> = [];
let failPipeline = false;
let preparedListings: string[] = [];

function decision(state: string, explanation: string, quotation?: string) {
  return {
    state, rule: `${state}_rule`, explanation, conflicts: [], requirements: [],
    evidence: quotation ? [{ kind: state === "ineligible" ? "negative" : "positive", rule: `${state}_rule`, quotation, field: "location", countries: [], explanation }] : [],
    source_url: "https://job-boards.greenhouse.io/gitlab/jobs/1", source_type: "greenhouse board (direct employer)",
    source_authoritative: true, checked_at: now, assessment_id: null,
  };
}

function pipelineCard(id: string, title: string, queue: string, eligibility: Record<string, unknown>, extra: Record<string, unknown> = {}) {
  const tracked = preparedListings.includes(id);
  return {
    listing_id: id, title, employer: "GitLab", location: "Nairobi, Kenya", workplace_type: null,
    posted_at: "2026-10-16T06:00:00Z", first_seen_at: now, application_deadline: null,
    listing_url: `https://job-boards.greenhouse.io/gitlab/jobs/${id}`, application_url: `https://job-boards.greenhouse.io/gitlab/jobs/${id}`,
    source: { name: "GitLab", category: "direct_employer", registered: true },
    queue, reasons: [], next_step: "Read the quoted wording.", eligibility,
    application_method: {
      submission: "manual_submission", reason: "Greenhouse only accepts applications through its API with the employer's private API key.",
      jobpilot_prepares: ["Tailored CV draft from confirmed evidence (you review and approve it)"],
      candidate_steps: ["Answer screening questions yourself; JobPilot does not answer them for you."],
    },
    application: tracked ? { id: "application-new", status: "preparing" } : null, fit: null, ...extra,
  };
}

const serviceDeskMatch = {
  family: "help_desk", label: "Help desk and service desk", matched_text: "Service Desk",
  reason: "The title contains \"Service Desk\" (role family: Help desk and service desk).",
};

function makePipeline() {
  const needs = [pipelineCard("listing-ready", "Service Desk Analyst", "needs_action", decision("eligible", "The employer's location for this job names Kenya.", "Nairobi, Kenya"), {
    role_match: serviceDeskMatch,
    reasons: [{ code: "manual_submission", message: "Greenhouse only accepts applications through its API with the employer's private API key." }],
    next_step: "Prepare the application here, then submit it yourself on the official page.",
    fit: { score: 72, potential_score: 80, verdict: "moderate_match", headline: "Your confirmed records support part of what this job asks for.", essential_met: 3, essential_total: 4, missing_essential: ["ITIL certification"], missing_preferred: [] },
  })];
  const review = [pipelineCard("listing-remote", "Remote Support Engineer", "review_needed", decision("unverified", "The listing says remote but does not say which countries applicants may be in."), { location: "Remote" })];
  const excluded = [pipelineCard("listing-us", "US Support Specialist", "not_eligible", decision("ineligible", "The employer's location for this job lists only places outside Kenya.", "Remote, United States"), {
    location: "Remote, United States", reasons: [{ code: "location_label_excludes_kenya", message: "The employer's location for this job lists only places outside Kenya." }],
    next_step: "No action needed: the employer's wording rules out Kenya-based applicants.",
  })];
  return {
    counts: { auto_apply: 0, needs_action: needs.length, review_needed: review.length, not_eligible: excluded.length },
    queues: { auto_apply: [], needs_action: needs, review_needed: review, not_eligible: excluded },
    automation: { automatic_submission_available: false, explanation: "None of the current job sources lets an applicant submit through an official channel." },
    generated_at: now,
  };
}

function makePreparedApplication(listingId: string) {
  return {
    listing_id: listingId, job_description_id: jobId, cv_draft_id: draftId, cv_draft_status: "generated",
    application_id: "application-new", application_status: "preparing", submitted: false,
    steps: [
      { step: "Kenya eligibility rechecked", status: "done", detail: "The employer's location for this job names Kenya." },
      { step: "Submission", status: "handed_to_you", detail: "Greenhouse only accepts applications through its API with the employer's private API key." },
    ],
    eligibility: decision("eligible", "The employer's location for this job names Kenya.", "Nairobi, Kenya"),
    fit: { score: 72, potential_score: 80, headline: "Part match." },
    cover_letter: { text: "Dear Hiring Team at GitLab,\n\nI am applying for the Service Desk Analyst role.", sources: [], notes: ["Draft only: read it, edit it in your own words, and only send what is true."] },
    handoff: { application_url: "https://job-boards.greenhouse.io/gitlab/jobs/listing-ready", reason: "Manual submission.", candidate_steps: [] },
  };
}
let failEvidencePatch = false;
let reviewedDraft: (Record<string, unknown> & { id: string }) | null = null;
let draftNeedsConfirmation = false;
// Overrides what generating a draft returns: a status and body, or a network failure.
let generationResponse: { status: number; body: unknown } | "network" | null = null;
let reviewOverrides: Record<string, unknown> = {};

function withApproval<T extends Record<string, unknown>>(value: T, status: "pending_review" | "approved"): T {
  return {
    ...value,
    structured_content: {
      review: {
        writer_version: "reviewed-writer/1", job_description_id: jobId, source_document_id: documentId,
        parent_draft_id: null, approval_status: status, approved_at: status === "approved" ? now : null,
        attested_unconfirmed_statements: false, suggestions: [], ats_score: 72, ats_potential_score: 80,
      },
    },
  };
}

function makeAtsReport(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const requirement = (id: string, text: string, status: string, extra: Record<string, unknown> = {}) => ({
    id, category: "tool", importance: "essential", basis: "explicit", text, source_text: text, section: "Requirements",
    terms: [], note: null, status, explanation: `${status} explanation for ${text}`, evidence: [], ...extra,
  });
  return {
    analysis_version: "ats-analysis/1", job_description_id: jobId, source_document_id: null,
    verdict: "moderate_match", headline: "Your confirmed records support part of what this job asks for.",
    eligibility_overrides_score: false, score: 64, potential_score: 78,
    score_explanation: {
      method: "Each requirement earns full credit when your records demonstrate it.",
      components: [
        { name: "essential", items: 2, base_weight: 55, effective_weight: 55, fraction_credited: 0.75, points: 41.3 },
        { name: "keywords", items: 3, base_weight: 15, effective_weight: 15, fraction_credited: 0.5, points: 7.5 },
      ],
      potential_note: "The potential score counts uncertain items as if you confirmed them.",
      limitations: ["This score does not reproduce any employer's screening system."],
    },
    requirements: {
      essential: [
        requirement("r1", "Experience with Python", "matched", { evidence: [{ kind: "demonstrated", source_type: "work_experience", source_id: "experience-123", label: "Platform Engineer at Northstar Systems", excerpt: null }] }),
        requirement("r2", "Kubernetes in production", "missing"),
      ],
      preferred: [requirement("r3", "Terraform is a plus", "uncertain", { importance: "preferred", basis: "inferred" })],
      responsibilities: [], eligibility: [], counts: { essential: 2, preferred: 1 }, sections_found: ["Requirements"],
    },
    keywords: [
      { term: "python", count: 3, kind: "tool", importance: "high", status: "shown" },
      { term: "kubernetes", count: 2, kind: "tool", importance: "high", status: "absent" },
    ],
    eligibility: {
      geographic: { status: "eligibility_unknown", reason: "This job was pasted, so no eligibility review exists.", quotation: null },
      disqualifiers: [], location_items: [], candidate_details_confirmed: false,
    },
    screening_concerns: [{ severity: "high", text: "Essential requirement not shown: Kubernetes in production" }],
    cv_document: null,
    recommendations: [{ rank: 1, priority: 4, category: "gap", text: "Essential requirement not shown: \"Kubernetes in production\". Do not claim it unless it is true." }],
    experience_summary: { total_years: 4.8, roles: 1 },
    ...overrides,
  };
}

function makeDraftReview(): Record<string, unknown> {
  const approved = (reviewedDraft?.structured_content as { review: { approval_status: string } }).review.approval_status === "approved";
  return {
    ...reviewOverrides,
    draft_id: reviewedDraft?.id, writer_version: "reviewed-writer/1", requires_approval: true,
    approval: { approval_status: approved ? "approved" : "pending_review", approved_at: approved ? now : null, attested_unconfirmed_statements: false, parent_draft_id: null },
    ats_score: 72, ats_potential_score: 80,
    change_log: [
      {
        key: "role:experience-123:0", section: "Professional Experience", role: "Platform Engineer at Northstar Systems",
        original: "responsible for maintaining deployment systems", proposed: "Maintained deployment systems.", changed: true, significance: "wording", origin: "rewritten",
        reasons: ["Starts with what you did rather than \"responsible for\" or \"duties included\"."],
        evidence: [{ source_type: "work_experience", source_field: "achievements[0]", text: "responsible for maintaining deployment systems", source_excerpt: null, confirmed: true }],
        needs_confirmation: false, confirmation_note: null,
      },
      {
        key: "role:experience-123:1", section: "Professional Experience", role: "Platform Engineer at Northstar Systems",
        original: "Improved release checks.", proposed: "Improved release checks by 40%.", changed: true, significance: "wording", origin: "candidate_edited",
        reasons: ["Edited by you."],
        evidence: [{ source_type: "work_experience", source_field: "achievements[1]", text: "Improved release checks.", source_excerpt: null, confirmed: true }],
        needs_confirmation: draftNeedsConfirmation, confirmation_note: draftNeedsConfirmation ? "Contains wording not found in your records: 40." : null,
      },
    ],
    needs_confirmation: draftNeedsConfirmation ? 1 : 0,
    suggestions: ["\"results-driven\" is a common filler phrase; replace it with a specific example if you have one."],
    checks: {
      passed: true, word_count: 220, plain_text: "Taylor Candidate\nPlatform Engineer\n\nProfessional Summary\n\n- I build reliable systems.",
      checks: [{ name: "Sections", status: "pass", detail: "Found Professional Summary." }, { name: "Writing", status: "warn", detail: "Several statements open with \"managed\"." }],
    },
    trace: {
      job_description: { id: jobId, job_title: "Platform Engineer", company: "Example Org", source_job_listing_id: null },
      source_document: { id: documentId, filename: "candidate-cv.txt" }, evidence_used: [], parent_draft_id: null,
    },
    export_ready: approved, export_blockers: approved ? [] : ["Review the changes and approve this draft before exporting it."],
  };
}

function makeFit(overrides: Record<string, unknown> = {}) {
  return {
    job_description_id: jobId, verdict: "eligibility_unknown",
    headline: "Kenya eligibility has not been established for this job. Review it before applying.",
    geographic_eligibility: { status: "eligibility_unknown", currency: "not_assessed", listing_id: null, reason: "This job was pasted, not imported from a discovered listing, so no eligibility review exists for it.", quotation: null, assessment_id: null, assessed_at: null },
    candidate_details_confirmed: false, candidate_country_of_residence: null,
    coverage: { met: 1, total: 2, summary: "1 of 2 stated skill requirements are supported by your own information. This measures skills coverage only; it is not eligibility." },
    matched: [{ kind: "skill", requirement: "Python", status: "met", explanation: "Supported by your own information (1 source).", quotation: null, sources: [{ source_type: "skill", source_id: "skill-123", label: "Skill: Python" }] }],
    missing: [{ kind: "skill", requirement: "Kubernetes", status: "missing", explanation: "None of your profile records or confirmed evidence mention this. It is not added to your CV.", quotation: null, sources: [] }],
    uncertain: [], disqualifiers: [], location_requirements_met: [], preferences: [],
    ...overrides,
  };
}
// Mirrors the server's allowed status transitions.
const applicationTransitions: Record<string, string[]> = {
  saved: ["eligibility_review", "preparing", "withdrawn", "closed"],
  eligibility_review: ["saved", "preparing", "withdrawn", "closed"],
  preparing: ["eligibility_review", "ready_for_review", "withdrawn", "closed"],
  ready_for_review: ["preparing", "applied", "withdrawn", "closed"],
  applied: ["interviewing", "offer", "rejected", "withdrawn", "closed"],
  interviewing: ["offer", "rejected", "withdrawn", "closed"],
  offer: ["withdrawn", "closed"],
  rejected: ["closed"],
  withdrawn: ["closed"],
  closed: [],
};

function makeApplication(overrides: Record<string, unknown> = {}) {
  const status = (overrides.status as string) || "saved";
  return {
    id: "application-1", candidate_profile_id: profileId, job_description_id: jobId, cv_draft_id: null,
    status, applied_on: null, deadline_on: null, follow_up_on: null, contact_name: null, contact_email: null,
    notes: null, created_at: now, updated_at: now,
    events: [{ id: "event-1", from_status: null, to_status: status, note: null, occurred_at: now }],
    ...overrides,
    allowed_next_statuses: applicationTransitions[status],
  };
}
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
  if (path.endsWith(`/documents/${documentId}/extraction`) && method === "POST") {
    return jsonResponse({
      id: "extraction-123", source_document_id: documentId, status: extractionPostStatus,
      character_count: extractionPostStatus === "succeeded" ? 29 : 0, extractor_version: "PyMuPDF/1",
      error_category: extractionPostStatus === "failed" ? "invalid_document" : null, extracted_at: now,
      trust_status: "unverified_source_text",
    });
  }
  if (path.endsWith(`/documents/${documentId}/evidence-suggestions`) && method === "POST") {
    const fresh = suggestedEvidence.length ? [] : [{
      ...evidenceBase, id: "evidence-suggested", category: "metric", description: "Resolved 40 tickets a day",
      source_excerpt: "Resolved 40 tickets a day", source_section: "WORK EXPERIENCE", source_current: true,
    }];
    suggestedEvidence = [...suggestedEvidence, ...fresh];
    return jsonResponse({ created: fresh.length, skipped_existing: fresh.length ? 0 : 1, limited: false, evidence: fresh });
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/evidence`) {
    return jsonResponse([{ ...evidenceBase, confirmation_status: evidenceStatus, source_current: evidenceSourceCurrent }, ...suggestedEvidence, ...batchEvidence]);
  }
  const batchPatch = path.match(new RegExp(`^/api/v1/candidate-profiles/${profileId}/evidence/(batch-\\d+)$`));
  if (batchPatch && method === "PATCH") {
    if (failEvidencePatch) return jsonResponse({ detail: "The source text changed since this evidence was recorded." }, 409);
    const item = batchEvidence.find((entry) => entry.id === batchPatch[1]) as Record<string, unknown>;
    const updated = { ...item, ...JSON.parse(body || "{}") };
    // Like PostgreSQL with equal created_at values: the updated row comes back last.
    batchEvidence = [...batchEvidence.filter((entry) => entry.id !== item.id), updated];
    return jsonResponse(updated);
  }
  if (path.endsWith(`/evidence/${evidenceId}`) && method === "PATCH") {
    const patch = JSON.parse(body || "{}");
    if ("source_excerpt" in patch) evidenceSourceCurrent = true;
    if (patch.confirmation_status) evidenceStatus = patch.confirmation_status;
    return jsonResponse({ ...evidenceBase, confirmation_status: evidenceStatus, source_current: evidenceSourceCurrent });
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/job-descriptions`) {
    if (method === "POST") {
      if (failJobSave) return jsonResponse({ detail: "Job description is invalid." }, 422);
      return jsonResponse(job, 201);
    }
    return jsonResponse([job, ...importedJobs]);
  }
  const listingImport = path.match(new RegExp(`^/api/v1/candidate-profiles/${profileId}/job-descriptions/from-listing/([^/]+)$`));
  if (listingImport && method === "POST") {
    const listingId = decodeURIComponent(listingImport[1]);
    const existing = importedJobs.find((item) => item.source_job_listing_id === listingId);
    if (existing) return jsonResponse(existing);
    const imported = { ...job, id: `job-from-${listingId}`, job_title: "Technical Support Specialist", company: "Synthetic Co", source_job_listing_id: listingId };
    importedJobs = [...importedJobs, imported];
    return jsonResponse(imported, 201);
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/cv-drafts`) {
    if (method === "GET") return jsonResponse(reviewedDraft ? [reviewedDraft] : [draft]);
  }
  if (path.match(/\/job-descriptions\/[^/]+\/cv-drafts$/) && method === "POST") {
    if (generationResponse === "network") throw new TypeError("Failed to fetch");
    if (generationResponse) return jsonResponse(generationResponse.body, generationResponse.status);
    return jsonResponse({ ...draft, id: "draft-new" }, 201);
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
    const params = new URL(url, "http://localhost").searchParams;
    const eligibilityFilter = params.get("eligibility");
    const kenyaFilter = params.get("kenya");
    const items = jobListings
      .filter((item) => !params.get("posted_within_hours") || item.posted_at)
      .filter((item) => !eligibilityFilter || (item.eligibility as { status: string }).status === eligibilityFilter)
      .filter((item) => !kenyaFilter || (item.kenya_eligibility as { state: string } | undefined)?.state === kenyaFilter);
    return jsonResponse({ items, total: listingTotal ?? items.length, limit: 50, offset: Number(params.get("offset") ?? 0) });
  }
  if (path === "/api/v1/job-sources") return jsonResponse(jobSources);
  if (path === "/api/v1/job-discovery/refresh") {
    const idle = { state: "idle", started_at: null, finished_at: null, requested: [], current: null, outcomes: [] };
    if (method === "POST") return jsonResponse(refreshStates.shift() ?? idle, 202);
    return jsonResponse(refreshStates.length > 1 ? refreshStates.shift() : refreshStates[0] ?? idle);
  }
  const evidenceMatch = path.match(/^\/api\/v1\/job-listings\/([^/]+)\/eligibility-evidence$/);
  if (evidenceMatch) return jsonResponse(eligibilityEvidence);
  const listingDetail = path.match(/^\/api\/v1\/job-listings\/([^/]+)(\/eligibility-assessments)?$/);
  if (listingDetail) {
    const listing = jobListings.find((item) => item.id === listingDetail[1]);
    if (!listing) return jsonResponse({ detail: "Job listing not found" }, 404);
    if (listingDetail[2] && method === "POST") {
      const payload = JSON.parse(body || "{}");
      const eligibility = {
        status: payload.outcome, reason: "Reviewed.", currency: "current", assessed_at: now,
        explanation: payload.explanation, quotation: payload.quotation ?? null,
        evidence_field: payload.evidence_field ?? null, statement_scope: payload.statement_scope ?? null,
        role_applicability: payload.role_applicability ?? null,
      };
      jobListings = jobListings.map((item) => (item.id === listing.id ? { ...item, eligibility } : item));
      return jsonResponse(eligibility, 201);
    }
    return jsonResponse({ ...listing, description_text: "Support customers worldwide.\nThis role is open to candidates in any country." });
  }
  if (path === "/api/v1/job-discovery/runs" && method === "GET") return jsonResponse(discoveryRuns);
  if (path === `/api/v1/candidate-profiles/${profileId}/skill-confirmations` && method === "GET") return jsonResponse(confirmations);
  if (path === `/api/v1/candidate-profiles/${profileId}/skill-confirmations` && method === "POST") {
    const payload = JSON.parse(body || "{}");
    const created = { id: `confirmation-${confirmations.length + 1}`, candidate_profile_id: profileId, status: "active", provenance: "candidate_confirmed",
      independently_verified: false, requirement_text: null, proficiency_level: null, work_experience_id: null, project_name: null, example: null,
      job_description_id: null, requirement_key: null, confirmed_at: now, created_at: now, updated_at: now, ...payload };
    confirmations = [...confirmations, created];
    return jsonResponse(created, 201);
  }
  if (path === "/api/v1/countries") {
    return jsonResponse(Object.entries(countryNames).map(([code, name]) => ({ code, name })));
  }
  if (path === `/api/v1/candidate-profiles/${profileId}/eligibility-details`) {
    if (method === "PUT") {
      const payload = JSON.parse(body || "{}");
      eligibilityDetails = {
        confirmation_status: "confirmed", confirmed_at: now,
        country_of_residence: payload.country_of_residence,
        country_of_residence_name: payload.country_of_residence ? countryNames[payload.country_of_residence] : null,
        relocation_willingness: payload.relocation_willingness, relocation_countries: payload.relocation_countries,
        accepted_work_arrangements: payload.accepted_work_arrangements,
        work_authorizations: payload.work_authorizations.map((item: { country_code: string; status: string }) => ({ ...item, country_name: countryNames[item.country_code], confirmed_at: now })),
      };
    }
    return jsonResponse(eligibilityDetails);
  }
  if (path.match(/\/job-descriptions\/[^/]+\/fit$/) && method === "GET") return jsonResponse(jobFit || makeFit());
  if (path.match(/\/job-descriptions\/[^/]+\/ats-analysis$/) && method === "GET") return jsonResponse(atsReport || makeAtsReport());
  if (path === `/api/v1/candidate-profiles/${profileId}/job-pipeline` && method === "GET") {
    if (failPipeline) return jsonResponse({ detail: "The pipeline is unavailable." }, 503);
    return jsonResponse(makePipeline());
  }
  const prepareMatch = path.match(new RegExp(`^/api/v1/candidate-profiles/${profileId}/job-listings/([^/]+)/prepare-application$`));
  if (prepareMatch && method === "POST") {
    preparedListings = [...preparedListings, prepareMatch[1]];
    return jsonResponse(makePreparedApplication(prepareMatch[1]));
  }
  const reviewMatch = path.match(new RegExp(`^/api/v1/candidate-profiles/${profileId}/cv-drafts/([^/]+)/(review|revisions|approval)$`));
  if (reviewMatch && reviewedDraft && reviewMatch[1] === reviewedDraft.id) {
    if (reviewMatch[2] === "review") return jsonResponse(makeDraftReview());
    if (reviewMatch[2] === "revisions" && method === "POST") return jsonResponse({ ...reviewedDraft, id: "draft-revised" }, 201);
    if (reviewMatch[2] === "approval" && method === "POST") {
      if (reviewOverrides.status === "needs_review" && !JSON.parse(body || "{}").acknowledge_incomplete) {
        return jsonResponse({ detail: "This draft is incomplete." }, 409);
      }
      if (draftNeedsConfirmation && !JSON.parse(body || "{}").attest_unconfirmed_statements) {
        return jsonResponse({ detail: "1 statement(s) contain wording that is not in your records." }, 409);
      }
      reviewedDraft = withApproval(reviewedDraft, "approved");
      return jsonResponse(reviewedDraft);
    }
  }
  if (path.match(/\/cv-drafts\/[^/]+\/exports$/) && method === "GET") return jsonResponse([]);
  const applicationsPath = `/api/v1/candidate-profiles/${profileId}/applications`;
  if (path === applicationsPath) {
    if (method === "GET") return jsonResponse(applications);
    const payload = JSON.parse(body || "{}");
    if (applications.some((item) => item.job_description_id === payload.job_description_id)) {
      return jsonResponse({ detail: "This job is already being tracked as an application." }, 409);
    }
    const created = makeApplication({ id: `application-${applications.length + 1}`, ...payload });
    applications = [...applications, created];
    return jsonResponse(created, 201);
  }
  const applicationMatch = path.match(new RegExp(`^${applicationsPath}/([^/]+)(/status)?$`));
  if (applicationMatch) {
    const existing = applications.find((item) => item.id === applicationMatch[1]);
    if (!existing) return jsonResponse({ detail: "Application not found" }, 404);
    const payload = JSON.parse(body || "{}");
    let updated: Record<string, unknown>;
    if (applicationMatch[2] && method === "POST") {
      if (!applicationTransitions[existing.status as string].includes(payload.status)) {
        return jsonResponse({ detail: `An application cannot move from ${existing.status} to ${payload.status}.` }, 409);
      }
      const events = [...(existing.events as unknown[]), { id: `event-${Date.now()}`, from_status: existing.status, to_status: payload.status, note: payload.note || null, occurred_at: now }];
      updated = makeApplication({ ...existing, status: payload.status, applied_on: payload.applied_on ?? existing.applied_on, events });
    } else if (method === "PATCH") {
      updated = makeApplication({ ...existing, ...payload });
    } else {
      return jsonResponse(existing);
    }
    applications = applications.map((item) => (item.id === existing.id ? updated : item));
    return jsonResponse(updated);
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
    importedJobs = [];
    jobSources = [];
    confirmations = [];
    refreshStates = [];
    listingTotal = null;
    eligibilityEvidence = { passages: [], conflicts: [] };
    applications = [];
    eligibilityDetails = notConfirmed;
    jobFit = null;
    atsReport = null;
    generationResponse = null;
    reviewOverrides = {};
    suggestedEvidence = [];
    extractionPostStatus = "succeeded";
    evidenceSourceCurrent = true;
    batchEvidence = [];
    failEvidencePatch = false;
    failPipeline = false;
    preparedListings = [];
    reviewedDraft = null;
    draftNeedsConfirmation = false;
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

  it("logs in through a pre-auth challenge and uses credentialed cross-origin requests", async () => {
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
    expect(requests[loginIndex].credentials).toBe("include");
    expect(requests[loginIndex].mode).toBe("cors");
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
    expect(logoutRequest?.credentials).toBe("include");
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

      expect(await screen.findByText("The download could not reach the configured API.")).toBeInTheDocument();
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
  describe("work eligibility and job fit", () => {
    async function openProfile(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Candidate profile" }));
      return screen.findByRole("region", { name: "Work eligibility details" });
    }

    it("keeps the free-text location unconfirmed and shows unknowns as unknown", async () => {
      const user = userEvent.setup();
      const panel = await openProfile(user);

      expect(within(panel).getByText("Not confirmed")).toBeInTheDocument();
      expect(within(panel).getByText(/Your profile location \("Nairobi, Kenya"\) is free text and is not treated as confirmed/)).toBeInTheDocument();
      expect(within(panel).getByText("Country of residence").nextElementSibling).toHaveTextContent("Unknown");
      expect(within(panel).getByText("Authorized to work in").nextElementSibling).toHaveTextContent("None confirmed");
    });

    it("confirms details only after the candidate ticks the confirmation", async () => {
      const user = userEvent.setup();
      const panel = await openProfile(user);

      await user.click(within(panel).getByRole("button", { name: "Confirm your details" }));
      const form = within(panel).getByRole("form", { name: "Confirm work eligibility details" });
      await waitFor(() => expect(within(form).getAllByRole("option", { name: "Kenya" }).length).toBeGreaterThan(0));
      await user.selectOptions(within(form).getByRole("combobox", { name: "Country of residence" }), "KE");
      await user.click(within(form).getByRole("button", { name: "Add a country" }));
      await user.selectOptions(within(form).getByRole("combobox", { name: "Authorization country 1" }), "KE");
      await user.click(within(form).getByRole("checkbox", { name: "Remote" }));
      const submit = within(form).getByRole("button", { name: "Confirm details" });
      expect(submit).toBeDisabled();

      await user.click(within(form).getByRole("checkbox", { name: /I confirm these details are accurate/ }));
      await user.click(submit);

      await screen.findByText("Work eligibility details confirmed.");
      const put = requests.find((request) => request.method === "PUT" && request.path.endsWith("/eligibility-details"));
      expect(JSON.parse(put?.body || "{}")).toEqual({
        confirmed: true, country_of_residence: "KE", relocation_willingness: null, relocation_countries: [],
        accepted_work_arrangements: ["remote"], work_authorizations: [{ country_code: "KE", status: "authorized" }],
      });
      const updated = await screen.findByRole("region", { name: "Work eligibility details" });
      expect(within(updated).getByText(/Confirmed by you/)).toBeInTheDocument();
      expect(within(updated).getByText("Authorized to work in").nextElementSibling).toHaveTextContent("Kenya");
    });

    async function openFit(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
      await user.selectOptions(screen.getByRole("combobox", { name: "Saved job description" }), jobId);
      return screen.findByRole("region", { name: "Job fit" });
    }

    it("shows met, missing and uncertain requirements with their sources", async () => {
      const user = userEvent.setup();
      const panel = await openFit(user);

      expect(within(panel).getByText(/not eligibility/)).toBeInTheDocument();
      const met = within(panel).getByRole("region", { name: "Requirements you meet" });
      expect(within(met).getByText("Python")).toBeInTheDocument();
      expect(within(met).getByText("From: Skill: Python")).toBeInTheDocument();
      expect(within(within(panel).getByRole("region", { name: "Not found in your information" })).getByText("Kubernetes")).toBeInTheDocument();
      expect(within(panel).getByText(/You have not confirmed your work eligibility details/)).toBeInTheDocument();
      expect(requests.some((request) => request.path.endsWith(`/job-descriptions/${jobId}/fit`))).toBe(true);
    });

    it("keeps a stated Kenya exclusion separate from full skills coverage", async () => {
      jobFit = makeFit({
        verdict: "excluded_by_employer",
        headline: "The employer's own wording excludes applicants based in Kenya. Skills coverage does not change this.",
        geographic_eligibility: { status: "not_eligible", currency: "current", listing_id: "listing-1", reason: "The employer's wording rules out applicants based in Kenya.", quotation: "Applicants must reside in the United Kingdom.", assessment_id: "assessment-1", assessed_at: now },
        coverage: { met: 2, total: 2, summary: "2 of 2 stated skill requirements are supported by your own information. This measures skills coverage only; it is not eligibility." },
        missing: [],
      });
      const user = userEvent.setup();
      const panel = await openFit(user);

      expect(within(panel).getByText(/Skills coverage does not change this/)).toBeInTheDocument();
      const kenya = within(panel).getByRole("region", { name: "Kenya eligibility" });
      expect(within(kenya).getByText("Kenya-based applicants excluded")).toBeInTheDocument();
      expect(within(kenya).getByText("Applicants must reside in the United Kingdom.")).toBeInTheDocument();
      expect(within(kenya).getByText(/From your eligibility review of/)).toBeInTheDocument();
      expect(within(within(panel).getByRole("region", { name: "Skills coverage" })).getByText("2 of 2")).toBeInTheDocument();
    });

    it("lists potential disqualifiers with the quoted requirement", async () => {
      jobFit = makeFit({
        verdict: "potential_disqualifiers",
        headline: "1 potential disqualifier need your attention before you apply.",
        candidate_details_confirmed: true,
        disqualifiers: [{ kind: "work_authorization", requirement: "Work authorization", status: "disqualifier", explanation: "The job asks for the right to work in United States, and you confirmed you are not authorized to work in United States. No sponsorship is mentioned.", quotation: "You must be authorized to work in the United States.", sources: [{ source_type: "eligibility_details", source_id: profileId, label: "Your confirmed eligibility details" }] }],
      });
      const user = userEvent.setup();
      const panel = await openFit(user);

      const disqualifiers = within(panel).getByRole("region", { name: "Potential disqualifiers" });
      expect(within(disqualifiers).getByText("You must be authorized to work in the United States.")).toBeInTheDocument();
      expect(within(disqualifiers).getByText(/you confirmed you are not authorized/)).toBeInTheDocument();
      expect(within(panel).queryByText(/You have not confirmed your work eligibility details/)).not.toBeInTheDocument();
    });
  });

  describe("evidence suggestions", () => {
    async function openDocuments(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Documents" }));
      await screen.findByRole("heading", { name: "Your documents" });
    }

    it("suggests unreviewed evidence after a successful extraction and shows its source section", async () => {
      const user = userEvent.setup();
      await openDocuments(user);
      await user.click(screen.getByRole("button", { name: "Retry extraction" }));

      expect(await screen.findByText(/Text extraction completed. 1 evidence suggestion added for your review/)).toBeInTheDocument();
      const extraction = requests.findIndex((request) => request.method === "POST" && request.path.endsWith(`/documents/${documentId}/extraction`));
      const suggestion = requests.findIndex((request) => request.method === "POST" && request.path.endsWith(`/documents/${documentId}/evidence-suggestions`));
      expect(extraction).toBeGreaterThanOrEqual(0);
      expect(suggestion).toBeGreaterThan(extraction);
      expect(requests[suggestion].headers.get("X-CSRF-Token")).toBe("session-csrf-test");

      await user.click(screen.getByRole("button", { name: /Evidence review/ }));
      const card = (await screen.findByText("Resolved 40 tickets a day", { selector: "h3" })).closest("article") as HTMLElement;
      expect(within(card).getByText("Unreviewed")).toBeInTheDocument();
      expect(within(card).getByText("Metric")).toBeInTheDocument();
      expect(within(card).getByText("Source: candidate-cv.txt · Section: WORK EXPERIENCE")).toBeInTheDocument();
      expect(within(card).getByRole("button", { name: "Confirm evidence" })).toBeEnabled();
    });

    it("offers suggestions for an already extracted document and reports when nothing new is found", async () => {
      const user = userEvent.setup();
      await openDocuments(user);
      await user.click(screen.getByRole("button", { name: "Suggest evidence" }));
      expect(await screen.findByText(/1 evidence suggestion added for your review/)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Suggest evidence" }));
      expect(await screen.findByText("No new evidence suggestions. 1 already recorded were left unchanged.")).toBeInTheDocument();
      expect(requests.filter((request) => request.path.endsWith("/evidence-suggestions"))).toHaveLength(2);
    });

    it("does not request suggestions when extraction does not succeed", async () => {
      extractionPostStatus = "failed";
      const user = userEvent.setup();
      await openDocuments(user);
      await user.click(screen.getByRole("button", { name: "Retry extraction" }));
      expect(await screen.findByText("Text extraction finished: failed. No evidence was suggested.")).toBeInTheDocument();
      expect(requests.some((request) => request.path.endsWith("/evidence-suggestions"))).toBe(false);
    });

    it("flags evidence whose source text changed and re-links it without changing the decision", async () => {
      evidenceSourceCurrent = false;
      evidenceStatus = "rejected";
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: /Evidence review/ }));
      const card = (await screen.findByText("Automated deployment checks.", { selector: "h3" })).closest("article") as HTMLElement;

      expect(within(card).getByText("Source text changed")).toBeInTheDocument();
      expect(within(card).getByRole("note")).toHaveTextContent(/not used for CVs or matching/);
      expect(within(card).getByRole("button", { name: "Confirm evidence" })).toBeDisabled();
      await user.click(within(card).getByRole("button", { name: "Re-link to current text" }));

      expect(await screen.findByText(/re-linked to the current extracted text. Your review decision is unchanged/)).toBeInTheDocument();
      const relink = requests.find((request) => request.method === "PATCH" && request.path.endsWith(`/evidence/${evidenceId}`));
      expect(JSON.parse(relink?.body || "{}")).toEqual({ source_excerpt: "Automated deployment checks.", source_start: null, source_end: null });
      await waitFor(() => expect(screen.queryByText("Source text changed")).not.toBeInTheDocument());
      expect(screen.getByText("Rejected")).toBeInTheDocument();
    });
  });

  describe("job pipeline", () => {
    async function openPipeline(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Job pipeline" }));
      return screen.findByRole("tablist", { name: "Job pipeline queues" });
    }

    it("separates the four queues with counts and opens on the first non-empty one", async () => {
      const user = userEvent.setup();
      const tabs = await openPipeline(user);
      expect(within(tabs).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Auto-apply eligible 0", "Needs your action 1", "Review needed 1", "Not eligible 1",
      ]);
      expect(within(tabs).getByRole("tab", { name: /Needs your action/ })).toHaveAttribute("aria-selected", "true");
      const panel = screen.getByRole("tabpanel");
      const card = within(panel).getByRole("article", { name: "Service Desk Analyst at GitLab" });
      expect(within(card).getByText("Kenya-qualified")).toBeInTheDocument();
      expect(within(card).getByText("Nairobi, Kenya", { exact: false, selector: "blockquote" })).toBeInTheDocument();
      expect(within(card).getByText(/employer's private API key/, { selector: "li" })).toBeInTheDocument();
      expect(within(card).getByText(/submit it yourself on the official page/)).toBeInTheDocument();
      expect(within(card).getByText(/Posted by the employer/)).toBeInTheDocument();
      expect(within(card).getByText(/Found by JobPilot/)).toBeInTheDocument();
      expect(within(card).getByText(/Match 72 \/ 100/)).toBeInTheDocument();
      expect(within(card).getByRole("link", { name: /Official application page/ })).toHaveAttribute("href", "https://job-boards.greenhouse.io/gitlab/jobs/listing-ready");
      expect(requests.some((request) => request.path.endsWith("/job-pipeline") && request.search === "")).toBe(true);

      await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "24");
      await waitFor(() => expect(requests.some((request) => request.path.endsWith("/job-pipeline") && request.search === "?posted_within_hours=24")).toBe(true));
    });

    it("never shows review or excluded jobs as Kenya-qualified and explains each", async () => {
      const user = userEvent.setup();
      const tabs = await openPipeline(user);
      await user.click(within(tabs).getByRole("tab", { name: /Review needed/ }));
      const review = screen.getByRole("article", { name: "Remote Support Engineer at GitLab" });
      expect(within(review).getByText("Kenya not established")).toBeInTheDocument();
      expect(within(review).queryByText("Kenya-qualified")).not.toBeInTheDocument();
      expect(within(review).queryByRole("button", { name: "Prepare application" })).not.toBeInTheDocument();

      await user.click(within(tabs).getByRole("tab", { name: /Not eligible/ }));
      const excluded = screen.getByRole("article", { name: "US Support Specialist at GitLab" });
      expect(within(excluded).getByText("Not open to Kenya")).toBeInTheDocument();
      expect(within(excluded).getByText("The employer's location for this job lists only places outside Kenya.", { selector: "li" })).toBeInTheDocument();
      expect(within(excluded).queryByRole("button", { name: "Prepare application" })).not.toBeInTheDocument();
    });

    it("explains why nothing can be auto-applied", async () => {
      const user = userEvent.setup();
      const tabs = await openPipeline(user);
      await user.click(within(tabs).getByRole("tab", { name: /Auto-apply eligible/ }));
      expect(screen.getByRole("heading", { name: "No job can be submitted automatically" })).toBeInTheDocument();
      expect(screen.getByText(/None of the current job sources lets an applicant submit/)).toBeInTheDocument();
    });

    it("prepares an application without submitting it and shows the hand-off", async () => {
      const user = userEvent.setup();
      await openPipeline(user);
      const card = screen.getByRole("article", { name: "Service Desk Analyst at GitLab" });
      await user.click(within(card).getByRole("button", { name: "Prepare application" }));

      expect(await screen.findByText(/Application prepared, not submitted/)).toBeInTheDocument();
      const prepare = requests.find((request) => request.path.endsWith("/job-listings/listing-ready/prepare-application"));
      expect(prepare?.method).toBe("POST");
      expect(prepare?.headers.get("X-CSRF-Token")).toBe("session-csrf-test");
      const pack = await screen.findByRole("region", { name: "Prepared application" });
      expect(within(pack).getByText("Prepared, not submitted")).toBeInTheDocument();
      expect(within(pack).getByText("your turn")).toBeInTheDocument();
      expect(within(pack).getByRole("textbox", { name: /Cover letter draft/ })).toHaveValue("Dear Hiring Team at GitLab,\n\nI am applying for the Service Desk Analyst role.");
      expect(within(pack).getByRole("button", { name: "Review the tailored CV" })).toBeInTheDocument();
      await waitFor(() => expect(within(screen.getByRole("article", { name: "Service Desk Analyst at GitLab" })).getByText(/stage: preparing/)).toBeInTheDocument());
    });

    it("explains the role match only when the support and IT filter is on", async () => {
      const user = userEvent.setup();
      await openPipeline(user);
      const before = screen.getByRole("article", { name: "Service Desk Analyst at GitLab" });
      expect(within(before).queryByText(/role family/)).not.toBeInTheDocument();

      await user.click(screen.getByRole("checkbox", { name: /Technical and IT support/ }));
      await waitFor(() => expect(requests.some((request) => request.path.endsWith("/job-pipeline") && request.search === "?role_family=support_it")).toBe(true));
      const card = await screen.findByRole("article", { name: "Service Desk Analyst at GitLab" });
      expect(within(card).getByText("Role: Help desk and service desk")).toBeInTheDocument();
      expect(within(card).getByText(/The title contains "Service Desk"/)).toBeInTheDocument();
      expect(within(card).getByText("Kenya-qualified")).toBeInTheDocument();
    });

    it("shows a clear error when the pipeline cannot load", async () => {
      failPipeline = true;
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Job pipeline" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("The job pipeline could not be loaded: The pipeline is unavailable.");
    });
  });

  describe("evidence review keeps its place", () => {
    const batchTime = "2026-10-17T09:00:00Z";

    async function openBatch(user: ReturnType<typeof userEvent.setup>) {
      // Suggestions created together share one timestamp.
      batchEvidence = Array.from({ length: 6 }, (_, index) => ({
        ...evidenceBase, id: `batch-${index}`, description: `Batch claim ${index}`, source_excerpt: `Batch claim ${index}`,
        source_start: 100 + index * 20, source_end: 112 + index * 20, created_at: batchTime, updated_at: batchTime,
        source_current: true, confirmation_status: "unreviewed",
      }));
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: /Evidence review/ }));
      await screen.findByRole("article", { name: "Evidence: Batch claim 3" });
    }

    function cardOrder(): string[] {
      return screen.getAllByRole("article", { name: /^Evidence: Batch claim/ }).map((card) => card.getAttribute("aria-label") || "");
    }

    it.each([
      ["Confirm evidence", "Candidate-confirmed", "Evidence marked candidate-confirmed."],
      ["Reject", "Rejected", "Evidence rejected and excluded from CV generation."],
    ])("%s updates the card in place and keeps the list order even when the server reorders", async (button, label, message) => {
      const user = userEvent.setup();
      await openBatch(user);
      const before = cardOrder();
      const card = screen.getByRole("article", { name: "Evidence: Batch claim 3" });

      await user.click(within(card).getByRole("button", { name: button }));
      expect(await screen.findByText(message)).toBeInTheDocument();

      expect(batchEvidence[batchEvidence.length - 1].id).toBe("batch-3");  // the server did reorder
      expect(cardOrder()).toEqual(before);
      const after = screen.getByRole("article", { name: "Evidence: Batch claim 3" });
      expect(after).toBe(card);  // same element: not remounted
      expect(within(after).getByText(label)).toBeInTheDocument();
      expect(window.document.activeElement).toBe(after);  // focus stays on the reviewed item
      expect(screen.getByRole("heading", { name: "Evidence review" })).toBeInTheDocument();
    });

    it("keeps the status and position when the server refuses the decision", async () => {
      failEvidencePatch = true;
      const user = userEvent.setup();
      await openBatch(user);
      const before = cardOrder();
      const card = screen.getByRole("article", { name: "Evidence: Batch claim 2" });

      await user.click(within(card).getByRole("button", { name: "Confirm evidence" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("The source text changed since this evidence was recorded.");
      expect(within(card).getByText("Unreviewed")).toBeInTheDocument();
      expect(within(card).queryByText("Candidate-confirmed")).not.toBeInTheDocument();
      expect(cardOrder()).toEqual(before);
      expect(screen.getByRole("article", { name: "Evidence: Batch claim 2" })).toBe(card);
    });
  });

  describe("ATS analysis and reviewed CV drafts", () => {
    async function openAts(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
      await user.selectOptions(screen.getByRole("combobox", { name: "Saved job description" }), jobId);
      return screen.findByRole("region", { name: "ATS match report" });
    }

    it("shows the score with its method, requirement statuses with sources and ranked recommendations", async () => {
      const user = userEvent.setup();
      const panel = await openAts(user);

      expect(within(panel).getByText("64 / 100")).toBeInTheDocument();
      expect(within(panel).getByText(/Could reach 78/)).toBeInTheDocument();
      expect(within(panel).getByText("How this score is calculated")).toBeInTheDocument();
      expect(within(panel).getByText(/does not reproduce any employer's screening system/)).toBeInTheDocument();
      const essential = within(panel).getByRole("region", { name: "Essential requirements" });
      expect(within(essential).getByText("Shown in your records")).toBeInTheDocument();
      expect(within(essential).getByText("From: Platform Engineer at Northstar Systems")).toBeInTheDocument();
      expect(within(essential).getByText("Not shown")).toBeInTheDocument();
      const preferred = within(panel).getByRole("region", { name: "Preferred requirements" });
      expect(within(preferred).getByText("Needs your confirmation")).toBeInTheDocument();
      expect(within(preferred).getByText("Inferred from the duties")).toBeInTheDocument();
      expect(within(within(panel).getByRole("region", { name: "Recommended improvements" })).getByText(/Do not claim it unless it is true/)).toBeInTheDocument();
      expect(within(within(panel).getByRole("region", { name: "Important terms" })).getByText(/kubernetes/)).toBeInTheDocument();
    });

    it("keeps an eligibility exclusion separate and ahead of a high score", async () => {
      atsReport = makeAtsReport({
        verdict: "excluded_by_employer", score: 92, eligibility_overrides_score: true,
        headline: "The employer's wording excludes Kenya-based applicants. The skills score below does not change this.",
        eligibility: {
          geographic: { status: "not_eligible", reason: "The employer's wording rules out applicants based in Kenya.", quotation: "Applicants must reside in the United Kingdom." },
          disqualifiers: [], location_items: [], candidate_details_confirmed: true,
        },
      });
      const user = userEvent.setup();
      const panel = await openAts(user);

      expect(within(panel).getByText(/The skills score below does not change this/)).toBeInTheDocument();
      expect(within(panel).getByText(/this score does not outweigh the location or authorization issue/)).toBeInTheDocument();
      const eligibility = within(panel).getByRole("region", { name: "Eligibility, assessed separately" });
      expect(within(eligibility).getByText("Kenya-based applicants excluded")).toBeInTheDocument();
      expect(within(eligibility).getByText("Applicants must reside in the United Kingdom.")).toBeInTheDocument();
    });

    it("checks a chosen uploaded CV and asks the reviewed writer for a draft", async () => {
      const user = userEvent.setup();
      await openAts(user);
      await user.selectOptions(screen.getByRole("combobox", { name: "Uploaded CV to check" }), documentId);
      await waitFor(() => expect(requests.some((request) => request.path.endsWith("/ats-analysis") && request.search === `?source_document_id=${documentId}`)).toBe(true));
      await user.click(screen.getByRole("button", { name: "Generate CV draft" }));

      await waitFor(() => expect(requests.some((request) => request.method === "POST" && request.path.endsWith(`/job-descriptions/${jobId}/cv-drafts`))).toBe(true));
      const generation = requests.find((request) => request.method === "POST" && request.path.endsWith(`/job-descriptions/${jobId}/cv-drafts`));
      expect(JSON.parse(generation?.body || "{}")).toEqual({ writer: "reviewed", source_document_id: documentId });
      expect(await screen.findByText(/Review the changes, then approve it for export/)).toBeInTheDocument();
    });

    it("keeps a generation failure short, dismissible and recoverable (regression)", async () => {
      // The real failure: one long message per missing requirement used to fill a notification
      // taller than the screen, pushing its close button out of reach.
      const gaps = Array.from({ length: 9 }, (_, index) => `Essential requirement not shown in your records: requirement ${index} ${"with long wording ".repeat(8)}`);
      generationResponse = { status: 422, body: { detail: {
        message: "CV draft failed validation. Add or confirm the evidence described below.", draft_id: "draft-failed",
        validation_results: { is_valid: false, errors: ["Customer Support Specialist at Tourism fund needs five substantive supported bullets; only 1 are available."], gaps, warnings: [] },
      } } };
      const user = userEvent.setup();
      await openAts(user);
      await user.click(screen.getByRole("button", { name: "Generate CV draft" }));

      const message = await screen.findByText(/listed under the draft in Tailored CVs/);
      expect(message.closest("[role=alert]")).not.toBeNull();
      expect(message.textContent!.length).toBeLessThan(400);
      expect(screen.queryByText(/requirement 3 with long wording/)).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Dismiss error" }));
      expect(screen.queryByText(/listed under the draft in Tailored CVs/)).not.toBeInTheDocument();
      // The page is usable again: the button is back and the chosen job is kept.
      expect(screen.getByRole("button", { name: "Generate CV draft" })).toBeEnabled();
      expect(screen.getByRole("combobox", { name: "Saved job description" })).toHaveValue(jobId);
      await user.click(screen.getByRole("button", { name: "Job descriptions" }));
      expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    });

    it("restores the generate button after a network failure", async () => {
      generationResponse = "network";
      const user = userEvent.setup();
      await openAts(user);
      await user.click(screen.getByRole("button", { name: "Generate CV draft" }));
      expect(await screen.findByText(/Cannot connect to JobPilot API/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Generate CV draft" })).toBeEnabled();
      expect(requests.filter((request) => request.method === "POST" && request.path.endsWith("/cv-drafts"))).toHaveLength(1);
    });

    it("saves an incomplete draft for review and requires explicit approval as incomplete", async () => {
      const issue = { group: "experience_evidence", role: "Platform Engineer at Northstar Systems", work_experience_id: "experience-123",
        message: "Platform Engineer at Northstar Systems has 2 supported bullets; the CV layout aims for 5.",
        action: "Add truthful achievements to this role in your profile. JobPilot will not invent bullets to fill the gap." };
      const incomplete = { ...withApproval({ ...draft }, "pending_review"), id: "draft-incomplete", status: "needs_review",
        validation_results: { is_valid: true, errors: [], gaps: [], warnings: [], completeness: "incomplete", issues: [issue] } };
      generationResponse = { status: 201, body: incomplete };
      reviewedDraft = incomplete;
      reviewOverrides = { status: "needs_review", completeness: "incomplete", issues: [issue], from_confirmations: [{ section: "Core Skills", proposed: "Technical communication" }] };
      const user = userEvent.setup();
      await openAts(user);
      await user.click(screen.getByRole("button", { name: "Generate CV draft" }));

      expect(await screen.findByText(/Draft saved, but incomplete \(1 item to address\)/)).toBeInTheDocument();
      expect(screen.getByText("Incomplete: needs your review")).toBeInTheDocument();
      const evidence = screen.getByRole("heading", { name: "Work experience evidence" }).parentElement!;
      expect(within(evidence).getByText(/has 2 supported bullets/)).toBeInTheDocument();
      expect(within(evidence).getByText(/will not invent bullets/)).toBeInTheDocument();
      const added = await screen.findByRole("region", { name: "Added from your answers" });
      expect(within(added).getByText("Technical communication")).toBeInTheDocument();

      const approve = screen.getByRole("button", { name: "Approve as incomplete" });
      expect(approve).toBeDisabled();
      await user.click(screen.getByRole("checkbox", { name: /I understand this CV is incomplete/ }));
      await user.click(approve);
      await waitFor(() => expect(requests.some((request) => request.path.endsWith("/cv-drafts/draft-incomplete/approval"))).toBe(true));
      const approval = requests.find((request) => request.path.endsWith("/cv-drafts/draft-incomplete/approval"));
      expect(JSON.parse(approval?.body || "{}")).toEqual({ attest_unconfirmed_statements: false, acknowledge_incomplete: true });
    });

    it("records a truthful answer to a missing requirement, with inline validation", async () => {
      atsReport = makeAtsReport();
      (atsReport.requirements as { essential: Record<string, unknown>[] }).essential[1] = {
        ...(atsReport.requirements as { essential: Record<string, unknown>[] }).essential[1],
        key: "abcdef0123456789", category: "communication", action: "If you genuinely have this, confirm it or add an example.",
      };
      const user = userEvent.setup();
      const panel = await openAts(user);
      const essential = within(panel).getByRole("region", { name: "Essential requirements" });
      expect(within(essential).getByText(/If you genuinely have this/)).toBeInTheDocument();
      await user.click(within(essential).getByRole("button", { name: "Answer this requirement" }));
      const form = within(essential).getByRole("form", { name: /Your answer: Kubernetes in production/ });
      await user.click(within(form).getByRole("radio", { name: /I have used this skill in a role or project/ }));
      await user.selectOptions(within(form).getByRole("combobox", { name: "Role where you used it" }), "experience-123");
      await user.type(within(form).getByRole("textbox", { name: /What you did/ }), "Ran clusters");
      await user.click(within(form).getByRole("button", { name: "Save answer" }));
      expect(within(form).getByText(/at least six words/)).toBeInTheDocument();
      expect(requests.some((request) => request.method === "POST" && request.path.endsWith("/skill-confirmations"))).toBe(false);

      await user.type(within(form).getByRole("textbox", { name: /What you did/ }), " for customer workloads on the support platform.");
      await user.click(within(form).getByRole("button", { name: "Save answer" }));
      await waitFor(() => expect(requests.some((request) => request.method === "POST" && request.path.endsWith("/skill-confirmations"))).toBe(true));
      const saved = JSON.parse(requests.find((request) => request.method === "POST" && request.path.endsWith("/skill-confirmations"))?.body || "{}");
      expect(saved).toMatchObject({
        job_description_id: jobId, requirement_key: "abcdef0123456789", response: "used_in_role", category: "communication",
        work_experience_id: "experience-123", example: "Ran clusters for customer workloads on the support platform.",
      });
      expect(await screen.findByText(/Saved as your own statement/)).toBeInTheDocument();
    });

    it("shows each change with its reason and evidence and blocks export until approval", async () => {
      reviewedDraft = withApproval({ ...draft }, "pending_review");
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
      const review = await screen.findByRole("region", { name: "Review before export" });

      expect(within(review).getByText("Awaiting your review")).toBeInTheDocument();
      expect(within(review).getByText("responsible for maintaining deployment systems")).toBeInTheDocument();
      expect(within(review).getByText("Maintained deployment systems.")).toBeInTheDocument();
      expect(within(review).getByText(/Why: Starts with what you did/)).toBeInTheDocument();
      expect(within(review).getAllByText(/Evidence: work experience/).length).toBe(2);
      expect(within(within(review).getByRole("region", { name: "Pre-export checks" })).getByText("Sections")).toBeInTheDocument();
      expect(within(review).getByText(/candidate-cv.txt/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Export PDF" })).toBeDisabled();
      expect(screen.getByText("Approve this draft to export it:")).toBeInTheDocument();

      await user.click(within(review).getByRole("button", { name: "Approve for export" }));
      await waitFor(() => expect(screen.getByRole("button", { name: "Export PDF" })).toBeEnabled());
      const approval = requests.find((request) => request.path.endsWith(`/cv-drafts/${draftId}/approval`));
      expect(JSON.parse(approval?.body || "{}")).toEqual({ attest_unconfirmed_statements: false });
      expect(approval?.headers.get("X-CSRF-Token")).toBe("session-csrf-test");
    });

    it("requires explicit confirmation of unsupported wording before approval", async () => {
      reviewedDraft = withApproval({ ...draft }, "pending_review");
      draftNeedsConfirmation = true;
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
      const review = await screen.findByRole("region", { name: "Review before export" });

      expect(within(review).getByText(/Needs your confirmation. Contains wording not found in your records: 40./)).toBeInTheDocument();
      const approve = within(review).getByRole("button", { name: "Approve for export" });
      expect(approve).toBeDisabled();
      await user.click(within(review).getByRole("checkbox", { name: /I confirm the 1 statement marked as needing confirmation is accurate/ }));
      await user.click(approve);
      await waitFor(() => expect(requests.some((request) => request.path.endsWith("/approval"))).toBe(true));
      const approval = requests.find((request) => request.path.endsWith("/approval"));
      expect(JSON.parse(approval?.body || "{}")).toEqual({ attest_unconfirmed_statements: true });
    });

    it("saves edited statements as a new version without touching the original", async () => {
      reviewedDraft = withApproval({ ...draft }, "pending_review");
      const user = userEvent.setup();
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Tailored CVs" }));
      const review = await screen.findByRole("region", { name: "Review before export" });

      await user.click(within(review).getByRole("button", { name: "Edit statements" }));
      const field = within(review).getByRole("textbox", { name: "Edit statement 1" });
      await user.clear(field);
      await user.type(field, "Maintained deployment systems for six product teams.");
      await user.click(within(review).getByRole("button", { name: "Save edits as a new version" }));

      await waitFor(() => expect(requests.some((request) => request.path.endsWith(`/cv-drafts/${draftId}/revisions`))).toBe(true));
      const revision = requests.find((request) => request.path.endsWith("/revisions"));
      expect(JSON.parse(revision?.body || "{}")).toEqual({ edits: [{ key: "role:experience-123:0", text: "Maintained deployment systems for six product teams." }] });
      expect(await screen.findByText(/saved as a new draft version. The earlier version is unchanged/)).toBeInTheDocument();
    });
  });

  describe("application tracking", () => {
    async function openApplications(user: ReturnType<typeof userEvent.setup>) {
      mountApp();
      await screen.findByRole("heading", { name: "Good to see you, Taylor" });
      await user.click(screen.getByRole("button", { name: "Applications" }));
      await screen.findByRole("heading", { name: "Applications" });
    }

    it("starts tracking a saved job and records submitting it with a date", async () => {
      const user = userEvent.setup();
      await openApplications(user);

      await user.selectOptions(screen.getByRole("combobox", { name: /Saved job/ }), jobId);
      await user.selectOptions(screen.getByRole("combobox", { name: "Starting stage" }), "ready_for_review");
      await user.click(screen.getByRole("button", { name: "Start tracking" }));

      const card = await screen.findByRole("article", { name: "Platform Engineer" });
      expect(within(card).getByText("Ready for review")).toBeInTheDocument();
      expect(within(card).queryByLabelText(/Date you submitted it/)).not.toBeInTheDocument();

      await user.selectOptions(within(card).getByRole("combobox", { name: "Move to" }), "applied");
      const dateInput = within(card).getByLabelText(/Date you submitted it/);
      expect(dateInput).toHaveValue(new Date().toLocaleDateString("en-CA"));
      await user.clear(dateInput);
      await user.type(dateInput, "2026-10-15");
      await user.type(within(card).getByLabelText("Note (optional)"), "Submitted on the employer site.");
      await user.click(within(card).getByRole("button", { name: "Update stage" }));

      await waitFor(() => expect(within(screen.getByRole("article", { name: "Platform Engineer" })).getByText("Applied")).toBeInTheDocument());
      const statusRequest = requests.find((request) => request.method === "POST" && request.path.endsWith("/applications/application-1/status"));
      expect(JSON.parse(statusRequest?.body || "{}")).toEqual({ status: "applied", applied_on: "2026-10-15", note: "Submitted on the employer site." });
      expect(screen.getByText("Application stage updated.")).toBeInTheDocument();
    });

    it("only offers the next stages the server allows", async () => {
      applications = [makeApplication({ status: "saved" })];
      const user = userEvent.setup();
      await openApplications(user);

      const card = await screen.findByRole("article", { name: "Platform Engineer" });
      const options = within(within(card).getByRole("combobox", { name: "Move to" })).getAllByRole("option").map((option) => option.textContent);
      expect(options).toEqual(["Choose the next stage", "Eligibility review", "Preparing application", "Withdrawn", "Closed"]);
      expect(within(card).getByRole("button", { name: "Update stage" })).toBeDisabled();
    });

    it("shows a closed application as final with its history", async () => {
      applications = [makeApplication({
        status: "closed",
        events: [
          { id: "event-1", from_status: null, to_status: "saved", note: null, occurred_at: now },
          { id: "event-2", from_status: "saved", to_status: "closed", note: "Role filled.", occurred_at: now },
        ],
      })];
      const user = userEvent.setup();
      await openApplications(user);

      const card = await screen.findByRole("article", { name: "Platform Engineer" });
      expect(within(card).queryByRole("combobox", { name: "Move to" })).not.toBeInTheDocument();
      expect(within(card).getByText("This application is closed. Its history is kept below.")).toBeInTheDocument();
      expect(within(card).getByText(/Saved → Closed .* Role filled\./)).toBeInTheDocument();
    });

    it("saves edited details and clears emptied fields", async () => {
      applications = [makeApplication({ notes: "Old note.", contact_name: "Recruiter" })];
      const user = userEvent.setup();
      await openApplications(user);

      const card = await screen.findByRole("article", { name: "Platform Engineer" });
      await user.click(within(card).getByText("Edit details"));
      await user.clear(within(card).getByLabelText("Notes"));
      await user.type(within(card).getByLabelText("Contact email"), "recruiter@example.com");
      await user.click(within(card).getByRole("button", { name: "Save details" }));

      await screen.findByText("Application details saved.");
      const patch = requests.find((request) => request.method === "PATCH" && request.path.endsWith("/applications/application-1"));
      expect(JSON.parse(patch?.body || "{}")).toEqual({
        cv_draft_id: null, deadline_on: null, follow_up_on: null,
        contact_name: "Recruiter", contact_email: "recruiter@example.com", notes: null,
      });
    });

    it("lists upcoming follow-ups on the dashboard and leaves finished ones out", async () => {
      const soon = new Date(Date.now() + 3 * 86_400_000).toLocaleDateString("en-CA");
      applications = [
        makeApplication({ follow_up_on: soon }),
        makeApplication({ id: "application-2", job_description_id: "job-gone", status: "rejected", applied_on: "2026-10-01", deadline_on: soon }),
      ];
      mountApp();

      const upcoming = await screen.findByRole("region", { name: "Upcoming application dates" });
      expect(within(upcoming).getByText("Platform Engineer")).toBeInTheDocument();
      expect(within(upcoming).getByText(/Follow up · Saved/)).toBeInTheDocument();
      expect(within(upcoming).getAllByRole("listitem")).toHaveLength(1);
      expect(within(screen.getByRole("region", { name: "Workspace totals" })).getByText("Active applications")).toBeInTheDocument();
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
        eligibility: { status: "eligibility_unknown", reason: "Eligibility for Kenya-based applicants has not been assessed.", currency: "not_assessed" },
        listing_url: null, source_category: "direct_employer", relisted_at: null, vacancy_status: "listed_by_source", duplicate_group_size: 1,
        source: { registered: true, registry_id: "syntheticco", name: "Synthetic Co", category: "direct_employer", official_domain: "synthetic.example", verification_outcome: "board_found_on_official_page", verification_checked_at: now },
        links: { listing: null, application: null },
        ...overrides,
      };
    }

    function makeDecision(state: string, rule: string, explanation: string, quotes: string[]) {
      return {
        state, rule, explanation, conflicts: [], requirements: [],
        evidence: quotes.map((quotation) => ({ kind: "positive", rule, quotation, field: "location", countries: ["Kenya"], explanation })),
        source_url: "https://boards.greenhouse.io/syntheticco/jobs/101", source_type: "greenhouse board (direct employer)",
        source_authoritative: true, checked_at: now, assessment_id: null,
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
      await user.selectOptions(await screen.findByRole("combobox", { name: "Show" }), "all");

      expect(await screen.findByText("Technical Support Specialist")).toBeInTheDocument();
      const cards = screen.getAllByRole("article");
      expect(cards).toHaveLength(2);
      for (const card of cards) {
        expect(within(card).getByText("Kenya eligibility not established")).toBeInTheDocument();
      }
      expect(screen.getByText("Posting date not provided by source")).toBeInTheDocument();
      const link = screen.getByRole("link", { name: /Open original listing/ });
      expect(link).toHaveAttribute("href", "https://boards.greenhouse.io/syntheticco/jobs/101");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
      expect(screen.getAllByRole("link", { name: /Open original listing/ })).toHaveLength(1);
      expect(screen.getByText("The source did not provide a secure listing link.")).toBeInTheDocument();
    });

    it("opens on all stored active listings and can narrow to the 24-hour window", async () => {
      jobListings = [makeListing(), makeListing({ id: "listing-2", title: "Dated role", posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);

      expect(await screen.findByText("Dated role")).toBeInTheDocument();
      expect(screen.getByText("Technical Support Specialist")).toBeInTheDocument();
      const listingRequests = requests.filter((request) => request.path === "/api/v1/job-listings");
      expect(listingRequests[0].search).toBe("");

      await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "24");

      await waitFor(() => expect(screen.queryByText("Technical Support Specialist")).not.toBeInTheDocument());
      expect(screen.getByText("Dated role")).toBeInTheDocument();
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

    it("imports a listing on the server and opens it in Tailored CVs", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);

      await user.click(await screen.findByRole("button", { name: "Prepare tailored CV" }));

      expect(await screen.findByRole("heading", { name: "Tailored CVs" })).toBeInTheDocument();
      const importRequests = requests.filter((request) => request.method === "POST" && request.path.endsWith("/job-descriptions/from-listing/listing-1"));
      expect(importRequests).toHaveLength(1);
      // The browser sends no listing text; the server copies its stored record.
      expect(importRequests[0].body).toBeNull();
      await waitFor(() => expect(screen.getByRole("combobox", { name: "Saved job description" })).toHaveValue("job-from-listing-1"));
      expect(screen.getByText(/Check its Kenya eligibility below before applying/)).toBeInTheDocument();
      expect(await screen.findByRole("region", { name: "Kenya eligibility" })).toBeInTheDocument();
      expect(screen.getByText("Job description imported from the listing. Review it, then generate a tailored CV.")).toBeInTheDocument();
    });

    it("opens an already imported listing instead of importing it again", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      importedJobs = [{ ...job, id: "job-from-listing-1", job_title: "Technical Support Specialist", source_job_listing_id: "listing-1" }];
      const user = userEvent.setup();
      await openDiscovery(user);

      await user.click(await screen.findByRole("button", { name: "Open in Tailored CVs" }));

      expect(await screen.findByRole("heading", { name: "Tailored CVs" })).toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: "Saved job description" })).toHaveValue("job-from-listing-1");
      expect(requests.some((request) => request.path.includes("/from-listing/"))).toBe(false);
    });

    it("offers no import for a listing that is no longer at its source", async () => {
      jobListings = [makeListing({ source_status: "missing_from_source", posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);

      expect(await screen.findByText("Technical Support Specialist")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Prepare tailored CV" })).not.toBeInTheDocument();
    });

    it("records a quoted Kenya eligibility review and shows its evidence", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);

      const card = await screen.findByRole("article", { name: "Technical Support Specialist" });
      await user.click(within(card).getByRole("button", { name: "Review Kenya eligibility" }));
      const form = await within(card).findByRole("form", { name: /Kenya eligibility review/ });
      expect(await within(form).findByText(/This role is open to candidates in any country\./)).toBeInTheDocument();

      await user.selectOptions(within(form).getByRole("combobox", { name: "Result" }), "eligible_confirmed");
      const quote = within(form).getByRole("textbox", { name: /Exact quotation/ });
      expect(quote).toBeRequired();
      await user.type(quote, "This role is open to candidates in any country.");
      await user.type(within(form).getByRole("textbox", { name: /Explanation/ }), "Open to any country.");
      await user.click(within(form).getByRole("button", { name: "Record review" }));

      const recorded = requests.find((request) => request.method === "POST" && request.path.endsWith("/listing-1/eligibility-assessments"));
      expect(JSON.parse(recorded?.body || "{}")).toEqual({
        outcome: "eligible_confirmed", explanation: "Open to any country.",
        quotation: "This role is open to candidates in any country.", evidence_field: "description",
        statement_scope: "role", role_applicability: "direct", geographic_scope: "kenya_named",
      });
      const updated = await screen.findByRole("article", { name: "Technical Support Specialist" });
      expect(await within(updated).findByText("Kenya applicants accepted")).toBeInTheDocument();
      expect(within(updated).getByText("This role is open to candidates in any country.", { selector: "blockquote" })).toBeInTheDocument();
    });

    it("does not present stale evidence as a current result", async () => {
      jobListings = [makeListing({
        posted_at: "2026-10-16T06:00:00Z",
        eligibility: { status: "eligibility_unknown", reason: "Eligibility evidence changed; reassessment needed.", currency: "stale", previous_status: "eligible_confirmed" },
      })];
      const user = userEvent.setup();
      await openDiscovery(user);

      const card = await screen.findByRole("article", { name: "Technical Support Specialist" });
      expect(within(card).getByText("Kenya eligibility not established")).toBeInTheDocument();
      expect(within(card).getByText("Evidence changed: reassessment needed.")).toBeInTheDocument();
      expect(within(card).queryByText("Kenya applicants accepted")).not.toBeInTheDocument();
    });

    it("filters strictly: Kenya-qualified shows only listings with quoted positive evidence", async () => {
      jobListings = [
        makeListing({ posted_at: "2026-10-16T06:00:00Z", kenya_eligibility: makeDecision("unverified", "remote_without_country", "The listing says remote but does not say which countries applicants may be in.", []) }),
        makeListing({ id: "listing-2", title: "Nairobi Support Agent", posted_at: "2026-10-16T06:00:00Z", location_text: "Nairobi, Kenya", kenya_eligibility: makeDecision("eligible", "location_label_names_kenya", "The employer's location for this job names Kenya.", ["Nairobi, Kenya"]) }),
      ];
      const user = userEvent.setup();
      await openDiscovery(user);
      await screen.findByText("Nairobi Support Agent");
      expect(within(screen.getByRole("article", { name: "Technical Support Specialist" })).getByText("Kenya not established")).toBeInTheDocument();

      await user.selectOptions(screen.getByRole("combobox", { name: "Kenya eligibility" }), "eligible");

      await waitFor(() => expect(screen.queryByText("Technical Support Specialist")).not.toBeInTheDocument());
      const card = screen.getByRole("article", { name: "Nairobi Support Agent" });
      expect(within(card).getByText("Kenya-qualified")).toBeInTheDocument();
      expect(within(card).getByText("Nairobi, Kenya", { selector: "blockquote" })).toBeInTheDocument();
      expect(requests.some((request) => request.path === "/api/v1/job-listings" && request.search === "?kenya=eligible")).toBe(true);
    });

    it("shows source, separate link checks and posting versus discovery dates", async () => {
      jobListings = [makeListing({
        posted_at: "2026-10-16T06:00:00Z", relisted_at: now,
        listing_url: "https://jobs.ashbyhq.com/syntheticco/101",
        application_url: "https://jobs.ashbyhq.com/syntheticco/101/application",
        duplicate_group_size: 2,
        links: {
          listing: { url: "https://jobs.ashbyhq.com/syntheticco/101", final_url: null, outcome: "reachable", http_status: 200, detail: null, checked_at: now },
          application: { url: "https://jobs.ashbyhq.com/syntheticco/101/application", final_url: null, outcome: "auth_required", http_status: 403, detail: null, checked_at: now },
        },
      })];
      const user = userEvent.setup();
      await openDiscovery(user);

      const card = await screen.findByRole("article", { name: "Technical Support Specialist" });
      expect(within(card).getByText(/Source: Synthetic Co \(Direct employer; registry-verified board\)/)).toBeInTheDocument();
      expect(within(card).getByText("Vacancy page").nextElementSibling).toHaveTextContent("Reachable on the source's own site");
      expect(within(card).getByText("Application link").nextElementSibling).toHaveTextContent("Requires sign-in");
      expect(within(card).getByText("Relisted").nextElementSibling).toHaveTextContent("not a new posting date");
      expect(within(card).getByText(/Also listed by 1 other source/)).toBeInTheDocument();
      expect(within(card).getByRole("link", { name: /Open original listing/ })).toHaveAttribute("href", "https://jobs.ashbyhq.com/syntheticco/101");
      expect(within(card).getByRole("link", { name: /Application page/ })).toHaveAttribute("href", "https://jobs.ashbyhq.com/syntheticco/101/application");
    });

    it("marks unregistered sources and unchecked links honestly", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z", source: { registered: false, registry_id: null, name: null, category: null, official_domain: null, verification_outcome: null, verification_checked_at: null } })];
      const user = userEvent.setup();
      await openDiscovery(user);

      const card = await screen.findByRole("article", { name: "Technical Support Specialist" });
      expect(within(card).getByText(/not in the verified source registry/)).toBeInTheDocument();
      expect(within(card).getByText("Application link").nextElementSibling).toHaveTextContent("Not checked yet");
    });

    it("shows why a listing counts as a support or IT role when that filter is on", async () => {
      jobListings = [makeListing({ title: "NOC Engineer", role_match: {
        family: "network_support", label: "Network and operations support", matched_text: "NOC",
        reason: "The title contains \"NOC\" (role family: Network and operations support).",
      } })];
      const user = userEvent.setup();
      await openDiscovery(user);
      const before = await screen.findByRole("article", { name: "NOC Engineer" });
      expect(within(before).queryByText(/role family/)).not.toBeInTheDocument();

      await user.click(screen.getByRole("checkbox", { name: /Technical and IT support/ }));
      await waitFor(() => expect(requests.some((request) => request.path === "/api/v1/job-listings" && request.search === "?role_family=support_it")).toBe(true));
      const card = await screen.findByRole("article", { name: "NOC Engineer" });
      expect(within(card).getByText("Role: Network and operations support")).toBeInTheDocument();
      expect(within(card).getByText(/The title contains "NOC"/)).toBeInTheDocument();
    });

    it("sends the source, scope, role and link filters to the API", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      const user = userEvent.setup();
      await openDiscovery(user);
      await screen.findByText("Technical Support Specialist");

      await user.selectOptions(screen.getByRole("combobox", { name: "Accepted scope" }), "africa");
      await user.selectOptions(screen.getByRole("combobox", { name: "Source type" }), "staffing_agency");
      await user.click(screen.getByRole("checkbox", { name: /Technical and IT support/ }));
      await user.click(screen.getByRole("checkbox", { name: /Verified application links only/ }));
      await user.type(screen.getByRole("textbox", { name: "Search title or employer" }), "VoIP");
      await user.click(screen.getByRole("button", { name: "Search" }));

      await waitFor(() => expect(requests.some((request) => request.path === "/api/v1/job-listings"
        && request.search === "?eligible_scope=africa&q=VoIP&role_family=support_it&source_category=staffing_agency&verified_application_link=true")).toBe(true));
    });

    it("shows review passages and a conflict warning before any review is recorded", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      eligibilityEvidence = {
        passages: [
          { kind: "worldwide_claim", field: "description", sentence: "This role is open to candidates in any country.", countries: [] },
          { kind: "kenya_exclusion", field: "description", sentence: "We are unable to hire in Kenya.", countries: ["KE"] },
        ],
        conflicts: ["The listing contains a statement excluding Kenya."],
      };
      const user = userEvent.setup();
      await openDiscovery(user);

      const card = await screen.findByRole("article", { name: "Technical Support Specialist" });
      await user.click(within(card).getByRole("button", { name: "Review Kenya eligibility" }));
      const form = await within(card).findByRole("form", { name: /Kenya eligibility review/ });

      expect(await within(form).findByText(/The listing contains a statement excluding Kenya\. It cannot be recorded as accepting/)).toBeInTheDocument();
      const passages = within(form).getByRole("region", { name: "Passages to review" });
      expect(within(passages).getByText("Excludes Kenya")).toBeInTheDocument();
      expect(within(passages).getByText("We are unable to hire in Kenya.")).toBeInTheDocument();
      await user.selectOptions(within(form).getByRole("combobox", { name: "Result" }), "eligibility_unknown");
      const scopeOptions = within(within(form).getByRole("combobox", { name: "What the wording establishes" })).getAllByRole("option").map((o) => o.textContent);
      expect(scopeOptions).toEqual(["Unclear", "Conflicting statements", "Awaiting employer confirmation"]);
    });

    it("lists job sources with their health and verification evidence", async () => {
      jobSources = [
        { id: "gitlab", name: "GitLab", category: "direct_employer", official_domain: "gitlab.com", careers_url: "https://about.gitlab.com/jobs/all-jobs/", method: "greenhouse", board: "gitlab", enabled: true, verification: { checked_at: now, outcome: "board_found_on_official_page", evidence: "Official page links to the Greenhouse board." }, limitations: "", health: "healthy", consecutive_failures: 0, last_run_at: now, last_success_at: now, last_error_category: null, active_listings: 229 },
        { id: "randstad", name: "Randstad", category: "staffing_agency", official_domain: "randstad.com", careers_url: "https://www.randstad.com/jobs/", method: "manual", board: null, enabled: false, verification: { checked_at: now, outcome: "careers_page_reachable_no_feed", evidence: "No ATS board link found." }, limitations: "", health: "manual_only", consecutive_failures: 0, last_run_at: null, last_success_at: null, last_error_category: null, active_listings: 0 },
      ];
      const user = userEvent.setup();
      await openDiscovery(user);

      const panel = await screen.findByRole("group", { name: "Job sources" });
      expect(within(panel).getByText("Job sources: 1 automatic, 1 manual or disabled")).toBeInTheDocument();
      expect(within(panel).getByText("Healthy")).toBeInTheDocument();
      expect(within(panel).getByText("Manual only")).toBeInTheDocument();
      expect(within(panel).getByText(/229 active/)).toBeInTheDocument();
    });

    it("sends several role groups, an exclusion, keywords, source, workplace, sort and date window", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      jobSources = [{ id: "jobicy", name: "Jobicy", category: "aggregator", official_domain: "jobicy.com", careers_url: "https://jobicy.com/jobs-rss-feed", method: "jobicy", board: "public", enabled: true, verification: { checked_at: now, outcome: "public_api_documented", evidence: "Documented public API." }, limitations: "", health: "healthy", consecutive_failures: 0, last_run_at: now, last_success_at: now, last_error_category: null, active_listings: 12 }];
      const user = userEvent.setup();
      await openDiscovery(user);
      await screen.findByText("Technical Support Specialist");

      await user.click(screen.getByRole("checkbox", { name: /Technical and IT support/ }));
      await user.click(screen.getByRole("checkbox", { name: /Customer support and service/ }));
      await user.selectOptions(screen.getByRole("combobox", { name: "Hide role group" }), "ecommerce_support");
      await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "168");
      await user.selectOptions(screen.getByRole("combobox", { name: "Source" }), "jobicy");
      await user.selectOptions(screen.getByRole("combobox", { name: "Work arrangement" }), "remote");
      await user.selectOptions(screen.getByRole("combobox", { name: "Sort by" }), "relevance");
      await user.type(screen.getByRole("textbox", { name: "Search title or employer" }), "help desk, noc");
      await user.click(screen.getByRole("button", { name: "Search" }));

      await waitFor(() => expect(requests.some((request) => request.path === "/api/v1/job-listings"
        && request.search === "?posted_within_hours=168&q=help+desk%2C+noc&role_family=support_it&role_family=customer_support&exclude_role_family=ecommerce_support&source=jobicy&workplace=remote&sort=relevance")).toBe(true));
    });

    it("labels undated listings and job-board publication dates honestly", async () => {
      jobListings = [
        makeListing(),
        makeListing({ id: "listing-2", title: "Customer Support Agent", posted_at: "2026-10-16T06:00:00Z", posted_at_source: "job_board", source_category: "aggregator",
          source: { registered: true, registry_id: "jobicy", name: "Jobicy", category: "aggregator", official_domain: "jobicy.com", verification_outcome: "public_api_documented", verification_checked_at: now } }),
      ];
      const user = userEvent.setup();
      await openDiscovery(user);

      const undated = await screen.findByRole("article", { name: "Technical Support Specialist" });
      expect(within(undated).getByText("Undated")).toBeInTheDocument();
      expect(within(undated).getByText(/never shown as fresh/)).toBeInTheDocument();
      const boardDated = screen.getByRole("article", { name: "Customer Support Agent" });
      expect(within(boardDated).getByText("Published on job board")).toBeInTheDocument();
      expect(within(boardDated).getByText(/not necessarily the employer's/)).toBeInTheDocument();
      expect(within(boardDated).getByText(/job-board aggregator, not the employer/)).toBeInTheDocument();
      expect(within(boardDated).queryByText("Undated")).not.toBeInTheDocument();
    });

    it("pages through results with correct counts", async () => {
      jobListings = [makeListing({ posted_at: "2026-10-16T06:00:00Z" })];
      listingTotal = 120;
      const user = userEvent.setup();
      await openDiscovery(user);
      const pages = await screen.findByRole("navigation", { name: "Listing pages" });
      expect(within(pages).getByText("Page 1 of 3")).toBeInTheDocument();
      expect(within(pages).getByRole("button", { name: "Previous" })).toBeDisabled();

      await user.click(within(pages).getByRole("button", { name: "Next" }));
      await waitFor(() => expect(requests.some((request) => request.path === "/api/v1/job-listings" && request.search === "?offset=50")).toBe(true));
      expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
      // A filter change returns to the first page.
      await user.selectOptions(screen.getByRole("combobox", { name: "Show" }), "24");
      await waitFor(() => expect(requests.some((request) => request.search === "?posted_within_hours=24")).toBe(true));
      expect(requests.some((request) => request.search.includes("posted_within_hours=24&offset"))).toBe(false);
    });

    it("refreshes sources in the background and shows progress and per-source results", async () => {
      const started = { state: "running", started_at: now, finished_at: null, requested: ["jobicy", "remoteok"], current: "jobicy", outcomes: [] };
      const finished = { ...started, state: "finished", finished_at: now, current: null, outcomes: [
        { source_id: "jobicy", status: "succeeded", message: "fetched 120, new 40, updated 0, unchanged 80, no longer listed 0, skipped 0", run_id: "r1", fetched: 120, created: 40, updated: 0, skipped: 0 },
        { source_id: "remoteok", status: "failed", message: "failed (rate_limited); stored listings were not changed", run_id: "r2", fetched: 0, created: 0, updated: 0, skipped: 0 },
      ] };
      const user = userEvent.setup();
      await openDiscovery(user);
      await screen.findByText("No discovered jobs");
      expect(screen.getByText(/Use "Refresh all sources"/)).toBeInTheDocument();
      refreshStates = [started, finished];

      await user.click(screen.getByRole("button", { name: "Refresh all sources" }));
      const post = requests.find((request) => request.path === "/api/v1/job-discovery/refresh" && request.method === "POST");
      expect(post?.headers.get("X-CSRF-Token")).toBe("session-csrf-test");
      expect(await screen.findByText("Reading jobicy… 0 of 2 done.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();

      expect(await screen.findByText("Finished: 1 of 2 sources read.", undefined, { timeout: 5000 })).toBeInTheDocument();
      expect(screen.getByText(/fetched 120, new 40/)).toBeInTheDocument();
      expect(screen.getByText(/failed \(rate_limited\)/)).toBeInTheDocument();
      await waitFor(() => expect(requests.filter((request) => request.path === "/api/v1/job-listings").length).toBeGreaterThan(1));
    });

    it("reports an interrupted run by source name", async () => {
      discoveryRuns = [{
        id: "run-1", source_kind: "jobicy", source_key: "public", status: "running", display_status: "interrupted", source_id: "jobicy", source_name: "Jobicy", error_category: null,
        started_at: now, finished_at: null, fetched_count: 0, created_count: 0, updated_count: 0, unchanged_count: 0, missing_count: 0, skipped_count: 0,
      }];
      const user = userEvent.setup();
      await openDiscovery(user);
      expect(await screen.findByText(/Jobicy was interrupted/)).toBeInTheDocument();
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
