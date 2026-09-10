from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.agents.client import AgentError
from app.applications import api
from app.applications.service import (
    ApplicationDraftOutput,
    ApplicationInputError,
    approve_application,
    build_application_prompt,
    prepare_application,
    update_application,
)
from app.models import (
    Application,
    ApplicationStatus,
    JobLead,
    JobLeadStatus,
    LeadMatch,
    Profile,
)


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value


class _Session:
    def __init__(self, *, application: Application | None = None, shortlisted: bool = True):
        self.profile = Profile(id=1, name="Onur", cv_text="C# ve .NET deneyimi")
        self.lead = JobLead(
            id=2,
            fingerprint="lead-2",
            title="Backend Developer",
            company_name="Örnek AŞ",
            description_md="C# ve .NET ile servis geliştirecek takım arkadaşı arıyoruz. " * 2,
            apply_url="https://example.com/apply",
            status=JobLeadStatus.SHORTLISTED if shortlisted else JobLeadStatus.NEW,
        )
        self.match = LeadMatch(
            id=3,
            lead_id=2,
            profile_id=1,
            score=91,
            rationale="Güçlü teknik uyum",
            gaps=["Azure"],
            model="yerel/qwen3:8b",
        )
        self.application = application
        if application is not None:
            self.match.updated_at = application.created_at
        self.added = None

    def get(self, model, ident):
        values = {
            LeadMatch: self.match,
            JobLead: self.lead,
            Profile: self.profile,
            Application: self.application,
        }
        value = values[model]
        if value is None or value.id != ident:
            return None
        return value

    def exec(self, _query):
        return _Result(self.application)

    def add(self, value):
        self.added = value
        if isinstance(value, Application):
            self.application = value

    def commit(self):
        pass

    def refresh(self, value):
        if value.id is None:
            value.id = 7


def _draft() -> ApplicationDraftOutput:
    return ApplicationDraftOutput(
        cover_letter="Örnek AŞ ekibine katkı sunmak istiyorum.",
        email_subject="Backend Developer başvurusu",
        email_body="Merhaba, özgeçmişimi değerlendirmenize sunuyorum.",
    )


def _application() -> Application:
    return Application(
        id=7,
        lead_match_id=3,
        job_title="Backend Developer",
        company_name="Örnek AŞ",
        cover_letter="Ön yazı",
        email_subject="Konu",
        email_body="Mesaj",
    )


def test_application_prompt_contains_cv_job_and_match_evidence() -> None:
    session = _Session()

    prompt = build_application_prompt(session.profile, session.lead, session.match)

    assert "C# ve .NET deneyimi" in prompt
    assert "Backend Developer" in prompt
    assert "Puan: 91/100" in prompt
    assert "Eksikler: Azure" in prompt


def test_prepares_and_persists_draft(monkeypatch) -> None:
    session = _Session()
    monkeypatch.setattr(
        "app.applications.service.call_structured",
        lambda **_kwargs: SimpleNamespace(data=_draft()),
    )

    application = prepare_application(session, 3)  # type: ignore[arg-type]

    assert application.id == 7
    assert application.lead_match_id == 3
    assert application.status is ApplicationStatus.DRAFT
    assert application.channel.value == "external"
    assert application.job_title == "Backend Developer"
    assert application.company_name == "Örnek AŞ"
    assert application.email_subject == "Backend Developer başvurusu"
    assert session.added is application


def test_requires_shortlisted_lead() -> None:
    session = _Session(shortlisted=False)

    with pytest.raises(ApplicationInputError, match="kısa listeye"):
        prepare_application(session, 3)  # type: ignore[arg-type]


def test_editing_approved_application_returns_it_to_draft() -> None:
    application = _application()
    application.status = ApplicationStatus.APPROVED
    session = _Session(application=application)

    updated = update_application(
        session,  # type: ignore[arg-type]
        7,
        cover_letter="Yeni ön yazı",
        email_subject="Yeni konu",
        email_body="Yeni mesaj",
    )

    assert updated.status is ApplicationStatus.DRAFT
    assert updated.cover_letter == "Yeni ön yazı"


def test_approves_complete_draft() -> None:
    session = _Session(application=_application())

    approved = approve_application(session, 7)  # type: ignore[arg-type]

    assert approved.status is ApplicationStatus.APPROVED


def test_rejects_approval_when_match_is_newer_than_draft() -> None:
    application = _application()
    session = _Session(application=application)
    session.match.updated_at = application.created_at + timedelta(seconds=1)

    with pytest.raises(ApplicationInputError, match="yeniden hazırlanmalı"):
        approve_application(session, 7)  # type: ignore[arg-type]


def test_rejects_approval_when_match_was_removed() -> None:
    application = _application()
    application.lead_match_id = None
    session = _Session(application=application)

    with pytest.raises(ApplicationInputError, match="yeniden hazırlanmalı"):
        approve_application(session, 7)  # type: ignore[arg-type]


def test_rejects_blank_application_update() -> None:
    session = _Session(application=_application())

    with pytest.raises(ApplicationInputError, match="boş bırakılamaz"):
        update_application(
            session,  # type: ignore[arg-type]
            7,
            cover_letter=" ",
            email_subject="Konu",
            email_body="Mesaj",
        )


def test_application_api_hides_provider_details(monkeypatch) -> None:
    def fail(_session, _lead_match_id):
        raise AgentError("sağlayıcı ayrıntısı")

    monkeypatch.setattr(api, "prepare_application", fail)

    with pytest.raises(HTTPException) as error:
        api.create_application(3, object())  # type: ignore[arg-type]

    assert error.value.status_code == 503
    assert error.value.detail == "Yerel başvuru modeli şu anda kullanılamıyor"
