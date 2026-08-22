"""Workable hesap job board API — auth gerektirmez.

GET https://www.workable.com/api/accounts/{subdomain}?details=true
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType, RemoteType
from app.net import HttpClient
from app.util.text import html_to_text

BASE = "https://www.workable.com/api/accounts/{subdomain}?details=true"
_URL_SUB = re.compile(
    r"(?:apply\.workable\.com/([A-Za-z0-9_-]+)|workable\.com/api/accounts/([A-Za-z0-9_-]+))"
)


class WorkableAdapter(Adapter):
    type = AdapterType.WORKABLE
    config_key = "subdomain"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        subdomain = config.get("subdomain")
        if not subdomain:
            raise AdapterError("workable: 'subdomain' ayarı eksik")

        payload = await http.get_json(BASE.format(subdomain=subdomain))
        if not isinstance(payload, dict):
            raise AdapterError("workable: beklenmeyen yanıt")

        jobs: list[RawJob] = []
        for item in payload.get("jobs") or []:
            description = "\n\n".join(
                part
                for part in (
                    html_to_text(item.get("description")),
                    html_to_text(item.get("requirements")),
                    html_to_text(item.get("benefits")),
                )
                if part
            )
            jobs.append(
                RawJob(
                    external_id=str(item.get("shortcode") or item.get("id")),
                    title=item.get("title") or "",
                    apply_url=item.get("application_url") or item.get("url"),
                    location=_location(item),
                    remote_type=(
                        RemoteType.REMOTE if item.get("telecommuting") else RemoteType.UNKNOWN
                    ),
                    department=item.get("department"),
                    employment_type=item.get("employment_type"),
                    description_md=description,
                    posted_at=_parse_date(item.get("published_on") or item.get("created_at")),
                    raw=item,
                ).finalize()
            )
        return jobs

    def probe_urls(self, slug: str) -> list[str]:
        return [BASE.format(subdomain=slug)]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_SUB.search(url or "")
        if not match:
            return None
        return {"subdomain": match.group(1) or match.group(2)}


def _location(item: dict[str, Any]) -> str | None:
    parts = [item.get("city"), item.get("state"), item.get("country")]
    joined = ", ".join(p for p in parts if p)
    return joined or item.get("location") or None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None
