"""Greenhouse job board API — auth gerektirmez.

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType
from app.net import HttpClient
from app.util.text import html_to_text

BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
_URL_TOKEN = re.compile(
    r"(?:boards\.greenhouse\.io|job-boards\.greenhouse\.io|boards-api\.greenhouse\.io/v1/boards)/([A-Za-z0-9_-]+)"
)


class GreenhouseAdapter(Adapter):
    type = AdapterType.GREENHOUSE
    config_key = "token"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        token = config.get("token")
        if not token:
            raise AdapterError("greenhouse: 'token' ayarı eksik")

        payload = await http.get_json(BASE.format(token=token))
        if not isinstance(payload, dict):
            raise AdapterError("greenhouse: beklenmeyen yanıt")

        jobs: list[RawJob] = []
        for item in payload.get("jobs") or []:
            location = (item.get("location") or {}).get("name")
            departments = [d.get("name") for d in item.get("departments") or [] if d.get("name")]
            jobs.append(
                RawJob(
                    external_id=str(item.get("id")),
                    title=item.get("title") or "",
                    apply_url=item.get("absolute_url"),
                    location=location,
                    department=", ".join(departments) or None,
                    description_md=html_to_text(item.get("content")),
                    posted_at=_parse_date(item.get("updated_at") or item.get("first_published")),
                    raw=item,
                ).finalize()
            )
        return jobs

    def probe_urls(self, slug: str) -> list[str]:
        return [BASE.format(token=slug)]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_TOKEN.search(url or "")
        return {"token": match.group(1)} if match else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
