import type {
  AtsReport,
  CvDraftReview,
  EvidenceSuggestions,
  JobPipeline,
  KenyaState,
  PreparedApplication,
  ApplicationStatus,
  CandidateDocument,
  CandidateEligibilityDetails,
  CandidateEligibilityInput,
  Country,
  JobFit,
  CandidateEvidence,
  CandidateProfile,
  CandidateProfileInput,
  SessionResponse,
  CertificationInput,
  Certification,
  CvDraft,
  CvExport,
  DocumentExtraction,
  Education,
  EducationInput,
  EligibilityAssessmentInput,
  EligibilityEvidence,
  EligibilityStatus,
  JobSourceHealth,
  SourceCategory,
  EvidenceStatus,
  ExportFormat,
  ExtractedText,
  JobApplication,
  JobApplicationDetails,
  JobDescription,
  JobDiscoveryRun,
  DiscoveryRefresh,
  RoleGroup,
  SkillConfirmation,
  SkillConfirmationInput,
  JobListingDetail,
  JobListingPage,
  ListingEligibility,
  Skill,
  SkillInput,
  WorkExperience,
  WorkExperienceInput,
  WorkspaceData,
} from "./types";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL =
  (configuredBase || "/api/v1").replace(/\/+$/, "");

let sessionCsrfToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;
let sessionRestorePromise: Promise<SessionResponse> | null = null;

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function clearSessionCsrfToken(): void {
  sessionCsrfToken = null;
}

export interface JobListingFilters {
  postedWithinHours?: number;
  eligibility?: EligibilityStatus;
  eligibleScope?: "kenya_named" | "africa" | "emea" | "worldwide";
  // Strict state: only listings in exactly this state are returned.
  kenya?: KenyaState;
  // Comma-separated keywords; any one may match the title or employer.
  search?: string;
  supportRolesOnly?: boolean;
  roleGroups?: RoleGroup[];
  excludeRoleGroups?: RoleGroup[];
  sourceCategory?: SourceCategory;
  verifiedLinksOnly?: boolean;
  source?: string;
  workplace?: "remote" | "hybrid" | "onsite";
  sort?: "posted" | "discovered" | "relevance";
  offset?: number;
}

export interface PipelineFilters {
  postedWithinHours?: number;
  supportRolesOnly?: boolean;
  roleGroups?: RoleGroup[];
  search?: string;
  source?: string;
  workplace?: "remote" | "hybrid" | "onsite";
}

function roleGroups(options: { supportRolesOnly?: boolean; roleGroups?: RoleGroup[] }): RoleGroup[] {
  return [...new Set([...(options.supportRolesOnly ? ["support_it" as const] : []), ...(options.roleGroups ?? [])])];
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const data = detail as { message?: unknown; detail?: unknown };
    if (typeof data.message === "string") return data.message;
    if (typeof data.detail === "string") return data.detail;
    if (data.detail && typeof data.detail === "object") {
      const nested = data.detail as { message?: unknown };
      if (typeof nested.message === "string") return nested.message;
    }
  }
  return "The request could not be completed.";
}

// Restoring the session in another tab rotates the session CSRF token.
const CSRF_VERIFICATION_FAILED = "Request verification failed.";
// No request may leave the page waiting forever: every call ends in a result or an error.
export const REQUEST_TIMEOUT_MS = 90_000;

