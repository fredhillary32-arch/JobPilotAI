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

export interface AuthenticatedUser {
  id: string;
  email: string;
}

export interface SessionResponse {
  user: AuthenticatedUser;
  csrf_token: string;
}

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
  // False when the document's current extracted text no longer contains this excerpt.
  source_current?: boolean;
}

export interface EvidenceSuggestions {
  created: number;
  skipped_existing: number;
  limited: boolean;
  evidence: CandidateEvidence[];
}

export interface JobDescription {
  id: string;
  candidate_profile_id: string;
  job_title: string;
  company: string | null;
  description: string;
  source_url: string | null;
  source_job_listing_id?: string | null;
  created_at: string;
}

// One thing the candidate's records do not yet support, with what they can do about it.
export interface CvIssue {
  group: "profile_evidence" | "experience_evidence";
  message: string;
  action: string;
  role?: string;
  work_experience_id?: string;
}

export interface CVValidationResults {
  // is_valid: no integrity errors. completeness: whether the records support the full layout.
  is_valid: boolean;
  errors: string[];
  gaps: string[];
  warnings: string[];
  completeness?: "complete" | "incomplete";
  issues?: CvIssue[];
}

export interface CvDraftReviewState {
  writer_version: string;
  job_description_id: string;
  source_document_id: string | null;
  parent_draft_id: string | null;
  approval_status: "pending_review" | "approved";
  approved_at: string | null;
  attested_unconfirmed_statements: boolean;
  acknowledged_incomplete?: boolean;
  suggestions: string[];
  ats_score: number | null;
  ats_potential_score: number | null;
}

export interface CvDraft {
  id: string;
  candidate_profile_id: string;
  job_description_id: string;
  // "needs_review": sound but incomplete content, exported only after explicit approval.
  status: "generated" | "needs_review" | "failed";
  generated_content: string | null;
  // Drafts from the reviewed writer carry review state; older drafts do not.
  structured_content: { review?: CvDraftReviewState | null } | null;
  validation_results: CVValidationResults;
  source_references: unknown[];
  created_at: string;
}

export type RequirementStatus = "matched" | "partial" | "uncertain" | "missing" | "candidate_confirmed" | "not_possessed" | "unverified";
export type SkillResponse = "has_skill" | "used_in_role" | "needs_details" | "not_possessed" | "unsure";
export type SkillCategory = "technical" | "tool" | "communication" | "customer_service" | "work_style" | "language" | "other";

// The candidate's own statement about a skill; never independent verification.
export interface SkillConfirmation {
  id: string;
  candidate_profile_id: string;
  job_description_id: string | null;
  requirement_key: string | null;
  requirement_text: string | null;
  skill_name: string;
  category: SkillCategory;
  response: SkillResponse;
  proficiency_level: "beginner" | "intermediate" | "advanced" | "expert" | null;
  work_experience_id: string | null;
  project_name: string | null;
  example: string | null;
  status: "active" | "withdrawn";
  confirmed_at: string;
  created_at: string;
  updated_at: string;
  provenance: "candidate_confirmed";
  independently_verified: false;
}

export interface SkillConfirmationInput {
  job_description_id?: string;
  requirement_key?: string;
  skill_name: string;
  category: SkillCategory;
  response: SkillResponse;
  proficiency_level?: "beginner" | "intermediate" | "advanced" | "expert" | null;
  work_experience_id?: string | null;
  project_name?: string | null;
  example?: string | null;
}

export interface AtsEvidenceRef {
  kind: "demonstrated" | "listed" | "unconfirmed";
  source_type: string;
  source_id: string;
  label: string;
  excerpt: string | null;
}

