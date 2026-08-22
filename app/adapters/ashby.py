"""Ashby posting API — auth gerektirmez.

GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.adapters.base import Adapter, AdapterError, RawJob
from app.models import AdapterType, RemoteType
from app.net import HttpClient
from app.util.text import html_to_text

BASE = "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
_URL_BOARD = re.compile(
    r"(?:jobs\.ashbyhq\.com|ashbyhq\.com/posting-api/job-board)/([A-Za-z0-9_.-]+)"
)


class AshbyAdapter(Adapter):
    type = AdapterType.ASHBY
    config_key = "board"

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        board = config.get("board")
        if not board:
            raise AdapterError("ashby: 'board' ayarı eksik")

        payload = await http.get_json(BASE.format(board=board))
        if not isinstance(payload, dict):
            raise AdapterError("ashby: beklenmeyen yanıt")

        jobs: list[RawJob] = []
        for item in payload.get("jobs") or []:
            jobs.append(
                RawJob(
                    external_id=str(item.get("id")),
                    title=item.get("title") or "",
                    apply_url=item.get("applyUrl") or item.get("jobUrl"),
                    location=item.get("location"),
                    remote_type=_remote(item),
                    department=item.get("department") or item.get("team"),
                    employment_type=item.get("employmentType"),
                    description_md=(
                        item.get("descriptionPlain") or html_to_text(item.get("descriptionHtml"))
                    ),
                    posted_at=_parse_date(item.get("publishedAt") or item.get("updatedAt")),
                    raw=item,
                ).finalize()
            )
        return jobs

    def probe_urls(self, slug: str) -> list[str]:
        return [BASE.format(board=slug)]

    def config_from_url(self, url: str) -> dict[str, Any] | None:
        match = _URL_BOARD.search(url or "")
        return {"board": match.group(1)} if match else None


def _remote(item: dict[str, Any]) -> RemoteType:
    workplace = (item.get("workplaceType") or "").casefold()
    if workplace in {"remote", "hybrid", "onsite"}:
        return RemoteType(workplace)
    if item.get("isRemote") is True:
        return RemoteType.REMOTE
    return RemoteType.UNKNOWN


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
