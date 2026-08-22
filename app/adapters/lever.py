"""Lever postings API — auth gerektirmez.

GET https://api.lever.co/v0/postings/{site}?mode=json
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType, RemoteType
from app.net import HttpClient
from app.util.text import html_to_text

BASE = "https://api.lever.co/v0/postings/{site}?mode=json"
_URL_SITE = re.compile(r"(?:jobs\.lever\.co|api\.lever\.co/v0/postings)/([A-Za-z0-9_-]+)")


class LeverAdapter(Adapter):
    type = AdapterType.LEVER
    config_key = "site"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        site = config.get("site")
        if not site:
            raise AdapterError("lever: 'site' ayarı eksik")

        payload = await http.get_json(BASE.format(site=site))
        if not isinstance(payload, list):
            raise AdapterError("lever: beklenmeyen yanıt")

        jobs: list[RawJob] = []
        for item in payload:
            categories = item.get("categories") or {}
            location = categories.get("location")
            workplace = (item.get("workplaceType") or "").casefold()
            remote = {
                "remote": RemoteType.REMOTE,
                "hybrid": RemoteType.HYBRID,
                "onsite": RemoteType.ONSITE,
            }.get(workplace, RemoteType.UNKNOWN)

            jobs.append(
                RawJob(
                    external_id=str(item.get("id")),
                    title=item.get("text") or "",
                    apply_url=item.get("applyUrl") or item.get("hostedUrl"),
                    location=location,
                    remote_type=remote,
                    seniority=categories.get("level"),
                    department=categories.get("team") or categories.get("department"),
                    employment_type=categories.get("commitment"),
                    description_md=_description(item),
                    posted_at=_from_epoch_ms(item.get("createdAt")),
                    raw=item,
                ).finalize()
            )
        return jobs

    def probe_urls(self, slug: str) -> list[str]:
        return [BASE.format(site=slug)]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_SITE.search(url or "")
        return {"site": match.group(1)} if match else None


def _description(item: dict[str, Any]) -> str:
    """Lever açıklamayı gövde + 'lists' bölümleri olarak ikiye böler; ikisini birleştir."""
    parts = [item.get("descriptionPlain") or html_to_text(item.get("description"))]
    for block in item.get("lists") or []:
        heading = block.get("text")
        body = html_to_text(block.get("content"))
        if heading:
            parts.append(f"\n{heading}\n{body}")
        elif body:
            parts.append(body)
    parts.append(item.get("additionalPlain") or html_to_text(item.get("additional")))
    return "\n\n".join(p for p in parts if p).strip()


def _from_epoch_ms(value: object) -> datetime | None:
    if not isinstance(value, int | float):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
