"""Recruitee offers API — auth gerektirmez.

GET https://{company}.recruitee.com/api/offers/
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType, RemoteType
from app.net import HttpClient
from app.util.text import html_to_text

BASE = "https://{company}.recruitee.com/api/offers/"
_URL_COMPANY = re.compile(r"([A-Za-z0-9_-]+)\.recruitee\.com")


class RecruiteeAdapter(Adapter):
    type = AdapterType.RECRUITEE
    config_key = "company"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        company = config.get("company")
        if not company:
            raise AdapterError("recruitee: 'company' ayarı eksik")

        payload = await http.get_json(BASE.format(company=company))
        if not isinstance(payload, dict):
            raise AdapterError("recruitee: beklenmeyen yanıt")

        jobs: list[RawJob] = []
        for item in payload.get("offers") or []:
            description = "\n\n".join(
                part
                for part in (
                    html_to_text(item.get("description")),
                    html_to_text(item.get("requirements")),
                )
                if part
            )
            jobs.append(
                RawJob(
                    external_id=str(item.get("id")),
                    title=item.get("title") or "",
                    apply_url=item.get("careers_apply_url") or item.get("careers_url"),
                    location=_location(item),
                    remote_type=(RemoteType.REMOTE if item.get("remote") else RemoteType.UNKNOWN),
                    department=item.get("department"),
                    employment_type=item.get("employment_type_code"),
                    description_md=description,
                    posted_at=_parse_date(item.get("published_at") or item.get("created_at")),
                    raw=item,
                ).finalize()
            )
        return jobs

    def probe_urls(self, slug: str) -> list[str]:
        return [BASE.format(company=slug)]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_COMPANY.search(url or "")
        return {"company": match.group(1)} if match else None


def _location(item: dict[str, Any]) -> str | None:
    parts = [item.get("city"), item.get("state_name"), item.get("country")]
    joined = ", ".join(p for p in parts if p)
    return joined or item.get("location") or None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
