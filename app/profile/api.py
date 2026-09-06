from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.db import get_session
from app.models import Profile
from app.profile.service import MAX_CV_BYTES, CvValidationError, save_candidate_profile

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]
CandidateName = Annotated[str, Form(min_length=2, max_length=100)]
CandidateCv = Annotated[UploadFile, File()]


class CandidateProfileView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filename: str
    text_length: int
    updated_at: datetime


def _profile_view(profile: Profile) -> CandidateProfileView:
    return CandidateProfileView(
        id=profile.id,
        name=profile.name,
        filename=Path(profile.cv_file_path or "").name,
        text_length=len(profile.cv_text),
        updated_at=profile.updated_at,
    )


@router.get("/profile", response_model=CandidateProfileView | None)
def get_candidate_profile(session: SessionDep) -> CandidateProfileView | None:
    profile = session.exec(select(Profile).order_by(Profile.id)).first()
    if profile is None or not profile.cv_file_path or not profile.cv_text:
        return None
    return _profile_view(profile)


@router.put("/profile", response_model=CandidateProfileView)
async def upload_candidate_profile(
    session: SessionDep,
    name: CandidateName,
    file: CandidateCv,
) -> CandidateProfileView:
    content = await file.read(MAX_CV_BYTES + 1)
    try:
        profile = save_candidate_profile(
            session,
            name=name,
            filename=file.filename or "",
            content=content,
            upload_dir=Path("data/cv"),
        )
    except CvValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _profile_view(profile)
