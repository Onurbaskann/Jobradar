"""Ajan katmanı testleri — Anthropic API'ye çıkmadan.

Burada test edilen şey modelin zekâsı değil, *bizim* kodumuz: budama, şema
eşleme ve en önemlisi **doğrulama**. Ajanın önerisi doğrulanmadan kabul
edilirse, L1 slug tahmininde ölçtüğümüz yanlış-pozitif sorunu bu kez modelin
uydurması olarak geri gelir.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.base import RawJob
from app.agents import detect_ats as detect_mod
from app.agents import extract_jobs as extract_mod
from app.agents.client import AgentError, AgentResult
from app.agents.detect_ats import AtsDetection, detect_ats
from app.agents.extract_jobs import ExtractedJob, ExtractionResult, extract_jobs, prune_html
from app.models import AdapterType, ApplyChannel, RemoteType
from app.net import HttpClient

CAREERS_HTML = """
<html><body>
<nav><a href="/hakkimizda">Hakkımızda</a></nav>
<main>
  <h1>Açık Pozisyonlar</h1>
  <p>Ekibimize katılmak ister misin? Aşağıdaki pozisyonlara başvurabilirsin.
     Sorularınız için bize ulaşın, birlikte çalışmayı çok isteriz.</p>
  <ul>
    <li><a href="/kariyer/backend">Backend Geliştirici</a> — İstanbul</li>
    <li><a href="/kariyer/veri">Veri Analisti</a> — Uzaktan</li>
  </ul>
  <p>Başvuru için ik@acme.com adresine yazabilirsiniz. Tüm başvurular
     değerlendirilecektir ve size geri dönüş yapılacaktır.</p>
</main>
<script>var x = 1;</script>
</body></html>
"""


@pytest.fixture
def http() -> HttpClient:
    return HttpClient(domain_delay=0.0, max_retries=0, respect_robots=False)


def _result(data):
    return AgentResult(data=data, input_tokens=100, output_tokens=50, cache_read_tokens=0)


# --------------------------------------------------------------------- budama


def test_prune_html_strips_markup_and_scripts() -> None:
    text = prune_html(CAREERS_HTML, url="https://acme.com/kariyer")
    assert "<script>" not in text
    assert "var x = 1" not in text
    assert "Backend Geliştirici" in text


def test_prune_html_respects_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Devasa bir sayfa token bütçesini patlatmamalı."""
    monkeypatch.setattr(extract_mod, "MAX_INPUT_CHARS", 200)
    huge = "<html><body>" + "<p>ilan metni burada</p>" * 5000 + "</body></html>"
    assert len(prune_html(huge, url="https://acme.com/kariyer")) <= 200


# --------------------------------------------------------------------- çıkarım


def test_extract_jobs_maps_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = ExtractionResult(
        is_listing_page=True,
        jobs=[
            ExtractedJob(
                title="Backend Geliştirici",
                location="İstanbul",
                remote_type="onsite",
                apply_url="https://acme.com/kariyer/backend",
            ),
            ExtractedJob(
                title="Veri Analisti",
                remote_type="remote",
                apply_email="ik@acme.com",
            ),
        ],
    )
    monkeypatch.setattr(extract_mod, "call_structured", lambda **_: _result(payload))

    jobs = extract_jobs(CAREERS_HTML, url="https://acme.com/kariyer", company_name="Acme")

    assert [j.title for j in jobs] == ["Backend Geliştirici", "Veri Analisti"]
    assert jobs[0].remote_type is RemoteType.ONSITE
    assert jobs[0].apply_channel is ApplyChannel.ATS_FORM
    assert jobs[1].remote_type is RemoteType.REMOTE
    assert jobs[1].apply_channel is ApplyChannel.EMAIL
    assert jobs[1].apply_email == "ik@acme.com"


