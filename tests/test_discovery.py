from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.discovery.contracts import DiscoveredJob, SearchQuery
from app.discovery.service import lead_fingerprint
from app.discovery.sources import (
    SourceUnavailable,
    TurkiyeWebSource,
    map_jobspy_row,
    map_turkiye_web_result,
)
from app.models import RemoteType


def test_fingerprint_merges_source_formatting_differences() -> None:
    first = DiscoveredJob(
        source="indeed",
        title="Senior .NET Developer",
        company_name="Acme Yazılım",
        location="İstanbul",
    )
    second = DiscoveredJob(
        source="tracked:lever",
        title="  SENIOR .net developer ",
        company_name="ACME YAZILIM",
        location="istanbul",
    )

    assert lead_fingerprint(first) == lead_fingerprint(second)


def test_fingerprint_keeps_different_locations_separate() -> None:
    istanbul = DiscoveredJob("indeed", ".NET Developer", "Acme", "İstanbul")
    ankara = DiscoveredJob("indeed", ".NET Developer", "Acme", "Ankara")

    assert lead_fingerprint(istanbul) != lead_fingerprint(ankara)


def test_jobspy_row_maps_to_canonical_contract() -> None:
    result = map_jobspy_row(
        {
            "site": "indeed",
            "title": "Backend Developer",
            "company": "Acme",
            "location": "Türkiye",
            "is_remote": True,
            "description": "C# ve .NET",
            "job_url": "https://example.com/jobs/1",
            "date_posted": "2026-08-21T12:00:00Z",
        }
    )

    assert result.source == "indeed"
    assert result.remote_type is RemoteType.REMOTE
    assert result.apply_url == "https://example.com/jobs/1"
    assert result.posted_at == datetime(2026, 8, 21, 12, tzinfo=UTC)


def test_turkiye_web_result_maps_yenibiris_title_and_company() -> None:
    result = map_turkiye_web_result(
        {
            "title": (
                "ACME YAZILIM A.Ş. - İstanbul Senior .NET Developer "
                "İş İlanları - Yenibiris.com"
            ),
            "url": "https://www.yenibiris.com/is-ilani/senior-net-developer/12345",
            "description": "Hibrit çalışma, C# ve ASP.NET Core",
        },
        "İstanbul",
    )

    assert result is not None
    assert result.source == "web:yenibiris.com"
    assert result.title == "Senior .NET Developer"
    assert result.company_name == "ACME YAZILIM A.Ş."
    assert result.location == "İstanbul"


def test_turkiye_web_result_rejects_unapproved_domain() -> None:
    assert (
        map_turkiye_web_result(
            {"title": "Backend Developer", "url": "https://example.com/jobs/1"}
        )
        is None
    )


@pytest.mark.asyncio
async def test_turkiye_web_source_requires_api_key() -> None:
    with pytest.raises(SourceUnavailable, match="BRAVE_SEARCH_API_KEY"):
        await TurkiyeWebSource("").discover(
            SearchQuery(".NET Developer", "Türkiye", False, 168, 10)
        )


@pytest.mark.asyncio
@respx.mock
async def test_turkiye_web_source_uses_site_filtered_brave_search() -> None:
    route = respx.get(TurkiyeWebSource.endpoint).mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Backend Developer | Kariyer.net",
                            "url": "https://www.kariyer.net/is-ilani/backend-developer-123",
                            "description": "Uzaktan çalışma imkanı",
                        }
                    ]
                }
            },
        )
    )

    jobs = await TurkiyeWebSource("test-key").discover(
        SearchQuery("Backend Developer", "Türkiye", False, 168, 10)
    )

    assert len(jobs) == 1
    assert jobs[0].source == "web:kariyer.net"
    assert jobs[0].remote_type is RemoteType.REMOTE
    assert route.calls[0].request.headers["x-subscription-token"] == "test-key"
    assert "site%3Akariyer.net" in str(route.calls[0].request.url)
    assert "%22T%C3%BCrkiye%22" in str(route.calls[0].request.url)


@pytest.mark.asyncio
@respx.mock
async def test_turkiye_web_source_filters_non_remote_results() -> None:
    respx.get(TurkiyeWebSource.endpoint).mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Backend Developer | Kariyer.net",
                            "url": "https://www.kariyer.net/is-ilani/backend-developer-123",
                            "description": "İstanbul ofisinde çalışma",
                        }
                    ]
                }
            },
        )
    )

    jobs = await TurkiyeWebSource("test-key").discover(
        SearchQuery("Backend Developer", "Türkiye", True, 168, 10)
    )

    assert jobs == []
