"""robots.txt kapısı testleri.

Kapsam ayrımı bilinçli: şirket siteleri robots.txt'ye tabi, ATS'lerin public
JSON uçları değil. Bu testler o ayrımın korunduğunu doğrular.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.net import HttpClient

DISALLOW_ALL = "User-agent: *\nDisallow: /\n"
DISALLOW_CAREERS = "User-agent: *\nDisallow: /kariyer\n"


@pytest.fixture
def http() -> HttpClient:
    return HttpClient(domain_delay=0.0, max_retries=0, respect_robots=True)


@respx.mock
async def test_disallowed_page_is_not_requested(http: HttpClient) -> None:
    robots = respx.get("https://acme.com/robots.txt").mock(
        return_value=httpx.Response(200, text=DISALLOW_ALL)
    )
    page = respx.get(url__regex=r"^https://acme\.com/kariyer$").mock(
        return_value=httpx.Response(200, html="<a href='https://jobs.lever.co/x'>x</a>")
    )

    response = await http.probe_page("https://acme.com/kariyer")
    await http.aclose()

    assert response is None
    assert robots.called
    assert not page.called, "robots.txt yasaklıyorsa sayfaya hiç istek gitmemeli"


@respx.mock
async def test_allowed_page_is_fetched(http: HttpClient) -> None:
    respx.get("https://acme.com/robots.txt").mock(
        return_value=httpx.Response(200, text=DISALLOW_CAREERS)
    )
    page = respx.get(url__regex=r"^https://acme\.com/jobs$").mock(
        return_value=httpx.Response(200, html="<html></html>")
    )

    response = await http.probe_page("https://acme.com/jobs")
    await http.aclose()

    assert response is not None
    assert page.called


@respx.mock
async def test_missing_robots_means_allowed(http: HttpClient) -> None:
    respx.get("https://acme.com/robots.txt").mock(return_value=httpx.Response(404))
    page = respx.get(url__regex=r"^https://acme\.com/kariyer$").mock(
        return_value=httpx.Response(200, html="<html></html>")
    )

    response = await http.probe_page("https://acme.com/kariyer")
    await http.aclose()

    assert response is not None
    assert page.called


@respx.mock
async def test_robots_is_fetched_once_per_host(http: HttpClient) -> None:
    robots = respx.get("https://acme.com/robots.txt").mock(
        return_value=httpx.Response(200, text=DISALLOW_CAREERS)
    )
    respx.get(url__regex=r"^https://acme\.com/(a|b|c)$").mock(
        return_value=httpx.Response(200, html="<html></html>")
    )

    for path in ("a", "b", "c"):
        await http.probe_page(f"https://acme.com/{path}")
    await http.aclose()

    assert robots.call_count == 1, "robots.txt host başına önbelleğe alınmalı"


@respx.mock
async def test_ats_api_calls_bypass_robots(http: HttpClient) -> None:
    """ATS public JSON uçları taranan sayfa değil; robots kapısına takılmamalı."""
    robots = respx.get("https://boards-api.greenhouse.io/robots.txt").mock(
        return_value=httpx.Response(200, text=DISALLOW_ALL)
    )
    api = respx.get(url__regex=r"^https://boards-api\.greenhouse\.io/v1/boards/acme/jobs.*").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )

    response = await http.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs")
    await http.aclose()

    assert response.status_code == 200
    assert api.called
    assert not robots.called, "API çağrıları için robots.txt sorgulanmamalı"
