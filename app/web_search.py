"""Resmî web arama sağlayıcısı sınırı."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class WebSearchError(RuntimeError):
    """Web arama sağlayıcısı kullanılabilir sonuç üretemedi."""


@dataclass(frozen=True, slots=True)
class WebSearchResult:
    title: str
    url: str
    description: str = ""


class BraveSearchClient:
    """Brave Search API yanıtını küçük, sağlayıcıdan bağımsız bir sözleşmeye çevirir."""

    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self._api_key = api_key.strip()
        self._timeout = timeout

    async def search(
        self,
        query: str,
        *,
        count: int = 10,
        country: str = "TR",
        search_lang: str = "tr",
        freshness: str | None = None,
    ) -> list[WebSearchResult]:
        if not self._api_key:
            raise WebSearchError("BRAVE_SEARCH_API_KEY tanımlanmalı")

        params = {
            "q": query,
            "country": country,
            "search_lang": search_lang,
            "count": max(1, min(count, 20)),
        }
        if freshness:
            params["freshness"] = freshness

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    self.endpoint,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "X-Subscription-Token": self._api_key,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Brave Search isteği başarısız: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WebSearchError("Brave Search geçersiz JSON döndürdü") from exc
        if not isinstance(payload, dict):
            raise WebSearchError("Brave Search beklenmeyen yanıt döndürdü")
        web = payload.get("web", {})
        if not isinstance(web, dict):
            raise WebSearchError("Brave Search beklenmeyen web alanı döndürdü")
        raw_results = web.get("results", [])
        if not isinstance(raw_results, list):
            raise WebSearchError("Brave Search sonuç listesi beklenen biçimde değil")
        return [
            parsed
            for item in raw_results
            if isinstance(item, dict)
            if (parsed := _parse_result(item)) is not None
        ]


def _parse_result(item: dict[str, Any]) -> WebSearchResult | None:
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    return WebSearchResult(
        title=str(item.get("title") or "").strip(),
        url=url,
        description=str(item.get("description") or "").strip(),
    )
