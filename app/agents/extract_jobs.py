"""Ajan 2 — özel tasarım kariyer sayfasından ilan çıkarımı (L4).

Bu ajan yalnızca deterministik katmanların (L1 ATS API, L2 JSON-LD, L3 sitemap)
hepsi başarısız olduğunda ve sayfanın içerik hash'i değiştiğinde çalışır.

Maliyeti üç şey aşağıda tutuyor:
  * ucuz model (varsayılan Haiku 4.5),
  * ham HTML yerine budanmış metin,
  * sabit sistem promptunun önbelleğe alınması.
"""

from __future__ import annotations

import logging
from typing import Literal

import trafilatura
from pydantic import BaseModel, Field

from app.adapters.base import RawJob, stable_external_id
from app.agents.client import AgentError, call_structured
from app.config import get_settings
from app.models import ApplyChannel, RemoteType
from app.util.text import normalize_ws

log = logging.getLogger(__name__)

#: Budanmış metnin üst sınırı. Bir kariyer sayfası bundan uzunsa zaten
#: listeleme sayfasıdır ve ilk kısmı ilanları içerir.
MAX_INPUT_CHARS = 40_000

SYSTEM = """Sen bir iş ilanı çıkarım aracısın. Sana bir şirketin kariyer \
sayfasından çıkarılmış metin verilecek. Görevin, sayfadaki AÇIK İŞ İLANLARINI \
yapılandırılmış olarak listelemek.

Kurallar:
- Sadece sayfada gerçekten yer alan ilanları çıkar. İlan yoksa boş liste döndür.
- Hiçbir alanı uydurma. Sayfada yoksa null bırak.
- `title` ilanın kendi başlığı olmalı; "Açık Pozisyonlar", "Bize Katıl" gibi \
sayfa başlıkları ilan değildir.
- `description` alanına o ilana ait metni koy. Sayfa sadece başlık listeliyorsa \
description boş kalabilir.
- `apply_url` mutlak URL olmalı; sayfada göreli link varsa verilen temel adrese göre tamamla.
- Aynı ilan birden çok kez geçiyorsa bir kez döndür.
- Dil ne olursa olsun alan adlarını İngilizce şemaya göre doldur, içeriği \
kaynaktaki dilde bırak.

`is_listing_page`: sayfa bir veya daha fazla açık iş ilanı içeriyorsa true. Tek \
bir ilanın ayrıntı/başvuru sayfası da true kabul edilir. Kurumsal tanıtım, blog, \
genel kariyer sayfası (ilan başlığı yoksa) veya hata sayfasıysa false."""


class ExtractedJob(BaseModel):
    title: str
    location: str | None = None
    remote_type: Literal["onsite", "hybrid", "remote", "unknown"] = "unknown"
    seniority: str | None = None
    department: str | None = None
    employment_type: str | None = None
    description: str = ""
    apply_url: str | None = None
    apply_email: str | None = None


class ExtractionResult(BaseModel):
    is_listing_page: bool = Field(
        description="Sayfa açık iş ilanı listesi veya tekil ilan ayrıntısı içeriyor mu"
    )
    jobs: list[ExtractedJob] = Field(default_factory=list)


def prune_html(html: str, *, url: str) -> str:
    """HTML'i LLM'e uygun metne indirger. Ham HTML asla modele gönderilmez."""
    extracted = trafilatura.extract(
        html,
        url=url,
        include_links=True,  # başvuru bağlantıları korunmalı
        include_tables=True,
        favor_recall=True,
        output_format="markdown",
    )
    text = normalize_ws(extracted or "")
    return text[:MAX_INPUT_CHARS]


def extract_jobs(
    html: str, *, url: str, company_name: str, company_id: int | None = None
) -> list[RawJob]:
    """Sayfadan ilanları çıkarır. Sayfa ilan içermiyorsa boş liste döner."""
    text = prune_html(html, url=url)
    if len(text) < 200:
        # Budama sonrası neredeyse hiç metin kalmadıysa sayfa muhtemelen JS ile
        # doluyor; modeli boşuna çalıştırmayalım.
        raise AgentError(f"extract_jobs: {url} budandıktan sonra anlamlı metin kalmadı")

    settings = get_settings()
    result = call_structured(
        agent="extract_jobs",
        model=settings.model_extract,
        system=SYSTEM,
        # Değişken içerik sistem ön ekinden SONRA — önbellek ön eki bozulmasın
        user_content=(
            f"Şirket: {company_name}\nSayfa adresi: {url}\n\n--- SAYFA METNİ ---\n{text}"
        ),
        output_model=ExtractionResult,
        max_tokens=16000,
        company_id=company_id,
    )

    if not result.data.is_listing_page:
        log.info("extract_jobs: %s ilan listeleme sayfası değil", url)
        return []

    return [_to_raw_job(job, page_url=url) for job in result.data.jobs if job.title.strip()]


def _to_raw_job(job: ExtractedJob, *, page_url: str) -> RawJob:
    return RawJob(
        # Kaynakta kimlik yok; başlık+lokasyon+URL üzerinden kararlı kimlik üret
        external_id=stable_external_id(job.apply_url or page_url, job.title, job.location),
        title=job.title.strip(),
        apply_url=job.apply_url or page_url,
        location=job.location,
        remote_type=RemoteType(job.remote_type),
        seniority=job.seniority,
        department=job.department,
        employment_type=job.employment_type,
        description_md=job.description,
        apply_email=job.apply_email,
        apply_channel=ApplyChannel.EMAIL if job.apply_email else ApplyChannel.UNKNOWN,
        raw={"source": "llm_extract", "page_url": page_url},
    ).finalize()
