"""L4 — LLM çıkarım adaptörü.

Kademenin son basamağı. Buraya yalnızca L1/L2/L3'ün hiçbiri tutmayan şirketler
düşer ve tarama döngüsü bu adaptörü ancak sayfa hash'i değiştiğinde çağırır
(bkz. `app/pipeline/crawl.py`), böylece her tarama değil sadece gerçek
değişiklikler modele para ödetir.
"""

from __future__ import annotations

import logging
from typing import Any

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType
from app.net import HttpClient
from app.util.text import content_hash

log = logging.getLogger(__name__)

MAX_PAGES = 2


class LlmExtractAdapter(Adapter):
    """config: {"urls": [...], "company_name": "..."} (veya tek "url")"""

    type = AdapterType.LLM

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        # Çağrı anında import: adaptör kaydı ile ajan modülü birbirini import
        # ediyor; üst seviyede tutulursa dairesel import oluşuyor.
        from app.agents.extract_jobs import extract_jobs

        urls = _config_urls(config)
        if not urls:
            raise AdapterError("llm: 'url' veya 'urls' ayarı eksik")
        company_name = config.get("company_name") or ""
        company_id = config.get("company_id")

        jobs: list[RawJob] = []
        seen: set[str] = set()
        reachable = False

        for url in urls[:MAX_PAGES]:
            response = await http.probe_page(url)
            if response is None or response.status_code != 200:
                continue
            reachable = True

            for job in extract_jobs(
                response.text, url=url, company_name=company_name, company_id=company_id
            ):
                if job.external_id in seen:
                    continue
                seen.add(job.external_id)
                jobs.append(job)

        if not reachable:
            raise AdapterError(f"llm: hiçbir sayfa okunamadı ({', '.join(urls[:MAX_PAGES])})")
        return jobs

    async def source_fingerprint(self, http: HttpClient, config: dict[str, Any]) -> str | None:
        """Sayfaların ham içeriğinden imza — model çağrılmadan önce kontrol edilir.

        Bu, tüm maliyet modelinin dayandığı kanca: imza değişmediyse `fetch`
        hiç çalışmaz, dolayısıyla LLM'e tek token gitmez.
        """
        urls = _config_urls(config)
        if not urls:
            return None

        parts: list[str] = []
        for url in urls[:MAX_PAGES]:
            response = await http.probe_page(url)
            if response is None or response.status_code != 200:
                continue
            parts.append(response.text)
        return content_hash(*parts) if parts else None


def _config_urls(config: dict[str, Any]) -> list[str]:
    urls = config.get("urls") or []
    if isinstance(urls, str):
        urls = [urls]
    single = config.get("url")
    if single:
        urls = [single, *urls]
    return [u for u in urls if u]
