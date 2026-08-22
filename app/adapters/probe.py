"""LLM'siz ATS tespiti — kanıt gücüne göre sıralı.

Sıra önemli; hem maliyet hem güvenilirlik açısından:

  1. Verilen kariyer URL'si zaten bir ATS'e işaret ediyor mu?   (0 istek, YETKİLİ)
  2. Şirketin kendi sitesi bir ATS panosuna link veriyor mu?     (≤4 istek, YETKİLİ)
  3. Şirket adı/domaininden türetilen slug tutuyor mu?           (birkaç istek, TAHMİN)
  4. (Faz 3) Hiçbiri tutmazsa LLM tespit ajanı devreye girer.

3. adım tek başına güvenilmez: gerçek ölçümde 5 tahminden 2'si yanlış şirketi
işaret etti (`greenhouse/peak` → Teksas fizik tedavi zinciri, `greenhouse/insider`
→ Business Insider). Bu yüzden tahminler otomatik aktifleştirilmez; insan onayına
düşer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.adapters.base import Adapter
from app.adapters.jsonld import JsonLdAdapter
from app.adapters.registry import L1_ADAPTERS, detect_from_url
from app.adapters.site_links import find_ats_link
from app.adapters.sitemap import SitemapAdapter
from app.models import AdapterType
from app.net import HttpClient
from app.util.text import slugify

log = logging.getLogger(__name__)


class ProbeConfidence(StrEnum):
    #: Şirketin kendi alan adı bu panoya işaret ediyor — doğrudan kullanılabilir
    AUTHORITATIVE = "authoritative"
    #: Slug tuttu ama panonun bu şirkete ait olduğuna dair kanıt yok — onay gerekir
    GUESS = "guess"


@dataclass(slots=True)
class ProbeResult:
    adapter_type: AdapterType
    config: dict[str, Any]
    confidence: ProbeConfidence
    method: str  # "careers_url" | "site_link" | "slug"
    evidence: str | None = None  # kanıt URL'si veya denenen slug


def slug_candidates(name: str, domain: str | None = None) -> list[str]:
    """ATS slug tahminleri — en olasıdan en zayıfa, tekrarsız."""
    candidates: list[str] = []

    if domain:
        root = domain.split(":")[0].removeprefix("www.").split(".")[0]
        if root:
            candidates.append(root)

    base = slugify(name)
    if base:
        candidates.append(base)

    # "Acme Teknoloji" → "acme"; ilk kelime tek başına sık kullanılır
    first_word = slugify(name.split()[0]) if name.split() else ""
    if first_word and len(first_word) >= 3:
        candidates.append(first_word)

    # Tireli varyant: "acmeteknoloji" yanında "acme-teknoloji"
    words = [w for w in (slugify(word) for word in name.split()) if w]
    if len(words) > 1:
        candidates.append("-".join(words))

    seen: set[str] = set()
    return [c for c in candidates if c and not (c in seen or seen.add(c))]


async def probe_company(
    http: HttpClient,
    *,
    name: str,
    domain: str | None = None,
    careers_url: str | None = None,
    allow_guess: bool = True,
) -> ProbeResult | None:
    """Şirket için bir L1 adaptörü bulmaya çalışır. Bulamazsa None."""

    # 1. Verilen kariyer URL'si — ağ isteği yok
    if careers_url:
        detected = detect_from_url(careers_url)
        if detected:
            adapter_type, config = detected
            return ProbeResult(
                adapter_type=adapter_type,
                config=config,
                confidence=ProbeConfidence.AUTHORITATIVE,
                method="careers_url",
                evidence=careers_url,
            )

    # 2. Şirketin kendi sitesindeki bağlantı — yanlış şirkete bağlanmayı önler
    if domain:
        try:
            site_match = await find_ats_link(http, domain)
        except Exception:  # noqa: BLE001 — site erişilemezse tahmine düş
            log.debug("site link taraması başarısız: %s", domain, exc_info=True)
            site_match = None
        if site_match:
            return ProbeResult(
                adapter_type=site_match.adapter_type,
                config=site_match.config,
                confidence=ProbeConfidence.AUTHORITATIVE,
                method="site_link",
                evidence=site_match.evidence_url,
            )

    # 3. Şirketin kendi sayfalarında yapısal veri (L2) veya sitemap (L3)
    #    Bunlar da yetkilidir: veri şirketin kendi alan adından geliyor.
    if domain:
        structured = await _probe_structured(http, domain=domain, careers_url=careers_url)
        if structured:
            return structured

    # 4. Slug tahmini — kanıtsız, insan onayı gerektirir
    if not allow_guess:
        return None

    for slug in slug_candidates(name, domain):
        for adapter in L1_ADAPTERS:
            try:
                config = await adapter.probe(http, slug)
            except Exception:  # noqa: BLE001 — tek adaptörün hatası taramayı durdurmasın
                log.debug("probe hatası: %s / %s", adapter.type, slug, exc_info=True)
                continue
            if config:
                return ProbeResult(
                    adapter_type=adapter.type,
                    config=config,
                    confidence=ProbeConfidence.GUESS,
                    method="slug",
                    evidence=slug,
                )
    return None


async def _probe_structured(
    http: HttpClient, *, domain: str, careers_url: str | None
) -> ProbeResult | None:
    """L2 (JSON-LD) ve L3 (sitemap) adaptörlerini sırayla dener.

    Adaptörü "çalışıyor" saymak için gerçekten ilan üretmesini şart koşuyoruz;
    erişilebilir ama boş bir sayfa şirketi aktif etmeye yetmez.
    """
    root = f"https://{domain}"
    candidate_urls = [
        url for url in (careers_url, f"{root}/careers", f"{root}/kariyer", root) if url
    ]

    attempts: list[tuple[Adapter, dict[str, Any], str]] = [
        (JsonLdAdapter(), {"urls": candidate_urls}, candidate_urls[0]),
        (SitemapAdapter(), {"domain": domain}, f"{root}/sitemap.xml"),
    ]

    for adapter, config, evidence in attempts:
        try:
            jobs = await adapter.fetch(http, config)
        except Exception:  # noqa: BLE001 — bu katman yoksa bir sonrakine geç
            log.debug("yapısal veri probe başarısız: %s / %s", adapter.type, domain, exc_info=True)
            continue
        if jobs:
            return ProbeResult(
                adapter_type=adapter.type,
                config=config,
                confidence=ProbeConfidence.AUTHORITATIVE,
                method=str(adapter.type),
                evidence=evidence,
            )
    return None
