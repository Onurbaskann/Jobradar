from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.agents.client import AgentError
from app.applications.gmail import GmailDraftGateway, GmailError
from app.applications.service import (
    ApplicationInputError,
    approve_application,
    create_gmail_draft,
    list_applications,
    prepare_application,
    update_application,
)
from app.config import get_settings
from app.db import get_session
from app.models import Application, ApplicationStatus, ApplyChannel

router = APIRouter(prefix="/api/applications", tags=["applications"])
logger = logging.getLogger(__name__)
SessionDep = Annotated[Session, Depends(get_session)]


class ApplicationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lead_match_id: int | None
    job_title: str
    company_name: str
    cover_letter: str
    recipient_email: str
    email_subject: str
    email_body: str
    channel: ApplyChannel
    status: ApplicationStatus
    gmail_draft_id: str | None
    gmail_thread_id: str | None
    created_at: datetime


class ApplicationUpdate(BaseModel):
    cover_letter: str = Field(min_length=1, max_length=5_000)
    recipient_email: str = Field(default="", max_length=320)
    email_subject: str = Field(min_length=1, max_length=200)
    email_body: str = Field(min_length=1, max_length=3_000)


@router.get("", response_model=list[ApplicationView])
def get_applications(session: SessionDep) -> list[Application]:
    return list_applications(session)


@router.post("/from-match/{lead_match_id}", response_model=ApplicationView)
def create_application(lead_match_id: int, session: SessionDep) -> Application:
    try:
        return prepare_application(session, lead_match_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(
            status_code=503,
            detail="Yerel başvuru modeli şu anda kullanılamıyor",
        ) from exc


@router.put("/{application_id}", response_model=ApplicationView)
def edit_application(
    application_id: int,
    payload: ApplicationUpdate,
    session: SessionDep,
) -> Application:
    try:
        return update_application(session, application_id, **payload.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{application_id}/approve", response_model=ApplicationView)
def approve_application_draft(application_id: int, session: SessionDep) -> Application:
    try:
        return approve_application(session, application_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class GmailConnectionView(BaseModel):
    configured: bool
    connected: bool


@router.get("/gmail/status", response_model=GmailConnectionView)
def get_gmail_status() -> GmailConnectionView:
    connection = GmailDraftGateway(get_settings()).connection()
    return GmailConnectionView(
        configured=connection.configured,
        connected=connection.connected,
    )


@router.get("/gmail/authorize")
def authorize_gmail() -> RedirectResponse:
    try:
        return RedirectResponse(GmailDraftGateway(get_settings()).authorization_url())
    except GmailError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/gmail/callback", include_in_schema=False)
def gmail_callback(
    state: str = "",
    code: str = "",
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse("/?gmail=denied#applications")
    try:
        GmailDraftGateway(get_settings()).complete_authorization(code, state)
    except GmailError:
        logger.exception("Gmail OAuth callback failed")
        return RedirectResponse("/?gmail=error#applications")
    return RedirectResponse("/?gmail=connected#applications")


@router.post("/{application_id}/gmail-draft", response_model=ApplicationView)
def create_application_gmail_draft(
    application_id: int,
    session: SessionDep,
) -> Application:
    try:
        return create_gmail_draft(
            session,
            application_id,
            GmailDraftGateway(get_settings()),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplicationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GmailError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
