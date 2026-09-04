from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlparse

from sqlmodel import Session, col, select

from app.discovery.contracts import DiscoveredJob, SearchQuery
from app.models import Company, JobPosting, RemoteType
from app.web_search import BraveSearchClient, WebSearchError, WebSearchResult


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
            is_remote=query.remote_only,
            description_format="markdown",
            verbose=0,
        )
        return [map_jobspy_row(row) for row in frame.to_dict(orient="records")]


TURKIYE_PORTALS = {
    "kariyer.net": "Kariyer.net",
    "secretcv.com": "Secretcv",
    "yenibiris.com": "Yenibiriş",
}


class TurkiyeWebSource:
    """Türkiye portallarındaki ilanları resmi Brave Search API üzerinden bulur."""

    name = "turkiye_web"
    endpoint = BraveSearchClient.endpoint

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self._search = BraveSearchClient(api_key, timeout)

    async def discover(self, query: SearchQuery) -> list[DiscoveredJob]:
        term = " ".join(query.term.split()[:30])
        sites = " OR ".join(f"site:{domain}" for domain in TURKIYE_PORTALS)
        remote_term = " uzaktan" if query.remote_only else ""
        try:
            results = await self._search.search(
                f'{term} "{query.location}"{remote_term} ({sites})',
                count=query.results_wanted,
                freshness=_brave_freshness(query.hours_old),
            )
        except WebSearchError as exc:
            raise SourceUnavailable(f"Türkiye portal araması kullanılamıyor: {exc}") from exc
        jobs = [
            map_turkiye_web_result(item, query.location)
            for item in results
        ]
        discovered = [job for job in jobs if job is not None]
        if query.remote_only:
            discovered = [
                job for job in discovered if job.remote_type is RemoteType.REMOTE
            ]
        return discovered[: query.results_wanted]


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


def map_turkiye_web_result(
    result: WebSearchResult, location: str = "Türkiye"
) -> DiscoveredJob | None:
    url = result.url
    portal = _portal_for_url(url)
    if portal is None:
        return None

    raw_title = html.unescape(result.title).strip()
    description = html.unescape(result.description).strip()
    title = _job_title(raw_title, url, portal)
    company = _company_name(raw_title, portal)
    searchable = f"{title} {description}".casefold()
    remote = (
        RemoteType.REMOTE
        if any(term in searchable for term in ("remote", "uzaktan", "home office"))
        else RemoteType.UNKNOWN
    )
    domain = next(domain for domain, name in TURKIYE_PORTALS.items() if name == portal)
    return DiscoveredJob(
        source=f"web:{domain}",
        title=title,
        company_name=company,
        location=location,
        remote_type=remote,
        description_md=description,
        apply_url=url,
    )


def _search_terms(value: str) -> list[str]:
    return [part.casefold() for part in value.replace('"', " ").split() if len(part) > 1]


def _portal_for_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").casefold()
    for domain, name in TURKIYE_PORTALS.items():
        if host == domain or host.endswith(f".{domain}"):
            return name
    return None


def _job_title(raw_title: str, url: str, portal: str) -> str:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if portal == "Yenibiriş" and "is-ilani" in path_parts:
        index = path_parts.index("is-ilani")
        if len(path_parts) > index + 1:
            slug = unquote(path_parts[index + 1]).replace("-", " ").strip()
            if slug:
                return re.sub(r"\bNet\b", ".NET", slug.title())

    cleaned = re.sub(
        r"\s*[-|]\s*(Kariyer\.net|Secretcv|Yenibiriş|Yenibiris\.com)\s*$",
        "",
        raw_title,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+İş İlanlar[ıi]\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -|") or "Başlıksız ilan"


def _company_name(raw_title: str, portal: str) -> str:
    if portal == "Yenibiriş" and " - " in raw_title:
        company = raw_title.split(" - ", maxsplit=1)[0].strip()
        if company:
            return company
    return portal


def _brave_freshness(hours_old: int) -> str:
    if hours_old <= 24:
        return "pd"
    if hours_old <= 24 * 7:
        return "pw"
    if hours_old <= 24 * 31:
        return "pm"
    return "py"


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