export interface AtsRequirement {
  id: string;
  key: string;
  // "cv": a CV can show it; "interview": a personal quality or way of working.
  cv_use?: "cv" | "interview" | "not_applicable";
  action?: string | null;
  evidence_strength?: "document_or_record" | "work_history" | "candidate_statement" | "listed_only" | "none";
  confirmation?: { id: string; response: SkillResponse; skill_name: string; category: SkillCategory; work_experience_id: string | null; project_name: string | null; example: string | null; proficiency_level: string | null; confirmed_at: string | null; provenance: "candidate_confirmed"; independently_verified: false } | null;
  category: "skill" | "tool" | "experience" | "education" | "certification" | "responsibility" | "eligibility" | "communication" | "work_style";
  importance: "essential" | "preferred" | "not_scored";
  basis: "explicit" | "inferred" | "ambiguous";
  text: string;
  source_text: string;
  section: string | null;
  terms: string[];
  note: string | null;
  status?: RequirementStatus;
  explanation?: string;
  evidence?: AtsEvidenceRef[];
}

export interface AtsRisk {
  code: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
}

export interface AtsReport {
  analysis_version: string;
  job_description_id: string;
  source_document_id: string | null;
  verdict: string;
  headline: string;
  eligibility_overrides_score: boolean;
  score: number | null;
  potential_score: number | null;
  score_explanation: {
    method: string;
    components: { name: string; items: number; base_weight: number; effective_weight: number; fraction_credited: number | null; points: number }[];
    potential_note: string;
    limitations: string[];
  };
  requirements: {
    essential: AtsRequirement[];
    preferred: AtsRequirement[];
    responsibilities: AtsRequirement[];
    work_style?: AtsRequirement[];
    context?: { text: string; section: string | null }[];
    eligibility: AtsRequirement[];
    counts: Record<string, number>;
    sections_found: string[];
  };
  keywords: { term: string; count: number; kind: "tool" | "term"; importance: "high" | "medium"; status: "shown" | "listed_only" | "unconfirmed_only" | "absent" }[];
  eligibility: {
    geographic: { status: EligibilityStatus; reason: string; quotation: string | null };
    disqualifiers: FitItem[];
    location_items: FitItem[];
    candidate_details_confirmed: boolean;
  };
  screening_concerns: { severity: "high" | "medium" | "low"; text: string }[];
  cv_document: {
    document_id: string;
    filename: string;
    status: "analyzed" | "unavailable";
    error: string | null;
    formatting_risks: AtsRisk[];
    sections_detected: string[];
    contact: { email_found: boolean; phone_found: boolean };
    tools_mentioned: string[];
    unconfirmed_statements: { text: string; reason: string }[];
    contradictions: { record: string; explanation: string }[];
  } | null;
  recommendations: { rank: number; priority: number; category: string; text: string }[];
  experience_summary: { total_years: number; roles: number };
  evidence_strength?: { method: string; essential: Record<"document_or_record" | "work_history" | "candidate_statement" | "listed_only" | "none", number> };
  candidate_answers?: { confirmed: number; not_possessed: number; unverified: number };
}

export interface ChangeLogEntry {
  key: string | null;
  section: string;
  role: string | null;
  original: string | null;
  proposed: string;
  changed: boolean;
  significance: "none" | "minor" | "wording";
  origin: "source" | "rewritten" | "composed" | "candidate_edited";
  reasons: string[];
  evidence: { source_type: string; source_field: string; text: string; source_excerpt: string | null; confirmed: boolean }[];
  needs_confirmation: boolean;
  confirmation_note: string | null;
}

