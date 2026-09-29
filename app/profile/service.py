from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import (
    Profile,
    Resume,
    ResumeCertification,
    ResumeEducation,
    ResumeExperience,
    ResumeLanguage,
    ResumeProject,
    ResumeSkill,
    utcnow,
)

MAX_CV_BYTES = 5 * 1024 * 1024
MAX_CV_TEXT_CHARS = 200_000
SUPPORTED_CV_EXTENSIONS = {".docx", ".pdf", ".txt"}
MIME_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}


class CvValidationError(ValueError):
    """Yüklenen dosya güvenli biçimde işlenemediğinde oluşur."""


def extract_cv_text(filename: str, content: bytes) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_CV_EXTENSIONS:
        raise CvValidationError("CV dosyası PDF, DOCX veya TXT olmalı")
    if not content:
        raise CvValidationError("CV dosyası boş")
    if len(content) > MAX_CV_BYTES:
        raise CvValidationError("CV dosyası en fazla 5 MB olabilir")

    try:
        if extension == ".pdf":
            pages = PdfReader(BytesIO(content)).pages
            text = "\n".join(page.extract_text() or "" for page in pages)
        elif extension == ".docx":
            document = Document(BytesIO(content))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        else:
            text = content.decode("utf-8-sig")
    except (
        BadZipFile,
        OSError,
        PackageNotFoundError,
        PdfReadError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise CvValidationError("CV dosyası okunamadı veya bozuk") from exc

    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if not normalized:
        raise CvValidationError("CV dosyasından okunabilir metin çıkarılamadı")
    return normalized[:MAX_CV_TEXT_CHARS], extension


def get_current_resume(session: Session, profile_id: int | None = None) -> Resume | None:
    query = select(Resume)
    if profile_id is not None:
        query = query.where(Resume.profile_id == profile_id)
    return session.exec(
        query.order_by(col(Resume.version).desc(), col(Resume.uploaded_at).desc())
    ).first()


def save_candidate_profile(
    session: Session,
    *,
    name: str,
    filename: str,
    content: bytes,
    upload_dir: Path,
) -> tuple[Profile, Resume]:
    clean_name = name.strip()
    if len(clean_name) < 2:
        raise CvValidationError("Aday adı en az 2 karakter olmalı")
    cv_text, extension = extract_cv_text(filename, content)
    original_filename = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    content_hash = sha256(content).hexdigest()

    profile = session.exec(select(Profile).order_by(Profile.id)).first()
    if profile is None:
        profile = Profile(name=clean_name)
        session.add(profile)
        session.flush()
    profile.name = clean_name

    existing = session.exec(
        select(Resume).where(
            Resume.profile_id == profile.id,
            Resume.sha256 == content_hash,
        )
    ).first()
    if existing is not None:
        profile.updated_at = utcnow()
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile, existing

    latest_version = session.exec(
        select(func.max(Resume.version)).where(Resume.profile_id == profile.id)
    ).one()
    version = int(latest_version or 0) + 1
    profile_dir = upload_dir / f"profile-{profile.id}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    target = profile_dir / f"resume-v{version}{extension}"
    target.write_bytes(content)

    resume = Resume(
        profile_id=profile.id,
        version=version,
        original_filename=original_filename[:255] or f"candidate-cv{extension}",
        file_path=str(target),
        sha256=content_hash,
        mime_type=MIME_TYPES[extension],
        extracted_text=cv_text,
    )
    session.add(resume)

    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    session.refresh(resume)
    return profile, resume


def build_resume_context(session: Session, resume: Resume) -> str:
    """Eşleştirme ve başvuru için DB'deki doğrulanabilir CV bilgisini üretir."""
    experiences = session.exec(
        select(ResumeExperience)
        .where(ResumeExperience.resume_id == resume.id)
        .order_by(col(ResumeExperience.display_order))
    ).all()
    education = session.exec(
        select(ResumeEducation)
        .where(ResumeEducation.resume_id == resume.id)
        .order_by(col(ResumeEducation.display_order))
    ).all()
    projects = session.exec(
        select(ResumeProject)
        .where(ResumeProject.resume_id == resume.id)
        .order_by(col(ResumeProject.display_order))
    ).all()
    skills = session.exec(
        select(ResumeSkill).where(ResumeSkill.resume_id == resume.id)
    ).all()
    certifications = session.exec(
        select(ResumeCertification)
        .where(ResumeCertification.resume_id == resume.id)
        .order_by(col(ResumeCertification.display_order))
    ).all()
    languages = session.exec(
        select(ResumeLanguage).where(ResumeLanguage.resume_id == resume.id)
    ).all()

    if not any((experiences, education, projects, skills, certifications, languages)):
        return resume.extracted_text

    lines = [f"Özet: {resume.summary}" if resume.summary else ""]
    if resume.location:
        lines.append(f"Konum: {resume.location}")
    if skills:
        lines.append("Beceriler: " + ", ".join(skill.name for skill in skills))
    for item in experiences:
        period = _format_period(
            item.start_year,
            item.start_month,
            item.end_year,
            item.end_month,
            current=item.is_current,
        )
        lines.append(
            f"Deneyim: {item.title} - {item.employer} ({period}). {item.description}"
        )
    for item in education:
        period = _format_period(
            item.start_year,
            item.start_month,
            item.end_year,
            item.end_month,
        )
        lines.append(
            f"Eğitim: {item.institution}, {item.degree or ''} {item.field_of_study or ''} "
            f"({period}). "
            f"{item.description}"
        )
    for item in projects:
        lines.append(f"Proje: {item.name}. {item.description}")
    if certifications:
        lines.append(
            "Sertifikalar: " + ", ".join(item.name for item in certifications)
        )
    if languages:
        lines.append(
            "Diller: "
            + ", ".join(
                f"{item.name} ({item.level})" if item.level else item.name
                for item in languages
            )
        )
    return "\n".join(line.strip() for line in lines if line.strip())


def _format_period(
    start_year: int | None,
    start_month: int | None,
    end_year: int | None,
    end_month: int | None,
    *,
    current: bool = False,
) -> str:
    def part(year: int | None, month: int | None) -> str:
        if year is None:
            return "belirtilmemiş"
        return f"{month:02d}/{year}" if month else str(year)

    end = "günümüz" if current else part(end_year, end_month)
    return f"{part(start_year, start_month)} - {end}"
