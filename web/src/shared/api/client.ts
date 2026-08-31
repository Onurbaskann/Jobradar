import type {
  DashboardStats,
  DiscoveryRun,
  JobLead,
  JobLeadStatus,
  ProfileCreate,
  SearchProfile,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? `İstek başarısız (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  stats: () => request<DashboardStats>("/stats"),
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
};
