"""HTTP istemcisinin nezaket davranışı."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.net import API_HOST_DELAY, HttpClient


def test_company_sites_keep_the_full_courtesy_delay() -> None:
    client = HttpClient(domain_delay=2.0, respect_robots=False)
    assert client._delay_for("acme.com") == 2.0
    assert client._delay_for("careers.acme.com") == 2.0


def test_public_ats_apis_use_a_shorter_delay() -> None:
    """Nezaket gecikmesi şirket sunucuları için; ATS API'leri gömülmek üzere yayımlanır."""
    client = HttpClient(domain_delay=2.0, respect_robots=False)
    for host in (
        "boards-api.greenhouse.io",
        "api.lever.co",
        "api.ashbyhq.com",
        "acme.recruitee.com",
        "acme.jobs.personio.de",
    ):
        assert client._delay_for(host) == API_HOST_DELAY, host


def test_shorter_configured_delay_is_never_increased() -> None:
    """Test/geliştirme için 0 gecikme verildiyse API host'ları onu yükseltmemeli."""
    client = HttpClient(domain_delay=0.0, respect_robots=False)
    assert client._delay_for("api.lever.co") == 0.0
    assert client._delay_for("acme.com") == 0.0


@respx.mock
async def test_retries_then_succeeds_on_transient_error() -> None:
    route = respx.get("https://api.lever.co/v0/postings/acme")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json=[])]

    client = HttpClient(domain_delay=0.0, max_retries=1, respect_robots=False)
    response = await client.get("https://api.lever.co/v0/postings/acme")
    await client.aclose()

    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_max_retries() -> None:
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=httpx.Response(503))

    client = HttpClient(domain_delay=0.0, max_retries=1, respect_robots=False)
    with pytest.raises(httpx.HTTPError):
        await client.get("https://api.lever.co/v0/postings/acme")
    await client.aclose()


@respx.mock
async def test_probe_swallows_errors() -> None:
    respx.get(url__regex=r".*").mock(side_effect=httpx.ConnectError("bağlanılamadı"))

    client = HttpClient(domain_delay=0.0, max_retries=0, respect_robots=False)
    assert await client.probe("https://acme.com/") is None
    await client.aclose()


@respx.mock
async def test_user_agent_identifies_the_crawler() -> None:
    route = respx.get("https://acme.com/").mock(return_value=httpx.Response(200))

    client = HttpClient(
        domain_delay=0.0, max_retries=0, respect_robots=False, user_agent="jobradar/test (+mail)"
    )
    await client.get("https://acme.com/")
    await client.aclose()

    assert route.calls[0].request.headers["user-agent"] == "jobradar/test (+mail)"
