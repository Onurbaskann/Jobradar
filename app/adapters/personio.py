"""Personio XML feed — auth gerektirmez.

GET https://{company}.jobs.personio.de/xml?language=tr
Tek XML yanıtı gelir; sayfalama yoktur.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from lxml import etree

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType
from app.net import HttpClient
from app.util.text import html_to_text

BASE = "https://{company}.jobs.personio.de/xml?language={language}"
_URL_COMPANY = re.compile(r"([A-Za-z0-9_-]+)\.jobs\.personio\.(?:de|com)")


class PersonioAdapter(Adapter):
    type = AdapterType.PERSONIO
    config_key = "company"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        company = config.get("company")
        if not company:
            raise AdapterError("personio: 'company' ayarı eksik")
        language = config.get("language", "tr")

        text = await http.get_text(BASE.format(company=company, language=language))
        try:
            root = etree.fromstring(text.encode("utf-8"))
        except etree.XMLSyntaxError as exc:
            raise AdapterError(f"personio: XML ayrıştırılamadı ({exc})") from exc

        jobs: list[RawJob] = []
        for position in root.iter("position"):
            job_id = _text(position, "id")
            if not job_id:
                continue
            title = _text(position, "name") or ""
            jobs.append(
                RawJob(
                    external_id=job_id,
                    title=title,
                    apply_url=_text(position, "url")
                    or f"https://{company}.jobs.personio.de/job/{job_id}",
                    location=_text(position, "office"),
                    seniority=_text(position, "seniority"),
                    department=_text(position, "department"),
                    employment_type=_text(position, "employmentType"),
                    description_md=_descriptions(position),
                    posted_at=_parse_date(_text(position, "createdAt")),
                    raw={"id": job_id, "title": title},
                ).finalize()
            )
        return jobs

    def probe_urls(self, slug: str) -> list[str]:
        return [BASE.format(company=slug, language="tr")]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_COMPANY.search(url or "")
        return {"company": match.group(1)} if match else None


def _text(node: etree._Element, tag: str) -> str | None:
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def _descriptions(position: etree._Element) -> str:
    """Personio açıklamayı başlıklı bölümler halinde verir; hepsini birleştir."""
    parts: list[str] = []
    for block in position.iter("jobDescription"):
        heading = _text(block, "name")
        body = html_to_text(_text(block, "value"))
        if heading and body:
            parts.append(f"{heading}\n{body}")
        elif body:
            parts.append(body)
    return "\n\n".join(parts)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
