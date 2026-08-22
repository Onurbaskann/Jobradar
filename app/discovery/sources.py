from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, col, select

from app.discovery.contracts import DiscoveredJob, SearchQuery
from app.models import Company, JobPosting, RemoteType


class SourceUnavailable(RuntimeError):
    """İsteğe bağlı keşif kaynağı bu kurulumda kullanılamıyor."""


class TrackedJobsSource:
    """Mevcut ATS taramalarının veritabanına yazdığı ilanları keşif akışına taşır."""

    name = "tracked"

    def __init__(self, session: Session) -> None:
        self._session = session

    async def discover(self, query: SearchQuery) -> list[DiscoveredJob]:
        rows = self._session.exec(
            select(JobPosting, Company)
            .join(Company)
            .where(col(JobPosting.closed_at).is_(None))
            .limit(500)
        ).all()
        terms = _search_terms(query.term)
        discovered: list[DiscoveredJob] = []
        for job, company in rows:
            searchable = f"{job.title} {job.description_md}".casefold()
            if terms and not any(term in searchable for term in terms):
                continue
            if query.remote_only and job.remote_type is not RemoteType.REMOTE:
                continue
            discovered.append(
                DiscoveredJob(
                    source=f"tracked:{job.source_adapter}",
                    title=job.title,
                    company_name=company.name,
                    location=job.location,
                    remote_type=job.remote_type,
                    description_md=job.description_md,
                    apply_url=job.apply_url,
                    posted_at=job.posted_at,
                )
            )
        return discovered[: query.results_wanted]


class JobSpySource:
    """Indeed ve Google Jobs sonuçlarını ortak keşif sözleşmesine dönüştürür."""

    name = "jobspy"

    async def discover(self, query: SearchQuery) -> list[DiscoveredJob]:
        try:
            from jobspy import scrape_jobs
        except ImportError as exc:
            raise SourceUnavailable(
                'JobSpy kurulu değil; `pip install -e ".[discovery]"` çalıştır.'
            ) from exc

        frame = await asyncio.to_thread(
            scrape_jobs,
            site_name=["indeed", "google"],
            search_term=query.term,
            google_search_term=f"{query.term} jobs {query.location}",
            location=query.location,
            country_indeed="Turkey",
            results_wanted=query.results_wanted,
            hours_old=query.hours_old,
            is_remote=True if query.remote_only else None,
            description_format="markdown",
            verbose=0,
        )
        return [map_jobspy_row(row) for row in frame.to_dict(orient="records")]


def map_jobspy_row(row: dict[str, Any]) -> DiscoveredJob:
    remote = RemoteType.REMOTE if _clean(row.get("is_remote")) is True else RemoteType.UNKNOWN
    posted_at = _as_datetime(row.get("date_posted"))
    return DiscoveredJob(
        source=str(_clean(row.get("site")) or "jobspy"),
        title=str(_clean(row.get("title")) or "Başlıksız ilan"),
        company_name=str(_clean(row.get("company")) or "Bilinmeyen şirket"),
        location=str(_clean(row.get("location")) or "") or None,
        remote_type=remote,
        description_md=str(_clean(row.get("description")) or ""),
        apply_url=str(
            _clean(row.get("job_url_direct")) or _clean(row.get("job_url")) or ""
        )
        or None,
        posted_at=posted_at,
    )


def _search_terms(value: str) -> list[str]:
    return [part.casefold() for part in value.replace('"', " ").split() if len(part) > 1]


def _clean(value: Any) -> Any | None:
    if value is None:
        return None
    try:
        if value != value:  # NaN / NaT
            return None
    except (TypeError, ValueError):
        pass
    return value


def _as_datetime(value: Any) -> datetime | None:
    value = _clean(value)
    if value is None:
        return None
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
