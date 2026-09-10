import type { components } from "./schema";

export type SearchProfile = components["schemas"]["ProfileView"];
export type ProfileCreate = components["schemas"]["ProfileCreate"];
export type DiscoveryRun = components["schemas"]["RunView"];
export type JobLead = components["schemas"]["LeadView"];
export type JobLeadStatus = components["schemas"]["JobLeadStatus"];
export type CandidateProfile = components["schemas"]["CandidateProfileView"];
export type LeadMatch = components["schemas"]["LeadMatchView"];
export type JobApplication = components["schemas"]["ApplicationView"];
export type ApplicationUpdate = components["schemas"]["ApplicationUpdate"];

export interface DashboardStats {
  open_jobs: number;
  active_companies: number;
  pending_companies: number;
  needs_review_companies: number;
  action_required_companies: number;
}
