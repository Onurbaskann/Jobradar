from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlmodel import Session, delete, select

from app.models import LeadMatch, Profile, utcnow

MAX_CV_BYTES = 5 * 1024 * 1024
MAX_CV_TEXT_CHARS = 200_000
SUPPORTED_CV_EXTENSIONS = {".docx", ".pdf", ".txt"}


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


def save_candidate_profile(
    session: Session,
    *,
    name: str,
    filename: str,
    content: bytes,
    upload_dir: Path,
) -> Profile:
    clean_name = name.strip()
    if len(clean_name) < 2:
        raise CvValidationError("Aday adı en az 2 karakter olmalı")
    cv_text, extension = extract_cv_text(filename, content)
    profile = session.exec(select(Profile).order_by(Profile.id)).first()
    if profile is None:
        profile = Profile(name=name)

    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / f"candidate-cv{extension}"
    target.write_bytes(content)

    profile.name = clean_name
    profile.cv_file_path = str(target)
    profile.cv_text = cv_text
    profile.cv_summary = ""
    profile.embedding = None
    profile.updated_at = utcnow()
    session.add(profile)
    if profile.id is not None:
        session.exec(delete(LeadMatch).where(LeadMatch.profile_id == profile.id))
    session.commit()
    session.refresh(profile)
    return profile
