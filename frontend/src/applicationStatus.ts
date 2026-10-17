import type { ApplicationStatus } from "./api/types";

export const APPLICATION_STATUS_LABELS: Record<ApplicationStatus, string> = {
  saved: "Saved",
  eligibility_review: "Eligibility review",
  preparing: "Preparing application",
  ready_for_review: "Ready for review",
  applied: "Applied",
  interviewing: "Assessment or interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  closed: "Closed",
};

// Applications in these stages need no further action.
export const FINISHED_STATUSES: ApplicationStatus[] = ["rejected", "withdrawn", "closed"];

// The candidate's own calendar date (YYYY-MM-DD), used for date defaults.
export function localToday(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}
