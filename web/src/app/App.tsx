import { useCallback, useEffect, useState } from "react";

import { DiscoveryPanel } from "../features/discovery/DiscoveryPanel";
import { ApplicationWorkspace } from "../features/applications/ApplicationWorkspace";
import { JobInbox } from "../features/jobs/JobInbox";
import { CandidateProfilePanel } from "../features/profile/CandidateProfilePanel";
import { api } from "../shared/api/client";
import type {
  CandidateProfile,
  ApplicationUpdate,
  DashboardStats,
  DiscoveryRun,
  JobLead,
  JobApplication,
  LeadMatch,
  ProfileCreate,
  SearchProfile,
} from "../shared/api/types";

const PREFERRED_LOCATION = "İzmir";

export function App() {
  const today = new Date();
  const [profiles, setProfiles] = useState<SearchProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [leads, setLeads] = useState<JobLead[]>([]);
  const [matches, setMatches] = useState<LeadMatch[]>([]);
  const [applications, setApplications] = useState<JobApplication[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [candidateProfile, setCandidateProfile] = useState<CandidateProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scoringLeadId, setScoringLeadId] = useState<number | null>(null);
  const [preparingMatchId, setPreparingMatchId] = useState<number | null>(null);

  const refreshData = useCallback(async (profileId?: number) => {
    const [nextLeads, nextStats, nextRun, nextMatches, nextApplications] = await Promise.all([
      api.leads(PREFERRED_LOCATION),
      api.stats(),
      api.latestRun(profileId),
      api.leadMatches(),
      api.applications(),
    ]);
    setLeads(nextLeads);
    setStats(nextStats);
    setRun(nextRun);
    setMatches(nextMatches);
    setApplications(nextApplications);
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextProfiles, nextCandidateProfile] = await Promise.all([
          api.profiles(),
          api.candidateProfile(),
        ]);
        if (!active) return;
        const firstId = nextProfiles[0]?.id ?? null;
        setProfiles(nextProfiles);
        setSelectedProfileId(firstId);
        setCandidateProfile(nextCandidateProfile);
        await refreshData(firstId ?? undefined);
      } catch (cause) {
        if (active) setError(messageOf(cause));
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [refreshData]);

  useEffect(() => {
    if (!run || !["pending", "running"].includes(run.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const nextRun = await api.run(run.id);
        setRun(nextRun);
        if (["completed", "failed"].includes(nextRun.status)) {
          await refreshData(selectedProfileId ?? undefined);
        }
      } catch (cause) {
        setError(messageOf(cause));
      }
    }, 1600);
    return () => window.clearTimeout(timer);
  }, [refreshData, run, selectedProfileId]);

  async function createProfile(payload: ProfileCreate) {
    try {
      setError(null);
      const profile = await api.createProfile(payload);
      setProfiles((current) => [...current, profile]);
      setSelectedProfileId(profile.id);
      setRun(null);
    } catch (cause) {
      setError(messageOf(cause));
    }
  }

  async function startDiscovery() {
    if (!selectedProfileId) return;
    try {
      setError(null);
      setRun(await api.startRun(selectedProfileId));
    } catch (cause) {
      setError(messageOf(cause));
    }
  }

  async function changeProfile(profileId: number) {
    setSelectedProfileId(profileId);
    try {
      setRun(await api.latestRun(profileId));
    } catch (cause) {
      setError(messageOf(cause));
    }
  }

  async function enableProfileSource(profileId: number, source: string) {
    const profile = profiles.find((item) => item.id === profileId);
    const currentSources = profile?.sources ?? [];
    if (!profile || currentSources.includes(source)) return;
    try {
      setError(null);
      const updated = await api.setProfileSources(profileId, [...currentSources, source]);
      setProfiles((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (cause) {
      setError(messageOf(cause));
    }
  }

  async function changeLeadStatus(leadId: number, status: JobLead["status"]) {
    try {
      const updated = await api.setLeadStatus(leadId, status);
      setLeads((current) => current.map((lead) => (lead.id === updated.id ? updated : lead)));
    } catch (cause) {
      setError(messageOf(cause));
    }
  }

  async function uploadCandidateProfile(name: string, file: File) {
    try {
      setError(null);
      setCandidateProfile(await api.uploadCandidateProfile(name, file));
      await refreshData(selectedProfileId ?? undefined);
      return true;
    } catch (cause) {
      setError(messageOf(cause));
      return false;
    }
  }

  async function scoreLead(leadId: number) {
    try {
      setError(null);
      setScoringLeadId(leadId);
      const match = await api.scoreLead(leadId);
      setMatches((current) => [match, ...current.filter((item) => item.lead_id !== leadId)]);
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setScoringLeadId(null);
    }
  }

  async function prepareApplication(leadMatchId: number) {
    try {
      setError(null);
      setPreparingMatchId(leadMatchId);
      const application = await api.prepareApplication(leadMatchId);
      setApplications((current) => [
        application,
        ...current.filter((item) => item.id !== application.id),
      ]);
      window.requestAnimationFrame(() => {
        document.getElementById("applications")?.scrollIntoView({ behavior: "smooth" });
      });
    } catch (cause) {
      setError(messageOf(cause));
    } finally {
      setPreparingMatchId(null);
    }
  }

  async function saveApplication(applicationId: number, payload: ApplicationUpdate) {
    try {
      setError(null);
      const updated = await api.updateApplication(applicationId, payload);
      replaceApplication(updated);
      return true;
    } catch (cause) {
      setError(messageOf(cause));
      return false;
    }
  }

  async function approveApplication(applicationId: number) {
    try {
      setError(null);
      const approved = await api.approveApplication(applicationId);
      replaceApplication(approved);
      return true;
    } catch (cause) {
      setError(messageOf(cause));
      return false;
    }
  }

  function replaceApplication(application: JobApplication) {
    setApplications((current) =>
      current.map((item) => (item.id === application.id ? application : item)),
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Jobradar ana sayfa">
          <span className="brand-mark" aria-hidden="true"><i /></span>
          <span><strong>jobradar</strong><small>kariyer keşif masası</small></span>
        </a>
        <nav aria-label="Ana menü">
          <a className="nav-item nav-item--active" href="#overview"><span>⌁</span> Genel bakış</a>
          <a className="nav-item" href="#discovery"><span>◉</span> Keşif</a>
          <a className="nav-item" href="#profile"><span>◇</span> CV profili</a>
          <a className="nav-item" href="#inbox"><span>▤</span> İlan kutusu</a>
        </nav>
        <div className="sidebar-note">
          <span className="live-dot" />
          <div><strong>Yerel ve kontrollü</strong><small>Başvurular sen onaylamadan ilerlemez.</small></div>
        </div>
      </aside>

      <main id="top">
        <header className="topbar">
          <div>
            <time className="eyebrow" dateTime={formatIsoDate(today)}>
              {formatFullDate(today)}
            </time>
            <h1>İş aramanın kontrolü sende.</h1>
          </div>
          <div className="system-state"><span className="live-dot" /> Sistem hazır</div>
        </header>

        {error && <div className="error-banner" role="alert"><strong>İşlem tamamlanamadı.</strong> {error}</div>}

        <section className="overview" id="overview" aria-labelledby="overview-title">
          <div className="radar-card">
            <div>
              <span className="eyebrow">Bugünün odağı</span>
              <h2 id="overview-title">Yeni fırsatları bul, gürültüyü ele.</h2>
              <p>Takip ettiğin şirketleri ve Türkiye odaklı iş portallarını tek aramada tara.</p>
            </div>
            <div className="radar-visual" aria-hidden="true"><span /><i /></div>
          </div>
          <div className="metric-grid" aria-label="Jobradar istatistikleri">
            <Metric value={stats?.open_jobs} label="Açık ATS ilanı" note="takip edilen şirketler" />
            <Metric value={leads.filter((lead) => lead.status === "new").length} label="Yeni aday ilan" note="inceleme bekliyor" accent />
            <Metric value={leads.filter((lead) => lead.status === "shortlisted").length} label="Kısa liste" note="senin seçtiklerin" />
            <Metric value={stats?.active_companies} label="Aktif şirket" note="düzenli taranıyor" />
          </div>
        </section>

        <CandidateProfilePanel profile={candidateProfile} loading={loading} onUpload={uploadCandidateProfile} />

        <DiscoveryPanel
          profiles={profiles}
          selectedProfileId={selectedProfileId}
          run={run}
          loading={loading}
          onCreateProfile={createProfile}
          onSelectProfile={changeProfile}
          onEnableSource={enableProfileSource}
          onStart={startDiscovery}
        />
        <JobInbox
          leads={leads}
          matches={matches}
          preferredLocation={PREFERRED_LOCATION}
          loading={loading}
          profileReady={candidateProfile !== null}
          scoringLeadId={scoringLeadId}
          applicationMatchIds={applications.flatMap((item) =>
            item.lead_match_id === null ? [] : [item.lead_match_id],
          )}
          preparingMatchId={preparingMatchId}
          onScore={scoreLead}
          onPrepareApplication={prepareApplication}
          onStatusChange={changeLeadStatus}
        />
        <ApplicationWorkspace
          applications={applications}
          leads={leads}
          matches={matches}
          onSave={saveApplication}
          onApprove={approveApplication}
          onRegenerate={prepareApplication}
        />
      </main>
    </div>
  );
}

function Metric({ value, label, note, accent = false }: { value?: number; label: string; note: string; accent?: boolean }) {
  return (
    <div className={`metric ${accent ? "metric--accent" : ""}`}>
      <strong>{value ?? "—"}</strong><span>{label}</span><small>{note}</small>
    </div>
  );
}

function messageOf(cause: unknown) {
  return cause instanceof Error ? cause.message : "Bilinmeyen hata";
}

function formatFullDate(value: Date) {
  return new Intl.DateTimeFormat("tr-TR", {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(value);
}

function formatIsoDate(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
