"""L3 — sitemap üzerinden ilan detay sayfalarını keşfetme.

Kariyer sayfası ilanları listeliyor ama listede yapısal veri yoksa, ilanlar
genellikle ayrı detay sayfalarındadır ve o sayfalarda JSON-LD bulunur.
Sitemap bize o URL'leri ücretsiz ve deterministik olarak verir.

Sınırlar bilinçli: sitemap'ler on binlerce URL içerebilir, hepsini çekmek
ne kibar ne de gerekli.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit

from lxml import etree

from app.adapters.base import Adapter, AdapterError, RawJob
from app.adapters.jsonld import extract_job_postings
from app.models import AdapterType
from app.net import HttpClient

log = logging.getLogger(__name__)

MAX_SITEMAPS = 5
MAX_DETAIL_PAGES = 60

# Bir URL'nin ilan detay sayfası olduğunu düşündüren yollar
JOB_URL_HINT = re.compile(
    r"(/jobs?/|/careers?/|/kariyer/|/is-ilan|/isilan|/pozisyon|/vacanc|/opening|/position)",
    re.I,
)

# İlan detayı olmayan, kalıp olarak benzeyen sayfalar
JOB_URL_EXCLUDE = re.compile(
    r"(/blog/|/news/|/haber|/category/|/tag/|\.(pdf|jpg|png|svg|css|js)$)", re.I
)

_SITEMAP_IN_ROBOTS = re.compile(r"^\s*sitemap:\s*(\S+)", re.I | re.M)


class SitemapAdapter(Adapter):
    """config: {"domain": "..."} ve opsiyonel {"sitemap_url": "..."}"""

    type = AdapterType.SITEMAP

    async def fetch(self, http: HttpClient, config: dict[str, Any]) -> list[RawJob]:
        domain = config.get("domain")
        sitemap_url = config.get("sitemap_url")
        if not domain and not sitemap_url:
            raise AdapterError("sitemap: 'domain' veya 'sitemap_url' ayarı eksik")

        roots = [sitemap_url] if sitemap_url else await discover_sitemaps(http, domain)
        if not roots:
            raise AdapterError(f"sitemap: {domain} için sitemap bulunamadı")

        job_urls = await collect_job_urls(http, roots)
        if not job_urls:
            raise AdapterError("sitemap: ilan görünümlü URL bulunamadı")

        jobs: list[RawJob] = []
        seen: set[str] = set()
        for url in job_urls[:MAX_DETAIL_PAGES]:
            response = await http.probe_page(url)
            if response is None or response.status_code != 200:
                continue
            for job in extract_job_postings(response.text, page_url=url):
                if job.external_id in seen:
                    continue
                seen.add(job.external_id)
                jobs.append(job)

        if not jobs:
            raise AdapterError(
                f"sitemap: {len(job_urls)} aday sayfada JobPosting yapısal verisi yok"
            )
        return jobs


async def discover_sitemaps(http: HttpClient, domain: str) -> list[str]:
    """robots.txt'deki Sitemap satırları, yoksa /sitemap.xml."""
    origin = f"https://{domain}"
    found: list[str] = []

    robots = await http.probe(f"{origin}/robots.txt")
    if robots is not None and robots.status_code == 200:
        found.extend(_SITEMAP_IN_ROBOTS.findall(robots.text))

    if not found:
        found.append(f"{origin}/sitemap.xml")

    # Kariyer görünümlü sitemap'leri öne al. Büyük siteler onlarca sitemap
    # yayınlar (ürün, kategori, marka...) ve bütçemiz MAX_SITEMAPS ile sınırlı;
    # sıralamazsak bütçe alakasız sitemap'lerde tükenir.
    found.sort(key=lambda u: 0 if JOB_URL_HINT.search(u) else 1)
    return found[:MAX_SITEMAPS]


async def collect_job_urls(http: HttpClient, roots: list[str]) -> list[str]:
    """Sitemap (ve sitemap index) ağacını gezip ilan görünümlü URL'leri toplar."""
    queue = list(roots)
    visited: set[str] = set()
    job_urls: list[str] = []
    seen_jobs: set[str] = set()

    while queue and len(visited) < MAX_SITEMAPS:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        response = await http.probe_page(url)
        if response is None or response.status_code != 200:
            continue

        children, pages = _parse_sitemap(response.content)

        # Alt sitemap'lerde önce kariyer/iş geçenleri sıraya al — bütçe onlara gitsin
        children.sort(key=lambda u: 0 if JOB_URL_HINT.search(u) else 1)
        queue.extend(children)

        for page in pages:
            if page in seen_jobs:
                continue
            if JOB_URL_EXCLUDE.search(page) or not JOB_URL_HINT.search(page):
                continue
            seen_jobs.add(page)
            job_urls.append(page)

    return job_urls


def _parse_sitemap(content: bytes) -> tuple[list[str], list[str]]:
    """(alt sitemap URL'leri, sayfa URL'leri) döner."""
    try:
        root = etree.fromstring(content)
    except etree.XMLSyntaxError:
        return [], []

    children: list[str] = []
    pages: list[str] = []
    for element in root.iter():
        tag = etree.QName(element).localname if element.tag is not etree.Comment else ""
        if tag != "loc" or not element.text:
            continue
        loc = element.text.strip()
        if not loc.startswith(("http://", "https://")):
            continue
        parent_tag = (
            etree.QName(element.getparent()).localname if element.getparent() is not None else ""
        )
        if parent_tag == "sitemap":
            children.append(loc)
        else:
            pages.append(loc)
    return children, pages


def same_host(url: str, domain: str) -> bool:
    host = urlsplit(url).netloc.removeprefix("www.")
    return host == domain.removeprefix("www.") or host.endswith(f".{domain}")
