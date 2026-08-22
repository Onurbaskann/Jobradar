"""Jobradar API ve yerel web uygulaması."""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, text
from sqlmodel import Session, col, select

from app.db import get_session
from app.discovery.api import router as discovery_router
from app.models import Company, CompanyStatus, JobPosting

api = FastAPI(title="jobradar", version="0.1.0")
app = api

api.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
api.include_router(discovery_router)


@api.get("/health")
def health() -> dict[str, str]:
    """Süreç canlılık kontrolü; veritabanına ihtiyaç duymaz."""
    return {"status": "ok"}


@api.get("/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    """Trafik almadan önce veritabanı bağlantısını da doğrula."""
    try:
        session.exec(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — dışarıya bağlantı ayrıntısı sızdırma
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}


@api.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict[str, int]:
    """Panel gelene kadar sistemin canlı olduğunu doğrulamanın hızlı yolu."""
    open_jobs = session.exec(
        select(func.count()).select_from(JobPosting).where(col(JobPosting.closed_at).is_(None))
    ).one()
    active_companies = session.exec(
        select(func.count()).select_from(Company).where(Company.status == CompanyStatus.ACTIVE)
    ).one()
    pending_companies = session.exec(
        select(func.count()).select_from(Company).where(Company.status == CompanyStatus.PENDING)
    ).one()
    review_companies = session.exec(
        select(func.count())
        .select_from(Company)
        .where(Company.status == CompanyStatus.NEEDS_REVIEW)
    ).one()
    return {
        "open_jobs": int(open_jobs),
        "active_companies": int(active_companies),
        "pending_companies": int(pending_companies),
        "needs_review_companies": int(review_companies),
        "action_required_companies": int(pending_companies) + int(review_companies),
    }


web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
if web_dist.is_dir():
    api.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
