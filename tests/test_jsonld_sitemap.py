"""L2 (JSON-LD) ve L3 (sitemap) katman testleri."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.adapters.base import AdapterError
from app.adapters.jsonld import JsonLdAdapter, extract_job_postings
from app.adapters.sitemap import SitemapAdapter, collect_job_urls, discover_sitemaps
from app.models import RemoteType
from app.net import HttpClient

JOB_JSONLD = """
<html><head><script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "JobPosting",
  "title": "Kıdemli Python Geliştirici",
  "identifier": {"@type": "PropertyValue", "name": "acme", "value": "PY-42"},
  "datePosted": "2026-07-01",
  "employmentType": "FULL_TIME",
  "description": "<p>Django ve PostgreSQL.</p><ul><li>5 yıl deneyim</li></ul>",
  "hiringOrganization": {"@type": "Organization", "name": "Acme"},
  "jobLocation": {
    "@type": "Place",
    "address": {
      "@type": "PostalAddress",
      "addressLocality": "İstanbul",
      "addressCountry": "TR"
    }
  },
  "url": "https://acme.com/kariyer/python-gelistirici"
}
</script></head><body></body></html>
"""

REMOTE_JOB_IN_GRAPH = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"Organization","name":"Acme"},
  {"@type":"JobPosting","title":"Remote SRE","jobLocationType":"TELECOMMUTE",
   "description":"Kubernetes.","url":"https://acme.com/kariyer/sre"}
]}
</script></head></html>
"""


@pytest.fixture
def http() -> HttpClient:
    return HttpClient(domain_delay=0.0, max_retries=0, respect_robots=False)


def test_extract_job_posting_fields() -> None:
    jobs = extract_job_postings(JOB_JSONLD, page_url="https://acme.com/kariyer")
    assert len(jobs) == 1

    job = jobs[0]
    assert job.title == "Kıdemli Python Geliştirici"
    assert job.location == "İstanbul, TR"
    assert job.employment_type == "FULL_TIME"
    assert job.apply_url == "https://acme.com/kariyer/python-gelistirici"
    assert job.posted_at is not None and job.posted_at.year == 2026
    # Açıklama HTML'i düz metne çevrilmeli
    assert "Django ve PostgreSQL." in job.description_md
    assert "- 5 yıl deneyim" in job.description_md
    assert "<p>" not in job.description_md


def test_extract_handles_graph_and_remote_flag() -> None:
    jobs = extract_job_postings(REMOTE_JOB_IN_GRAPH, page_url="https://acme.com/kariyer")
    assert len(jobs) == 1, "@graph içindeki JobPosting bulunmalı, Organization atlanmalı"
    assert jobs[0].remote_type is RemoteType.REMOTE


def test_extract_returns_empty_without_structured_data() -> None:
    assert extract_job_postings("<html><body>iş yok</body></html>", page_url="https://x/") == []


def test_extract_survives_broken_json() -> None:
    broken = '<script type="application/ld+json">{ bozuk json </script>'
    assert extract_job_postings(broken, page_url="https://x/") == []


@respx.mock
async def test_jsonld_adapter_deduplicates_across_pages(http: HttpClient) -> None:
    """Aynı ilan iki sayfada göründüğünde tek kayıt üretilmeli."""
    respx.get(url__regex=r"^https://acme\.com/(kariyer|careers)$").mock(
        return_value=httpx.Response(200, html=JOB_JSONLD)
    )

    jobs = await JsonLdAdapter().fetch(
        http, {"urls": ["https://acme.com/kariyer", "https://acme.com/careers"]}
    )
    await http.aclose()

    assert len(jobs) == 1


@respx.mock
async def test_jsonld_adapter_raises_when_no_page_reachable(http: HttpClient) -> None:
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    with pytest.raises(AdapterError):
        await JsonLdAdapter().fetch(http, {"url": "https://acme.com/kariyer"})
    await http.aclose()


SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://acme.com/sitemap-blog.xml</loc></sitemap>
  <sitemap><loc>https://acme.com/sitemap-kariyer.xml</loc></sitemap>
