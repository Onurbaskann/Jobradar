from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from app.models import Profile, Resume, ResumeAssessment
from app.profile.api import _profile_view, download_candidate_cv
from app.profile.service import (
    MAX_CV_BYTES,
    CvValidationError,
    _format_period,
    extract_cv_text,
    save_candidate_profile,
)


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value

    def one(self):
        return self.value


class _Session:
    def __init__(self, profile=None, resume=None):
        self.existing_profile = profile
        self.resume = resume
        self.exec_count = 0

    def exec(self, _query):
        self.exec_count += 1
        values = [self.existing_profile, self.resume, 0]
        return _Result(values[self.exec_count - 1] if self.exec_count <= len(values) else None)

    def add(self, profile) -> None:
        self.profile = profile

    def commit(self) -> None:
        pass

    def flush(self) -> None:
        if getattr(self, "profile", None) is not None:
            self.profile.id = 1

    def refresh(self, profile) -> None:
        if profile.id is None:
            profile.id = 1


def test_extracts_utf8_text_cv() -> None:
    text, extension = extract_cv_text("özgeçmiş.TXT", b"Python\n\n.NET")

    assert text == "Python\n.NET"
    assert extension == ".txt"


def test_formats_partial_resume_dates_without_inventing_days() -> None:
    assert _format_period(2021, 12, 2024, 10) == "12/2021 - 10/2024"
    assert _format_period(2024, 11, None, None, current=True) == "11/2024 - günümüz"


def test_completed_database_status_exposes_ats_assessment() -> None:
    profile = Profile(id=1, name="Onur")
    resume = Resume(
        id=2,
        profile_id=1,
        version=1,
        original_filename="cv.txt",
        file_path="data/cv.txt",
        mime_type="text/plain",
        extracted_text="Backend developer",
        status="completed",  # type: ignore[arg-type] -- DB sürücüsünün döndürdüğü biçim
    )
    assessment = ResumeAssessment(
        resume_id=2,
        overall_score=92,
        parsing_score=30,
        contact_score=10,
        section_score=20,
        chronology_score=12,
        evidence_score=15,
        consistency_score=5,
    )

    view = _profile_view(profile, resume, assessment)

    assert view.ats_score == 92
    assert view.ats_metrics["Okunabilirlik"] == 30


def test_extracts_docx_cv() -> None:
    output = BytesIO()
    document = Document()
    document.add_paragraph("Onur Başkan")
    document.add_paragraph("Backend Developer")
    document.save(output)

    text, extension = extract_cv_text("cv.docx", output.getvalue())

    assert text == "Onur Başkan\nBackend Developer"
    assert extension == ".docx"


@pytest.mark.parametrize("filename", ["cv.exe", "cv.doc", "cv.jpg"])
def test_rejects_unsupported_cv_types(filename: str) -> None:
    with pytest.raises(CvValidationError, match="PDF, DOCX veya TXT"):
        extract_cv_text(filename, b"content")


def test_rejects_oversized_cv() -> None:
    with pytest.raises(CvValidationError, match="en fazla 5 MB"):
        extract_cv_text("cv.txt", b"x" * (MAX_CV_BYTES + 1))


def test_rejects_empty_extracted_text() -> None:
    with pytest.raises(CvValidationError, match="okunabilir metin"):
        extract_cv_text("cv.txt", b"  \n")


def test_saves_normalized_profile_and_local_file(tmp_path) -> None:
    session = _Session()

    profile, resume = save_candidate_profile(
        session,  # type: ignore[arg-type]
        name="  Onur Başkan  ",
        filename="onur.txt",
        content=b"Python\n\nFastAPI",
        upload_dir=tmp_path,
    )

    assert profile.id == 1
    assert profile.name == "Onur Başkan"
    assert resume.extracted_text == "Python\nFastAPI"
    assert resume.original_filename == "onur.txt"
    assert resume.version == 1
    assert (tmp_path / "profile-1" / "resume-v1.txt").read_bytes() == b"Python\n\nFastAPI"


def test_keeps_only_the_uploaded_cv_basename(tmp_path) -> None:
    profile, resume = save_candidate_profile(
        _Session(),  # type: ignore[arg-type]
        name="Onur",
        filename="C:\\fakepath\\ozgecmis.txt",
        content=b"Backend developer",
        upload_dir=tmp_path,
    )

    assert resume.original_filename == "ozgecmis.txt"


def test_downloads_the_saved_cv_with_its_original_name(tmp_path) -> None:
    cv_path = tmp_path / "candidate-cv.txt"
    cv_path.write_text("Backend developer", encoding="utf-8")
    profile = Profile(
        id=1,
        name="Onur",
        cv_text="Backend developer",
        cv_file_path=str(cv_path),
        cv_original_filename="Onur-Baskan-CV.txt",
    )

    resume = Resume(
        id=2,
        profile_id=1,
        version=1,
        original_filename="Onur-Baskan-CV.txt",
        file_path=str(cv_path),
        mime_type="text/plain",
        extracted_text="Backend developer",
    )
    response = download_candidate_cv(_Session(profile, resume))  # type: ignore[arg-type]

    assert Path(response.path) == cv_path
    assert "Onur-Baskan-CV.txt" in response.headers["content-disposition"]


def test_rejects_blank_candidate_name(tmp_path) -> None:
    with pytest.raises(CvValidationError, match="en az 2 karakter"):
        save_candidate_profile(
            _Session(),  # type: ignore[arg-type]
            name="  ",
            filename="cv.txt",
            content=b"Python",
            upload_dir=tmp_path,
        )


def test_uploading_new_cv_creates_a_new_resume_version(tmp_path) -> None:
    profile = Profile(
        id=1,
        name="Onur",
        cv_text="Eski CV",
        cv_file_path="data/cv/old.txt",
    )
    previous = Resume(
        id=4,
        profile_id=1,
        version=1,
        original_filename="old.txt",
        file_path="data/cv/old.txt",
        mime_type="text/plain",
        extracted_text="Eski CV",
        sha256="different",
    )
    session = _Session(profile, None)
    session.exec = lambda _query: next(  # type: ignore[method-assign]
        session.results
    )
    session.results = iter([_Result(profile), _Result(None), _Result(previous.version)])

    _, resume = save_candidate_profile(
        session,  # type: ignore[arg-type]
        name="Onur",
        filename="new.txt",
        content=b"Yeni CV metni",
        upload_dir=tmp_path,
    )

    assert resume.version == 2