def test_extract_jobs_ids_are_stable_and_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kimlik kararlı olmalı; yoksa her tarama aynı ilanı yeniden yaratır."""
    payload = ExtractionResult(
        is_listing_page=True,
        jobs=[
            ExtractedJob(title="Backend", apply_url="https://acme.com/kariyer/backend"),
            ExtractedJob(title="Frontend", apply_url="https://acme.com/kariyer/frontend"),
        ],
    )
    monkeypatch.setattr(extract_mod, "call_structured", lambda **_: _result(payload))

    first = extract_jobs(CAREERS_HTML, url="https://acme.com/kariyer", company_name="Acme")
    second = extract_jobs(CAREERS_HTML, url="https://acme.com/kariyer", company_name="Acme")

    assert [j.external_id for j in first] == [j.external_id for j in second]
    assert first[0].external_id != first[1].external_id


def test_extract_jobs_returns_empty_for_non_listing_page(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = ExtractionResult(is_listing_page=False, jobs=[])
    monkeypatch.setattr(extract_mod, "call_structured", lambda **_: _result(payload))

    assert extract_jobs(CAREERS_HTML, url="https://acme.com/", company_name="Acme") == []


def test_extract_jobs_skips_model_when_page_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """JS ile dolan sayfada modeli boşuna çalıştırıp para harcamamalıyız."""
    called = False

    def _spy(**_):
        nonlocal called
        called = True
        raise AssertionError("model çağrılmamalıydı")

    monkeypatch.setattr(extract_mod, "call_structured", _spy)

    with pytest.raises(AgentError, match="anlamlı metin"):
        extract_jobs(
            "<html><body><div id='root'></div></body></html>",
            url="https://acme.com/kariyer",
            company_name="Acme",
        )
    assert not called


# --------------------------------------------------------------------- tespit


@respx.mock
async def test_detect_rejects_ats_suggestion_that_returns_no_jobs(
    http: HttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asıl güvenlik özelliği: doğrulanamayan öneri kabul edilmemeli."""
    detection = AtsDetection(ats="greenhouse", slug="uydurma", confidence="high", evidence="—")
    monkeypatch.setattr(detect_mod, "call_structured", lambda **_: _result(detection))

    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    outcome = await detect_ats(http, name="Acme", domain="acme.com")
    await http.aclose()

    assert outcome is None, "pano ilan döndürmüyorsa tespit reddedilmeli"


@respx.mock
async def test_detect_accepts_verified_ats_suggestion(
    http: HttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    detection = AtsDetection(
        ats="lever",
        slug="acmeco",
        careers_url="https://acme.com/kariyer",
        confidence="high",
        evidence="jobs.lever.co/acmeco",
    )
    monkeypatch.setattr(detect_mod, "call_structured", lambda **_: _result(detection))

    respx.get("https://api.lever.co/v0/postings/acmeco").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "1",
                    "text": "Backend",
                    "categories": {"location": "İstanbul"},
                    "descriptionPlain": "Django",
                    "hostedUrl": "https://jobs.lever.co/acmeco/1",
                }
            ],
        )
    )

    outcome = await detect_ats(http, name="Acme", domain="acme.com")
    await http.aclose()

    assert outcome is not None
    assert outcome.adapter_type is AdapterType.LEVER
    assert outcome.config == {"site": "acmeco"}


@respx.mock
async def test_detect_falls_back_to_careers_page_structured_data(
    http: HttpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ATS yoksa kariyer sayfasındaki JSON-LD kabul edilebilir bir sonuçtur."""
    detection = AtsDetection(ats="none", careers_url="https://acme.com/kariyer", evidence="—")
    monkeypatch.setattr(detect_mod, "call_structured", lambda **_: _result(detection))

    jsonld = """<script type="application/ld+json">
    {"@context":"https://schema.org","@type":"JobPosting","title":"SRE",
     "description":"Kubernetes","url":"https://acme.com/kariyer/sre"}</script>"""
    respx.get(url__regex=r"^https://acme\.com/kariyer$").mock(
        return_value=httpx.Response(200, html=jsonld)
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    outcome = await detect_ats(http, name="Acme", domain="acme.com")
    await http.aclose()

    assert outcome is not None
    assert outcome.adapter_type is AdapterType.JSONLD


def test_extracted_job_without_title_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = ExtractionResult(
        is_listing_page=True,
        jobs=[ExtractedJob(title="   "), ExtractedJob(title="Gerçek İlan")],
    )
    monkeypatch.setattr(extract_mod, "call_structured", lambda **_: _result(payload))

    jobs = extract_jobs(CAREERS_HTML, url="https://acme.com/kariyer", company_name="Acme")
    assert [j.title for j in jobs] == ["Gerçek İlan"]
    assert all(isinstance(j, RawJob) for j in jobs)