</sitemapindex>
"""

SITEMAP_JOBS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://acme.com/kariyer/python-gelistirici</loc></url>
  <url><loc>https://acme.com/kariyer/sre</loc></url>
  <url><loc>https://acme.com/blog/nasil-calisiyoruz</loc></url>
  <url><loc>https://acme.com/hakkimizda</loc></url>
</urlset>
"""


@respx.mock
async def test_collect_job_urls_filters_and_follows_index(http: HttpClient) -> None:
    respx.get("https://acme.com/sitemap.xml").mock(
        return_value=httpx.Response(200, content=SITEMAP_INDEX.encode())
    )
    respx.get("https://acme.com/sitemap-kariyer.xml").mock(
        return_value=httpx.Response(200, content=SITEMAP_JOBS.encode())
    )
    respx.get("https://acme.com/sitemap-blog.xml").mock(
        return_value=httpx.Response(200, content=SITEMAP_JOBS.encode())
    )

    urls = await collect_job_urls(http, ["https://acme.com/sitemap.xml"])
    await http.aclose()

    assert "https://acme.com/kariyer/python-gelistirici" in urls
    assert "https://acme.com/kariyer/sre" in urls
    # Blog ve kurumsal sayfalar ilan adayı sayılmamalı
    assert not any("/blog/" in u for u in urls)
    assert not any("hakkimizda" in u for u in urls)


@respx.mock
async def test_discover_sitemaps_prefers_career_looking_ones(http: HttpClient) -> None:
    """Büyük siteler onlarca sitemap yayınlar; sınırlı bütçe kariyere ayrılmalı.

    Gerçek örnek: hepsiburada.com robots.txt'sinde beş sitemap var ve hepsi
    ürün/kategori — sıralamazsak bütçe kariyere hiç ulaşamıyor.
    """
    robots = (
        "\n".join(
            f"Sitemap: https://acme.com/sitemaps/{name}/sitemap.xml"
            for name in ("product", "category", "brand", "review", "collection")
        )
        + "\nSitemap: https://acme.com/sitemaps/kariyer/sitemap.xml\n"
    )
    respx.get("https://acme.com/robots.txt").mock(return_value=httpx.Response(200, text=robots))

    roots = await discover_sitemaps(http, "acme.com")
    await http.aclose()

    assert roots[0] == "https://acme.com/sitemaps/kariyer/sitemap.xml"
    assert len(roots) <= 5


@respx.mock
async def test_sitemap_adapter_end_to_end(http: HttpClient) -> None:
    respx.get("https://acme.com/robots.txt").mock(
        return_value=httpx.Response(200, text="Sitemap: https://acme.com/sitemap-kariyer.xml\n")
    )
    respx.get("https://acme.com/sitemap-kariyer.xml").mock(
        return_value=httpx.Response(200, content=SITEMAP_JOBS.encode())
    )
    respx.get(url__regex=r"^https://acme\.com/kariyer/.+$").mock(
        return_value=httpx.Response(200, html=JOB_JSONLD)
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    jobs = await SitemapAdapter().fetch(http, {"domain": "acme.com"})
    await http.aclose()

    # İki detay sayfası da aynı JSON-LD'yi döndürüyor → tekilleştirilmeli
    assert len(jobs) == 1
    assert jobs[0].title == "Kıdemli Python Geliştirici"


@respx.mock
async def test_sitemap_adapter_raises_when_pages_lack_structured_data(http: HttpClient) -> None:
    """İlan URL'leri bulunsa da yapısal veri yoksa bu katman başarısız sayılmalı.

    Aksi halde şirket "aktif" görünür ama hiç ilan üretmez ve sessizce ölü kalır.
    """
    respx.get("https://acme.com/robots.txt").mock(
        return_value=httpx.Response(200, text="Sitemap: https://acme.com/sitemap-kariyer.xml\n")
    )
    respx.get("https://acme.com/sitemap-kariyer.xml").mock(
        return_value=httpx.Response(200, content=SITEMAP_JOBS.encode())
    )
    respx.get(url__regex=r"^https://acme\.com/kariyer/.+$").mock(
        return_value=httpx.Response(200, html="<html><body>ilan</body></html>")
    )
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    with pytest.raises(AdapterError, match="JobPosting"):
        await SitemapAdapter().fetch(http, {"domain": "acme.com"})
    await http.aclose()
