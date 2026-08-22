from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models import RemoteType


@dataclass(frozen=True, slots=True)
class SearchQuery:
    term: str
    location: str
    remote_only: bool
    hours_old: int
    results_wanted: int


@dataclass(slots=True)
class DiscoveredJob:
    source: str
    title: str
    company_name: str
    location: str | None = None
    remote_type: RemoteType = RemoteType.UNKNOWN
    description_md: str = ""
    apply_url: str | None = None
    posted_at: datetime | None = None


class JobSource(Protocol):
    name: str

    async def discover(self, query: SearchQuery) -> list[DiscoveredJob]: ...
