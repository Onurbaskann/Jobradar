"""SmartRecruiters posting API — auth gerektirmez.

GET https://api.smartrecruiters.com/v1/companies/{company}/postings?offset=&limit=100
Liste yanıtı açıklama içermez; açıklama için ilan başına detay çağrısı gerekir.
Detay çağrılarını `detail_limit` ile sınırlıyoruz ki bir şirket yüzlerce istek doğurmasın.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from app.adapters.base import Adapter, AdapterError, RawJob, redirect_kept_slug
from app.models import AdapterType, RemoteType
from app.net import HttpClient
from app.util.text import html_to_text

LIST_URL = (
    "https://api.smartrecruiters.com/v1/companies/{company}/postings?offset={offset}&limit={limit}"
)
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"
_URL_COMPANY = re.compile(
    r"(?:careers\.smartrecruiters\.com|jobs\.smartrecruiters\.com|api\.smartrecruiters\.com/v1/companies)/([A-Za-z0-9_.-]+)"
)

PAGE_SIZE = 100
MAX_PAGES = 10


class SmartRecruitersAdapter(Adapter):
    type = AdapterType.SMARTRECRUITERS
    config_key = "company"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        company = config.get("company")
        if not company:
            raise AdapterError("smartrecruiters: 'company' ayarı eksik")
        detail_limit = int(config.get("detail_limit", 50))

        postings = await self._list_postings(http, company)

        jobs: list[RawJob] = []
        for index, item in enumerate(postings):
            posting_id = str(item.get("id"))
            location = item.get("location") or {}
            description = ""
            if index < detail_limit:
                description = await self._description(http, company, posting_id)

            jobs.append(
                RawJob(
                    external_id=posting_id,
                    title=item.get("name") or "",
                    apply_url=item.get("applyUrl")
                    or f"https://jobs.smartrecruiters.com/{company}/{posting_id}",
                    location=_location(location),
                    remote_type=(
                        RemoteType.REMOTE if location.get("remote") else RemoteType.UNKNOWN
                    ),
                    department=(item.get("department") or {}).get("label"),
                    employment_type=(item.get("typeOfEmployment") or {}).get("label"),
                    description_md=description,
                    posted_at=_parse_date(item.get("releasedDate")),
                    raw=item,
                ).finalize()
            )
        return jobs

    async def _list_postings(self, http: HttpClient, company: str) -> list[dict[str, Any]]:
        postings: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            url = LIST_URL.format(company=company, offset=page * PAGE_SIZE, limit=PAGE_SIZE)
            payload = await http.get_json(url)
            if not isinstance(payload, dict):
                raise AdapterError("smartrecruiters: beklenmeyen yanıt")
            batch = payload.get("content") or []
            postings.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
        return postings

    async def _description(self, http: HttpClient, company: str, posting_id: str) -> str:
        """Detay çağrısı başarısız olursa ilanı düşürmek yerine açıklamasız devam et."""
        try:
            payload = await http.get_json(DETAIL_URL.format(company=company, posting_id=posting_id))
        except httpx.HTTPError:
            return ""
        if not isinstance(payload, dict):
            return ""

        job_ad = payload.get("jobAd") or {}
        sections = (job_ad.get("sections") or {}).values()
        parts: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            title = section.get("title")
            body = html_to_text(section.get("text"))
            if title and body:
                parts.append(f"{title}\n{body}")
            elif body:
                parts.append(body)
        return "\n\n".join(parts)

    def probe_urls(self, slug: str) -> list[str]:
        return [LIST_URL.format(company=slug, offset=0, limit=1)]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_COMPANY.search(url or "")
        return {"company": match.group(1)} if match else None

    async def probe(self, http: HttpClient, slug: str) -> dict[str, Any] | None:
        """Varsayılan probe tam fetch yapardı — bu ATS'te o, ilan başına bir detay
        çağrısı demek. Burada sadece liste ucunun ilan döndürdüğünü doğruluyoruz."""
        for url in self.probe_urls(slug):
            response = await http.probe(url)
            if response is None or response.status_code != 200:
                continue
            if not redirect_kept_slug(response, slug):
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("content"):
                return self.config_from_probe(url)
        return None


def _location(location: dict[str, Any]) -> str | None:
    parts = [location.get("city"), location.get("region"), location.get("country")]
    return ", ".join(p for p in parts if p) or None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
