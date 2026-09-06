from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.agents.client import AgentError
from app.matching import api
from app.matching.service import (
    MAX_MATCH_TEXT_CHARS,
    LeadScoreOutput,
    MatchInputError,
    build_match_prompt,
    score_lead,
)
from app.models import JobLead, LeadMatch, Profile


class _Result:
    def __init__(self, value=None):
        self.value = value

    def first(self):
        return self.value


class _Session:
    def __init__(self, profile: Profile | None, lead: JobLead | None, match=None):
        self.profile = profile
        self.lead = lead
        self.match = match
        self.exec_count = 0
        self.added = None

    def exec(self, _query):
        self.exec_count += 1
        return _Result(self.profile if self.exec_count == 1 else self.match)

    def get(self, _model, _ident):
        return self.lead

    def add(self, value):
        self.added = value

    def commit(self):
        pass

    def refresh(self, value):
        if value.id is None:
            value.id = 9


def _profile() -> Profile:
    return Profile(id=1, name="Onur", cv_text="Python ve FastAPI deneyimi")


def _lead() -> JobLead:
    return JobLead(
        id=2,
        fingerprint="lead-2",
        title="Backend Developer",
        company_name="Örnek AŞ",
        description_md="Python ve FastAPI bilen, PostgreSQL deneyimli ekip arkadaşı arıyoruz. " * 2,
    )


def test_build_match_prompt_limits_untrusted_text() -> None:
    profile = _profile()
    profile.cv_text = "x" * (MAX_MATCH_TEXT_CHARS + 20)

    prompt = build_match_prompt(profile, _lead())

    assert "ADAY CV'Sİ" in prompt
    assert "Backend Developer" in prompt
    assert "x" * (MAX_MATCH_TEXT_CHARS + 1) not in prompt


def test_scores_and_persists_a_lead(monkeypatch) -> None:
    session = _Session(_profile(), _lead())
    output = LeadScoreOutput(score=78, rationale="Güçlü teknik uyum.", gaps=["Docker"])
    monkeypatch.setattr(
        "app.matching.service.call_structured",
        lambda **_kwargs: SimpleNamespace(data=output),
    )

    match = score_lead(session, 2)  # type: ignore[arg-type]

    assert match.id == 9
    assert match.lead_id == 2
    assert match.profile_id == 1
    assert match.score == 78
    assert match.gaps == ["Docker"]
    assert match.model == "yerel/qwen3:8b"
    assert session.added is match


def test_updates_existing_score(monkeypatch) -> None:
    existing = LeadMatch(
        id=4,
        lead_id=2,
        profile_id=1,
        score=40,
        rationale="Eski sonuç",
        model="yerel/qwen3:8b",
    )
    session = _Session(_profile(), _lead(), existing)
    output = LeadScoreOutput(score=84, rationale="Güncel sonuç", gaps=[])
    monkeypatch.setattr(
        "app.matching.service.call_structured",
        lambda **_kwargs: SimpleNamespace(data=output),
    )

    match = score_lead(session, 2)  # type: ignore[arg-type]

    assert match is existing
    assert match.score == 84
    assert match.rationale == "Güncel sonuç"


def test_requires_a_cv_profile() -> None:
    with pytest.raises(MatchInputError, match="CV profilini"):
        score_lead(_Session(None, _lead()), 2)  # type: ignore[arg-type]


def test_requires_a_useful_job_description() -> None:
    lead = _lead()
    lead.description_md = "Kısa açıklama"
    with pytest.raises(MatchInputError, match="yeterli açıklaması"):
        score_lead(_Session(_profile(), lead), 2)  # type: ignore[arg-type]


def test_matching_api_hides_provider_details(monkeypatch) -> None:
    def fail(_session, _lead_id):
        raise AgentError("gizli sağlayıcı ayrıntısı")

    monkeypatch.setattr(api, "score_lead", fail)

    with pytest.raises(HTTPException) as error:
        api.create_lead_score(2, object())  # type: ignore[arg-type]

    assert error.value.status_code == 503
    assert error.value.detail == "Yerel değerlendirme modeli şu anda kullanılamıyor"
