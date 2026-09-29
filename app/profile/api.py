from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlmodel import Session, select

from app.db import get_session
from app.models import Profile, Resume, ResumeAssessment, ResumeProcessingStatus
from app.profile.service import (
    MAX_CV_BYTES,
    CvValidationError,
    get_current_resume,
    save_candidate_profile,
)

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
    resume_id: int
    version: int
    processing_status: ResumeProcessingStatus
    processing_error: str | None
    ats_score: int | None
    ats_metrics: dict[str, int]
    ats_findings: list[str]
    updated_at: datetime


def _profile_view(
    profile: Profile,
    resume: Resume,
    assessment: ResumeAssessment | None,
) -> CandidateProfileView:
    completed_assessment = (
        assessment if resume.status == ResumeProcessingStatus.COMPLETED else None
    )
    return CandidateProfileView(
        id=profile.id,
        name=profile.name,
        filename=resume.original_filename or Path(resume.file_path).name,
        text_length=len(resume.extracted_text),
        resume_id=resume.id,
        version=resume.version,
        processing_status=resume.status,
        processing_error=resume.processing_error,
        ats_score=completed_assessment.overall_score if completed_assessment else None,
        ats_metrics=(
            {
                "Okunabilirlik": completed_assessment.parsing_score,
                "İletişim": completed_assessment.contact_score,
                "Bölümler": completed_assessment.section_score,
                "Tarih düzeni": completed_assessment.chronology_score,
                "Beceri kanıtı": completed_assessment.evidence_score,
                "Tutarlılık": completed_assessment.consistency_score,
            }
            if completed_assessment
            else {}
        ),
        ats_findings=completed_assessment.findings if completed_assessment else [],
        updated_at=profile.updated_at,
    )


def _assessment(session: Session, resume: Resume) -> ResumeAssessment | None:
    return session.exec(
        select(ResumeAssessment).where(ResumeAssessment.resume_id == resume.id)
    ).first()


@router.get("/profile", response_model=CandidateProfileView | None)
def get_candidate_profile(session: SessionDep) -> CandidateProfileView | None:
    profile = session.exec(select(Profile).order_by(Profile.id)).first()
    if profile is None or profile.id is None:
        return None
    resume = get_current_resume(session, profile.id)
    if resume is None:
        return None
    return _profile_view(profile, resume, _assessment(session, resume))


@router.get("/profile/cv", response_class=FileResponse)
def download_candidate_cv(session: SessionDep) -> FileResponse:
    profile = session.exec(select(Profile).order_by(Profile.id)).first()
    if profile is None or profile.id is None:
        raise HTTPException(status_code=404, detail="Yüklü CV bulunamadı")
    resume = get_current_resume(session, profile.id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Yüklü CV bulunamadı")
    path = Path(resume.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="CV dosyası diskte bulunamadı")
    return FileResponse(
        path,
        filename=resume.original_filename or path.name,
        media_type=resume.mime_type,
    )


@router.put("/profile", response_model=CandidateProfileView)
async def upload_candidate_profile(
    session: SessionDep,
    name: CandidateName,
    file: CandidateCv,
) -> CandidateProfileView:
    content = await file.read(MAX_CV_BYTES + 1)
    try:
        profile, resume = save_candidate_profile(
            session,
            name=name,
            filename=file.filename or "",
            content=content,
            upload_dir=Path("data/cv"),
        )
    except CvValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _profile_view(profile, resume, _assessment(session, resume))
