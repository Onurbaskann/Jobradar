"""robots.txt kapısı.

Kapsam bilinçli olarak *web sayfası* çekimleriyle sınırlı: kariyer sayfası
taraması, JSON-LD çıkarımı ve sitemap gezintisi. ATS'lerin herkese açık JSON
uçları (Greenhouse boards-api gibi) bu kapıdan geçmez — onlar sitelerin kendi
kariyer sayfalarına gömmek için yayımladığı API'ler, taranan sayfalar değil.

robots.txt alınamazsa (404, ağ hatası) erişim serbest kabul edilir; standart
davranış budur.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

log = logging.getLogger(__name__)


class RobotsGate:
    """Host başına robots.txt'yi bir kez çeker ve önbelleğe alır."""

    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self._cache: dict[str, RobotFileParser | None] = {}

    async def allowed(self, http, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"

        if origin not in self._cache:
            self._cache[origin] = await self._load(http, origin)

        parser = self._cache[origin]
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    async def _load(self, http, origin: str) -> RobotFileParser | None:
        response = await http.probe(f"{origin}/robots.txt")
        if response is None or response.status_code != 200:
            return None

        parser = RobotFileParser()
        try:
            parser.parse(response.text.splitlines())
        except Exception:  # noqa: BLE001 — bozuk robots.txt erişimi engellememeli
            log.debug("robots.txt ayrıştırılamadı: %s", origin, exc_info=True)
            return None
        return parser
