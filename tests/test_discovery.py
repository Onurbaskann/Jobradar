from datetime import UTC, datetime

from app.discovery.contracts import DiscoveredJob
from app.discovery.service import lead_fingerprint
from app.discovery.sources import map_jobspy_row
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
