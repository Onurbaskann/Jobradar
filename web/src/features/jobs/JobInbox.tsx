import { useMemo, useState } from "react";

import type { JobLead, JobLeadStatus, LeadMatch, MatchQueueItem } from "../../shared/api/types";
import { Button } from "../../shared/ui/Button";
import { StatusPill } from "../../shared/ui/StatusPill";
import { sortJobLeadsForReview } from "./sortJobLeads";

interface JobInboxProps {
  leads: JobLead[];
  matches: LeadMatch[];
  matchQueue: MatchQueueItem[];
  preferredLocation: string;
  loading: boolean;
  profileReady: boolean;
  scoringLeadId: number | null;
  applicationMatchIds: number[];
  preparingMatchId: number | null;
  onScore: (leadId: number) => Promise<void>;
  onPrepareApplication: (leadMatchId: number) => Promise<void>;
  onStatusChange: (leadId: number, status: JobLeadStatus) => Promise<void>;
}

const filters: Array<{ value: "all" | JobLeadStatus; label: string }> = [
  { value: "all", label: "Tümü" },
  { value: "new", label: "Yeni" },
  { value: "shortlisted", label: "Kısa liste" },
  { value: "dismissed", label: "Elenen" },
];

export function JobInbox({
  leads,
  matches,
  matchQueue,
  preferredLocation,
  loading,
  profileReady,
  scoringLeadId,
  applicationMatchIds,
  preparingMatchId,
  onScore,
  onPrepareApplication,
  onStatusChange,
}: JobInboxProps) {
  const [filter, setFilter] = useState<"all" | JobLeadStatus>("new");
  const orderedLeads = useMemo(
    () => matchQueue.length > 0
      ? leads
      : sortJobLeadsForReview(leads, matches, preferredLocation),
    [leads, matchQueue.length, matches, preferredLocation],
  );
  const visible = useMemo(
    () => filter === "all"
      ? orderedLeads
      : orderedLeads.filter((lead) => lead.status === filter),
    [filter, orderedLeads],
  );

  return (
    <section className="section section--inbox" id="inbox" aria-labelledby="inbox-title">
      <div className="section-heading section-heading--jobs">
        <div>
          <span className="section-kicker">İlan kutusu · {preferredLocation} öncelikli</span>
          <h2 id="inbox-title">Karar bekleyen fırsatlar</h2>
        </div>
        <div className="filter-tabs" role="group" aria-label="İlan durumunu filtrele">
          {filters.map((item) => (
            <button className={filter === item.value ? "active" : ""} onClick={() => setFilter(item.value)} key={item.value}>
              {item.label}<span>{item.value === "all" ? leads.length : leads.filter((lead) => lead.status === item.value).length}</span>
            </button>
          ))}
        </div>
      </div>

      {matchQueue.length > 0 && (
        <div className="queue-summary" aria-live="polite">
          <span className="queue-pulse" aria-hidden="true" />
          <strong>Yerel Qwen değerlendiriyor</strong>
          <span>{matchQueue.filter((item) => item.status === "processing").length} aktif, {matchQueue.filter((item) => item.status === "pending").length} sırada</span>
        </div>
      )}

      {loading ? <div className="empty-state">İlan havuzu yükleniyor…</div> : visible.length === 0 ? (
        <div className="empty-state"><strong>Bu görünümde ilan yok.</strong><span>Keşif taraması başlat veya başka bir filtre seç.</span></div>
      ) : (
        <div className="job-list">
          {visible.map((lead) => (
            <JobRow
              lead={lead}
              match={matches.find((item) => item.lead_id === lead.id)}
              queueItem={matchQueue.find((item) => item.lead_id === lead.id)}
              profileReady={profileReady}
              scoring={scoringLeadId === lead.id}
              scoreBusy={scoringLeadId !== null}
              applicationReady={applicationMatchIds.includes(
                matches.find((item) => item.lead_id === lead.id)?.id ?? -1,
              )}
              preparingMatchId={preparingMatchId}
              onScore={onScore}
              onPrepareApplication={onPrepareApplication}
              onStatusChange={onStatusChange}
              key={lead.id}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function JobRow({ lead, match, queueItem, profileReady, scoring, scoreBusy, applicationReady, preparingMatchId, onScore, onPrepareApplication, onStatusChange }: {
  lead: JobLead;
  match?: LeadMatch;
  queueItem?: MatchQueueItem;
  profileReady: boolean;
  scoring: boolean;
  scoreBusy: boolean;
  applicationReady: boolean;
  preparingMatchId: number | null;
  onScore: JobInboxProps["onScore"];
  onPrepareApplication: JobInboxProps["onPrepareApplication"];
  onStatusChange: JobInboxProps["onStatusChange"];
}) {
  return (
    <article className="job-row">
      <div className="company-token" aria-hidden="true">{initials(lead.company_name)}</div>
      <div className="job-main">
        <div className="job-title">
          <h3>{lead.title}</h3>
          {lead.remote_type === "remote" && <StatusPill tone="info">Uzaktan</StatusPill>}
          {queueItem && <StatusPill tone="info">{queueItem.status === "processing" ? "Değerlendiriliyor" : "Sırada"}</StatusPill>}
        </div>
        <p><strong>{lead.company_name}</strong><span>·</span>{lead.location || "Konum belirtilmemiş"}</p>
        <div className="job-meta"><span>{lead.sources.join(" + ")}</span><span>{formatDate(lead.posted_at ?? lead.first_seen_at)}</span></div>
      </div>
      <div className="job-actions">
        {lead.apply_url && <a className="text-link" href={lead.apply_url} target="_blank" rel="noreferrer">İlanı aç ↗</a>}
        <Button
          variant="quiet"
          disabled={!profileReady || scoreBusy || queueItem !== undefined}
          onClick={() => void onScore(lead.id)}
          title={profileReady ? undefined : "Önce CV profilini yükle"}
        >
          {queueItem
            ? queueItem.status === "processing" ? "Değerlendiriliyor…" : "Değerlendirme sırasında"
            : scoring
            ? "Değerlendiriliyor…"
            : !profileReady
              ? "Önce CV yükle"
              : match
                ? "Yeniden değerlendir"
                : "CV ile değerlendir"}
        </Button>
        {lead.status !== "shortlisted" && <Button onClick={() => void onStatusChange(lead.id, "shortlisted")}>Kısa listeye al</Button>}
        {lead.status !== "dismissed" && <Button variant="quiet" onClick={() => void onStatusChange(lead.id, "dismissed")}>Ele</Button>}
        {lead.status !== "new" && <Button variant="quiet" onClick={() => void onStatusChange(lead.id, "new")}>Yeniye taşı</Button>}
      </div>
      {match && (
        <MatchResult
          match={match}
          shortlisted={lead.status === "shortlisted"}
          applicationReady={applicationReady}
          preparingMatchId={preparingMatchId}
          onPrepareApplication={onPrepareApplication}
        />
      )}
    </article>
  );
}

function MatchResult({ match, shortlisted, applicationReady, preparingMatchId, onPrepareApplication }: {
  match: LeadMatch;
  shortlisted: boolean;
  applicationReady: boolean;
  preparingMatchId: number | null;
  onPrepareApplication: JobInboxProps["onPrepareApplication"];
}) {
  const canPrepareApplication = match.score >= 50;
  const tone = match.score >= 70 ? "strong" : canPrepareApplication ? "medium" : "low";
  const level = match.score >= 70 ? "Yüksek uyum" : canPrepareApplication ? "Orta uyum" : "Düşük uyum";
  const preparing = preparingMatchId === match.id;
  return (
    <div className={`match-result match-result--${tone}`}>
      <div className="match-score" aria-label={`CV uyum puanı ${match.score} üzerinden 100`}>
        <strong>{match.score}</strong><span>/ 100</span>
      </div>
      <div className="match-copy">
        <strong>{level}</strong>
        <p>{match.rationale}</p>
        {match.gaps.length > 0 && (
          <div className="match-gaps">
            <span>Eksikler</span>
            {match.gaps.map((gap) => <em key={gap}>{gap}</em>)}
          </div>
        )}
      </div>
      <div className="match-next-step">
        {applicationReady ? (
          <a className="button button--quiet" href="#applications">Taslağı aç</a>
        ) : (
          <Button
            variant="quiet"
            disabled={!shortlisted || !canPrepareApplication || preparingMatchId !== null}
            onClick={() => void onPrepareApplication(match.id)}
            title={
              !canPrepareApplication
                ? "Uyum puanı 50 altında olduğu için başvuru hazırlanamaz"
                : shortlisted
                  ? undefined
                  : "Önce ilanı kısa listeye al"
            }
          >
            {preparing
              ? "Taslak hazırlanıyor…"
              : !canPrepareApplication
                ? "Uyum düşük"
                : shortlisted
                  ? "Başvuru hazırla"
                  : "Önce kısa listeye al"}
          </Button>
        )}
      </div>
    </div>
  );
}

function initials(value: string) {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toLocaleUpperCase("tr-TR");
}

function formatDate(value: string | null) {
  if (!value) return "Tarih yok";
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" }).format(new Date(value));
}
