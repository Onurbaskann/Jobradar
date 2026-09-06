from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session

from app.agents.client import AgentError
from app.db import get_session
from app.matching.service import MatchInputError, list_profile_matches, score_lead
from app.models import LeadMatch

router = APIRouter(prefix="/api/jobs/leads", tags=["matching"])
SessionDep = Annotated[Session, Depends(get_session)]


class LeadMatchView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_id: int
    profile_id: int
    score: int
    rationale: str
    gaps: list[str]
    model: str
    updated_at: datetime


@router.get("/matches", response_model=list[LeadMatchView])
def get_lead_matches(session: SessionDep) -> list[LeadMatch]:
    return list_profile_matches(session)


@router.post("/{lead_id}/score", response_model=LeadMatchView)
def create_lead_score(lead_id: int, session: SessionDep) -> LeadMatch:
    try:
        return score_lead(session, lead_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MatchInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="Yerel değerlendirme modeli şu anda kullanılamıyor",
        ) from exc
