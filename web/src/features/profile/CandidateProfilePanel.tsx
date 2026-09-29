import { useEffect, useRef, useState, type FormEvent } from "react";

import type { CandidateProfile } from "../../shared/api/types";
import { Button } from "../../shared/ui/Button";
import { StatusPill } from "../../shared/ui/StatusPill";

interface CandidateProfilePanelProps {
  profile: CandidateProfile | null;
  loading: boolean;
  onUpload: (name: string, file: File) => Promise<boolean>;
}

export function CandidateProfilePanel({ profile, loading, onUpload }: CandidateProfilePanelProps) {
  const [name, setName] = useState(profile?.name ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (profile) setName(profile.name);
  }, [profile]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setSaving(true);
    try {
      const saved = await onUpload(name, file);
      if (saved) {
        setFile(null);
        if (fileInput.current) fileInput.current.value = "";
      }
    } finally {
      setSaving(false);
    }
  }

  const processing = profile && ["pending", "processing"].includes(profile.processing_status);
  const failed = profile?.processing_status === "failed";
  const statusLabel = processing ? "CV değerlendiriliyor" : failed ? "İşleme hatası" : profile ? "Hazır" : "CV bekleniyor";
  const statusTone = failed ? "warning" : processing ? "info" : profile ? "success" : "neutral";

  return (
    <section className="section" id="profile" aria-labelledby="profile-title">
      <div className="section-heading">
        <div><span className="section-kicker">Aday profili</span><h2 id="profile-title">CV sinyalin</h2></div>
        {!loading && <StatusPill tone={statusTone}>{statusLabel}</StatusPill>}
      </div>
      <div className={`cv-panel ${profile ? "cv-panel--ready" : ""}`}>
        <form className="cv-upload" onSubmit={submit}>
          <div><strong>{profile ? "CV’ni güncelle" : "CV’ni radara tanıt"}</strong><p>PDF, DOCX veya TXT yükle. Dosya yalnızca yerel Jobradar verisinde tutulur.</p></div>
          {profile && (
            <div className="current-cv">
              <span><small>Yüklü CV · sürüm {profile.version}</small><strong>{profile.filename}</strong></span>
              <a className="button button--quiet" href="/api/profile/cv" download>CV’yi indir</a>
            </div>
          )}
          {profile?.processing_status === "completed" && profile.ats_score !== null && profile.ats_score !== undefined && (
            <div className="ats-details">
              <div><strong>Jobradar ATS okunabilirlik puanı</strong><span>{profile.ats_score}/100</span></div>
              <div className="ats-metrics">
                {Object.entries(profile.ats_metrics).map(([label, score]) => (
                  <span key={label}><small>{label}</small><strong>{score}</strong></span>
                ))}
              </div>
              {profile.ats_findings.length > 0 && <ul>{profile.ats_findings.map((finding) => <li key={finding}>{finding}</li>)}</ul>}
            </div>
          )}
          {failed && <p className="cv-processing-error">CV işlenemedi. {profile.processing_error ?? "Yerel model yanıt vermedi."}</p>}
          <label>Adın<input value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={100} required /></label>
          <label className="cv-file">CV dosyası<input ref={fileInput} type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /><span>{file?.name ?? "Dosya seçilmedi"}</span></label>
          <Button disabled={!file || saving}>{saving ? "CV işleniyor…" : profile ? "CV’yi güncelle" : "CV’yi kaydet"}</Button>
        </form>
        <div className="cv-signal" aria-live="polite">
          <span className="cv-scan" aria-hidden="true" />
          {profile ? <><span className="section-kicker">{processing ? "Yerel Qwen inceliyor" : "ATS okunabilirliği"}</span><strong>{processing ? "…" : profile.ats_score ?? "—"}</strong><small>{processing ? `${profile.text_length.toLocaleString("tr-TR")} karakter çıkarıldı` : profile.ats_score === null ? "puan hesaplanamadı" : "100 üzerinden"}</small><p>{profile.filename}</p></> : <><span className="section-kicker">Eşleştirme girdisi</span><strong>—</strong><small>CV yüklendiğinde hazır olacak</small></>}
        </div>
      </div>
    </section>
  );
}
