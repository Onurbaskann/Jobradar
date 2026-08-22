import { useCallback, useEffect, useState } from "react";

import { DiscoveryPanel } from "../features/discovery/DiscoveryPanel";
import { JobInbox } from "../features/jobs/JobInbox";
import { api } from "../shared/api/client";
import type {
  DashboardStats,
  DiscoveryRun,
  JobLead,
  ProfileCreate,
  SearchProfile,
} from "../shared/api/types";

export function App() {
  const [profiles, setProfiles] = useState<SearchProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [leads, setLeads] = useState<JobLead[]>([]);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refreshData = useCallback(async (profileId?: number) => {
    const [nextLeads, nextStats, nextRun] = await Promise.all([
      api.leads(),
      api.stats(),
      api.latestRun(profileId),
    ]);
    setLeads(nextLeads);
    setStats(nextStats);
    setRun(nextRun);
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const nextProfiles = await api.profiles();
        if (!active) return;
        const firstId = nextProfiles[0]?.id ?? null;
        setProfiles(nextProfiles);
        setSelectedProfileId(firstId);
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

  async function changeLeadStatus(leadId: number, status: JobLead["status"]) {
    try {
      const updated = await api.setLeadStatus(leadId, status);
      setLeads((current) => current.map((lead) => (lead.id === updated.id ? updated : lead)));
    } catch (cause) {
      setError(messageOf(cause));
    }
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
          <a className="nav-item" href="#inbox"><span>▤</span> İlan kutusu</a>
        </nav>
        <div className="sidebar-note">
          <span className="live-dot" />
          <div><strong>Yerel ve kontrollü</strong><small>Başvurular sen onaylamadan ilerlemez.</small></div>
        </div>
      </aside>

      <main id="top">
        <header className="topbar">
          <div><span className="eyebrow">22 Ağustos 2026</span><h1>İş aramanın kontrolü sende.</h1></div>
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

        <DiscoveryPanel
          profiles={profiles}
          selectedProfileId={selectedProfileId}
          run={run}
          loading={loading}
          onCreateProfile={createProfile}
          onSelectProfile={changeProfile}
          onStart={startDiscovery}
        />
        <JobInbox leads={leads} loading={loading} onStatusChange={changeLeadStatus} />
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
