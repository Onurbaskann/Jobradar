from __future__ import annotations

import httpx
import pytest
import respx

from app.web_search import BraveSearchClient, WebSearchError


@pytest.mark.asyncio
async def test_brave_search_requires_api_key() -> None:
    with pytest.raises(WebSearchError, match="BRAVE_SEARCH_API_KEY"):
        await BraveSearchClient("").search("Acme careers")


@pytest.mark.asyncio
@respx.mock
async def test_brave_search_normalizes_results() -> None:
    route = respx.get(BraveSearchClient.endpoint).mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Acme Careers",
                            "url": "https://jobs.lever.co/acme",
                            "description": "Open positions",
                        },
                        {"title": "Eksik adres"},
                    ]
                }
            },
        )
    )

    results = await BraveSearchClient("secret").search("Acme careers", count=50)

    assert len(results) == 1
    assert results[0].url == "https://jobs.lever.co/acme"
    assert route.calls[0].request.headers["x-subscription-token"] == "secret"
    assert "count=20" in str(route.calls[0].request.url)


@pytest.mark.asyncio
@respx.mock
async def test_brave_search_rejects_invalid_payload() -> None:
    respx.get(BraveSearchClient.endpoint).mock(
        return_value=httpx.Response(200, text="geçersiz")
    )

    with pytest.raises(WebSearchError, match="geçersiz JSON"):
        await BraveSearchClient("secret").search("Acme careers")


@pytest.mark.asyncio
@respx.mock
async def test_brave_search_rejects_invalid_web_shape() -> None:
    respx.get(BraveSearchClient.endpoint).mock(
        return_value=httpx.Response(200, json={"web": []})
    )

    with pytest.raises(WebSearchError, match="beklenmeyen web alanı"):
        await BraveSearchClient("secret").search("Acme careers")
