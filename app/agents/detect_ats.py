"""Ajan 1 — şirketin kariyer sayfasını ve ATS'ini bulma.

Şirket başına **bir kez** çalışır ve yalnızca deterministik yollar (URL deseni,
site bağlantısı, JSON-LD, sitemap, slug tahmini) tükendiğinde.

Önemli: ajanın çıktısı doğrudan kabul edilmez. Model bir ATS + slug söylüyorsa
gerçekten ilan dönüp dönmediğini ADAPTÖRLE doğruluyoruz; kariyer sayfası
söylüyorsa o sayfadan ilan çıkarılabildiğini kontrol ediyoruz. Böylece modelin
uydurması sisteme yanlış pano sokamaz — L1 slug tahmininde ölçtüğümüz aynı
yanlış-pozitif riski burada da geçerli.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.adapters.base import Adapter
from app.adapters.jsonld import JsonLdAdapter
from app.adapters.llm_extract import LlmExtractAdapter
from app.adapters.registry import L1_ADAPTERS
from app.agents.client import AgentError, call_structured
from app.config import get_settings
from app.models import AdapterType
from app.net import HttpClient

log = logging.getLogger(__name__)

AtsName = Literal[
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "recruitee",
    "personio",
    "smartrecruiters",
    "none",
]

SYSTEM = """Sen bir işe alım altyapısı tespit aracısın. Sana bir şirketin adı ve \
alan adı verilecek. Görevin iki şeyi bulmak:

1. `careers_url` — şirketin açık iş ilanlarını listelediği sayfanın gerçek adresi.
2. `ats` — o sayfanın arkasında bilinen bir işe alım platformu (ATS) var mı.

ATS tespiti için tipik izler:
- boards.greenhouse.io/<slug> veya job-boards.greenhouse.io/<slug>  → greenhouse
- jobs.lever.co/<slug>                                              → lever
- jobs.ashbyhq.com/<slug>                                           → ashby
- apply.workable.com/<slug>                                         → workable
- <slug>.recruitee.com                                              → recruitee
- <slug>.jobs.personio.de                                           → personio
- careers.smartrecruiters.com/<slug>                                → smartrecruiters

Kurallar:
- `slug` yalnızca yukarıdaki adreslerdeki kimlik kısmıdır; tam URL değil.
- Bir ATS izini GERÇEKTEN gördüysen bildir. Şirket adına bakıp tahmin etme — \
yanlış slug başka bir şirketin ilanlarını getirir.
- Emin değilsen `ats` alanına "none" yaz ve sadece `careers_url` ver.
- Kariyer sayfası bulunamıyorsa `careers_url` null olsun.
- `evidence` alanına kararını dayandırdığın somut bulguyu yaz (gördüğün URL gibi)."""


class AtsDetection(BaseModel):
    careers_url: str | None = Field(default=None, description="İlanların listelendiği sayfa")
    ats: AtsName = "none"
    slug: str | None = Field(default=None, description="ATS panosunun kimliği (tam URL değil)")
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: str = ""


class DetectionOutcome(BaseModel):
    """Doğrulanmış tespit sonucu."""

    adapter_type: AdapterType
    config: dict
    careers_url: str | None
    evidence: str


_ADAPTER_BY_NAME: dict[str, Adapter] = {str(a.type): a for a in L1_ADAPTERS}


async def detect_ats(
    http: HttpClient, *, name: str, domain: str, company_id: int | None = None
) -> DetectionOutcome | None:
    """Ajanı çalıştırır ve önerisini doğrular. Doğrulanamazsa None döner."""
    settings = get_settings()

    result = call_structured(
        agent="detect_ats",
        model=settings.model_detect,
        system=SYSTEM,
        user_content=(
            f"Şirket: {name}\nAlan adı: {domain}\n\n"
            "Bu şirketin kariyer sayfasını ve varsa ATS'ini bul."
        ),
        output_model=AtsDetection,
        max_tokens=8000,
        effort="medium",
        tools=[
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 6},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 6},
        ],
        company_id=company_id,
    )
    detection = result.data
    log.info(
        "detect_ats %s: ats=%s slug=%s careers=%s (%s)",
        name,
        detection.ats,
        detection.slug,
        detection.careers_url,
        detection.confidence,
    )

    # 1. ATS önerisi varsa adaptörle doğrula — dönen pano gerçekten ilan veriyor mu?
    if detection.ats != "none" and detection.slug:
        adapter = _ADAPTER_BY_NAME.get(detection.ats)
        if adapter is not None:
            config = adapter.config_from_slug(detection.slug.strip())
            try:
                jobs = await adapter.fetch(http, config)
            except Exception:  # noqa: BLE001 — doğrulanamayan öneri reddedilir
                log.info("detect_ats %s: %s/%s doğrulanamadı", name, detection.ats, detection.slug)
                jobs = []
            if jobs:
                return DetectionOutcome(
                    adapter_type=adapter.type,
                    config=config,
                    careers_url=detection.careers_url,
                    evidence=f"{detection.ats}:{detection.slug} — {detection.evidence}"[:500],
                )

    # 2. ATS yoksa kariyer sayfasından yapısal veri (ucuz) ya da LLM çıkarımı (pahalı)
    if detection.careers_url:
        for adapter, config in (
            (JsonLdAdapter(), {"url": detection.careers_url}),
            (
                LlmExtractAdapter(),
                {"url": detection.careers_url, "company_name": name, "company_id": company_id},
            ),
        ):
            try:
                jobs = await adapter.fetch(http, config)
            except Exception:  # noqa: BLE001 — bu katman tutmadı, sonrakine geç
                log.debug("detect_ats doğrulama başarısız: %s", adapter.type, exc_info=True)
                continue
            if jobs:
                return DetectionOutcome(
                    adapter_type=adapter.type,
                    config=config,
                    careers_url=detection.careers_url,
                    evidence=f"{detection.careers_url} — {detection.evidence}"[:500],
                )

    return None


async def detect_ats_safe(
    http: HttpClient, *, name: str, domain: str, company_id: int | None = None
) -> DetectionOutcome | None:
    """API hatası tespit turunu durdurmasın diye sarmalayıcı."""
    try:
        return await detect_ats(http, name=name, domain=domain, company_id=company_id)
    except AgentError as exc:
        log.warning("detect_ats %s: %s", name, exc)
        return None
