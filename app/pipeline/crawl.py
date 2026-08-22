"""Tarama döngüsü: adaptörü çalıştır, değişiklik varsa veritabanına yaz.

Maliyet kontrolünün kalbi burası. Her şirket için çekilen ilan kümesinin
hash'ini saklıyoruz; hash değişmediyse hiçbir yazma (ve L4'te hiçbir LLM
çağrısı) yapılmıyor.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from app.adapters.base import Adapter, RawJob
from app.adapters.registry import get_adapter, has_adapter
from app.config import get_settings
from app.db import get_engine
from app.models import (
    AdapterType,
    Company,
    CompanyStatus,
    JobPosting,
    utcnow,
)
from app.net import HttpClient
from app.util.text import content_hash

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
EMPTY_RESULT_CONFIRMATIONS = 2


@dataclass(slots=True)
class CrawlOutcome:
    company: str
    status: str  # "unchanged" | "updated" | "skipped" | "error"
    fetched: int = 0
    created: int = 0
    updated: int = 0
    closed: int = 0
    error: str | None = None


def jobset_hash(jobs: list[RawJob]) -> str:
    """İlan kümesinin anlamlı bütün alanlarını kapsayan, sıra bağımsız kimliği."""
    fingerprints = sorted(
        content_hash(
            job.external_id,
            job.title,
            job.location,
            job.remote_type,
            job.seniority,
            job.department,
            job.employment_type,
            job.description_md,
            job.apply_channel,
            job.apply_email,
            job.apply_url,
            job.posted_at.isoformat() if job.posted_at else None,
        )
        for job in jobs
    )
    return content_hash(*fingerprints)


async def crawl_company(http: HttpClient, session: Session, company: Company) -> CrawlOutcome:
    if company.adapter_type is AdapterType.UNKNOWN or not has_adapter(company.adapter_type):
        return CrawlOutcome(company.name, "skipped", error="adaptör tespit edilmedi")

    adapter: Adapter = get_adapter(company.adapter_type)
    config = dict(company.adapter_config or {})
    config.setdefault("company_name", company.name)
    config.setdefault("company_id", company.id)
    started_at = utcnow()

    # Pahalı adaptörler (LLM çıkarımı) için ön kontrol: kaynak imzası
    # değişmediyse adaptörü hiç çalıştırma. Ucuz adaptörler None döner ve
    # doğrudan fetch'e geçilir.
    try:
        fingerprint = await adapter.source_fingerprint(http, config)
    except Exception:  # noqa: BLE001 — ön kontrol başarısızsa normal yola devam
        log.debug("kaynak imzası alınamadı: %s", company.name, exc_info=True)
        fingerprint = None

    if fingerprint is not None and fingerprint == company.source_fingerprint:
        company.last_checked_at = started_at
        company.last_success_at = started_at
        session.add(company)
        session.commit()
        return CrawlOutcome(company.name, "unchanged")

    try:
        jobs = await adapter.fetch(http, config)
    except Exception as exc:  # noqa: BLE001 — bir şirketin hatası tüm taramayı düşürmesin
        company.consecutive_failures += 1
        company.last_error = f"{type(exc).__name__}: {exc}"
        company.last_checked_at = started_at
        if company.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            company.status = CompanyStatus.FAILED
        session.add(company)
        session.commit()
        log.warning("crawl hatası %s: %s", company.name, company.last_error)
        return CrawlOutcome(company.name, "error", error=company.last_error)

    company.consecutive_failures = 0
    company.last_error = None
    company.last_checked_at = started_at
    company.last_success_at = started_at
    if company.status is CompanyStatus.FAILED:
        company.status = CompanyStatus.ACTIVE

    new_hash = jobset_hash(jobs)

    # Başarılı bir HTTP yanıtı her zaman güvenilir bir boş ilan kümesi demek
    # değildir: geçici bot koruması veya ayrıştırıcı değişikliği [] üretebilir.
    # Daha önce ilan görmüş kaynaklarda boş sonucu iki taramayla doğrula.
    if not jobs and company.content_hash and company.content_hash != new_hash:
        company.consecutive_empty_results += 1
        if company.consecutive_empty_results < EMPTY_RESULT_CONFIRMATIONS:
            company.last_error = "Boş sonuç doğrulama bekliyor (1/2)"
            session.add(company)
            session.commit()
            return CrawlOutcome(
                company.name,
                "skipped",
                error="şüpheli boş sonuç; kapanışlar için ikinci tarama bekleniyor",
            )
    else:
        company.consecutive_empty_results = 0

    company.source_fingerprint = fingerprint
    if new_hash == company.content_hash:
        session.add(company)
        session.commit()
        return CrawlOutcome(company.name, "unchanged", fetched=len(jobs))

    created, updated = _upsert_jobs(session, company, jobs, seen_at=started_at)
    closed = _close_missing(session, company, seen_at=started_at)

    company.content_hash = new_hash
    company.consecutive_empty_results = 0
    session.add(company)
    session.commit()

    return CrawlOutcome(
        company.name, "updated", fetched=len(jobs), created=created, updated=updated, closed=closed
    )


def _upsert_jobs(
    session: Session, company: Company, jobs: list[RawJob], *, seen_at: datetime
) -> tuple[int, int]:
    created = updated = 0
    for job in jobs:
        existing = session.exec(
            select(JobPosting).where(
                JobPosting.company_id == company.id,
                JobPosting.external_id == job.external_id,
            )
        ).first()

        if existing is None:
            session.add(_to_model(company, job, seen_at=seen_at))
            created += 1
            continue

        changed = (
            existing.title != job.title
            or existing.location != job.location
            or existing.description_md != job.description_md
            or existing.apply_url != job.apply_url
        )
        existing.title = job.title
        existing.location = job.location
        existing.remote_type = job.remote_type
        existing.seniority = job.seniority
        existing.department = job.department
        existing.employment_type = job.employment_type
        existing.description_md = job.description_md
        existing.apply_channel = job.apply_channel
        existing.apply_email = job.apply_email
        existing.apply_url = job.apply_url
        existing.posted_at = job.posted_at or existing.posted_at
        existing.raw = job.raw
        existing.last_seen_at = seen_at
        # Kapanmış sanılan ilan yeniden göründüyse geri aç
        existing.closed_at = None
        if changed:
            # Açıklama değiştiyse eski gömme geçersiz
            existing.embedding = None
            updated += 1
        session.add(existing)
    return created, updated


def _close_missing(session: Session, company: Company, *, seen_at: datetime) -> int:
    """Bu taramada görünmeyen açık ilanları kapalı olarak işaretle."""
    stale = session.exec(
        select(JobPosting).where(
            JobPosting.company_id == company.id,
            JobPosting.closed_at.is_(None),  # type: ignore[union-attr]
            JobPosting.last_seen_at < seen_at,
        )
    ).all()
    for job in stale:
        job.closed_at = seen_at
        session.add(job)
    return len(stale)


def _to_model(company: Company, job: RawJob, *, seen_at: datetime) -> JobPosting:
    return JobPosting(
        company_id=company.id,  # type: ignore[arg-type]
        external_id=job.external_id,
        title=job.title,
        location=job.location,
        remote_type=job.remote_type,
        seniority=job.seniority,
        department=job.department,
        employment_type=job.employment_type,
        description_md=job.description_md,
        apply_channel=job.apply_channel,
        apply_email=job.apply_email,
        apply_url=job.apply_url,
        posted_at=job.posted_at,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
        source_adapter=company.adapter_type,
        raw=job.raw,
    )


async def crawl_all(
    *, company_name: str | None = None, limit: int | None = None
) -> list[CrawlOutcome]:
    """Aktif şirketleri paralel (ama alan adı başına sıralı) tarar."""
    settings = get_settings()

    with Session(get_engine()) as session:
        query = select(Company).where(Company.status == CompanyStatus.ACTIVE)
        if company_name:
            query = query.where(Company.name == company_name)
        if limit:
            query = query.limit(limit)
        companies = session.exec(query).all()
        company_ids = [c.id for c in companies if c.id is not None]

    semaphore = asyncio.Semaphore(settings.crawl_concurrency)

    async with HttpClient() as http:

        async def run(company_id: int) -> CrawlOutcome:
            async with semaphore:
                # Her şirket kendi oturumunda — paralel yazmalar birbirine karışmasın
                with Session(get_engine()) as session:
                    company = session.get(Company, company_id)
                    if company is None:
                        return CrawlOutcome(str(company_id), "skipped", error="şirket bulunamadı")
                    return await crawl_company(http, session, company)

        return list(await asyncio.gather(*(run(cid) for cid in company_ids)))
