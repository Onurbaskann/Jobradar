import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.discovery.contracts import DiscoveredJob, SearchQuery
from app.discovery.service import (
    _execute_discovery_run,
    _store_jobs,
    lead_fingerprint,
    prioritize_leads_by_location,
)
from app.discovery.sources import (
    JobSpySource,
    SourceUnavailable,
    TurkiyeWebSource,
    map_jobspy_row,
    map_turkiye_web_result,
)
from app.matching.service import AutomaticMatchSummary
from app.models import (
    DiscoveryRun,
    DiscoveryRunStatus,
    JobLead,
    RemoteType,
    SearchProfile,
)
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


def test_changed_description_invalidates_existing_match() -> None:
    job = DiscoveredJob(
        source="jobspy",
        title="Backend Developer",
        company_name="Acme",
        location="İzmir",
        description_md="Yeni ve daha ayrıntılı ilan açıklaması " * 5,
    )
    existing = JobLead(
        id=7,
        fingerprint=lead_fingerprint(job),
        title=job.title,
        company_name=job.company_name,
        location=job.location,
        description_md="Kısa açıklama",
    )

    class Result:
        def first(self):
            return existing

    class Session:
        def __init__(self):
            self.queries = []

        def exec(self, query):
            self.queries.append(query)
            return Result()

        def add(self, _value):
            pass

        def commit(self):
            pass

    session = Session()
    created = _store_jobs(  # type: ignore[arg-type]
        session,
        DiscoveryRun(id=2, profile_id=1),
        [job],
        set(),
    )

    assert created == 0
    assert existing.description_md == job.description_md
    assert len(session.queries) == 2
    assert "DELETE FROM lead_match" in str(session.queries[1])


@pytest.mark.asyncio
async def test_completed_discovery_automatically_scores_unmatched_leads(monkeypatch) -> None:
    run = DiscoveryRun(id=1, profile_id=2)
    profile = SearchProfile(id=2, name="Backend", query="Python")

    class Session:
        def __init__(self, _engine):
            self.values = {DiscoveryRun: run, SearchProfile: profile}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, model, ident):
            value = self.values.get(model)
            return value if value is not None and value.id == ident else None

        def add(self, _value):
            pass

        def commit(self):
            pass

    class Source:
        name = "test"

        async def discover(self, _query):
            return []

    calls = []

    def fake_score(_session, *, limit):
        calls.append(limit)
        return AutomaticMatchSummary(considered=2, scored=2)

    monkeypatch.setattr("app.discovery.service.Session", Session)
    monkeypatch.setattr(
        "app.discovery.service._build_sources",
        lambda _names, _session: ([Source()], []),
    )
    monkeypatch.setattr("app.discovery.service.score_unmatched_leads", fake_score)

    await _execute_discovery_run(1)

    assert calls == [20]
    assert run.status is DiscoveryRunStatus.COMPLETED
    assert run.source_results["automatic_matching"] == {
        "status": "completed",
        "considered": 2,
        "scored": 2,
        "skipped": 0,
        "failed": 0,
    }


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
