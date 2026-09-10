import { useEffect, useState } from "react";

import type {
  ApplicationUpdate,
  JobApplication,
  JobLead,
  LeadMatch,
} from "../../shared/api/types";
import { Button } from "../../shared/ui/Button";
import { StatusPill } from "../../shared/ui/StatusPill";

interface ApplicationWorkspaceProps {
  applications: JobApplication[];
  leads: JobLead[];
  matches: LeadMatch[];
  onSave: (applicationId: number, payload: ApplicationUpdate) => Promise<boolean>;
  onApprove: (applicationId: number) => Promise<boolean>;
  onRegenerate: (leadMatchId: number) => Promise<void>;
}

export function ApplicationWorkspace({
  applications,
  leads,
  matches,
  onSave,
  onApprove,
  onRegenerate,
}: ApplicationWorkspaceProps) {
  return (
    <section className="section" id="applications" aria-labelledby="applications-title">
      <div className="section-heading">
        <div>
          <span className="section-kicker">Başvuru masası</span>
          <h2 id="applications-title">Kontrol senden çıkmadan hazırla</h2>
        </div>
      </div>

      {applications.length === 0 ? (
        <div className="empty-state">
          <strong>Henüz başvuru taslağı yok.</strong>
          <span>Puanlanmış bir ilanı kısa listeye al, ardından taslağını hazırla.</span>
        </div>
      ) : (
        <div className="application-list">
          {applications.map((application) => {
            const match = matches.find((item) => item.id === application.lead_match_id);
            const lead = leads.find((item) => item.id === match?.lead_id);
            return (
              <ApplicationEditor
                application={application}
                lead={lead}
                match={match}
                onSave={onSave}
                onApprove={onApprove}
                onRegenerate={onRegenerate}
                key={application.id}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

function ApplicationEditor({
  application,
  lead,
  match,
  onSave,
  onApprove,
  onRegenerate,
}: {
  application: JobApplication;
  lead?: JobLead;
  match?: LeadMatch;
  onSave: ApplicationWorkspaceProps["onSave"];
  onApprove: ApplicationWorkspaceProps["onApprove"];
  onRegenerate: ApplicationWorkspaceProps["onRegenerate"];
}) {
  const [draft, setDraft] = useState<ApplicationUpdate>(fieldsOf(application));
  const [busy, setBusy] = useState<"save" | "approve" | "regenerate" | null>(null);
  const stale =
    !match || new Date(match.updated_at).getTime() > new Date(application.created_at).getTime();

  useEffect(() => setDraft(fieldsOf(application)), [application]);

  async function save() {
    setBusy("save");
    await onSave(application.id, draft);
    setBusy(null);
  }

  async function approve() {
    setBusy("approve");
    const saved = await onSave(application.id, draft);
    if (saved) await onApprove(application.id);
    setBusy(null);
  }

  async function regenerate() {
    if (!match) return;
    setBusy("regenerate");
    await onRegenerate(match.id);
    setBusy(null);
  }

  return (
    <article className={`application-card application-card--${application.status}`}>
      <header className="application-card__header">
        <div>
          <span className="section-kicker">{lead?.company_name ?? application.company_name}</span>
          <h3>{lead?.title ?? application.job_title}</h3>
          {match && <small>CV uyumu {match.score}/100</small>}
        </div>
        <StatusPill tone={!stale && application.status === "approved" ? "success" : "warning"}>
          {stale
            ? "Yeniden hazırlanmalı"
            : application.status === "approved"
              ? "Onaylandı"
              : "Taslak"}
        </StatusPill>
      </header>

      <div className="application-fields">
        <label className="application-field application-field--wide">
          <span>E-posta konusu</span>
          <input
            value={draft.email_subject}
            maxLength={200}
            onChange={(event) => setDraft({ ...draft, email_subject: event.target.value })}
          />
        </label>
        <label className="application-field">
          <span>Ön yazı</span>
          <textarea
            value={draft.cover_letter}
            rows={12}
            maxLength={5000}
            onChange={(event) => setDraft({ ...draft, cover_letter: event.target.value })}
          />
        </label>
        <label className="application-field">
          <span>Kısa başvuru mesajı</span>
          <textarea
            value={draft.email_body}
            rows={12}
            maxLength={3000}
            onChange={(event) => setDraft({ ...draft, email_body: event.target.value })}
          />
        </label>
      </div>

      <footer className="application-card__footer">
        <span>
          {stale
            ? "CV eşleştirmesi değişti. Eski metin korunuyor ancak yeniden onaylanamaz."
            : "Kaydettiğin bir değişiklik yeniden onay gerektirir."}
        </span>
        <div>
          <Button variant="quiet" disabled={busy !== null} onClick={() => void save()}>
            {busy === "save" ? "Kaydediliyor…" : "Değişiklikleri kaydet"}
          </Button>
          {stale && match && (
            <Button variant="quiet" disabled={busy !== null} onClick={() => void regenerate()}>
              {busy === "regenerate" ? "Hazırlanıyor…" : "Taslağı yeniden hazırla"}
            </Button>
          )}
          <Button disabled={busy !== null || stale} onClick={() => void approve()}>
            {busy === "approve" ? "Onaylanıyor…" : "Başvuruyu onayla"}
          </Button>
        </div>
      </footer>
    </article>
  );
}

function fieldsOf(application: JobApplication): ApplicationUpdate {
  return {
    cover_letter: application.cover_letter,
    email_subject: application.email_subject,
    email_body: application.email_body,
  };
}