export interface CvDraftReview {
  draft_id: string;
  writer_version: string;
  requires_approval: boolean;
  approval: { approval_status: "pending_review" | "approved"; approved_at: string | null; attested_unconfirmed_statements: boolean; parent_draft_id: string | null } | null;
  ats_score: number | null;
  ats_potential_score: number | null;
  change_log: ChangeLogEntry[];
  needs_confirmation: number;
  suggestions: string[];
  checks: {
    passed: boolean;
    checks: { name: string; status: "pass" | "warn" | "fail"; detail: string }[];
    plain_text: string;
    word_count: number;
  };
  trace: {
    job_description: { id: string; job_title: string; company: string | null; source_job_listing_id: string | null } | null;
    source_document: { id: string; filename: string } | null;
    evidence_used: { id: string; description: string; confirmation_status: string }[];
    parent_draft_id: string | null;
  };
  export_ready: boolean;
  export_blockers: string[];
  status?: CvDraft["status"];
  completeness?: "complete" | "incomplete";
  issues?: CvIssue[];
  acknowledged_incomplete?: boolean;
  // Statements that exist because you confirmed a skill or gave an example.
  from_confirmations?: { section: string; proposed: string; role?: string | null }[];
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

export interface JobListing {
  id: string;
  source_kind: string;
  source_key: string;
  source_listing_id: string;
  source_url: string;
  application_url: string;
  employer_name: string;
  title: string;
  location_text: string | null;
  stated_workplace_type: string | null;
  stated_countries: string[];
  posted_at: string | null;
  source_updated_at: string | null;
  application_deadline: string | null;
  salary_min: string | null;
  salary_max: string | null;
  salary_currency: string | null;
  salary_period: string | null;
  source_status: "active" | "missing_from_source";
  first_seen_at: string;
  last_seen_at: string;
  last_verified_at: string;
  dedupe_key: string;
  eligibility: ListingEligibility;
  listing_url: string | null;
  source_category: SourceCategory | null;
  relisted_at: string | null;
  source: ListingSource;
  links: { listing: LinkCheck | null; application: LinkCheck | null };
  vacancy_status: "listed_by_source" | "no_longer_listed" | "link_expired";
  duplicate_group_size: number;
  kenya_eligibility?: KenyaDecision | null;
  role_match?: RoleMatch | null;
  // Where posted_at came from: the employer's own job board, or a job-board aggregator's
  // publication date. Null when the source gave no date (never the discovery time).
  posted_at_source?: "employer_board" | "job_board" | null;
}

export type SourceCategory = "direct_employer" | "staffing_agency" | "recruitment_outsourcing" | "aggregator";
export type GeographicScope =
  | "kenya_named" | "africa" | "emea" | "worldwide" | "other_countries" | "restricted"
  | "conflicting" | "unclear" | "awaiting_employer";

export interface ListingSource {
  registered: boolean;
  registry_id: string | null;
  name: string | null;
  category: SourceCategory | null;
  official_domain: string | null;
  verification_outcome: string | null;
  verification_checked_at: string | null;
}

export interface LinkCheck {
  url: string;
  final_url: string | null;
  outcome: "reachable" | "expired" | "auth_required" | "redirected_off_domain" | "unverified_domain" | "insecure" | "rate_limited" | "broken" | "unreachable";
  http_status: number | null;
  detail: string | null;
  checked_at: string;
}

export interface JobSourceHealth {
  id: string;
  name: string;
  category: SourceCategory;
  official_domain: string;
  careers_url: string;
  method: "greenhouse" | "lever" | "ashby" | "jobicy" | "arbeitnow" | "remoteok" | "manual";
  board: string | null;
  enabled: boolean;
  verification: { checked_at: string | null; outcome: string; evidence: string };
  limitations: string;
  health: "healthy" | "stale" | "failing" | "never_run" | "manual_only" | "disabled";
  consecutive_failures: number;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error_category: string | null;
  active_listings: number;
}

export interface EligibilityEvidence {
  passages: Array<{ kind: string; field: "description" | "location"; sentence: string; countries: string[] }>;
  conflicts: string[];
}

export type EligibilityStatus = "eligible_confirmed" | "not_eligible" | "eligibility_unknown";
export type EvidenceField = "description" | "location";
export type StatementScope = "role" | "company" | "team" | "market_or_customer" | "unclear";
export type RoleApplicability = "direct" | "established_by_wording" | "unclear" | "not_applicable";

export interface ListingEligibility {
  status: EligibilityStatus;
  reason: string;
  currency: "not_assessed" | "current" | "stale";
  previous_status?: EligibilityStatus | null;
  assessment_id?: string | null;
  assessed_at?: string | null;
  explanation?: string | null;
  quotation?: string | null;
  evidence_field?: EvidenceField | null;
  statement_scope?: StatementScope | null;
  role_applicability?: RoleApplicability | null;
  geographic_scope?: GeographicScope | null;
}

export interface JobListingDetail extends JobListing {
  description_text: string | null;
  alternates?: Array<{ id: string; source_kind: string; source_key: string; source_category: string | null; application_url: string; source_status: string }>;
}

export interface EligibilityAssessmentInput {
  outcome: EligibilityStatus;
  explanation: string;
  quotation?: string;
  evidence_field?: EvidenceField;
  statement_scope?: StatementScope;
  role_applicability?: RoleApplicability;
  geographic_scope?: GeographicScope;
}

export interface JobListingPage {
  items: JobListing[];
  total: number;
  limit: number;
  offset: number;
}

export interface JobDiscoveryRun {
  id: string;
  source_kind: string;
  source_key: string;
  status: "running" | "succeeded" | "failed";
  error_category: string | null;
  started_at: string;
  finished_at: string | null;
  fetched_count: number;
  created_count: number;
  updated_count: number;
  unchanged_count: number;
  missing_count: number;
  skipped_count: number;
  skip_reasons?: Record<string, number>;
  // "interrupted" when a run is still marked running long after it started.
  display_status?: "running" | "succeeded" | "failed" | "interrupted" | null;
  source_id?: string | null;
  source_name?: string | null;
}

export interface SourceOutcome {
  source_id: string;
  status: "succeeded" | "failed" | "skipped" | "error";
  message: string;
  run_id: string | null;
  fetched: number;
  created: number;
  updated: number;
  skipped: number;
}

// Progress of a discovery pass started from the app (in memory on the server).
export interface DiscoveryRefresh {
  state: "idle" | "running" | "finished";
  started_at: string | null;
  finished_at: string | null;
  requested: string[];
  current: string | null;
  outcomes: SourceOutcome[];
}

export type ApplicationStatus =
  | "saved"
  | "eligibility_review"
  | "preparing"
  | "ready_for_review"
  | "applied"
  | "interviewing"
  | "offer"
  | "rejected"
  | "withdrawn"
  | "closed";

export interface JobApplicationEvent {
  id: string;
  from_status: ApplicationStatus | null;
  to_status: ApplicationStatus;
  note: string | null;
  occurred_at: string;
}

export interface JobApplication {
  id: string;
  candidate_profile_id: string;
  job_description_id: string;
  cv_draft_id: string | null;
  status: ApplicationStatus;
  applied_on: string | null;
  deadline_on: string | null;
  follow_up_on: string | null;
  contact_name: string | null;
  contact_email: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  allowed_next_statuses: ApplicationStatus[];
  events: JobApplicationEvent[];
}

export interface JobApplicationDetails {
  cv_draft_id?: string | null;
  deadline_on?: string | null;
  follow_up_on?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  notes?: string | null;
}

export type WorkArrangement = "remote" | "hybrid" | "onsite";
export type WorkAuthorizationStatus = "authorized" | "not_authorized";

export interface Country {
  code: string;
  name: string;
}

export interface CandidateEligibilityDetails {
  confirmation_status: "not_confirmed" | "confirmed";
  confirmed_at: string | null;
  country_of_residence: string | null;
  country_of_residence_name: string | null;
  relocation_willingness: "willing" | "not_willing" | null;
  relocation_countries: string[];
  accepted_work_arrangements: WorkArrangement[];
  work_authorizations: Array<{ country_code: string; country_name: string; status: WorkAuthorizationStatus; confirmed_at: string }>;
}

export interface CandidateEligibilityInput {
  confirmed: true;
  country_of_residence: string | null;
  relocation_willingness: "willing" | "not_willing" | null;
  relocation_countries: string[];
  accepted_work_arrangements: WorkArrangement[];
  work_authorizations: Array<{ country_code: string; status: WorkAuthorizationStatus }>;
}

export interface FitItem {
  kind: "skill" | "work_authorization" | "location" | "relocation" | "schedule" | "contradiction" | "work_arrangement";
  requirement: string;
  status: "met" | "missing" | "uncertain" | "disqualifier" | "mismatch";
  explanation: string;
  quotation: string | null;
  sources: Array<{ source_type: string; source_id: string; label: string }>;
}

export interface JobFit {
  job_description_id: string;
  verdict: "excluded_by_employer" | "potential_disqualifiers" | "eligibility_unknown" | "no_blockers_found";
  headline: string;
  geographic_eligibility: {
    status: EligibilityStatus;
    currency: "not_assessed" | "current" | "stale" | "automatic";
    listing_id: string | null;
    reason: string;
    quotation: string | null;
    assessment_id: string | null;
    assessed_at: string | null;
  };
  candidate_details_confirmed: boolean;
  candidate_country_of_residence: string | null;
  coverage: { met: number; total: number; summary: string };
  matched: FitItem[];
  missing: FitItem[];
  uncertain: FitItem[];
  disqualifiers: FitItem[];
  location_requirements_met: FitItem[];
  preferences: FitItem[];
}

export interface WorkspaceData {
  profile: CandidateProfile;
  eligibilityDetails: CandidateEligibilityDetails;
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
  applications: JobApplication[];
  confirmations: SkillConfirmation[];
}

// Strict, evidence-based Kenya eligibility (backend app/services/kenya_eligibility.py).
export type KenyaState = "eligible" | "ineligible" | "unverified" | "needs_candidate_input";

export interface KenyaEvidence {
  kind: "positive" | "negative" | "requirement" | "conflict";
  rule: string;
  quotation: string;
  field: "location" | "description" | "title";
  countries: string[];
  explanation: string;
}

export interface KenyaDecision {
  state: KenyaState;
  rule: string;
  explanation: string;
  evidence: KenyaEvidence[];
  conflicts: KenyaEvidence[];
  requirements: KenyaEvidence[];
  source_url: string | null;
  source_type: string;
  source_authoritative: boolean;
  checked_at: string | null;
  assessment_id: string | null;
}

export type PipelineQueue = "auto_apply" | "needs_action" | "review_needed" | "not_eligible";

export interface PipelineCard {
  listing_id: string;
  title: string;
  employer: string;
  location: string | null;
  workplace_type: string | null;
  posted_at: string | null;
  first_seen_at: string;
  application_deadline: string | null;
  listing_url: string | null;
  application_url: string;
  source: { name: string | null; category: string | null; registered: boolean };
  queue: PipelineQueue;
  role_match?: RoleMatch | null;
  reasons: { code: string; message: string }[];
  next_step: string;
  eligibility: KenyaDecision;
  application_method: { submission: "automatic" | "manual_submission"; reason: string; jobpilot_prepares: string[]; candidate_steps: string[] };
  application: { id: string; status: string } | null;
  fit: {
    score: number | null;
    potential_score: number | null;
    verdict: string;
    headline: string;
    essential_met: number;
    essential_total: number;
    missing_essential: string[];
    missing_preferred: string[];
  } | null;
}

export interface JobPipeline {
  counts: Record<PipelineQueue, number>;
  queues: Record<PipelineQueue, PipelineCard[]>;
  automation: { automatic_submission_available: boolean; explanation: string };
  generated_at: string;
}

export interface PreparedApplication {
  listing_id: string;
  job_description_id: string;
  cv_draft_id: string;
  cv_draft_status: "generated" | "failed";
  application_id: string;
  application_status: string;
  submitted: false;
  steps: { step: string; status: "done" | "blocked" | "handed_to_you"; detail: string }[];
  eligibility: KenyaDecision;
  fit: { score: number | null; potential_score: number | null; headline: string };
  cover_letter: { text: string; sources: { source_type: string; source_id: string; source_field: string }[]; notes: string[] };
  handoff: { application_url: string; reason: string; candidate_steps: string[] };
}

export type RoleGroup = "support_it" | "customer_support" | "ecommerce_support" | "operations_support";

// Role family named by a title (backend app/services/role_relevance.py).
export interface RoleMatch {
  family: string;
  group?: RoleGroup;
  group_label?: string;
  label: string;
  matched_text: string;
  reason: string;
}
