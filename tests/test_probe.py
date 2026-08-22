"""Tespit güvenilirliği testleri.

Bu dosyanın varlık sebebi somut: canlı ölçümde slug tahminlerinin %40'ı yanlış
şirketi işaret etti (`greenhouse/peak` bir Teksas kliniği, `greenhouse/insider`
Business Insider). O yüzden burada asıl doğrulanan şey "tahmin çalışıyor mu"
değil, "tahmin yetkili kanıtla karıştırılmıyor mu".
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.probe import ProbeConfidence, probe_company
from app.adapters.site_links import MAX_PAGES, find_ats_link
from app.models import AdapterType
from app.net import HttpClient

GREENHOUSE_OK = {"jobs": [{"id": 1, "title": "Engineer", "location": {"name": "İstanbul"}}]}


@pytest.fixture
def http() -> HttpClient:
    return HttpClient(domain_delay=0.0, max_retries=0)


@respx.mock
async def test_careers_url_is_authoritative_and_costs_no_request(http: HttpClient) -> None:
    result = await probe_company(
        http, name="Acme", domain="acme.com", careers_url="https://jobs.lever.co/acme"
    )
    await http.aclose()

    assert result is not None
    assert result.adapter_type is AdapterType.LEVER
    assert result.confidence is ProbeConfidence.AUTHORITATIVE
    assert result.method == "careers_url"
    assert not respx.calls, "URL deseninden tespit hiç ağ isteği yapmamalı"


@respx.mock
async def test_site_link_makes_detection_authoritative(http: HttpClient) -> None:
    # respx'te host kalıbı tüm yolları yakalar; kök ile kariyer sayfasını
    # ayırt edebilmek için yola duyarlı kalıp gerekiyor.
    respx.get(url__regex=r"^https://acme\.com/$").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            html='<html><body><a href="/kariyer">Kariyer</a></body></html>',
        )
    )
    respx.get(url__regex=r"^https://acme\.com/kariyer$").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            html='<a href="https://boards.greenhouse.io/acmeco">Açık pozisyonlar</a>',
        )
    )
    # Sabit kariyer yolları ve kariyer alt alan adları bu sitede yok
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    result = await probe_company(http, name="Acme", domain="acme.com")
    await http.aclose()

    assert result is not None
    assert result.confidence is ProbeConfidence.AUTHORITATIVE
    assert result.method == "site_link"
    assert result.config == {"token": "acmeco"}


@respx.mock
async def test_site_link_found_in_script_body(http: HttpClient) -> None:
    """SPA kariyer sayfalarında ATS adresi <a> değil, script/JSON içinde geçer."""
    respx.get("https://acme.com").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            html='<script>window.__CFG={"board":"https://jobs.lever.co/acmeco"}</script>',
        )
    )

    match = await find_ats_link(http, "acme.com")
    await http.aclose()

    assert match is not None
    assert match.adapter_type is AdapterType.LEVER
    assert match.config == {"site": "acmeco"}


@respx.mock
async def test_slug_hit_without_site_evidence_is_only_a_guess(http: HttpClient) -> None:
    """Asıl regresyon koruması: kanıtsız slug isabeti YETKİLİ sayılmamalı."""
    respx.get("https://insider.com").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://insider\.com/.*").mock(return_value=httpx.Response(404))
    respx.get("https://boards-api.greenhouse.io/v1/boards/insider/jobs").mock(
        return_value=httpx.Response(200, json=GREENHOUSE_OK)
    )

    result = await probe_company(http, name="Insider", domain="insider.com")
    await http.aclose()

    assert result is not None
    assert result.adapter_type is AdapterType.GREENHOUSE
    assert result.confidence is ProbeConfidence.GUESS, (
        "kanıtsız slug isabeti yetkili sayılırsa yanlış şirketin ilanları sisteme girer"
    )
    assert result.evidence == "insider"


@respx.mock
async def test_probe_rejects_redirect_to_vendor_marketing_page(http: HttpClient) -> None:
    """Olmayan slug sağlayıcının kendi sitesine yönlenip 200 dönebiliyor.

    Canlı gözlem: `<slug>.jobs.personio.de` bilinmeyen slug'da 307 ile
    `personio.com`'a yönleniyor. Bunu "pano bulundu" saymak yanlış olur.
    """
    respx.get(url__regex=r"^https://logo\.jobs\.personio\.de/.*").mock(
        return_value=httpx.Response(307, headers={"location": "https://personio.com/"})
    )
    respx.get(url__regex=r"^https://personio\.com/?$").mock(
        return_value=httpx.Response(200, html="<html>Personio pazarlama sayfası</html>")
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    result = await probe_company(http, name="Logo", domain="logo.com.tr")
    await http.aclose()

    assert result is None


@respx.mock
async def test_probe_accepts_redirect_that_keeps_the_slug(http: HttpClient) -> None:
    """Meşru yönlendirmeler slug'ı korur — Workable www → apply gibi."""
    respx.get(url__regex=r"^https://www\.workable\.com/api/accounts/acmeco.*").mock(
        return_value=httpx.Response(
            302, headers={"location": "https://apply.workable.com/api/v1/widget/accounts/acmeco"}
        )
    )
    respx.get(url__regex=r"^https://apply\.workable\.com/api/v1/widget/accounts/acmeco.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Acme",
                "jobs": [
                    {
                        "shortcode": "AB1",
                        "title": "Backend",
                        "city": "İstanbul",
                        "url": "https://apply.workable.com/acmeco/j/AB1/",
                    }
                ],
            },
        )
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    result = await probe_company(http, name="Acmeco", domain="acmeco.com")
    await http.aclose()

    assert result is not None
    assert result.adapter_type is AdapterType.WORKABLE
    assert result.confidence is ProbeConfidence.GUESS


