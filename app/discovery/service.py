from __future__ import annotations

import asyncio
import re
import unicodedata

from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_engine
from app.discovery.contracts import DiscoveredJob, JobSource, SearchQuery
from app.discovery.sources import JobSpySource, TrackedJobsSource, TurkiyeWebSource
from app.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    JobLead,
    SearchProfile,
    utcnow,
)
from app.util.text import content_hash


def create_run(session: Session, profile_id: int) -> DiscoveryRun:
    profile = session.get(SearchProfile, profile_id)
    if profile is None:
        raise LookupError(f"Arama profili bulunamadı: {profile_id}")
    run = DiscoveryRun(profile_id=profile_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def execute_discovery_run(run_id: int) -> None:
    """FastAPI BackgroundTasks için senkron giriş noktası."""
    asyncio.run(_execute_discovery_run(run_id))


async def _execute_discovery_run(run_id: int) -> None:
    with Session(get_engine()) as session:
        run = session.get(DiscoveryRun, run_id)
        if run is None:
            return
        profile = session.get(SearchProfile, run.profile_id)
        if profile is None:
            _fail_run(session, run, "Arama profili silinmiş veya bulunamıyor")
            return

        run.status = DiscoveryRunStatus.RUNNING
        run.started_at = utcnow()
        session.add(run)
        session.commit()

        query = SearchQuery(
            term=profile.query,
            location=profile.location,
            remote_only=profile.remote_only,
            hours_old=profile.hours_old,
            results_wanted=profile.results_wanted,
        )
        sources, unknown_sources = _build_sources(profile.sources, session)
        source_results: dict[str, object] = {
            name: {"status": "failed", "error": "Bilinmeyen kaynak"}
            for name in unknown_sources
        }
        fingerprints: set[str] = set()
        new_count = 0
        successful_sources = 0

        for source in sources:
            try:
                jobs = await source.discover(query)
                created = _store_jobs(session, run, jobs, fingerprints)
                new_count += created
                successful_sources += 1
                source_results[source.name] = {
                    "status": "completed",
                    "found": len(jobs),
                    "new": created,
                }
            except Exception as exc:  # noqa: BLE001 — kaynaklar birbirinden izole
                source_results[source.name] = {
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {str(exc)[:240]}",
                }

        run.source_results = source_results
        run.found_count = len(fingerprints)
        run.new_count = new_count
        run.completed_at = utcnow()
        if successful_sources:
            run.status = DiscoveryRunStatus.COMPLETED
            failed_names = [
                name
                for name, result in source_results.items()
                if isinstance(result, dict) and result.get("status") == "failed"
            ]
            run.error = (
                f"Bazı kaynaklar başarısız: {', '.join(failed_names)}"
                if failed_names
                else None
            )
        else:
            run.status = DiscoveryRunStatus.FAILED
            run.error = "Hiçbir keşif kaynağı tamamlanamadı"
        session.add(run)
        session.commit()


def lead_fingerprint(job: DiscoveredJob) -> str:
    """Aynı ilanın farklı portallardaki kopyalarını tek havuzda birleştirir."""
    return content_hash(
        _identity_part(job.company_name),
        _identity_part(job.title),
        _identity_part(job.location or ""),
    )


def prioritize_leads_by_location(
    leads: list[JobLead], preferred_location: str
) -> list[JobLead]:
    """Tercih edilen konumdaki ilanları öne alır, diğerlerinin sırasını korur."""
    preferred = _identity_part(preferred_location)
    if not preferred:
        return leads
    return sorted(
        leads,
        key=lambda lead: preferred not in _identity_part(lead.location or ""),
    )


def _build_sources(names: list[str], session: Session) -> tuple[list[JobSource], list[str]]:
    sources: list[JobSource] = []
    unknown: list[str] = []
    for name in dict.fromkeys(names):
        if name == "tracked":
            sources.append(TrackedJobsSource(session))
        elif name == "jobspy":
            sources.append(JobSpySource())
        elif name == "turkiye_web":
            settings = get_settings()
            sources.append(
                TurkiyeWebSource(
                    api_key=settings.brave_search_api_key,
                    timeout=settings.crawl_timeout,
                )
            )
        else:
            unknown.append(name)
    return sources, unknown


def _store_jobs(
    session: Session,
    run: DiscoveryRun,
    jobs: list[DiscoveredJob],
    run_fingerprints: set[str],
) -> int:
    created = 0
    for job in jobs:
        fingerprint = lead_fingerprint(job)
        if fingerprint in run_fingerprints:
            continue
        run_fingerprints.add(fingerprint)
        existing = session.exec(
            select(JobLead).where(JobLead.fingerprint == fingerprint)
        ).first()
        if existing is None:
            existing = JobLead(
                fingerprint=fingerprint,
                title=job.title,
                company_name=job.company_name,
                location=job.location,
                remote_type=job.remote_type,
                description_md=job.description_md,
                apply_url=job.apply_url,
                posted_at=job.posted_at,
                sources=[job.source],
                last_run_id=run.id,
            )
            created += 1
        else:
            existing.location = job.location or existing.location
            existing.remote_type = job.remote_type
            if len(job.description_md) > len(existing.description_md):
                existing.description_md = job.description_md
            existing.apply_url = job.apply_url or existing.apply_url
            existing.posted_at = job.posted_at or existing.posted_at
            existing.sources = sorted(set(existing.sources) | {job.source})
            existing.last_run_id = run.id
            existing.last_seen_at = utcnow()
        session.add(existing)
    session.commit()
    return created


def _identity_part(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold().replace("ı", "i")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)


def _fail_run(session: Session, run: DiscoveryRun, message: str) -> None:
    run.status = DiscoveryRunStatus.FAILED
    run.error = message
    run.completed_at = utcnow()
    session.add(run)
    session.commit()
