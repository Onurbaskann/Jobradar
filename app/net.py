"""Kibar HTTP istemcisi: alan adı başına hız sınırı, kimliklendirici User-Agent, yeniden deneme.

Tarama yaptığımız siteler bizim misafirimiz; bu modül "iyi vatandaş" davranışını
tek yerde toplar, böylece hiçbir adaptör yanlışlıkla agresif davranamaz.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from types import TracebackType
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.robots import RobotsGate

log = logging.getLogger(__name__)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

#: ATS'lerin herkese açık API host'ları. Nezaket gecikmesi şirketlerin kendi web
#: sunucularını yormamak için var; bu uçlar ise sitelerin kendi kariyer
#: sayfalarına gömmesi için yayımlanmış, yüksek kapasiteli API'ler. Onlara da
#: 2 saniye uygulamak tespit turunu gereksiz yere dakikalarca uzatıyor.
API_HOSTS = frozenset(
    {
        "boards-api.greenhouse.io",
        "api.lever.co",
        "api.ashbyhq.com",
        "www.workable.com",
        "api.smartrecruiters.com",
    }
)
API_HOST_SUFFIXES = (".recruitee.com", ".jobs.personio.de", ".jobs.personio.com")
API_HOST_DELAY = 0.25


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str | None = None,
        domain_delay: float | None = None,
        timeout: float | None = None,
        max_retries: int = 2,
        respect_robots: bool | None = None,
    ) -> None:
        settings = get_settings()
        self.domain_delay = (
            domain_delay if domain_delay is not None else settings.crawl_domain_delay
        )
        self.max_retries = max_retries
        agent = user_agent or settings.crawler_user_agent
        enforce = settings.respect_robots_txt if respect_robots is None else respect_robots
        self._robots = RobotsGate(agent) if enforce else None
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": agent,
                "Accept-Language": "tr,en;q=0.8",
            },
            timeout=timeout if timeout is not None else settings.crawl_timeout,
            follow_redirects=True,
        )

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _delay_for(self, host: str) -> float:
        """Nezaket gecikmesi host tipine göre değişir (bkz. API_HOSTS)."""
        if self.domain_delay <= API_HOST_DELAY:
            return self.domain_delay
        if host in API_HOSTS or host.endswith(API_HOST_SUFFIXES):
            return API_HOST_DELAY
        return self.domain_delay

    async def _throttle(self, host: str) -> None:
        """Aynı alan adına ardışık istekler arasında yeterli süre bırak."""
        delay = self._delay_for(host)
        async with self._locks[host]:
            elapsed = time.monotonic() - self._last_request[host]
            if elapsed < delay:
                await asyncio.sleep(delay - elapsed)
            self._last_request[host] = time.monotonic()

    async def get(self, url: str, *, retries: int | None = None, **kwargs) -> httpx.Response:
        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        max_retries = self.max_retries if retries is None else retries

        for attempt in range(max_retries + 1):
            await self._throttle(host)
            try:
                response = await self._client.get(url, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = exc
            else:
                if response.status_code not in RETRY_STATUS:
                    return response
                last_exc = httpx.HTTPStatusError(
                    f"{response.status_code} for {url}", request=response.request, response=response
                )

            if attempt < max_retries:
                await asyncio.sleep(2**attempt)

        assert last_exc is not None
        raise last_exc

    async def get_json(self, url: str, **kwargs) -> object:
        response = await self.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    async def get_text(self, url: str, **kwargs) -> str:
        response = await self.get(url, **kwargs)
        response.raise_for_status()
        return response.text

    async def probe(self, url: str) -> httpx.Response | None:
        """Bir ucun var olup olmadığını sınar. Hata fırlatmaz — yoksa None döner.

        Yeniden deneme yapmaz: bu bir "var mı" sorusu, ve olmayan slug'lar
        sağlayıcının pazarlama sitesine yönlenip 429 döndürebiliyor. Böyle bir
        cevabı ısrarla tekrarlamak hem faydasız hem nezaketsiz olurdu.
        """
        try:
            return await self.get(url, retries=0)
        except httpx.HTTPError:
            return None

    # --- Web sayfası çekimleri: robots.txt kapısından geçer -------------------
    #
    # ATS'lerin public JSON uçları için `get`/`probe` kullanılır; onlar taranan
    # sayfa değil, sitelerin kendi kariyer sayfalarına gömmek için yayımladığı
    # API'lerdir. Aşağıdaki metotlar ise şirketlerin kendi sitelerine yapılan
    # istekler içindir.

    async def _robots_allow(self, url: str) -> bool:
        if self._robots is None:
            return True
        return await self._robots.allowed(self, url)

    async def probe_page(self, url: str) -> httpx.Response | None:
        """Sayfayı çeker; robots.txt izin vermiyorsa hiç istek yapmadan None döner."""
        if not await self._robots_allow(url):
            log.debug("robots.txt engelledi: %s", url)
            return None
        return await self.probe(url)
