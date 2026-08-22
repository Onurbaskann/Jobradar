from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField
from sqlmodel import Session, col, select

from app.db import get_session
from app.discovery.service import create_run, execute_discovery_run
from app.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    JobLead,
    JobLeadStatus,
    RemoteType,
    SearchProfile,
    utcnow,
)

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]
LeadLimit = Annotated[int, Query(ge=1, le=200)]


class ProfileCreate(BaseModel):
    name: str = PydanticField(min_length=2, max_length=80)
    query: str = PydanticField(min_length=2, max_length=200)
    location: str = PydanticField(default="Türkiye", min_length=2, max_length=100)
    remote_only: bool = False
    hours_old: int = PydanticField(default=168, ge=1, le=24 * 30)
    results_wanted: int = PydanticField(default=30, ge=1, le=100)
    sources: list[str] = PydanticField(default_factory=lambda: ["tracked", "jobspy"])


class ProfileView(ProfileCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    active: bool
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    profile_id: int


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_id: int
    status: DiscoveryRunStatus
    found_count: int
    new_count: int
    source_results: dict[str, object]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class LeadView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    company_name: str
    location: str | None
    remote_type: RemoteType
    description_md: str
    apply_url: str | None
    posted_at: datetime | None
    sources: list[str]
    status: JobLeadStatus
    first_seen_at: datetime
    last_seen_at: datetime


class LeadStatusUpdate(BaseModel):
    status: JobLeadStatus


@router.get("/discovery/profiles", response_model=list[ProfileView])
def list_profiles(session: SessionDep) -> list[SearchProfile]:
    return list(
        session.exec(
            select(SearchProfile)
            .where(SearchProfile.active.is_(True))  # type: ignore[union-attr]
            .order_by(col(SearchProfile.created_at))
        ).all()
    )


@router.post("/discovery/profiles", response_model=ProfileView, status_code=201)
def add_profile(payload: ProfileCreate, session: SessionDep) -> SearchProfile:
    existing = session.exec(select(SearchProfile).where(SearchProfile.name == payload.name)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Bu isimde bir arama profili zaten var")
    profile = SearchProfile(**payload.model_dump())
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


@router.post("/discovery/runs", response_model=RunView, status_code=202)
def start_run(
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    session: SessionDep,
) -> DiscoveryRun:
    try:
        run = create_run(session, payload.profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(execute_discovery_run, run.id)
    return run


@router.get("/discovery/runs/latest", response_model=RunView | None)
def latest_run(
    session: SessionDep, profile_id: int | None = None
) -> DiscoveryRun | None:
    query = select(DiscoveryRun)
    if profile_id is not None:
        query = query.where(DiscoveryRun.profile_id == profile_id)
    return session.exec(query.order_by(col(DiscoveryRun.created_at).desc())).first()


@router.get("/discovery/runs/{run_id}", response_model=RunView)
def get_run(run_id: int, session: SessionDep) -> DiscoveryRun:
    run = session.get(DiscoveryRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Keşif çalışması bulunamadı")
    return run


@router.get("/jobs/leads", response_model=list[LeadView])
def list_leads(
    session: SessionDep,
    status: JobLeadStatus | None = None,
    limit: LeadLimit = 50,
) -> list[JobLead]:
    query = select(JobLead)
    if status is not None:
        query = query.where(JobLead.status == status)
    return list(
        session.exec(query.order_by(col(JobLead.first_seen_at).desc()).limit(limit)).all()
    )


@router.patch("/jobs/leads/{lead_id}", response_model=LeadView)
def update_lead_status(
    lead_id: int,
    payload: LeadStatusUpdate,
    session: SessionDep,
) -> JobLead:
    lead = session.get(JobLead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="İlan bulunamadı")
    lead.status = payload.status
    lead.last_seen_at = utcnow()
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return lead
