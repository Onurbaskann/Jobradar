"""L2 — schema.org/JobPosting yapısal verisi.

Birçok kurumsal kariyer sayfası Google for Jobs için zaten JSON-LD yayınlıyor.
Bu, LLM'e hiç uğramadan tam yapılandırılmış ilan almak demek: başlık, lokasyon,
tarih, istihdam tipi ve açıklama hepsi kaynakta etiketli.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

import extruct

from app.adapters.base import Adapter, AdapterError, RawJob, stable_external_id
from app.models import AdapterType, RemoteType
from app.net import HttpClient
from app.util.text import html_to_text

log = logging.getLogger(__name__)

MAX_PAGES = 3


class JsonLdAdapter(Adapter):
    """Verilen sayfalardaki JobPosting yapısal verisini okur.

    config: {"url": "..."} veya {"urls": ["...", "..."]}
    """

    type = AdapterType.JSONLD

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        urls = _config_urls(config)
        if not urls:
            raise AdapterError("jsonld: 'url' veya 'urls' ayarı eksik")

        jobs: list[RawJob] = []
        seen: set[str] = set()
        reachable = False

        for url in urls[:MAX_PAGES]:
            response = await http.probe_page(url)
            if response is None or response.status_code != 200:
                continue
            reachable = True
            for job in extract_job_postings(response.text, page_url=url):
                if job.external_id in seen:
                    continue
                seen.add(job.external_id)
                jobs.append(job)

        if not reachable:
            raise AdapterError(f"jsonld: hiçbir sayfa okunamadı ({', '.join(urls[:MAX_PAGES])})")
        return jobs


def _config_urls(config: dict[str, Any]) -> list[str]:
    urls = config.get("urls") or []
    if isinstance(urls, str):
        urls = [urls]
    single = config.get("url")
    if single:
        urls = [single, *urls]
    return [u for u in urls if u]


# --------------------------------------------------------------------------- parsing


def extract_job_postings(html: str, *, page_url: str) -> list[RawJob]:
    """Bir HTML sayfasındaki tüm JobPosting kayıtlarını çıkarır."""
    try:
        data = extruct.extract(
            html, base_url=page_url, syntaxes=["json-ld", "microdata"], uniform=True
        )
    except Exception:  # noqa: BLE001 — bozuk yapısal veri sayfayı düşürmesin
        log.debug("yapısal veri ayrıştırılamadı: %s", page_url, exc_info=True)
        return []

    jobs: list[RawJob] = []
    for item in _iter_items(data):
        if _type_of(item) != "jobposting":
            continue
        job = _to_raw_job(item, page_url=page_url)
        if job is not None:
            jobs.append(job)
    return jobs


def _iter_items(data: dict[str, list[Any]]):
    """json-ld ve microdata girdilerini düzleştir; @graph ve iç içe listeleri aç."""
    stack: list[Any] = []
    for syntax in ("json-ld", "microdata"):
        stack.extend(data.get(syntax) or [])

    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            yield item


def _type_of(item: dict[str, Any]) -> str:
    raw = item.get("@type") or item.get("type") or ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw).rsplit("/", 1)[-1].casefold()


def _to_raw_job(item: dict[str, Any], *, page_url: str) -> RawJob | None:
    title = _text(item.get("title")) or _text(item.get("name"))
    if not title:
        return None

    url = _text(item.get("url")) or page_url
    identifier = _identifier(item) or url
    description = html_to_text(_text(item.get("description")))

    return RawJob(
        external_id=stable_external_id(identifier, title),
        title=title,
        apply_url=url,
        location=_location(item),
        remote_type=_remote(item),
        employment_type=_text(item.get("employmentType")),
        department=_text(item.get("occupationalCategory") or None),
        description_md=description,
        posted_at=_parse_date(_text(item.get("datePosted"))),
        raw={"jsonld": _compact(item)},
    ).finalize()


def _identifier(item: dict[str, Any]) -> str | None:
    identifier = item.get("identifier")
    if isinstance(identifier, dict):
        return _text(identifier.get("value")) or _text(identifier.get("name"))
    return _text(identifier)


def _location(item: dict[str, Any]) -> str | None:
    location = item.get("jobLocation")
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return _text(location)

    address = location.get("address")
    if isinstance(address, list):
        address = address[0] if address else None
    if not isinstance(address, dict):
        return _text(address) or _text(location.get("name"))

    parts = [
        _text(address.get("addressLocality")),
        _text(address.get("addressRegion")),
        _text(address.get("addressCountry")),
    ]
    return ", ".join(p for p in parts if p) or None


def _remote(item: dict[str, Any]) -> RemoteType:
    if str(item.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return RemoteType.REMOTE
    return RemoteType.UNKNOWN


def _text(value: Any) -> str | None:
    """schema.org alanları string, dict ({"@value": ...}) veya liste olabilir."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _text(value.get("@value") or value.get("name"))
    if isinstance(value, list):
        for entry in value:
            text = _text(entry)
            if text:
                return text
        return None
    if isinstance(value, int | float | date | datetime):
        return str(value)
    return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    """Ham JSON-LD'yi saklarken devasa açıklama alanını tekrar tutma."""
    slim = {k: v for k, v in item.items() if k != "description"}
    try:
        json.dumps(slim, default=str)
    except (TypeError, ValueError):
        return {}
    return json.loads(json.dumps(slim, default=str))
