"""Adaptör testleri — ağa çıkmaz, kaydedilmiş yanıtlara karşı çalışır.

Amaç regresyon güvencesi: bir ATS yanıt şemasını değiştirdiğinde fixture'ı
güncellerken testin kırılması, sessizce boş ilan listesi dönmesinden iyidir.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.ashby import AshbyAdapter
from app.adapters.greenhouse import GreenhouseAdapter
from app.adapters.lever import LeverAdapter
from app.adapters.recruitee import RecruiteeAdapter
from app.adapters.registry import detect_from_url
from app.adapters.workable import WorkableAdapter
from app.models import AdapterType, ApplyChannel, RemoteType
from app.net import HttpClient


@pytest.fixture
def http() -> HttpClient:
    # Testlerde hız sınırını kapat — gerçek ağa çıkmıyoruz
    return HttpClient(domain_delay=0.0, max_retries=0)


@respx.mock
async def test_greenhouse_parses_jobs(http: HttpClient, fixture_json) -> None:
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=fixture_json("greenhouse_jobs.json"))
    )

    jobs = await GreenhouseAdapter().fetch(http, {"token": "acme"})
    await http.aclose()

    assert len(jobs) == 2
    first = jobs[0]
    assert first.external_id == "4567890"
    assert first.title == "Senior Backend Engineer"
    assert first.location == "Istanbul, Turkey"
    assert first.department == "Engineering"
    # HTML kaçışları çözülmeli ve liste madde işaretine dönmeli
    assert "backend engineer" in first.description_md
    assert "- 5+ years Python" in first.description_md
    assert "<p>" not in first.description_md
    # Açıklamadaki başvuru adresi yakalanmalı ve kanal e-postaya dönmeli
    assert first.apply_email == "jobs@acme.com"
    assert first.apply_channel is ApplyChannel.EMAIL
    assert first.posted_at is not None

    # "Remote - Türkiye" lokasyonundan uzaktan çalışma çıkarılmalı
    assert jobs[1].remote_type is RemoteType.REMOTE
    # E-posta yoksa kanal ATS formuna düşmeli
    assert jobs[1].apply_channel is ApplyChannel.ATS_FORM


@respx.mock
async def test_lever_merges_description_sections(http: HttpClient, fixture_json) -> None:
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(200, json=fixture_json("lever_postings.json"))
    )

    jobs = await LeverAdapter().fetch(http, {"site": "acme"})
    await http.aclose()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Frontend Developer"
    assert job.employment_type == "Full-time"
    assert job.seniority == "Mid"
    assert job.remote_type is RemoteType.HYBRID
    # Gövde + "lists" bölümleri + additional tek metinde birleşmeli
    assert "React ve TypeScript" in job.description_md
    assert "Aradıklarımız" in job.description_md
    assert "- 3+ yıl React" in job.description_md
    assert job.apply_email == "kariyer@acme.com"


@respx.mock
async def test_ashby_uses_workplace_type(http: HttpClient) -> None:
    respx.get("https://api.ashbyhq.com/posting-api/job-board/acme").mock(
        return_value=httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": "job-1",
                        "title": "Platform Engineer",
                        "location": "Ankara",
                        "workplaceType": "Remote",
                        "employmentType": "FullTime",
                        "applyUrl": "https://jobs.ashbyhq.com/acme/job-1/application",
                        "descriptionPlain": "Kubernetes ve Terraform.",
                        "publishedAt": "2026-08-05T12:00:00.000Z",
                    }
                ]
            },
        )
    )

    jobs = await AshbyAdapter().fetch(http, {"board": "acme"})
    await http.aclose()

    assert jobs[0].remote_type is RemoteType.REMOTE
    assert jobs[0].employment_type == "FullTime"
    assert jobs[0].posted_at is not None


@respx.mock
async def test_workable_joins_description_and_requirements(http: HttpClient) -> None:
    respx.get("https://www.workable.com/api/accounts/acme").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Acme",
                "jobs": [
                    {
                        "shortcode": "AB12CD",
                        "title": "QA Engineer",
                        "city": "İzmir",
                        "country": "Turkey",
                        "telecommuting": True,
                        "employment_type": "Full-time",
                        "url": "https://apply.workable.com/acme/j/AB12CD/",
                        "description": "<p>Test otomasyonu.</p>",
                        "requirements": "<ul><li>Playwright</li></ul>",
                        "published_on": "2026-07-15",
                    }
                ],
            },
        )
    )

    jobs = await WorkableAdapter().fetch(http, {"subdomain": "acme"})
    await http.aclose()

    job = jobs[0]
    assert job.external_id == "AB12CD"
    assert job.location == "İzmir, Turkey"
    assert job.remote_type is RemoteType.REMOTE
    assert "Test otomasyonu." in job.description_md
    assert "- Playwright" in job.description_md


@respx.mock
async def test_recruitee_reads_offers(http: HttpClient) -> None:
    respx.get("https://acme.recruitee.com/api/offers/").mock(
        return_value=httpx.Response(
            200,
            json={
                "offers": [
                    {
                        "id": 99,
                        "title": "DevOps Mühendisi",
                        "city": "İstanbul",
                        "country": "Türkiye",
                        "remote": False,
                        "department": "Altyapı",
                        "employment_type_code": "fulltime",
                        "careers_apply_url": "https://acme.recruitee.com/o/devops/c/new",
                        "description": "<p>CI/CD hatları.</p>",
                        "requirements": "<ul><li>Docker</li></ul>",
                        "published_at": "2026-06-01T08:00:00.000Z",
                    }
                ]
            },
        )
    )

    jobs = await RecruiteeAdapter().fetch(http, {"company": "acme"})
    await http.aclose()

    assert jobs[0].external_id == "99"
    assert jobs[0].location == "İstanbul, Türkiye"
    assert "- Docker" in jobs[0].description_md


@respx.mock
async def test_adapter_error_when_config_missing(http: HttpClient) -> None:
    from app.adapters.base import AdapterError

    with pytest.raises(AdapterError):
        await GreenhouseAdapter().fetch(http, {})
    await http.aclose()


@pytest.mark.parametrize(
    ("url", "expected_type", "expected_config"),
    [
        (
            "https://boards.greenhouse.io/trendyol",
            AdapterType.GREENHOUSE,
            {"token": "trendyol"},
        ),
        ("https://jobs.lever.co/getir", AdapterType.LEVER, {"site": "getir"}),
        (
            "https://jobs.ashbyhq.com/dreamgames",
            AdapterType.ASHBY,
            {"board": "dreamgames"},
        ),
        (
            "https://apply.workable.com/acme-tech/",
            AdapterType.WORKABLE,
            {"subdomain": "acme-tech"},
        ),
        (
            "https://acme.recruitee.com/o/devops",
            AdapterType.RECRUITEE,
            {"company": "acme"},
        ),
        (
            "https://acme.jobs.personio.de/",
            AdapterType.PERSONIO,
            {"company": "acme"},
        ),
    ],
)
def test_detect_from_url(url: str, expected_type: AdapterType, expected_config: dict) -> None:
    """En ucuz tespit yolu: hiç ağ isteği yapmadan URL deseninden tanıma."""
    result = detect_from_url(url)
    assert result is not None
    adapter_type, config = result
    assert adapter_type is expected_type
    assert config == expected_config


def test_detect_from_url_returns_none_for_custom_site() -> None:
    assert detect_from_url("https://acme.com.tr/kariyer") is None
