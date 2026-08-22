"""Adaptör sözleşmesi.

Her kaynak (ATS API, JSON-LD, sitemap, LLM) aynı arayüzü uygular ve aynı
`RawJob` yapısını üretir. Böylece crawl döngüsü kaynağı hiç bilmeden çalışır.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models import AdapterType, ApplyChannel, RemoteType
from app.net import HttpClient
from app.util.text import content_hash, find_apply_email


@dataclass(slots=True)
class RawJob:
    """Kaynaktan çıkarılmış, henüz veritabanına yazılmamış ilan."""

    external_id: str
    title: str
    apply_url: str | None = None
    location: str | None = None
    remote_type: RemoteType = RemoteType.UNKNOWN
    seniority: str | None = None
    department: str | None = None
    employment_type: str | None = None
    description_md: str = ""
    apply_email: str | None = None
    apply_channel: ApplyChannel = ApplyChannel.UNKNOWN
    posted_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def finalize(self) -> RawJob:
        """Kaynaktan sonra çalışan ortak zenginleştirme."""
        if not self.apply_email:
            self.apply_email = find_apply_email(self.description_md)
        if self.apply_channel is ApplyChannel.UNKNOWN:
            if self.apply_email:
                self.apply_channel = ApplyChannel.EMAIL
            elif self.apply_url:
                self.apply_channel = ApplyChannel.ATS_FORM
        if self.remote_type is RemoteType.UNKNOWN:
            self.remote_type = infer_remote_type(f"{self.title} {self.location or ''}")
        return self


def infer_remote_type(text: str) -> RemoteType:
    lowered = (text or "").casefold()
    if any(k in lowered for k in ("hibrit", "hybrid")):
        return RemoteType.HYBRID
    if any(k in lowered for k in ("uzaktan", "remote", "work from home", "evden")):
        return RemoteType.REMOTE
    return RemoteType.UNKNOWN


class AdapterError(RuntimeError):
    """Adaptör bu şirket için ilan çekemedi."""


class Adapter(ABC):
    """Tek bir kaynak tipini temsil eder."""

    type: AdapterType

    #: Bu adaptörün ayarında pano kimliğini tutan anahtar ("token", "site"...).
    #: LLM tespit ajanı sadece slug döner; ayarı bu anahtarla kuruyoruz.
    config_key: str | None = None

    @abstractmethod
    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        """Şirketin açık ilanlarını döner. Kaynak erişilemezse AdapterError fırlatır."""

    def config_from_slug(self, slug: str) -> dict[str, Any]:
        if not self.config_key:
            raise AdapterError(f"{self.type}: slug'dan ayar üretilemez")
        return {self.config_key: slug}

    async def source_fingerprint(self, http: HttpClient, config: dict[str, Any]) -> str | None:
        """Adaptörü çalıştırmadan kaynağın değişip değişmediğini anlatan ucuz imza.

        `None` döndürmek "bu adaptör ön kontrolü desteklemiyor" demektir; o zaman
        tarama döngüsü doğrudan `fetch` çağırır. Bunu uygulamak yalnızca `fetch`
        maliyetli olduğunda anlamlıdır — LLM çıkarımı gibi. Ücretsiz ATS API'leri
        için ön kontrol fazladan istek demek olurdu.
        """
        return None

    def probe_urls(self, slug: str) -> list[str]:
        """Slug tahmininden denenecek ucları üretir (LLM'siz tespit için)."""
        return []

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        """Bilinen bir kariyer sayfası URL'sinden adaptör ayarını çıkarır."""
        return None

    def config_from_probe(self, url: str) -> dict[str, Any]:
        """probe_urls ile bulunan çalışan uçtan kalıcı ayar üretir."""
        return self.config_from_url(url) or {}

    async def probe(self, http: HttpClient, slug: str) -> dict[str, Any] | None:
        """Slug bu ATS'te var mı? Varsa ayarı, yoksa None döner."""
        for url in self.probe_urls(slug):
            response = await http.probe(url)
            if response is None or response.status_code != 200:
                continue
            if not redirect_kept_slug(response, slug):
                continue
            try:
                jobs = await self.fetch(http, self.config_from_probe(url))
            except (AdapterError, ValueError):
                continue
            if jobs:
                return self.config_from_probe(url)
        return None


def redirect_kept_slug(response: Any, slug: str) -> bool:
    """Yönlendirme sonrası hâlâ o slug'ın panosunda mıyız?

    Bazı sağlayıcılar olmayan bir slug'ı kendi pazarlama sitesine yönlendirip
    200 döndürüyor (ör. `<slug>.jobs.personio.de` → `personio.com`). Slug son
    URL'de yoksa gördüğümüz sayfa o şirketin panosu değildir.

    Meşru yönlendirmeler slug'ı korur — Workable'ın `www.workable.com/...` →
    `apply.workable.com/...` yönlendirmesi gibi — o yüzden host değişimini
    değil slug'ın kaybolmasını ölçüyoruz.
    """
    final_url = str(getattr(response, "url", "") or "")
    return slug.casefold() in final_url.casefold()


def stable_external_id(*parts: object) -> str:
    """Kaynakta kimlik yoksa içerikten kararlı bir kimlik üretir."""
    return content_hash(*parts)[:32]
