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

  return (
    <section className="section" id="profile" aria-labelledby="profile-title">
      <div className="section-heading">
        <div><span className="section-kicker">Aday profili</span><h2 id="profile-title">CV sinyalin</h2></div>
        {!loading && <StatusPill tone={profile ? "success" : "neutral"}>{profile ? "Hazır" : "CV bekleniyor"}</StatusPill>}
      </div>
      <div className={`cv-panel ${profile ? "cv-panel--ready" : ""}`}>
        <form className="cv-upload" onSubmit={submit}>
          <div><strong>{profile ? "CV’ni güncelle" : "CV’ni radara tanıt"}</strong><p>PDF, DOCX veya TXT yükle. Dosya yalnızca yerel Jobradar verisinde tutulur.</p></div>
          <label>Adın<input value={name} onChange={(event) => setName(event.target.value)} minLength={2} maxLength={100} required /></label>
          <label className="cv-file">CV dosyası<input ref={fileInput} type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /><span>{file?.name ?? "Dosya seçilmedi"}</span></label>
          <Button disabled={!file || saving}>{saving ? "CV işleniyor…" : profile ? "CV’yi güncelle" : "CV’yi kaydet"}</Button>
        </form>
        <div className="cv-signal" aria-live="polite">
          <span className="cv-scan" aria-hidden="true" />
          {profile ? <><span className="section-kicker">Okunabilir profil</span><strong>{profile.text_length.toLocaleString("tr-TR")}</strong><small>karakter çıkarıldı</small><p>{profile.filename}</p></> : <><span className="section-kicker">Eşleştirme girdisi</span><strong>—</strong><small>CV yüklendiğinde hazır olacak</small></>}
        </div>
      </div>
    </section>
  );
}
