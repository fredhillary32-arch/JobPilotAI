export type RemoteWorkPreference = "remote" | "hybrid" | "onsite" | "flexible";
export type EvidenceStatus = "unreviewed" | "candidate_confirmed" | "rejected";
export type EvidenceCategory =
  | "employment_responsibility"
  | "technical_skill"
  | "project"
  | "achievement"
  | "qualification"
  | "metric";
export type ExportFormat = "pdf" | "docx";

export interface CandidateProfile {
  id: string;
  name: string;
  contact_email: string | null;
  contact_phone: string | null;
  professional_headline: string | null;
  summary: string | null;
  location: string | null;
  remote_work_preference: RemoteWorkPreference | null;
  target_job_categories: string[];
  created_at: string;
  updated_at: string;
}

export interface CandidateProfileInput {
  name: string;
  contact_email?: string | null;
  contact_phone?: string | null;
  professional_headline?: string | null;
  summary?: string | null;
  location?: string | null;
  remote_work_preference?: RemoteWorkPreference | null;
  target_job_categories?: string[];
}

export interface WorkExperience {
  id: string;
  candidate_profile_id: string;
  employer: string;
  job_title: string;
  location: string | null;
  work_arrangement: string | null;
  start_date: string;
  end_date: string | null;
  current_role: boolean;
  description: string | null;
  achievements: string[];
}

export interface Education {
  id: string;
  candidate_profile_id: string;
  institution: string;
  qualification: string;
  field_of_study: string | null;
  start_date: string;
  end_date: string | null;
}

export interface Skill {
  id: string;
  candidate_profile_id: string;
  name: string;
  proficiency_level: string | null;
}

export interface Certification {
  id: string;
  candidate_profile_id: string;
  name: string;
  issuer: string;
  issue_date: string;
  expires_on: string | null;
}

export interface WorkExperienceInput {
  employer: string;
  job_title: string;
  location: string | null;
  work_arrangement: "remote" | "hybrid" | "onsite" | null;
  start_date: string;
  end_date: string | null;
  current_role: boolean;
  description: string | null;
  achievements: string[];
}

export interface EducationInput {
  institution: string;
  qualification: string;
  field_of_study: string | null;
  start_date: string;
  end_date: string | null;
}

export interface SkillInput {
  name: string;
  proficiency_level: "beginner" | "intermediate" | "advanced" | "expert" | null;
}

export interface CertificationInput {
  name: string;
  issuer: string;
  issue_date: string;
  expires_on: string | null;
}

export interface CandidateDocument {
  id: string;
  candidate_profile_id: string;
  source_document_id: string | null;
  document_kind: string;
  provenance: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  target_job_title: string | null;
  target_company: string | null;
  created_at: string;
}

export interface DocumentExtraction {
  id: string;
  source_document_id: string;
  status: "succeeded" | "no_text" | "failed";
  character_count: number;
  extractor_version: string;
  error_category: string | null;
  extracted_at: string;
  trust_status: "unverified_source_text";
}

export interface ExtractedText {
  source_document_id: string;
  status: "succeeded" | "no_text" | "failed";
  text: string | null;
  character_count: number;
  trust_status: "unverified_source_text";
  note: string;
}

export interface CandidateEvidence {
  id: string;
  candidate_profile_id: string;
  source_document_id: string;
  category: EvidenceCategory;
  description: string;
  source_excerpt: string | null;
  source_start: number | null;
  source_end: number | null;
  source_section: string | null;
  confirmation_status: EvidenceStatus;
  created_at: string;
  updated_at: string;
}

export interface JobDescription {
  id: string;
  candidate_profile_id: string;
  job_title: string;
  company: string | null;
  description: string;
  source_url: string | null;
  created_at: string;
}

export interface CVValidationResults {
  is_valid: boolean;
  errors: string[];
  gaps: string[];
  warnings: string[];
}

export interface CvDraft {
  id: string;
  candidate_profile_id: string;
  job_description_id: string;
  status: "generated" | "failed";
  generated_content: string | null;
  structured_content: unknown;
  validation_results: CVValidationResults;
  source_references: unknown[];
  created_at: string;
}

export interface CvExport {
  id: string;
  candidate_profile_id: string;
  cv_draft_id: string;
  document_id: string;
  export_format: ExportFormat;
  page_count: number | null;
  filename: string;
  media_type: string;
  size_bytes: number;
  created_at: string;
}

export interface WorkspaceData {
  profile: CandidateProfile;
  experiences: WorkExperience[];
  education: Education[];
  skills: Skill[];
  certifications: Certification[];
  documents: CandidateDocument[];
  extractions: Record<string, DocumentExtraction | null>;
  evidence: CandidateEvidence[];
  jobs: JobDescription[];
  drafts: CvDraft[];
  exports: CvExport[];
}
