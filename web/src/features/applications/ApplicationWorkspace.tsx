import { useEffect, useState } from "react";

import type {
  ApplicationUpdate,
  GmailConnection,
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
  gmailConnection: GmailConnection;
  onCreateGmailDraft: (applicationId: number) => Promise<boolean>;
}

export function ApplicationWorkspace({
  applications,
  leads,
  matches,
  onSave,
  onApprove,
  onRegenerate,
  gmailConnection,
  onCreateGmailDraft,
}: ApplicationWorkspaceProps) {
  return (
    <section className="section" id="applications" aria-labelledby="applications-title">
      <div className="section-heading">
        <div>
          <span className="section-kicker">Başvuru masası</span>
          <h2 id="applications-title">Kontrol senden çıkmadan hazırla</h2>
        </div>
        <GmailConnectionBadge connection={gmailConnection} />
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
                gmailConnected={gmailConnection.connected}
                onCreateGmailDraft={onCreateGmailDraft}
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
  gmailConnected,
  onCreateGmailDraft,
}: {
  application: JobApplication;
  lead?: JobLead;
  match?: LeadMatch;
  onSave: ApplicationWorkspaceProps["onSave"];
  onApprove: ApplicationWorkspaceProps["onApprove"];
  onRegenerate: ApplicationWorkspaceProps["onRegenerate"];
  gmailConnected: boolean;
  onCreateGmailDraft: ApplicationWorkspaceProps["onCreateGmailDraft"];
}) {
  const [draft, setDraft] = useState<ApplicationUpdate>(fieldsOf(application));
  const [busy, setBusy] = useState<"save" | "approve" | "regenerate" | "gmail" | null>(null);
  const stale =
    !match || new Date(match.updated_at).getTime() > new Date(application.created_at).getTime();
  const dirty = !sameFields(draft, fieldsOf(application));

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

  async function createGmailDraft() {
    setBusy("gmail");
    await onCreateGmailDraft(application.id);
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
        <StatusPill
          tone={!stale && !dirty && application.status === "approved" ? "success" : "warning"}
        >
          {stale
            ? "Yeniden hazırlanmalı"
            : dirty
              ? "Kaydedilmemiş değişiklik"
              : application.status === "approved"
                ? "Onaylandı"
                : "Taslak"}
        </StatusPill>
      </header>

      <div className="application-fields">
        <label className="application-field">
          <span>Alıcı e-posta</span>
          <input
            type="email"
            value={draft.recipient_email ?? ""}
            maxLength={320}
            placeholder="ik@sirket.com"
            onChange={(event) => setDraft({ ...draft, recipient_email: event.target.value })}
          />
        </label>
        <label className="application-field">
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
          {gmailConnected && (
            <Button
              disabled={
                busy !== null ||
                stale ||
                dirty ||
                application.status !== "approved" ||
                !(draft.recipient_email ?? "").trim()
              }
              onClick={() => void createGmailDraft()}
            >
              {busy === "gmail"
                ? "Gmail hazırlanıyor…"
                : application.gmail_draft_id
                  ? "Gmail taslağını güncelle"
                  : "Gmail taslağı oluştur"}
            </Button>
          )}
          {application.gmail_draft_id && (
            <a
              className="button button--quiet"
              href="https://mail.google.com/mail/u/0/#drafts"
              target="_blank"
              rel="noreferrer"
            >
              Gmail'de aç ↗
            </a>
          )}
        </div>
      </footer>
    </article>
  );
}

function fieldsOf(application: JobApplication): ApplicationUpdate {
  return {
    cover_letter: application.cover_letter,
    recipient_email: application.recipient_email,
    email_subject: application.email_subject,
    email_body: application.email_body,
  };
}

function sameFields(left: ApplicationUpdate, right: ApplicationUpdate) {
  return (
    left.cover_letter === right.cover_letter &&
    (left.recipient_email ?? "") === (right.recipient_email ?? "") &&
    left.email_subject === right.email_subject &&
    left.email_body === right.email_body
  );
}

function GmailConnectionBadge({ connection }: { connection: GmailConnection }) {
  if (connection.connected) {
    return (
      <div className="gmail-connection">
        <StatusPill tone="success">Gmail bağlı</StatusPill>
        <span>Onaylanan metin yalnızca taslaklara kaydedilir.</span>
      </div>
    );
  }
  if (connection.configured) {
    return (
      <div className="gmail-connection">
        <a className="button button--quiet" href="/api/applications/gmail/authorize">
          Gmail'i bağla
        </a>
        <span>Google iznini bir kez vermen yeterli.</span>
      </div>
    );
  }
  return (
    <div className="gmail-connection">
      <StatusPill tone="warning">Gmail ayarı gerekli</StatusPill>
      <span>OAuth kimlik dosyasını secrets klasörüne ekle.</span>
    </div>
  );
}