async function request<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  let response: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const method = (init?.method || "GET").toUpperCase();
  const mutating = !["GET", "HEAD", "OPTIONS"].includes(method);
  const headers = new Headers(init?.headers);
  if (mutating && sessionCsrfToken) {
    headers.set("X-CSRF-Token", sessionCsrfToken);
  }
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
      credentials: "include",
      mode: "cors",
      signal: controller.signal,
    });
  } catch {
    if (controller.signal.aborted) {
      throw new ApiError(
        0,
        `The JobPilot API did not respond within ${REQUEST_TIMEOUT_MS / 1000} seconds. Nothing you entered was lost; try again.`,
        null,
      );
    }
    throw new ApiError(
      0,
      `Cannot connect to JobPilot API at ${API_BASE_URL}. Check the API URL and backend availability.`,
      null,
    );
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    if (
      response.status === 403 &&
      mutating &&
      !retried &&
      path !== "/auth/login" &&
      detailMessage(data) === CSRF_VERIFICATION_FAILED
    ) {
      await api.restoreSession();
      return request<T>(path, init, true);
    }
    const error = new ApiError(response.status, detailMessage(data), data);
    if (response.status === 401) unauthorizedHandler?.();
    throw error;
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const json = (method: string, payload: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

const profilePath = (profileId: string) =>
  `/candidate-profiles/${encodeURIComponent(profileId)}`;

export const api = {
  restoreSession(): Promise<SessionResponse> {
    if (!sessionRestorePromise) {
      sessionRestorePromise = request<SessionResponse>("/auth/session")
        .then((session) => {
          sessionCsrfToken = session.csrf_token;
          return session;
        })
        .finally(() => {
          sessionRestorePromise = null;
        });
    }
    return sessionRestorePromise;
  },
  async login(email: string, password: string): Promise<SessionResponse> {
    clearSessionCsrfToken();
    const challenge = await request<{ csrf_token: string }>("/auth/pre-auth-csrf", {
      method: "GET",
      credentials: "include",
      mode: "cors",
    });
    const session = await request<SessionResponse>(
      "/auth/login",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": challenge.csrf_token,
        },
        body: JSON.stringify({ email, password }),
        credentials: "include",
        mode: "cors",
      },
    );
    sessionCsrfToken = session.csrf_token;
    return session;
  },
  async logout(): Promise<void> {
    try {
      await request<void>("/auth/logout", { method: "POST" });
    } finally {
      clearSessionCsrfToken();
    }
  },
  listProfiles: () => request<CandidateProfile[]>("/candidate-profiles"),
  listJobListings: (options: JobListingFilters = {}) => {
    const query = new URLSearchParams();
    if (options.postedWithinHours) query.set("posted_within_hours", String(options.postedWithinHours));
    if (options.eligibility) query.set("eligibility", options.eligibility);
    if (options.kenya) query.set("kenya", options.kenya);
    if (options.eligibleScope) query.set("eligible_scope", options.eligibleScope);
    if (options.search?.trim()) query.set("q", options.search.trim());
    for (const group of roleGroups(options)) query.append("role_family", group);
    if (options.sourceCategory) query.set("source_category", options.sourceCategory);
    if (options.verifiedLinksOnly) query.set("verified_application_link", "true");
    for (const group of options.excludeRoleGroups ?? []) query.append("exclude_role_family", group);
    if (options.source) query.set("source", options.source);
    if (options.workplace) query.set("workplace", options.workplace);
    if (options.sort && options.sort !== "posted") query.set("sort", options.sort);
    if (options.offset) query.set("offset", String(options.offset));
    const search = query.toString();
    return request<JobListingPage>(`/job-listings${search ? `?${search}` : ""}`);
  },
  // Starts a background pass over the registry sources; returns at once.
  startDiscoveryRefresh: (sources: string[] = []) =>
    request<DiscoveryRefresh>("/job-discovery/refresh", json("POST", { sources })),
  getDiscoveryRefresh: () => request<DiscoveryRefresh>("/job-discovery/refresh"),
  listJobSources: () => request<JobSourceHealth[]>("/job-sources"),
  getJobPipeline: (profileId: string, options: PipelineFilters = {}) => {
    const query = new URLSearchParams();
    if (options.postedWithinHours) query.set("posted_within_hours", String(options.postedWithinHours));
    for (const group of roleGroups(options)) query.append("role_family", group);
    if (options.search?.trim()) query.set("q", options.search.trim());
    if (options.source) query.set("source", options.source);
    if (options.workplace) query.set("workplace", options.workplace);
    const search = query.toString();
    return request<JobPipeline>(`${profilePath(profileId)}/job-pipeline${search ? `?${search}` : ""}`);
  },
  // Prepares (never submits) an application for an eligible listing.
  prepareApplication: (profileId: string, listingId: string) =>
    request<PreparedApplication>(
      `${profilePath(profileId)}/job-listings/${encodeURIComponent(listingId)}/prepare-application`,
      { method: "POST" },
    ),
  getEligibilityEvidence: (listingId: string) =>
    request<EligibilityEvidence>(`/job-listings/${encodeURIComponent(listingId)}/eligibility-evidence`),
  getJobListing: (listingId: string) =>
    request<JobListingDetail>(`/job-listings/${encodeURIComponent(listingId)}`),
  recordEligibility: (listingId: string, payload: EligibilityAssessmentInput) =>
    request<ListingEligibility>(
      `/job-listings/${encodeURIComponent(listingId)}/eligibility-assessments`,
      json("POST", payload),
    ),
  listDiscoveryRuns: () => request<JobDiscoveryRun[]>("/job-discovery/runs"),
  getProfile: (id: string) =>
    request<CandidateProfile>(profilePath(id)),
  createProfile: (payload: CandidateProfileInput) =>
    request<CandidateProfile>("/candidate-profiles", json("POST", payload)),
  updateProfile: (id: string, payload: CandidateProfileInput) =>
    request<CandidateProfile>(profilePath(id), json("PATCH", payload)),
  listExperiences: (id: string) =>
    request<WorkExperience[]>(`${profilePath(id)}/experiences`),
  createExperience: (id: string, payload: WorkExperienceInput) =>
    request<WorkExperience>(`${profilePath(id)}/experiences`, json("POST", payload)),
  updateExperience: (profileId: string, recordId: string, payload: WorkExperienceInput) =>
    request<WorkExperience>(
      `${profilePath(profileId)}/experiences/${encodeURIComponent(recordId)}`,
      json("PATCH", payload),
    ),
  deleteExperience: (profileId: string, recordId: string) =>
    request<void>(
      `${profilePath(profileId)}/experiences/${encodeURIComponent(recordId)}`,
      { method: "DELETE" },
    ),
  listEducation: (id: string) =>
    request<Education[]>(`${profilePath(id)}/education`),
  createEducation: (id: string, payload: EducationInput) =>
    request<Education>(`${profilePath(id)}/education`, json("POST", payload)),
  updateEducation: (profileId: string, recordId: string, payload: EducationInput) =>
    request<Education>(
      `${profilePath(profileId)}/education/${encodeURIComponent(recordId)}`,
      json("PATCH", payload),
    ),
  deleteEducation: (profileId: string, recordId: string) =>
    request<void>(
      `${profilePath(profileId)}/education/${encodeURIComponent(recordId)}`,
      { method: "DELETE" },
    ),
  listSkills: (id: string) => request<Skill[]>(`${profilePath(id)}/skills`),
  createSkill: (id: string, payload: SkillInput) =>
    request<Skill>(`${profilePath(id)}/skills`, json("POST", payload)),
  updateSkill: (profileId: string, recordId: string, payload: SkillInput) =>
    request<Skill>(
      `${profilePath(profileId)}/skills/${encodeURIComponent(recordId)}`,
      json("PATCH", payload),
    ),
  deleteSkill: (profileId: string, recordId: string) =>
    request<void>(
      `${profilePath(profileId)}/skills/${encodeURIComponent(recordId)}`,
      { method: "DELETE" },
    ),
  listCertifications: (id: string) =>
    request<Certification[]>(`${profilePath(id)}/certifications`),
  createCertification: (id: string, payload: CertificationInput) =>
    request<Certification>(`${profilePath(id)}/certifications`, json("POST", payload)),
  updateCertification: (profileId: string, recordId: string, payload: CertificationInput) =>
    request<Certification>(
      `${profilePath(profileId)}/certifications/${encodeURIComponent(recordId)}`,
      json("PATCH", payload),
    ),
  deleteCertification: (profileId: string, recordId: string) =>
    request<void>(
      `${profilePath(profileId)}/certifications/${encodeURIComponent(recordId)}`,
      { method: "DELETE" },
    ),
  // Generated CV exports are listed through their draft's exports instead.
  listSourceDocuments: (id: string) =>
    request<CandidateDocument[]>(`${profilePath(id)}/documents?origin=source`),
  uploadDocument: (id: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    body.append("document_kind", "source_cv");
    return request<CandidateDocument>(`${profilePath(id)}/documents`, {
      method: "POST",
      body,
    });
  },
  downloadDocument: (profileId: string, documentId: string) =>
    download(`${profilePath(profileId)}/documents/${encodeURIComponent(documentId)}/download`),
  extractDocument: (profileId: string, documentId: string) =>
    request<DocumentExtraction>(
      `${profilePath(profileId)}/documents/${encodeURIComponent(documentId)}/extraction`,
      { method: "POST" },
    ),
  getExtraction: (profileId: string, documentId: string) =>
    request<DocumentExtraction>(
      `${profilePath(profileId)}/documents/${encodeURIComponent(documentId)}/extraction`,
    ),
  getExtractedText: (profileId: string, documentId: string) =>
    request<ExtractedText>(
      `${profilePath(profileId)}/documents/${encodeURIComponent(documentId)}/extraction/text`,
    ),
  listEvidence: (id: string) =>
    request<CandidateEvidence[]>(`${profilePath(id)}/evidence`),
  createEvidence: (
    profileId: string,
    payload: {
      source_document_id: string;
      category: string;
      description: string;
      source_excerpt: string;
      source_section?: string;
    },
  ) =>
    request<CandidateEvidence>(
      `${profilePath(profileId)}/evidence`,
      json("POST", payload),
    ),
  updateEvidenceStatus: (
    profileId: string,
    evidenceId: string,
    confirmation_status: EvidenceStatus,
  ) =>
    request<CandidateEvidence>(
      `${profilePath(profileId)}/evidence/${encodeURIComponent(evidenceId)}`,
      json("PATCH", { confirmation_status }),
    ),
  // Local, rule-based suggestions from the document's current extracted text.
  suggestEvidence: (profileId: string, documentId: string) =>
    request<EvidenceSuggestions>(
      `${profilePath(profileId)}/documents/${encodeURIComponent(documentId)}/evidence-suggestions`,
      { method: "POST" },
    ),
  // Re-locate an existing excerpt in the current text; the review decision is unchanged.
  relinkEvidence: (profileId: string, evidenceId: string, sourceExcerpt: string) =>
    request<CandidateEvidence>(
      `${profilePath(profileId)}/evidence/${encodeURIComponent(evidenceId)}`,
      json("PATCH", { source_excerpt: sourceExcerpt, source_start: null, source_end: null }),
    ),
  listJobs: (id: string) =>
    request<JobDescription[]>(`${profilePath(id)}/job-descriptions`),
  createJob: (
    profileId: string,
    payload: {
      job_title: string;
      company?: string;
      source_url?: string;
      description: string;
    },
  ) =>
    request<JobDescription>(
      `${profilePath(profileId)}/job-descriptions`,
      json("POST", payload),
    ),
  listCountries: () => request<Country[]>("/countries"),
  getEligibilityDetails: (id: string) =>
    request<CandidateEligibilityDetails>(`${profilePath(id)}/eligibility-details`),
  confirmEligibilityDetails: (id: string, payload: CandidateEligibilityInput) =>
    request<CandidateEligibilityDetails>(`${profilePath(id)}/eligibility-details`, json("PUT", payload)),
  getJobFit: (profileId: string, jobId: string) =>
    request<JobFit>(`${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/fit`),
  listApplications: (id: string) =>
    request<JobApplication[]>(`${profilePath(id)}/applications`),
  createApplication: (
    profileId: string,
    payload: { job_description_id: string; status: ApplicationStatus; applied_on?: string } & JobApplicationDetails,
  ) =>
    request<JobApplication>(`${profilePath(profileId)}/applications`, json("POST", payload)),
  updateApplication: (profileId: string, applicationId: string, payload: JobApplicationDetails) =>
    request<JobApplication>(
      `${profilePath(profileId)}/applications/${encodeURIComponent(applicationId)}`,
      json("PATCH", payload),
    ),
  changeApplicationStatus: (
    profileId: string,
    applicationId: string,
    payload: { status: ApplicationStatus; applied_on?: string; note?: string },
  ) =>
    request<JobApplication>(
      `${profilePath(profileId)}/applications/${encodeURIComponent(applicationId)}/status`,
      json("POST", payload),
    ),
  // The server copies the stored listing text; the browser never relays it.
  importJobFromListing: (profileId: string, listingId: string) =>
    request<JobDescription>(
      `${profilePath(profileId)}/job-descriptions/from-listing/${encodeURIComponent(listingId)}`,
      { method: "POST" },
    ),
  listDrafts: (id: string) =>
    request<CvDraft[]>(`${profilePath(id)}/cv-drafts`),
  generateDraft: (profileId: string, jobId: string, options?: { sourceDocumentId?: string }) =>
    request<CvDraft>(
      `${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/cv-drafts`,
      json("POST", { writer: "reviewed", ...(options?.sourceDocumentId && { source_document_id: options.sourceDocumentId }) }),
    ),
  // Read-only analysis computed locally by the backend; nothing is sent elsewhere.
  getAtsAnalysis: (profileId: string, jobId: string, sourceDocumentId?: string) =>
    request<AtsReport>(
      `${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/ats-analysis${sourceDocumentId ? `?source_document_id=${encodeURIComponent(sourceDocumentId)}` : ""}`,
    ),
  getDraftReview: (profileId: string, draftId: string) =>
    request<CvDraftReview>(`${profilePath(profileId)}/cv-drafts/${encodeURIComponent(draftId)}/review`),
  reviseDraft: (profileId: string, draftId: string, edits: { key: string; text: string }[]) =>
    request<CvDraft>(`${profilePath(profileId)}/cv-drafts/${encodeURIComponent(draftId)}/revisions`, json("POST", { edits })),
  approveDraft: (profileId: string, draftId: string, attestUnconfirmedStatements: boolean, acknowledgeIncomplete = false) =>
    request<CvDraft>(
      `${profilePath(profileId)}/cv-drafts/${encodeURIComponent(draftId)}/approval`,
      json("POST", { attest_unconfirmed_statements: attestUnconfirmedStatements, ...(acknowledgeIncomplete && { acknowledge_incomplete: true }) }),
    ),
  listConfirmations: (profileId: string) =>
    request<SkillConfirmation[]>(`${profilePath(profileId)}/skill-confirmations`),
  createConfirmation: (profileId: string, payload: SkillConfirmationInput) =>
    request<SkillConfirmation>(`${profilePath(profileId)}/skill-confirmations`, json("POST", payload)),
  updateConfirmation: (profileId: string, confirmationId: string, payload: SkillConfirmationInput) =>
    request<SkillConfirmation>(
      `${profilePath(profileId)}/skill-confirmations/${encodeURIComponent(confirmationId)}`,
      json("PUT", {
        skill_name: payload.skill_name, category: payload.category, response: payload.response,
        proficiency_level: payload.proficiency_level ?? null, work_experience_id: payload.work_experience_id ?? null,
        project_name: payload.project_name ?? null, example: payload.example ?? null,
      }),
    ),
  withdrawConfirmation: (profileId: string, confirmationId: string) =>
    request<SkillConfirmation>(
      `${profilePath(profileId)}/skill-confirmations/${encodeURIComponent(confirmationId)}/withdraw`,
      { method: "POST" },
    ),
  listExports: (profileId: string, jobId: string, draftId: string) =>
    request<CvExport[]>(
      `${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/cv-drafts/${encodeURIComponent(draftId)}/exports`,
    ),
  createExport: (
    profileId: string,
    jobId: string,
    draftId: string,
    export_format: ExportFormat,
  ) =>
    request<CvExport>(
      `${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/cv-drafts/${encodeURIComponent(draftId)}/exports`,
      json("POST", { export_format }),
    ),
  downloadExport: (
    profileId: string,
    jobId: string,
    draftId: string,
    exportId: string,
  ) =>
    download(
      `${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/cv-drafts/${encodeURIComponent(draftId)}/exports/${encodeURIComponent(exportId)}/download`,
    ),
};

