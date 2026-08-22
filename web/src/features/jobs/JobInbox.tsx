import { useMemo, useState } from "react";

import type { JobLead, JobLeadStatus } from "../../shared/api/types";
import { Button } from "../../shared/ui/Button";
import { StatusPill } from "../../shared/ui/StatusPill";

interface JobInboxProps {
  leads: JobLead[];
  loading: boolean;
  onStatusChange: (leadId: number, status: JobLeadStatus) => Promise<void>;
}

const filters: Array<{ value: "all" | JobLeadStatus; label: string }> = [
  { value: "all", label: "Tümü" },
  { value: "new", label: "Yeni" },
  { value: "shortlisted", label: "Kısa liste" },
  { value: "dismissed", label: "Elenen" },
];

export function JobInbox({ leads, loading, onStatusChange }: JobInboxProps) {
  const [filter, setFilter] = useState<"all" | JobLeadStatus>("new");
  const visible = useMemo(
    () => (filter === "all" ? leads : leads.filter((lead) => lead.status === filter)),
    [filter, leads],
  );

  return (
    <section className="section section--inbox" id="inbox" aria-labelledby="inbox-title">
      <div className="section-heading section-heading--jobs">
        <div><span className="section-kicker">İlan kutusu</span><h2 id="inbox-title">Karar bekleyen fırsatlar</h2></div>
        <div className="filter-tabs" role="group" aria-label="İlan durumunu filtrele">
          {filters.map((item) => (
            <button className={filter === item.value ? "active" : ""} onClick={() => setFilter(item.value)} key={item.value}>
              {item.label}<span>{item.value === "all" ? leads.length : leads.filter((lead) => lead.status === item.value).length}</span>
            </button>
          ))}
        </div>
      </div>

      {loading ? <div className="empty-state">İlan havuzu yükleniyor…</div> : visible.length === 0 ? (
        <div className="empty-state"><strong>Bu görünümde ilan yok.</strong><span>Keşif taraması başlat veya başka bir filtre seç.</span></div>
      ) : (
        <div className="job-list">
          {visible.map((lead) => <JobRow lead={lead} onStatusChange={onStatusChange} key={lead.id} />)}
        </div>
      )}
    </section>
  );
}

function JobRow({ lead, onStatusChange }: { lead: JobLead; onStatusChange: JobInboxProps["onStatusChange"] }) {
  return (
    <article className="job-row">
      <div className="company-token" aria-hidden="true">{initials(lead.company_name)}</div>
      <div className="job-main">
        <div className="job-title"><h3>{lead.title}</h3>{lead.remote_type === "remote" && <StatusPill tone="info">Uzaktan</StatusPill>}</div>
        <p><strong>{lead.company_name}</strong><span>·</span>{lead.location || "Konum belirtilmemiş"}</p>
        <div className="job-meta"><span>{lead.sources.join(" + ")}</span><span>{formatDate(lead.posted_at ?? lead.first_seen_at)}</span></div>
      </div>
      <div className="job-actions">
        {lead.apply_url && <a className="text-link" href={lead.apply_url} target="_blank" rel="noreferrer">İlanı aç ↗</a>}
        {lead.status !== "shortlisted" && <Button onClick={() => void onStatusChange(lead.id, "shortlisted")}>Kısa listeye al</Button>}
        {lead.status !== "dismissed" && <Button variant="quiet" onClick={() => void onStatusChange(lead.id, "dismissed")}>Ele</Button>}
        {lead.status !== "new" && <Button variant="quiet" onClick={() => void onStatusChange(lead.id, "new")}>Yeniye taşı</Button>}
      </div>
    </article>
  );
}

function initials(value: string) {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toLocaleUpperCase("tr-TR");
}

function formatDate(value: string | null) {
  if (!value) return "Tarih yok";
  return new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short" }).format(new Date(value));
}
