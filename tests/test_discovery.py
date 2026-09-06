import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.discovery.contracts import DiscoveredJob, SearchQuery
from app.discovery.service import lead_fingerprint, prioritize_leads_by_location
from app.discovery.sources import (
    JobSpySource,
    SourceUnavailable,
    TurkiyeWebSource,
    map_jobspy_row,
    map_turkiye_web_result,
)
from app.models import JobLead, RemoteType
from app.web_search import WebSearchResult


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


def test_prioritizes_izmir_without_reordering_other_locations() -> None:
    leads = [
        JobLead(fingerprint="1", title="A", company_name="A", location="İstanbul"),
        JobLead(fingerprint="2", title="B", company_name="B", location="Izmir, Türkiye"),
        JobLead(fingerprint="3", title="C", company_name="C", location="Ankara"),
        JobLead(fingerprint="4", title="D", company_name="D", location="İZMİR / Hibrit"),
    ]

    prioritized = prioritize_leads_by_location(leads, "İzmir")

    assert [lead.fingerprint for lead in prioritized] == ["2", "4", "1", "3"]


def test_location_priority_handles_missing_location() -> None:
    leads = [
        JobLead(fingerprint="1", title="A", company_name="A", location=None),
        JobLead(fingerprint="2", title="B", company_name="B", location="İzmir"),
    ]

    prioritized = prioritize_leads_by_location(leads, "İzmir")

    assert [lead.fingerprint for lead in prioritized] == ["2", "1"]


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


@pytest.mark.parametrize("remote_only", [False, True])
@pytest.mark.asyncio
async def test_jobspy_source_passes_boolean_remote_filter(
    monkeypatch: pytest.MonkeyPatch,
    remote_only: bool,
) -> None:
    call: dict[str, object] = {}

    def scrape_jobs(**kwargs: object) -> SimpleNamespace:
        call.update(kwargs)
        return SimpleNamespace(to_dict=lambda *, orient: [])

    monkeypatch.setitem(sys.modules, "jobspy", SimpleNamespace(scrape_jobs=scrape_jobs))

    await JobSpySource().discover(
        SearchQuery(".NET Developer", "Türkiye", remote_only, 168, 10)
    )

    assert call["is_remote"] is remote_only


def test_turkiye_web_result_maps_yenibiris_title_and_company() -> None:
    result = map_turkiye_web_result(
        WebSearchResult(
            title=(
                "ACME YAZILIM A.Ş. - İstanbul Senior .NET Developer "
                "İş İlanları - Yenibiris.com"
            ),
            url="https://www.yenibiris.com/is-ilani/senior-net-developer/12345",
            description="Hibrit çalışma, C# ve ASP.NET Core",
        ),
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
            WebSearchResult("Backend Developer", "https://example.com/jobs/1")
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