async function download(path: string): Promise<Blob> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      credentials: "include",
      mode: "cors",
    });
  } catch {
    throw new ApiError(0, "The download could not reach the configured API.", null);
  }
  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null);
    const error = new ApiError(response.status, detailMessage(data), data);
    if (response.status === 401) unauthorizedHandler?.();
    throw error;
  }
  return response.blob();
}

export async function loadWorkspace(profileId: string): Promise<WorkspaceData> {
  const [
    profile,
    experiences,
    education,
    skills,
    certifications,
    documents,
    evidence,
    jobs,
    drafts,
    applications,
    eligibilityDetails,
    confirmations,
  ] = await Promise.all([
    api.getProfile(profileId),
    api.listExperiences(profileId),
    api.listEducation(profileId),
    api.listSkills(profileId),
    api.listCertifications(profileId),
    api.listSourceDocuments(profileId),
    api.listEvidence(profileId),
    api.listJobs(profileId),
    api.listDrafts(profileId),
    api.listApplications(profileId),
    api.getEligibilityDetails(profileId),
    api.listConfirmations(profileId),
  ]);

  const extractions = Object.fromEntries(
    await Promise.all(
      documents
        .map(async (document) => {
          try {
            return [document.id, await api.getExtraction(profileId, document.id)] as const;
          } catch (error) {
            if (error instanceof ApiError && error.status === 404) {
              return [document.id, null] as const;
            }
            throw error;
          }
        }),
    ),
  );
  const jobsById = new Map(jobs.map((job) => [job.id, job]));
  const exports = (
    await Promise.all(
      drafts
        .filter((draft) => draft.status === "generated")
        .map((draft) => {
          const job = jobsById.get(draft.job_description_id);
          return job
            ? api.listExports(profileId, job.id, draft.id)
            : Promise.resolve([]);
        }),
    )
  ).flat();
  return {
    profile,
    experiences,
    education,
    skills,
    certifications,
    documents,
    extractions,
    evidence,
    jobs,
    drafts,
    exports,
    applications,
    eligibilityDetails,
    confirmations,
  };
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
