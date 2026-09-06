import type {
  CandidateProfile,
  DashboardStats,
  DiscoveryRun,
  JobLead,
  JobLeadStatus,
  LeadMatch,
  ProfileCreate,
  SearchProfile,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = init?.body instanceof FormData
    ? init.headers
    : { "Content-Type": "application/json", ...init?.headers };
  const response = await fetch(path, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `İstek başarısız (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  stats: () => request<DashboardStats>("/stats"),
  candidateProfile: () => request<CandidateProfile | null>("/api/profile"),
  uploadCandidateProfile: (name: string, file: File) => {
    const body = new FormData();
    body.set("name", name);
    body.set("file", file);
    return request<CandidateProfile>("/api/profile", { method: "PUT", body });
  },
  profiles: () => request<SearchProfile[]>("/api/discovery/profiles"),
  createProfile: (profile: ProfileCreate) =>
    request<SearchProfile>("/api/discovery/profiles", {
      method: "POST",
      body: JSON.stringify(profile),
    }),
  setProfileSources: (profileId: number, sources: string[]) =>
    request<SearchProfile>(`/api/discovery/profiles/${profileId}/sources`, {
      method: "PATCH",
      body: JSON.stringify({ sources }),
    }),
  latestRun: (profileId?: number) =>
    request<DiscoveryRun | null>(
      `/api/discovery/runs/latest${profileId ? `?profile_id=${profileId}` : ""}`,
    ),
  run: (runId: number) => request<DiscoveryRun>(`/api/discovery/runs/${runId}`),
  startRun: (profileId: number) =>
    request<DiscoveryRun>("/api/discovery/runs", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    }),
  leads: (status?: JobLeadStatus) =>
    request<JobLead[]>(`/api/jobs/leads${status ? `?status=${status}` : ""}`),
  setLeadStatus: (leadId: number, status: JobLeadStatus) =>
    request<JobLead>(`/api/jobs/leads/${leadId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  leadMatches: () => request<LeadMatch[]>("/api/jobs/leads/matches"),
  scoreLead: (leadId: number) =>
    request<LeadMatch>(`/api/jobs/leads/${leadId}/score`, { method: "POST" }),
};
