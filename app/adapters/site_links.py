"""Şirketin kendi sitesinden ATS bağlantısı bulma — yetkili (authoritative) tespit.

Neden gerekli: slug tahmini tek başına güvenilmez. Gerçek ölçümde 5 tahminden
2'si yanlış çıktı — `greenhouse/peak` bir Teksas fizik tedavi zinciri,
`greenhouse/insider` ise Business Insider. Bir ATS panosunun gerçekten o şirkete
ait olduğunun tek ucuz kanıtı, şirketin kendi alan adının o panoya link vermesi.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from app.adapters.registry import detect_from_url
from app.models import AdapterType
from app.net import HttpClient

log = logging.getLogger(__name__)

# Kök sayfada denenecek kariyer yolları (kök sayfada link bulunamazsa)
CAREER_PATHS = ("/careers", "/kariyer", "/jobs", "/en/careers", "/tr/kariyer")

# Kariyer sayfası sıklıkla ayrı bir alt alan adında durur. Bu ayrıca kök sayfanın
# bot korumasıyla 403 döndüğü durumları da kurtarır (ör. trendyol.com → 403,
# careers.trendyol.com → 200 ve Lever bağlantısını içeriyor).
CAREER_SUBDOMAINS = ("careers", "kariyer", "jobs", "job")

# Bir bağlantının kariyer sayfası olduğunu düşündüren ipuçları
_CAREER_HINT = re.compile(r"(career|kariyer|job|is-ilan|isilan|join-us|bize-katil)", re.I)

# SPA'larda ATS adresi HTML'de link olarak değil, script/JSON içinde geçebilir.
# Bu yüzden ham metni de tarıyoruz.
_ATS_IN_TEXT = re.compile(
    r"https?://(?:"
    r"boards\.greenhouse\.io/[A-Za-z0-9_-]+"
    r"|job-boards\.greenhouse\.io/[A-Za-z0-9_-]+"
    r"|jobs\.lever\.co/[A-Za-z0-9_-]+"
    r"|jobs\.ashbyhq\.com/[A-Za-z0-9_.-]+"
    r"|apply\.workable\.com/[A-Za-z0-9_-]+"
    r"|[A-Za-z0-9_-]+\.recruitee\.com"
    r"|[A-Za-z0-9_-]+\.jobs\.personio\.(?:de|com)"
    r"|careers\.smartrecruiters\.com/[A-Za-z0-9_.-]+"
    r"|jobs\.smartrecruiters\.com/[A-Za-z0-9_.-]+"
    r")",
    re.I,
)

MAX_PAGES = 8


@dataclass(slots=True)
class SiteMatch:
    adapter_type: AdapterType
    config: dict[str, Any]
    evidence_url: str  # ATS bağlantısının bulunduğu sayfa


async def find_ats_link(http: HttpClient, domain: str) -> SiteMatch | None:
    """Şirketin sitesinde bilinen bir ATS'e giden bağlantı ara.

    En fazla `MAX_PAGES` sayfa çeker: kök sayfa, kariyer alt alan adları,
    sayfalardan çıkarılan kariyer bağlantıları ve birkaç sabit kariyer yolu.
    """
    root = f"https://{domain}"
    bare = domain.removeprefix("www.")

    visited: set[str] = set()
    queue: list[str] = [root]
    queue.extend(f"https://{sub}.{bare}" for sub in CAREER_SUBDOMAINS)
    expanded = False

    while queue and len(visited) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        html = await _fetch(http, url)
        if html is None:
            continue

        match = _match_in_page(html, base_url=url)
        if match:
            return match

        # Erişilebilen ilk sayfadan kariyer bağlantılarını genişlet.
        # Kök sayfaya bağlamıyoruz: bazı siteler kökü bot koruması ile 403 döner.
        if not expanded:
            expanded = True
            queue.extend(_career_links(html, base_url=url))
            queue.extend(f"{root}{path}" for path in CAREER_PATHS)

    return None


async def _fetch(http: HttpClient, url: str) -> str | None:
    # Şirketin kendi sitesini geziyoruz — robots.txt burada geçerli
    response = await http.probe_page(url)
    if response is None or response.status_code != 200:
        return None
    if "html" not in response.headers.get("content-type", ""):
        return None
    return response.text


def _match_in_page(html: str, *, base_url: str) -> SiteMatch | None:
    tree = HTMLParser(html)

    # 1) Gerçek <a href> bağlantıları — en güçlü kanıt
    for node in tree.css("a[href]"):
        href = urljoin(base_url, node.attributes.get("href") or "")
        detected = detect_from_url(href)
        if detected:
            adapter_type, config = detected
            return SiteMatch(adapter_type, config, evidence_url=base_url)

    # 2) Script/JSON gövdesinde geçen ATS adresleri — SPA kariyer sayfaları için
    for raw_url in _ATS_IN_TEXT.findall(html):
        detected = detect_from_url(raw_url)
        if detected:
            adapter_type, config = detected
            return SiteMatch(adapter_type, config, evidence_url=base_url)

    return None


def _career_links(html: str, *, base_url: str) -> list[str]:
    """Kök sayfadaki kariyer sayfası adaylarını döner (aynı alan adıyla sınırlı)."""
    tree = HTMLParser(html)
    links: list[str] = []
    seen: set[str] = set()

    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        text = node.text(deep=True) or ""
        if not _CAREER_HINT.search(href) and not _CAREER_HINT.search(text):
            continue
        absolute = urljoin(base_url, href).split("#")[0]
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)

    return links[:3]
