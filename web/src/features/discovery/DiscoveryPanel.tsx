import { useState, type FormEvent } from "react";

import type { DiscoveryRun, ProfileCreate, SearchProfile } from "../../shared/api/types";
import { Button } from "../../shared/ui/Button";
import { StatusPill } from "../../shared/ui/StatusPill";

interface DiscoveryPanelProps {
  profiles: SearchProfile[];
  selectedProfileId: number | null;
  run: DiscoveryRun | null;
  loading: boolean;
  onCreateProfile: (profile: ProfileCreate) => Promise<void>;
  onSelectProfile: (profileId: number) => Promise<void>;
  onStart: () => Promise<void>;
}

const initialProfile: ProfileCreate = {
  name: ".NET backend",
  query: '".NET Developer" OR "Backend Developer" C#',
  location: "Türkiye",
  remote_only: false,
  hours_old: 168,
  results_wanted: 30,
  sources: ["tracked", "jobspy"],
};

export function DiscoveryPanel({
  profiles,
  selectedProfileId,
  run,
  loading,
  onCreateProfile,
  onSelectProfile,
  onStart,
}: DiscoveryPanelProps) {
  const [draft, setDraft] = useState(initialProfile);
  const [saving, setSaving] = useState(false);
  const running = run?.status === "pending" || run?.status === "running";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    await onCreateProfile(draft);
    setSaving(false);
  }

  return (
    <section className="section" id="discovery" aria-labelledby="discovery-title">
      <div className="section-heading">
        <div><span className="section-kicker">Keşif</span><h2 id="discovery-title">Arama profilin</h2></div>
        {run && <RunStatus run={run} />}
      </div>

      {profiles.length === 0 && !loading ? (
        <form className="profile-form" onSubmit={submit}>
          <div className="form-intro"><strong>İlk radarını ayarla</strong><p>Hangi rolleri ve nerede aradığını bir kez tanımla.</p></div>
          <label>Profil adı<input value={draft.name ?? ""} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required /></label>
          <label className="field-wide">Arama ifadesi<input value={draft.query} onChange={(e) => setDraft({ ...draft, query: e.target.value })} required /></label>
          <label>Konum<input value={draft.location ?? ""} onChange={(e) => setDraft({ ...draft, location: e.target.value })} required /></label>
          <label className="check-field"><input type="checkbox" checked={draft.remote_only ?? false} onChange={(e) => setDraft({ ...draft, remote_only: e.target.checked })} /><span>Yalnız uzaktan roller</span></label>
          <Button type="submit" disabled={saving}>{saving ? "Kaydediliyor…" : "Profili oluştur"}</Button>
        </form>
      ) : (
        <div className="discovery-console">
          <div className="profile-picker">
            <label htmlFor="profile">Aktif profil</label>
            <select id="profile" value={selectedProfileId ?? ""} onChange={(event) => void onSelectProfile(Number(event.target.value))}>
              {profiles.map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}
            </select>
            <p>{profiles.find((profile) => profile.id === selectedProfileId)?.query}</p>
          </div>
          <div className="source-lane">
            <Source name="Takip edilen şirketler" detail="ATS ve şirket kariyer sayfaları" active />
            <Source name="Türkiye iş portalları" detail="Indeed ve Google Jobs / JobSpy" active />
            <Source name="Yerel portal araması" detail="Kariyer.net, Secretcv, Yenibiriş" />
          </div>
          <div className="run-action">
            <span>{run ? runSummary(run) : "Henüz keşif çalışması yok."}</span>
            <Button onClick={() => void onStart()} disabled={!selectedProfileId || running}>
              {running ? "Radar tarıyor…" : "Taramayı başlat"}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

function Source({ name, detail, active = false }: { name: string; detail: string; active?: boolean }) {
  return <div className={`source ${active ? "source--active" : ""}`}><span>{active ? "✓" : "·"}</span><div><strong>{name}</strong><small>{detail}</small></div>{!active && <em>yakında</em>}</div>;
}

function RunStatus({ run }: { run: DiscoveryRun }) {
  const tone = run.status === "completed" ? "success" : run.status === "failed" ? "warning" : "info";
  const label = { pending: "Sırada", running: "Taranıyor", completed: "Tamamlandı", failed: "Başarısız" }[run.status];
  return <StatusPill tone={tone}>{label}</StatusPill>;
}

function runSummary(run: DiscoveryRun) {
  if (run.status === "pending") return "Tarama başlamak üzere.";
  if (run.status === "running") return "Kaynaklar kontrol ediliyor; sonuçlar birazdan burada.";
  if (run.status === "failed") return run.error ?? "Tarama tamamlanamadı.";
  return `${run.found_count} ilan bulundu, ${run.new_count} tanesi yeni.`;
}