@respx.mock
async def test_allow_guess_false_returns_nothing_without_evidence(http: HttpClient) -> None:
    respx.get(url__regex=r"https://acme\.com.*").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").mock(
        return_value=httpx.Response(200, json=GREENHOUSE_OK)
    )

    result = await probe_company(http, name="Acme", domain="acme.com", allow_guess=False)
    await http.aclose()

    assert result is None


@respx.mock
async def test_site_link_scan_is_bounded(http: HttpClient) -> None:
    """Kariyer bağlantısı bolca olan bir sitede istek sayısı patlamamalı."""
    links = "".join(f'<a href="/careers/{i}">Kariyer {i}</a>' for i in range(20))
    respx.get(url__regex=r"^https://acme\.com/.*$").mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/html"}, html=f"<html>{links}</html>"
        )
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    match = await find_ats_link(http, "acme.com")
    await http.aclose()

    assert match is None
    # MAX_PAGES sayfa bütçesini yönetir; robots.txt kontrolleri ayrı ve host başına
    # bir kez yapılır, o yüzden sayımdan çıkarılır.
    page_calls = [c for c in respx.calls if not c.request.url.path.endswith("/robots.txt")]
    assert len(page_calls) <= MAX_PAGES, "site taraması MAX_PAGES ile sınırlı kalmalı"


@respx.mock
async def test_careers_subdomain_is_checked(http: HttpClient) -> None:
    """Kök sayfa bot koruması nedeniyle 403 dönse bile kariyer alt alan adı kurtarır.

    Gerçek örnek: trendyol.com kökü 403, careers.trendyol.com ise Lever
    bağlantısını içeriyor.
    """
    respx.get(url__regex=r"^https://acme\.com/?$").mock(return_value=httpx.Response(403))
    respx.get(url__regex=r"^https://careers\.acme\.com/?$").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            html='<a href="https://jobs.lever.co/acmeco">Açık pozisyonlar</a>',
        )
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    match = await find_ats_link(http, "acme.com")
    await http.aclose()

    assert match is not None
    assert match.adapter_type is AdapterType.LEVER
    assert match.config == {"site": "acmeco"}
    assert match.evidence_url == "https://careers.acme.com"
