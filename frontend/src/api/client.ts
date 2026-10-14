import type {
  CandidateDocument,
  CandidateEvidence,
  CandidateProfile,
  CandidateProfileInput,
  Certification,
  CvDraft,
  CvExport,
  DocumentExtraction,
  Education,
  EvidenceStatus,
  ExportFormat,
  ExtractedText,
  JobDescription,
  Skill,
  WorkExperience,
  WorkspaceData,
} from "./types";

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_BASE_URL =
  (configuredBase || "/api/v1").replace(/\/+$/, "");

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(
      0,
      `Cannot connect to JobPilot API at ${API_BASE_URL}. Check that the local backend is running.`,
      null,
    );
  }
  if (!response.ok) {
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    throw new ApiError(response.status, detailMessage(data), data);
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
  getProfile: (id: string) =>
    request<CandidateProfile>(profilePath(id)),
  createProfile: (payload: CandidateProfileInput) =>
    request<CandidateProfile>("/candidate-profiles", json("POST", payload)),
  updateProfile: (id: string, payload: CandidateProfileInput) =>
    request<CandidateProfile>(profilePath(id), json("PATCH", payload)),
  listExperiences: (id: string) =>
    request<WorkExperience[]>(`${profilePath(id)}/experiences`),
  listEducation: (id: string) =>
    request<Education[]>(`${profilePath(id)}/education`),
  listSkills: (id: string) => request<Skill[]>(`${profilePath(id)}/skills`),
  listCertifications: (id: string) =>
    request<Certification[]>(`${profilePath(id)}/certifications`),
  listDocuments: (id: string) =>
    request<CandidateDocument[]>(`${profilePath(id)}/documents`),
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
  listDrafts: (id: string) =>
    request<CvDraft[]>(`${profilePath(id)}/cv-drafts`),
  generateDraft: (profileId: string, jobId: string) =>
    request<CvDraft>(
      `${profilePath(profileId)}/job-descriptions/${encodeURIComponent(jobId)}/cv-drafts`,
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
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError(0, "The download could not reach the local API.", null);
  }
  if (!response.ok) {
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    throw new ApiError(response.status, detailMessage(data), data);
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
  ] = await Promise.all([
    api.getProfile(profileId),
    api.listExperiences(profileId),
    api.listEducation(profileId),
    api.listSkills(profileId),
    api.listCertifications(profileId),
    api.listDocuments(profileId),
    api.listEvidence(profileId),
    api.listJobs(profileId),
    api.listDrafts(profileId),
  ]);

  const extractions = Object.fromEntries(
    await Promise.all(
      documents.map(async (document) => {
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
